"""Optional, offline PCSE 6 / WOFOST 8.1 crop backend.

The native model owns water, N, phenology and carbon allocation. FAIRY's old
engine objects are compatibility *views*, never additional growth models.
One call integrates the supplied day's rates exactly once; PCSE's clock then
points to the following day, whose rates have deliberately not been computed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

from .phenology_engine import SoybeanStage
from .canopy_biomass_engine import SeedType as CanopySeedType
from .soil_engine import SoilDayResult
from .wofost_profiles import load_cultivar_profile

_DATA = Path(__file__).with_name("data") / "wofost"
_MODEL = "Wofost81_NWLP_CWB_CNB"
_STATE_VARS = ("DVS", "TSUM", "TSUME", "LAI", "TAGP", "WSO", "TWSO", "TWLV",
               "TWST", "TWRT", "RD", "SM", "NAVAIL", "NamountLV", "NamountSO",
               "NuptakeTotal", "NfixTotal", "DOE", "DOA", "DOM", "TOTIRR", "TSR",
               "PERCT", "LOSST", "EVST", "WTRAT")
_RUNTIME: dict[str, Any] | None = None


def _json_safe(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "value"):
        return _json_safe(value.value)
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(v) for v in value]
    return value


def _number(value: Any, name: str, *, minimum: float | None = None) -> float:
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f"{name} must be finite and >= {minimum}, got {value!r}")
    return result


@dataclass
class WofostConfig:
    crop_name: str = "soybean"
    variety_name: str = "Soybean_901"
    cultivar_map: dict[str, str] = field(default_factory=dict)
    # Named literature transfer, scoped to the seed labels listed in its file.
    # Omission preserves the existing European default for every cultivar.
    cultivar_profile: str | None = None
    # Explicit per-seed profiles allow several researched cultivar references
    # within one scene without changing the fallback for historical scenarios.
    cultivar_profiles: dict[str, str] = field(default_factory=dict)
    # Keys are FAIRY SeedType values (or '*' for all seeds), values native PCSE
    # crop parameters. No legacy GDD/stress coefficients are auto-converted.
    parameter_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Migration guard: an explicit assignment is not proof of calibration,
    # but prevents distinct FAIRY seed labels silently sharing the default.
    require_explicit_cultivar_parameters: bool = False
    fertilizer_n_fraction: float = 0.46
    fertilizer_n_recovery: float = 0.7
    irrigation_efficiency: float = 0.92
    reference_density_plants_m2: float = 40.0
    latitude_deg: float = 45.7
    longitude_deg: float = 126.6
    elevation_m: float = 150.0
    relative_humidity_pct: float = 55.0
    co2_ppm: float = 420.0
    initial_available_n_kg_ha: float = 50.0
    base_soil_n_kg_ha: float = 50.0
    soil_n_mineralization_fraction: float = 0.025
    soil_overrides: dict[str, float] = field(default_factory=dict)
    site_overrides: dict[str, float] = field(default_factory=dict)
    max_duration_days: int = 366
    external_biotic_coupling: bool = True
    # Explicit transfer of a legacy rainfall gain into a declared external
    # surface-water source. This is not a spatial catchment model.
    allow_external_runon: bool = False
    external_runon_source: str | None = None

    def __post_init__(self) -> None:
        if self.crop_name != "soybean":
            raise ValueError("Offline WOFOST data currently supports crop_name='soybean' only")
        if not isinstance(self.require_explicit_cultivar_parameters, bool):
            raise ValueError("require_explicit_cultivar_parameters must be a boolean")
        if not isinstance(self.external_biotic_coupling, bool):
            raise ValueError("external_biotic_coupling must be a boolean")
        if type(self.allow_external_runon) is not bool:
            raise ValueError("allow_external_runon must be a boolean")
        if self.allow_external_runon and (
            not isinstance(self.external_runon_source, str) or not self.external_runon_source.strip()
        ):
            raise ValueError("allow_external_runon requires a non-empty external_runon_source declaration")
        if not self.allow_external_runon and self.external_runon_source is not None:
            raise ValueError("external_runon_source requires explicit allow_external_runon=True")
        if (not isinstance(self.cultivar_profiles, dict)
                or any(not isinstance(seed, str) or not seed or seed == "*"
                       or not isinstance(profile, str) or not profile
                       for seed, profile in self.cultivar_profiles.items())):
            raise ValueError("cultivar_profiles requires explicit seed labels and profile IDs")
        for name in ("fertilizer_n_fraction", "fertilizer_n_recovery", "irrigation_efficiency"):
            value = _number(getattr(self, name), name, minimum=0)
            if value > 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if _number(self.reference_density_plants_m2, "reference_density_plants_m2") <= 0:
            raise ValueError("reference_density_plants_m2 must be positive")
        if not -90 < self.latitude_deg < 90 or not -180 <= self.longitude_deg <= 180:
            raise ValueError("Invalid WOFOST site latitude/longitude")
        if not 0 < self.relative_humidity_pct <= 100:
            raise ValueError("relative_humidity_pct must be in (0, 100]")
        if self.max_duration_days < 2:
            raise ValueError("max_duration_days must be >= 2")
        for key, values in self.parameter_overrides.items():
            if not isinstance(values, dict):
                raise ValueError(f"parameter_overrides[{key!r}] must be a native parameter dictionary")
        if "NOTINF" in self.site_overrides:
            notinf = _number(self.site_overrides["NOTINF"], "site_overrides.NOTINF", minimum=0)
            if notinf > 1:
                raise ValueError("Native NOTINF is a non-infiltrating rainfall fraction in [0, 1]")


def _load_runtime() -> dict[str, Any]:
    """Import the optional dependency only when this backend is selected."""
    global _RUNTIME
    if _RUNTIME is not None:
        return _RUNTIME
    try:
        import pcse
        from pcse import signals
        from pcse.base import ParameterProvider, WeatherDataContainer, WeatherDataProvider
        from pcse.crop.assimilation import WOFOST81_Assimilation
        from pcse.input import WOFOST81SiteDataProvider_Classic
        from pcse.models import Wofost81_NWLP_CWB_CNB
        from pcse.traitlets import Float
        from pcse.util import reference_ET
        import yaml
    except ImportError as exc:
        raise RuntimeError("The WOFOST backend requires optional PCSE 6.0: install FAIRY's "
                           "wofost extra (pip install -e '.[wofost]') or pcse>=6.0,<6.1. "
                           "The reduced backend was not substituted.") from exc
    except OSError as exc:
        raise RuntimeError("PCSE could not initialize its user cache (~/.pcse). Give this "
                           "process a writable PCSE user directory before selecting WOFOST.") from exc
    if not str(pcse.__version__).startswith("6.0."):
        raise RuntimeError(f"WOFOST backend supports PCSE 6.0.x; found {pcse.__version__}")

    class DeferredRateModel(Wofost81_NWLP_CWB_CNB):
        def calc_rates(self, day, drv):
            # Engine.__init__ and Engine._run normally evaluate rates before
            # FAIRY has the next action/weather. Defer those evaluations.
            # Defer crop finalization as well: stock PCSE calculates the
            # boundary day's crop/soil rates BEFORE removing the crop. Those
            # soil rates must use actual forcing on the following explicit
            # daily call, not a placeholder or an immediate bare-soil reset.
            pass

        def calculate_current_day(self):
            super().calc_rates(self.day, self.drv)

    class ExternalStressAssimilation(WOFOST81_Assimilation):
        external_factor = Float(1.0)
        last_unstressed_pgass = Float(0.0)
        last_pgass = Float(0.0)

        def __call__(self, day, drv):
            # Empirical pest/weed/disease coupling changes current assimilation
            # before native respiration/partitioning, preserving carbon balance.
            self.last_unstressed_pgass = super().__call__(day, drv)
            self.last_pgass = self.last_unstressed_pgass * self.external_factor
            return self.last_pgass

    _RUNTIME = dict(pcse=pcse, signals=signals, ParameterProvider=ParameterProvider,
                    WeatherDataContainer=WeatherDataContainer, WeatherDataProvider=WeatherDataProvider,
                    SiteProvider=WOFOST81SiteDataProvider_Classic, reference_ET=reference_ET,
                    Model=DeferredRateModel, Assimilation=ExternalStressAssimilation, yaml=yaml)
    return _RUNTIME


@dataclass
class _RidgeRun:
    specification: dict[str, Any]
    model: Any = None
    provider: Any = None
    journal: list[dict[str, Any]] = field(default_factory=list)
    pcse: dict[str, Any] = field(default_factory=dict)
    maturity_snapshot: dict[str, Any] | None = None
    last_native_inputs: dict[str, Any] = field(default_factory=dict)
    cumulative_irrigation_mm: float = 0.0
    cumulative_fertilizer_kg: float = 0.0
    cumulative_n_kg_ha: float = 0.0
    cumulative_external_soil_n_delta_kg_ha: float = 0.0
    cumulative_external_runon_mm: float = 0.0
    cumulative_native_management_effective_irrigation_mm: float = 0.0
    last_soil_nitrogen_event_day: date | None = None
    last_day: date | None = None


class WofostBackend:
    def __init__(self, config: WofostConfig | Mapping[str, Any] | None = None) -> None:
        self.config = copy.deepcopy(config if isinstance(config, WofostConfig)
                                    else WofostConfig(**dict(config or {})))
        self._cultivar_profile = (load_cultivar_profile(self.config.cultivar_profile)
                                  if self.config.cultivar_profile is not None else None)
        self._cultivar_profiles = {seed: load_cultivar_profile(profile_id)
                                   for seed, profile_id in self.config.cultivar_profiles.items()}
        for seed, profile in self._cultivar_profiles.items():
            if not profile.applies_to(seed):
                raise ValueError(f"WOFOST profile {profile.profile_id!r} does not support seed {seed!r}")
        selected_seeds = set(self._cultivar_profiles)
        if self._cultivar_profile is not None:
            selected_seeds.update(self._cultivar_profile.supported_seed_types)
        for seed in selected_seeds:
            profile = self._profile_for_seed(seed)
            if profile is not None:
                explicit = self.config.cultivar_map.get(seed)
                if explicit is not None and explicit != profile.base_variety:
                    raise ValueError(f"cultivar_map[{seed!r}] conflicts with cultivar_profile "
                                     f"base_variety {profile.base_variety!r}; "
                                     "use parameter_overrides for explicit native parameter changes")
        self._runtime = _load_runtime()
        self._data_provenance = json.loads((_DATA / "provenance.json").read_text())
        content = (_DATA / "soybean.yaml").read_bytes()
        if hashlib.sha256(content).hexdigest() != self._data_provenance["sha256"]:
            raise RuntimeError("Bundled WOFOST soybean data failed its SHA-256 integrity check")
        self._varieties = self._runtime["yaml"].safe_load(content)["CropParameters"]["Varieties"]
        self._crop_parameters(self.config.variety_name, "*")  # fail early on invalid configuration
        for seed, variety in self.config.cultivar_map.items():
            self._crop_parameters(variety, seed)
        for seed in self.config.parameter_overrides:
            self._crop_parameters(self._variety_for_seed(seed), seed)
        for seed in selected_seeds:
            self._crop_parameters(self._variety_for_seed(seed), seed)
        self._runs: dict[int, _RidgeRun] = {}
        self._pending: dict[int, dict[str, float]] = {}
        self._pending_soil_nitrogen: dict[int, list[dict[str, Any]]] = {}
        self._soil_nitrogen_events: dict[str, dict[str, Any]] = {}
        self._preplant_totals: dict[int, dict[str, float]] = {}
        self._last_day: date | None = None
        self._soil_signature: dict[str, Any] = {}
        self._preplant_external_runon_inputs: dict[int, list[dict[str, Any]]] = {}

    @property
    def has_started(self) -> bool:
        return self._last_day is not None or bool(self._runs)

    @property
    def last_day(self) -> date | None:
        return self._last_day

    def native_soil_nitrogen(self, ridge_ids) -> dict[int, dict[str, Any]]:
        """Read the real CNB pools, without inventing values before native sowing.

        ``native_effective_day`` is the last completed forcing day. PCSE's
        internal clock already points at the following, uncalculated day.
        """
        result = {}
        for rid in ridge_ids:
            run = self._runs.get(int(rid))
            if run is None:
                result[int(rid)] = dict(status="not_started", available_n_kg_ha=None,
                    reserve_n_kg_ha=None, release_reference_n_kg_ha=None, native_effective_day=None,
                    nitrogen_state_effective_day=None)
                continue
            nitrogen = run.model.soil.nutrientbalance
            effective_days = [day for day in (run.last_day, run.last_soil_nitrogen_event_day) if day is not None]
            result[int(rid)] = dict(status="native", available_n_kg_ha=float(nitrogen.states.NAVAIL),
                reserve_n_kg_ha=float(nitrogen.states.NSOIL),
                release_reference_n_kg_ha=float(nitrogen.NSOILI),
                native_effective_day=run.last_day.isoformat() if run.last_day is not None else None,
                nitrogen_state_effective_day=max(effective_days).isoformat() if effective_days else None)
        return result

    def apply_soil_nitrogen_event(self, *, event_id: str, day: date, ridge_ids,
                                 available_n_kg_ha: float | None = None,
                                 reserve_n_kg_ha: float | None = None) -> bool:
        """Apply an external pool edit now and journal it with the coming day.

        This is a scenario disturbance, not fertilizer: no warehouse stock,
        fertilizer recovery factor or fertilizer total is changed. Reserve
        edits preserve CNB's original ``NSOILI`` release-rate reference.
        """
        if not isinstance(event_id, str) or not event_id.strip() or type(day) is not date:
            raise ValueError("Soil nitrogen events require an event_id and a calendar day")
        ridges = list(ridge_ids)
        if not ridges or any(type(rid) is not int or rid < 0 for rid in ridges) or len(set(ridges)) != len(ridges):
            raise ValueError("Soil nitrogen events require distinct nonnegative integer ridges")
        values = dict(available_n_kg_ha=available_n_kg_ha, reserve_n_kg_ha=reserve_n_kg_ha)
        if all(value is None for value in values.values()):
            raise ValueError("Soil nitrogen events must set an available and/or reserve pool")
        for name, value in values.items():
            if value is not None:
                if isinstance(value, bool):
                    raise ValueError(f"{name} must be a finite nonnegative number")
                values[name] = _number(value, name, minimum=0)
        declaration = dict(event_id=event_id, day=day.isoformat(), ridge_ids=ridges, **values)
        prior = self._soil_nitrogen_events.get(event_id)
        if prior is not None:
            if prior != declaration:
                raise ValueError("Cannot replace an applied soil nitrogen event")
            return False
        # Validate every target before queuing any, preventing a partial field
        # edit when an unplanted or already-integrated ridge is encountered.
        for rid in ridges:
            run = self._runs.get(rid)
            if run is None:
                raise ValueError("Soil nitrogen events require an already started native crop/soil run")
            if run.model.day != day:
                raise ValueError("Soil nitrogen event must precede its exact native growth day")
            if values["reserve_n_kg_ha"] and run.model.soil.nutrientbalance.NSOILI <= 0:
                raise ValueError("Cannot add reserve nitrogen with a zero initial release reference; configure initial soil N")
        self._soil_nitrogen_events[event_id] = copy.deepcopy(declaration)
        for rid in ridges:
            event = {key: value for key, value in declaration.items() if key != "ridge_ids"}
            run = self._runs[rid]
            change = self._apply_soil_nitrogen_events(run, dict(day=day.isoformat(),
                soil_nitrogen_events=[event]))[0]
            run.pcse["NAVAIL"] = run.model.soil.nutrientbalance.states.NAVAIL
            run.cumulative_external_soil_n_delta_kg_ha += change["external_n_delta_kg_ha"]
            run.last_soil_nitrogen_event_day = day
            self._pending_soil_nitrogen.setdefault(rid, []).append(dict(event=event, change=change))
        return True

    @staticmethod
    def _apply_soil_nitrogen_events(run: _RidgeRun, entry: dict[str, Any]) -> list[dict[str, Any]]:
        """Apply recorded external edits to native CNB, including during replay."""
        nitrogen = run.model.soil.nutrientbalance
        changes = []
        for event in entry.get("soil_nitrogen_events", []):
            if event["day"] != entry["day"]:
                raise ValueError("Soil nitrogen event and native forcing day disagree")
            before = dict(available_n_kg_ha=float(nitrogen.states.NAVAIL),
                          reserve_n_kg_ha=float(nitrogen.states.NSOIL))
            after = {name: before[name] if event.get(name) is None else _number(event[name], name, minimum=0)
                     for name in before}
            if after["reserve_n_kg_ha"] > 0 and nitrogen.NSOILI <= 0:
                raise ValueError("Positive soil reserve requires a positive initial release reference")
            # CNB has no generic PCSE setter for these pools. Updating its
            # registered states publishes NAVAIL to the crop's native kiosk.
            nitrogen.states.unlock()
            try:
                nitrogen.states.NAVAIL = after["available_n_kg_ha"]
                nitrogen.states.NSOIL = after["reserve_n_kg_ha"]
            finally:
                nitrogen.states.lock()
            changes.append(dict(event_id=event["event_id"], native_effective_day=entry["day"],
                before=before, after=after, release_reference_n_kg_ha=float(nitrogen.NSOILI),
                external_n_delta_kg_ha=sum(after.values()) - sum(before.values())))
        recorded = entry.get("soil_nitrogen_changes")
        if recorded is not None and recorded != changes:
            raise ValueError("Replayed soil nitrogen state changes disagree with the saved audit record")
        return changes

    def bind_physics(self, physics: Any) -> None:
        """Record static soil assumptions before any action (for oracle hashes)."""
        if getattr(physics, "crop_type", "soybean") != "soybean":
            raise ValueError("The bundled WOFOST backend supports soybean physics only")
        # Legacy profiles sometimes amplify rainfall as an empirical proxy for
        # run-on/poor drainage. A negative NOTINF would manufacture native
        # rainfall. Retain the rejection unless the caller explicitly declares
        # an external source; then local rain and external run-on stay separate.
        for rid in physics.soil.states:
            capture = _number(physics.soil.params_for_ridge(rid).rainfall_capture_efficiency,
                              f"ridge {rid} rainfall_capture_efficiency", minimum=0)
            self._external_runon_declaration(rid, capture)
        signature = {"parameters": _json_safe(asdict(physics.soil.params)),
                     "hydraulic_modifiers": _json_safe({rid: asdict(value) for rid, value in
                                                        physics.soil.hydraulic_modifiers.items()})}
        if self._soil_signature and signature != self._soil_signature and self.has_started:
            raise ValueError("Cannot change WOFOST soil assumptions after native simulation starts")
        self._soil_signature = signature

    def _external_runon_declaration(self, rid: int, capture: float) -> dict[str, Any] | None:
        if capture <= 1:
            return None
        if not self.config.allow_external_runon:
            raise ValueError(
                f"WOFOST cannot map ridge {rid} rainfall_capture_efficiency={capture} "
                "to native NOTINF: rainfall capture must be a fraction in [0, 1]. "
                "A legacy gain above 1 requires an explicit catchment/run-on water model."
            )
        if self.config.site_overrides.get("NOTINF", 0) != 0:
            raise ValueError("Declared external run-on split requires local rainfall NOTINF=0")
        return {
            "source": self.config.external_runon_source,
            "legacy_rainfall_capture_multiplier": capture,
            "external_runon_per_rain_mm": capture - 1.0,
            "local_rainfall_NOTINF": 0.0,
            "native_transport": "irrigation signal at efficiency 1; not Agent irrigation",
            "calibration": "unvalidated legacy capture transfer; no catchment geometry or runoff calibration",
        }

    def _profile_for_seed(self, seed: str):
        if seed in self._cultivar_profiles:
            return self._cultivar_profiles[seed]
        if self._cultivar_profile is not None and self._cultivar_profile.applies_to(seed):
            return self._cultivar_profile
        return None

    def _require_explicit_cultivar(self, seed: str) -> None:
        if not self.config.require_explicit_cultivar_parameters or seed == "*":
            return
        if (self._profile_for_seed(seed) is not None
                or seed in self.config.cultivar_map
                or self.config.parameter_overrides.get(seed)):
            return
        raise ValueError(
            f"WOFOST seed {seed!r} requires explicit cultivar parameters: select a "
            "cultivar_profile scoped to this seed, add non-empty parameter_overrides "
            f"for {seed!r}, or assign it explicitly in cultivar_map. The default "
            "variety_name and '*' overrides do not establish cultivar adaptation; "
            "an explicit assignment does not certify local calibration."
        )

    def _variety_for_seed(self, seed: str) -> str:
        self._require_explicit_cultivar(seed)
        profile = self._profile_for_seed(seed)
        if profile is not None:
            return profile.base_variety
        return self.config.cultivar_map.get(seed, self.config.variety_name)

    def _crop_parameters(self, variety: str, seed: str) -> dict[str, Any]:
        self._require_explicit_cultivar(seed)
        if variety not in self._varieties:
            raise ValueError(f"Unknown bundled WOFOST soybean variety {variety!r}; "
                             f"available: {', '.join(sorted(self._varieties))}")
        parameters = {key: copy.deepcopy(value[0]) for key, value in self._varieties[variety].items()
                      if key != "Metadata"}
        profile = self._profile_for_seed(seed)
        profile_overrides = profile.parameter_overrides if profile is not None else {}
        if (profile is not None
                and profile.provenance().get("parameter_set_kind")
                == "complete_native_parameters"):
            missing = set(parameters) - set(profile_overrides)
            if missing:
                raise ValueError(f"Complete WOFOST cultivar profile is missing native parameters: {sorted(missing)}")
        # Explicit caller overrides always win over transferred literature values.
        for overrides in (profile_overrides, self.config.parameter_overrides.get("*", {}),
                          self.config.parameter_overrides.get(seed, {})):
            unknown = set(overrides) - set(parameters)
            if unknown:
                raise ValueError(f"Unknown native WOFOST crop parameters: {sorted(unknown)}")
            parameters.update(copy.deepcopy(overrides))
        for key in ("TSUMEM", "TSUM1", "TSUM2", "TDWI"):
            if _number(parameters[key], key) <= 0:
                raise ValueError(f"Native WOFOST {key} must be positive")
        if float(parameters["DVSEND"]) != 2.0:
            raise ValueError("FAIRY's WOFOST stage adapter currently requires DVSEND=2.0")
        return parameters

    @staticmethod
    def _empty_inputs() -> dict[str, float]:
        return {"irrigation_mm": 0.0, "fertilizer_kg": 0.0, "n_kg_ha": 0.0}

    def check_replant(self, ridge_ids) -> str | None:
        """Reject crop replacement/gap filling before a tool spends its resources."""
        started = [int(rid) for rid in ridge_ids if int(rid) in self._runs]
        if started:
            return (f"WOFOST replanting or gap filling on started ridges {started} requires "
                    "a new native season; existing crop states cannot be edited through a stand proxy")
        return None

    def queue_actions(self, actions_by_ridge: Mapping[int, list[Any]], ridge_area_m2: float) -> None:
        """Consume a drained action batch once; subdaily water/N awaits next native day.

        FERTIGATION.amount is ambiguous in the old API. Only explicit water_mm
        metadata supplies its water component; the tractor uses amount for a
        normalized fertilizer dose and must not create irrigation accidentally.
        """
        area = _number(ridge_area_m2, "ridge_area_m2")
        if area <= 0:
            raise ValueError("ridge_area_m2 must be positive")
        for rid, actions in actions_by_ridge.items():
            delta = self._empty_inputs()
            for action in actions:
                kind = str(getattr(action.action_type, "value", action.action_type))
                metadata = action.metadata or {}
                if kind == "PLANTING" and int(rid) in self._runs:
                    raise ValueError("WOFOST rotations/replanting require a new native season")
                if kind == "IRRIGATION":
                    delta["irrigation_mm"] += _number(metadata.get("water_mm", action.amount),
                                                       "irrigation_mm", minimum=0)
                elif kind == "FERTIGATION":
                    delta["irrigation_mm"] += _number(metadata.get("water_mm", 0), "water_mm", minimum=0)
                if kind in {"BASE_FERTILIZER", "FERTIGATION"}:
                    kg = metadata.get("fertilizer_kg_per_ridge", metadata.get("kg_per_ridge"))
                    if kg is None:
                        raise ValueError("WOFOST fertilizer actions require actual kg_per_ridge or "
                                         "fertilizer_kg_per_ridge metadata; normalized amount is not kg")
                    kg = _number(kg, "fertilizer kg/ridge", minimum=0)
                    n_fraction = _number(metadata.get("n_fraction", self.config.fertilizer_n_fraction),
                                         "n_fraction", minimum=0)
                    if n_fraction > 1:
                        raise ValueError("fertilizer n_fraction must be in [0, 1]")
                    delta["fertilizer_kg"] += kg
                    delta["n_kg_ha"] += kg * n_fraction * 10000.0 / area
            if any(delta.values()):
                pending = self._pending.setdefault(int(rid), self._empty_inputs())
                for key, value in delta.items():
                    pending[key] += value

    def _weather_container(self, day: date, values: Mapping[str, Any], humidity: float) -> Any:
        c = self.config
        tmin = _number(values["air_temp_min_c"], "air_temp_min_c")
        tmax = _number(values["air_temp_max_c"], "air_temp_max_c")
        temp = _number(values["air_temp_mean_c"], "air_temp_mean_c")
        if tmin > tmax or not 0 < humidity <= 100:
            raise ValueError("Invalid WOFOST daily temperature range or relative humidity")
        radiation = _number(values["solar_rad_mj_m2"], "solar_rad_mj_m2", minimum=0) * 1e6
        rain = _number(values["rain_mm"], "rain_mm", minimum=0) / 10
        wind = _number(values.get("wind_ms", 0), "wind_ms", minimum=0)
        vapor = max(0.06, 6.108 * math.exp(17.27 * temp / (temp + 237.3)) * humidity / 100)
        e0, es0, et0 = self._runtime["reference_ET"](
            DAY=day, LAT=c.latitude_deg, ELEV=c.elevation_m, TMIN=tmin, TMAX=tmax,
            IRRAD=radiation, VAP=vapor, WIND=wind, ANGSTA=0.29, ANGSTB=0.49, ETMODEL="PM")
        return self._runtime["WeatherDataContainer"](
            DAY=day, LAT=c.latitude_deg, LON=c.longitude_deg, ELEV=c.elevation_m,
            TMIN=tmin, TMAX=tmax, TEMP=temp, IRRAD=radiation, VAP=vapor, RAIN=rain,
            WIND=wind, E0=e0 / 10, ES0=es0 / 10, ET0=et0 / 10)

    def _create_run(self, specification: dict[str, Any], first_weather: dict[str, Any],
                    humidity: float) -> _RidgeRun:
        runtime = self._runtime
        provider = runtime["WeatherDataProvider"]()
        start = date.fromisoformat(specification["start_date"])
        provider._store_WeatherDataContainer(self._weather_container(start, first_weather, humidity), start)
        crop = copy.deepcopy(specification["crop_parameters"])
        parameters = runtime["ParameterProvider"](cropdata=crop,
                                                  soildata=specification["soil_parameters"],
                                                  sitedata=specification["site_parameters"])
        agro = [{start: {"CropCalendar": {"crop_name": "soybean", "variety_name": specification["variety"],
                                          "crop_start_date": start, "crop_start_type": "sowing",
                                          "crop_end_date": None, "crop_end_type": "maturity",
                                          "max_duration": self.config.max_duration_days},
                         "TimedEvents": None, "StateEvents": None}},
                # Keep the native bare-soil balance alive after crop maturity.
                {start + timedelta(days=self.config.max_duration_days + 3660): None}]
        model = runtime["Model"](parameters, provider, agro,
                                  output_vars=list(_STATE_VARS), summary_vars=list(_STATE_VARS))
        # The stock assimilation has no registered states/rates. Replace it
        # before its first evaluation, preserving all native model equations.
        model.crop.assim = runtime["Assimilation"](start, model.kiosk, parameters)
        initial_inputs = specification.get("preplant_inputs", self._empty_inputs())
        return _RidgeRun(specification=copy.deepcopy(specification), model=model, provider=provider,
                         cumulative_irrigation_mm=initial_inputs["irrigation_mm"],
                         cumulative_fertilizer_kg=initial_inputs["fertilizer_kg"],
                         cumulative_n_kg_ha=initial_inputs["n_kg_ha"])

    def _specification(self, physics: Any, rid: int, day: date, density: float) -> dict[str, Any]:
        phen = physics.phenology.states[rid]
        if phen.emerged:
            raise ValueError("WOFOST cannot initialize an already emerged scenario without historical "
                             "weather and actions. Start from sowing or restore a WOFOST checkpoint.")
        if phen.planting_date is not None and (day - phen.planting_date).days > 1:
            raise ValueError("WOFOST first native day must be at sowing (or the next daily boundary); "
                             "historical pre-emergence weather is missing")
        seed = str(getattr(phen.seed_type, "value", phen.seed_type) or "STANDARD")
        variety = self._variety_for_seed(seed)
        crop = self._crop_parameters(variety, seed)
        density = _number(density, "density_plants_m2", minimum=0)
        if density <= 0:
            raise ValueError("Planted WOFOST ridges require positive realized plant density")
        stand = _number(physics.management.states[rid].stand_fraction,
                        "initial_stand_fraction", minimum=0)
        if stand > 1:
            raise ValueError("initial_stand_fraction must be in [0, 1]")
        if stand == 0:
            raise ValueError("initial_stand_fraction is zero: the failed stand has no initial "
                             "crop biomass; PCSE requires positive biomass and cannot start "
                             "this ridge until it is replanted")
        crop["TDWI"] *= density / self.config.reference_density_plants_m2 * stand
        p = physics.soil.params_for_ridge(rid)
        capture = _number(p.rainfall_capture_efficiency,
                          f"ridge {rid} rainfall_capture_efficiency", minimum=0)
        runon = self._external_runon_declaration(rid, capture)
        soil = {"SMW": p.wilting_point_vwc, "SMFCF": p.field_capacity_vwc,
                "SM0": p.saturation_vwc, "CRAIRC": 0.06,
                "SOPE": p.max_infiltration_mm_day / 10,
                "KSUB": p.max_infiltration_mm_day / 10,
                "K0": p.max_infiltration_mm_day / 10,
                "RDMSOL": p.root_depth_m * 100}
        soil.update(self.config.soil_overrides)
        if not 0 <= soil["SMW"] < soil["SMFCF"] < soil["SM0"] <= 1:
            raise ValueError("WOFOST soil requires 0 <= SMW < SMFCF < SM0 <= 1")
        sm = min(soil["SM0"], max(soil["SMW"], physics.soil.states[rid].root_vwc))
        site = dict(WAV=max(0., (sm - soil["SMW"]) * soil["RDMSOL"]), SMLIM=sm,
                    CO2=self.config.co2_ppm, NAVAILI=self.config.initial_available_n_kg_ha,
                    NSOILBASE=self.config.base_soil_n_kg_ha,
                    NSOILBASE_FR=self.config.soil_n_mineralization_fraction,
                    NOTINF=0.0 if runon else 1 - capture, SSI=0., SSMAX=0., IFUNRN=0)
        site.update(self.config.site_overrides)
        preplant = self._preplant_totals.get(rid, self._empty_inputs())
        # Preplant fertilizer is sent as a single native apply_n event on the
        # first native day. Do not force it into NAVAILI, whose PCSE provider
        # permits <=250 kg/ha even though real management inputs may exceed it.
        site = dict(self._runtime["SiteProvider"](**site))
        selected_profile = self._profile_for_seed(seed)
        profile = selected_profile.provenance() if selected_profile is not None else None
        specification = {"start_date": day.isoformat(), "planting_date": _json_safe(phen.planting_date or day),
                "seed_type": seed, "variety": variety, "crop_parameters": crop,
                "soil_parameters": soil, "site_parameters": site,
                "density_plants_m2": density, "initial_stand_fraction": stand,
                "preplant_inputs": copy.deepcopy(preplant),
                "cultivar_mapping": ("literature_transfer" if profile else
                                     "explicit" if seed in self.config.cultivar_map else "uncalibrated_default"),
                "calibration": "uncalibrated", "density_method": "TDWI_initial_biomass_scaling_only"}
        if runon is not None:
            specification["external_runon"] = runon
            # Preplant auxiliary soil already contains these inputs in SM/WAV.
            # They are provenance, not another native irrigation application.
            specification["preplant_external_runon_inputs"] = copy.deepcopy(
                self._preplant_external_runon_inputs.get(rid, [])
            )
        if profile is not None:
            specification["cultivar_profile"] = profile
            # A complete, versioned native parameter set has its own cultivar
            # identity. Keep its upstream completion source separately visible.
            if profile.get("parameter_set_kind") == "complete_native_parameters":
                specification["upstream_base_variety"] = variety
                specification["variety"] = profile.get("native_variety_name", variety)
                specification["calibration"] = profile.get("calibration", {}).get(
                    "status", "uncalibrated"
                )
        return specification

    def _advance_native(self, run: _RidgeRun, entry: dict[str, Any], *,
                        soil_nitrogen_preapplied: bool = False) -> None:
        model = run.model
        day = date.fromisoformat(entry["day"])
        if model.day != day:
            raise ValueError(f"WOFOST native clock expected {model.day}, received {day}; missing daily forcing")
        drv = self._weather_container(day, entry["weather"], entry["humidity_pct"])
        run.provider._store_WeatherDataContainer(drv, day)
        # The next day is only a clock placeholder. DeferredRateModel ensures
        # this weather is never integrated; the next call replaces it first.
        tomorrow = day + timedelta(days=1)
        run.provider._store_WeatherDataContainer(
            self._weather_container(tomorrow, entry["weather"], entry["humidity_pct"]), tomorrow)
        model.drv = model._get_driving_variables(day)
        soil_nitrogen_changes = (entry.get("soil_nitrogen_changes", []) if soil_nitrogen_preapplied
                                else self._apply_soil_nitrogen_events(run, entry))
        if soil_nitrogen_changes:
            entry["soil_nitrogen_changes"] = soil_nitrogen_changes
        if entry.get("harvested") and model.crop is not None:
            model._send_signal(signal=self._runtime["signals"].crop_finish,
                               day=day, finish_type="harvest", crop_delete=True)
        inputs = entry["inputs"]
        runon_mm = _number(entry.get("external_runon_mm", 0.0), "external_runon_mm", minimum=0)
        declaration = run.specification.get("external_runon")
        if declaration is not None:
            if not self.config.allow_external_runon or declaration.get("source") != self.config.external_runon_source:
                raise ValueError("Native external run-on specification lacks the configured source permission")
            expected_runon = declaration["external_runon_per_rain_mm"] * _number(
                entry["weather"]["rain_mm"], "rain_mm", minimum=0
            )
            if (entry.get("external_runon_source") != declaration["source"]
                    or not math.isclose(runon_mm, expected_runon, rel_tol=1e-12, abs_tol=1e-10)):
                raise ValueError("Native external run-on input does not match its declared source/rainfall ratio")
        elif runon_mm:
            raise ValueError("Native external run-on has no declared source and rainfall-capture split")
        effective_management_mm = inputs["irrigation_mm"] * self.config.irrigation_efficiency
        preplant_n = (run.specification.get("preplant_inputs", {}).get("n_kg_ha", 0.0)
                      if not run.journal else 0.0)
        if runon_mm:
            # CWB's _on_IRRIGATE REPLACES its pending amount. Send one combined
            # effective input, with separate accounting below; two signals would
            # silently discard one source. External water has no pump loss.
            model._send_signal(signal=self._runtime["signals"].irrigate,
                               amount=(effective_management_mm + runon_mm) / 10,
                               efficiency=1.0)
        elif inputs["irrigation_mm"]:
            model._send_signal(signal=self._runtime["signals"].irrigate,
                               amount=inputs["irrigation_mm"] / 10,
                               efficiency=self.config.irrigation_efficiency)
        if inputs["n_kg_ha"] + preplant_n:
            model._send_signal(signal=self._runtime["signals"].apply_n,
                               N_amount=inputs["n_kg_ha"] + preplant_n,
                               N_recovery=self.config.fertilizer_n_recovery)
        if model.crop is not None:
            model.crop.assim.external_factor = entry["external_growth_factor"]
        assimilation = model.crop.assim if model.crop is not None else None
        if assimilation is not None:
            # The pre-emergence and crop-finalization paths can skip assimilation.
            # Do not carry yesterday's PGASS into today's diagnostic record.
            assimilation.last_unstressed_pgass = assimilation.last_pgass = 0.0
        model.calculate_current_day()
        # Soil WTRA survives the boundary day's crop deletion; crop TRA may
        # already be absent here. Cache soil fluxes before integration resets rates.
        rates = {name: model.get_variable(name) for name in (
            "RFTRA", "RFRGRL", "TRA", "WTRA", "EVS", "EVW", "RIRR", "DTSR", "LOSS",
            "GASS", "MRES", "ASRC", "DMI", "ADMI",
        )}
        rates["PGASS_BEFORE_BIOTICS"] = assimilation.last_unstressed_pgass if assimilation is not None else 0.0
        rates["PGASS"] = assimilation.last_pgass if assimilation is not None else 0.0
        if model.crop is not None and model.crop.pheno.get_variable("STAGE") == "emerging":
            # Native crop stress routines have not run yet; zero-filled rate
            # templates do not mean complete water/N stress before emergence.
            rates["RFTRA"] = rates["RFRGRL"] = 1.0
        model.run(days=1)
        current = {name: model.get_variable(name) for name in _STATE_VARS}
        if run.maturity_snapshot is None and current.get("DOM") is not None:
            # Biological maturity is reached during integration. Freeze the
            # compatibility crop view now; native finalization itself remains
            # pending until the next real day's rate calculation, as above.
            run.maturity_snapshot = dict(current)
        if model.crop is None and run.maturity_snapshot is None:
            summaries = model.get_summary_output()
            if summaries:
                final = dict(summaries[-1])
                if final.get("DOM") is None and not entry.get("harvested"):
                    raise RuntimeError("WOFOST crop stopped before maturity; check max_duration and cultivar parameters")
                run.maturity_snapshot = final
        if run.maturity_snapshot is not None:
            # Only freeze crop output. The native bare-soil CWB/CNB continues.
            for key in _STATE_VARS:
                if key not in {"SM", "NAVAIL", "TOTIRR", "TSR", "PERCT", "LOSST", "EVST", "WTRAT"}:
                    current[key] = run.maturity_snapshot.get(key)
        current.update(rates)
        run.pcse = current
        run.last_native_inputs = {**inputs, "irrigation_cm": inputs["irrigation_mm"] / 10,
                                  "preplant_n_kg_ha": preplant_n,
                                  "recovered_n_kg_ha": (inputs["n_kg_ha"] + preplant_n) * self.config.fertilizer_n_recovery,
                                  "external_growth_factor": entry["external_growth_factor"]}
        run.last_native_inputs["biotic_pressure"] = copy.deepcopy(entry.get("biotic_pressure"))
        if soil_nitrogen_changes:
            run.last_native_inputs["soil_nitrogen_changes"] = copy.deepcopy(soil_nitrogen_changes)
            run.last_soil_nitrogen_event_day = day
            if not soil_nitrogen_preapplied:
                run.cumulative_external_soil_n_delta_kg_ha += sum(
                    change["external_n_delta_kg_ha"] for change in soil_nitrogen_changes)
        if self.config.allow_external_runon:
            run.last_native_inputs.update({
                "external_runon_mm": runon_mm,
                "external_runon_source": entry.get("external_runon_source"),
                "effective_management_irrigation_mm": effective_management_mm,
                "native_effective_irrigation_signal_mm": effective_management_mm + runon_mm,
                "native_TOTIRR_includes_external_runon": True,
            })
            run.cumulative_external_runon_mm += runon_mm
            run.cumulative_native_management_effective_irrigation_mm += effective_management_mm
        run.cumulative_irrigation_mm += inputs["irrigation_mm"]
        run.cumulative_fertilizer_kg += inputs["fertilizer_kg"]
        run.cumulative_n_kg_ha += inputs["n_kg_ha"]
        run.last_day = day
        run.journal.append(copy.deepcopy(entry))

    def advance_day(self, physics: Any, day: date, weather: Any,
                    actions_by_ridge: Mapping[int, list[Any]] | None = None,
                    density_by_ridge: Mapping[int, float] | None = None,
                    ridge_area_m2: float = 1.0, humidity_pct: float | None = None) -> list[SoilDayResult]:
        if weather.day != day:
            raise ValueError("WOFOST weather.day must match the requested daily tick")
        if self._last_day is not None and day <= self._last_day:
            return self._soil_results(physics, day)
        if self._last_day is not None and day != self._last_day + timedelta(days=1):
            raise ValueError("WOFOST requires consecutive daily forcing; no weather interpolation is performed")
        self.bind_physics(physics)
        # Validate every newly sown ridge before creating or advancing any
        # native model. An unsupported failed stand must not leave half a field
        # integrated and make a retry apply different forcing dates.
        specifications = {
            rid: self._specification(physics, rid, day, (density_by_ridge or {}).get(
                rid, self.config.reference_density_plants_m2))
            for rid, phen in physics.phenology.states.items()
            if rid not in self._runs and phen.planted
        }
        self.queue_actions(actions_by_ridge or {}, ridge_area_m2)
        values = {name: getattr(weather, name) for name in ("air_temp_min_c", "air_temp_max_c",
                  "air_temp_mean_c", "rain_mm", "solar_rad_mj_m2", "wind_ms")}
        humidity = self.config.relative_humidity_pct if humidity_pct is None else float(humidity_pct)
        for rid, phen in physics.phenology.states.items():
            run = self._runs.get(rid)
            if run is None and phen.planted:
                run = self._create_run(specifications[rid], values, humidity)
                self._runs[rid] = run
            if run is None:
                inputs = self._pending.pop(rid, self._empty_inputs())
                totals = self._preplant_totals.setdefault(rid, self._empty_inputs())
                for key, value in inputs.items():
                    totals[key] += value
                if self.config.allow_external_runon:
                    capture = physics.soil.params_for_ridge(rid).rainfall_capture_efficiency
                    declaration = self._external_runon_declaration(rid, capture)
                    if declaration is not None:
                        self._preplant_external_runon_inputs.setdefault(rid, []).append({
                            "day": day.isoformat(), "rain_mm": values["rain_mm"],
                            "external_runon_mm": declaration["external_runon_per_rain_mm"] * values["rain_mm"],
                            "source": declaration["source"],
                            "transport": "preplant auxiliary soil; included in initial native WAV, not applied twice",
                        })
                # Explicit auxiliary bare-soil physics before native sowing;
                # never run it alongside an active native CWB balance.
                physics.soil._update_ridge_day(physics.soil.states[rid], weather,
                                              inputs["irrigation_mm"], 0.0)
                tag = "preplant_auxiliary_soil_not_native_CWB"
                if tag not in physics.soil.states[rid].tags:
                    physics.soil.states[rid].tags.append(tag)
                continue
            if phen.planted and _json_safe(phen.planting_date) != run.specification["planting_date"]:
                raise ValueError("WOFOST rotations/replanting require a new native season; this adapter does not silently reuse a crop")
            biotic = physics.biotic.states[rid]
            factor = (physics.biotic.growth_stress_multiplier(rid)
                      if self.config.external_biotic_coupling else 1.0)
            entry = {"day": day.isoformat(), "weather": values, "humidity_pct": humidity,
                     "inputs": self._pending.pop(rid, self._empty_inputs()),
                     "external_growth_factor": factor, "harvested": not phen.planted,
                     "biotic_pressure": {name: float(getattr(biotic, name)) for name in (
                         "weed_pressure", "insect_pressure", "disease_pressure")}}
            nitrogen_events = self._pending_soil_nitrogen.pop(rid, [])
            if nitrogen_events:
                entry["soil_nitrogen_events"] = [record["event"] for record in nitrogen_events]
                entry["soil_nitrogen_changes"] = [record["change"] for record in nitrogen_events]
            if self.config.allow_external_runon:
                declaration = run.specification.get("external_runon")
                entry["external_runon_mm"] = (declaration["external_runon_per_rain_mm"] * values["rain_mm"]
                                               if declaration is not None else 0.0)
                entry["external_runon_source"] = declaration["source"] if declaration is not None else None
            self._advance_native(run, entry, soil_nitrogen_preapplied=bool(nitrogen_events))
            self._mirror(physics, rid, run, day, values)
        self._last_day = day
        return self._soil_results(physics, day)

    @staticmethod
    def _stage(dvs: float) -> SoybeanStage:
        thresholds = ((2, SoybeanStage.R8), (1.85, SoybeanStage.R7), (1.6, SoybeanStage.R6),
                      (1.4, SoybeanStage.R5), (1.2, SoybeanStage.R3), (1, SoybeanStage.R1),
                      (.45, SoybeanStage.V4_PLUS), (.35, SoybeanStage.V3), (.25, SoybeanStage.V2),
                      (.15, SoybeanStage.V1), (.07, SoybeanStage.VC), (0, SoybeanStage.VE))
        return next((stage for limit, stage in thresholds if dvs >= limit), SoybeanStage.PLANTED_PRE_EMERGENCE)

    def _mirror(self, physics: Any, rid: int, run: _RidgeRun, day: date, weather: Mapping[str, Any]) -> None:
        values = run.pcse
        phen, soil, canopy = (physics.phenology.states[rid], physics.soil.states[rid], physics.canopy.states[rid])
        dvs = float(values.get("DVS") or 0)
        if phen.planted:
            phen.stage = self._stage(dvs)
            phen.emerged = dvs >= 0
            phen.days_after_planting = (day - date.fromisoformat(run.specification["planting_date"])).days + 1
            # PCSE labels the integration boundary as tomorrow; FAIRY reports
            # the completed forcing day that produced the event.
            phen.emergence_date = (values["DOE"] - timedelta(days=1)) if values.get("DOE") else None
            phen.maturity_date = (values["DOM"] - timedelta(days=1)) if values.get("DOM") else None
            # Diagnostics use native thermal time, not the legacy GDD10 budget.
            previous = phen.accumulated_gdd
            phen.accumulated_gdd = float(values.get("TSUM") or 0) + float(values.get("TSUME") or 0)
            phen.effective_development_gdd = float(values.get("TSUM") or 0)
            phen.last_daily_gdd = max(0., phen.accumulated_gdd - previous)
            phen.last_effective_gdd = phen.last_daily_gdd
            phen.last_photoperiod_multiplier = 1.0
            phen.last_stress_multiplier = 1.0
            phen.tags = list(dict.fromkeys(phen.tags + ["wofost_native_DVS", "wofost_thermal_time_not_legacy_gdd",
                                                       "DVS_to_soybean_stage_approximation", "uncalibrated_cultivar"]))
            canopy.initialized = phen.emerged
            canopy.seed_type = CanopySeedType(run.specification["seed_type"])
            if canopy.initialized:
                canopy.lai = max(0., float(values.get("LAI") or 0))
                canopy.canopy_cover = 1 - math.exp(-.6 * canopy.lai)
                canopy.aboveground_biomass_g_m2 = max(0., float(values.get("TAGP") or 0) * .1)
                canopy.yield_potential_g_m2 = max(0., float(values.get("TWSO") or 0) * .1)
                canopy.ndvi_proxy = .18 + .7 * (1 - math.exp(-.65 * canopy.lai))
                canopy.cumulative_stress_days += 1 - float(values.get("RFTRA") or 0)
            coupling_tag = ("wofost_empirical_biotic_assimilation_coupling" if self.config.external_biotic_coupling
                            else "wofost_biotic_assimilation_coupling_disabled")
            canopy.tags = list(dict.fromkeys(canopy.tags + ["wofost_native_biomass", "density_TDWI_proxy", coupling_tag]))
            management = physics.management.states[rid]
            n_factor = values.get("RFRGRL")
            management.nutrient_stress = (max(0., min(1., float(n_factor)))
                                         if phen.emerged and n_factor is not None else 1.0)
            management.nutrient_index = .35 + .5 * management.nutrient_stress
            management.tags = list(dict.fromkeys(management.tags + ["wofost_native_RFRGRL_nutrition_proxy"]))
        soil.root_vwc = float(values.get("SM") or soil.root_vwc)
        soil.top_vwc = soil.root_vwc
        p = physics.soil.params_for_ridge(rid)
        soil.top_temp_c += p.top_temp_response * (weather["air_temp_mean_c"] - soil.top_temp_c)
        soil.root_temp_c += p.root_temp_response * (weather["air_temp_mean_c"] - soil.root_temp_c)
        for target, source in (("cumulative_runoff_mm", "TSR"), ("cumulative_drainage_mm", "LOSST"),
                               ("cumulative_evap_mm", "EVST"), ("cumulative_transpiration_mm", "WTRAT")):
            if values.get(source) is not None:
                setattr(soil, target, float(values[source]) * 10)
        soil.tags = list(dict.fromkeys(soil.tags + ["wofost_CWB_root_zone_SM",
                                                   "top_vwc_is_root_zone_proxy", "soil_temperature_auxiliary_air_lag"]))

    def _soil_results(self, physics: Any, day: date) -> list[SoilDayResult]:
        result = []
        for rid, soil in physics.soil.states.items():
            p = physics.soil.params_for_ridge(rid)
            run = self._runs.get(rid)
            water = float(run.pcse.get("RFTRA") or 0) if run else max(0., min(1.,
                (soil.root_vwc - p.wilting_point_vwc) / max(1e-9, p.water_stress_vwc - p.wilting_point_vwc)))
            result.append(SoilDayResult(day, rid, soil.top_vwc, soil.root_vwc, soil.top_temp_c,
                soil.root_temp_c, water, soil.root_vwc < p.irrigation_trigger_vwc,
                p.planting_vwc_min <= soil.top_vwc <= p.planting_vwc_max and soil.top_temp_c >= p.planting_temp_min_c,
                "blocked" if soil.top_vwc > p.planting_vwc_too_wet else "good",
                float((run.pcse.get("DTSR") or 0) * 10) if run else 0,
                float((run.pcse.get("LOSS") or 0) * 10) if run else 0,
                float((run.pcse.get("EVS") or 0) * 10) if run else 0,
                float((run.pcse.get("WTRA") or 0) * 10) if run else 0, list(soil.tags)))
        return result

    def snapshot(self) -> dict[str, Any]:
        config = _json_safe(asdict(self.config))
        provenance = {"backend": "wofost", "model": _MODEL,
                      "pcse_version": self._runtime["pcse"].__version__, "adapter_schema": 1,
                      "config": config, "soil_assumptions": self._soil_signature,
                      "crop_data": self._data_provenance,
                      "units": {"water_mm_to_cm": .1, "kg_ha_to_g_m2": .1,
                                "fertilizer": "actual kg/ridge * N fraction / area_m2 * 10000"},
                      "calibration": "uncalibrated", "external_biotic_coupling": "PGASS multiplier before respiration"}
        if self._cultivar_profile is not None:
            provenance["cultivar_profile"] = self._cultivar_profile.provenance()
        if self._cultivar_profiles:
            provenance["cultivar_profiles"] = {
                seed: profile.provenance() for seed, profile in sorted(self._cultivar_profiles.items())}
        if self.config.allow_external_runon:
            provenance["external_runon"] = {
                "source": self.config.external_runon_source,
                "rule": "external_runon_mm=(legacy rainfall_capture_efficiency-1)*unchanged local rain_mm for gains>1",
                "local_rainfall": "native RAIN unchanged; NOTINF=0 for the split ridges",
                "native_TOTIRR": "effective Agent irrigation plus external run-on; do not label all TOTIRR as Agent irrigation",
                "agent_quota": "external run-on never enters management action queues or irrigation quota counters",
                "preplant": "auxiliary-soil external water enters initial SM/WAV; not reapplied as native irrigation",
                "calibration": "unvalidated legacy capture transfer; no spatial catchment hydrology",
            }
        provenance["config_fingerprint"] = hashlib.sha256(json.dumps(provenance, sort_keys=True,
                                                                      separators=(",", ":")).encode()).hexdigest()
        return _json_safe({"backend": "wofost", "config": config, "provenance": provenance,
                           "assumptions": [("Selected cultivar profile is an unvalidated literature transfer; "
                                            "local cultivar calibration has not been established"
                                            if self._cultivar_profile is not None or self._cultivar_profiles else
                                            "European soybean defaults; Chinese seed labels uncalibrated unless explicitly configured"),
                             "Density changes TDWI initial biomass only; no individual plants or row geometry",
                             "A zero stand cannot initialize PCSE; failed stands require replanting before native growth",
                             "DVS-to-VE/R-stage mapping is approximate; DVSEND=2 is required",
                             "CWB root-zone SM is also exposed as top_vwc; no native seed-zone moisture",
                             "Preplant soil/temperature use labeled auxiliary models; preplant N enters native pool at sowing",
                             "Fertilizer defaults to 46% N and 70% recovery; configure actual product",
                             "Biotic stress empirically scales native PGASS before carbon allocation",
                             "Biotic treatment has no separate direct native LAI deletion; LAI responds through native growth",
                             "Scouting changes observations and time, not native crop health",
                             "Residue incorporation is an audit action; soil organic carbon and residue-N mineralization are not modeled",
                             "Replanting and rotation after native sowing require a new native season",
                             "Native crop yield freezes at maturity; FAIRY late-harvest/storage losses remain downstream",
                             "Events are exposed on completed forcing day; PCSE integration boundary is the next day",
                             *(["Explicit external run-on is a declared external water source, not extra rainfall or Agent irrigation"]
                               if self.config.allow_external_runon else [])],
                           "last_day": self._last_day,
                           "ridges": {rid: {"dvs": run.pcse.get("DVS"), "pcse": run.pcse,
                             "specification": run.specification, "last_day": run.last_day,
                             "native_model_day": run.model.day,
                             "maturity_snapshot": run.maturity_snapshot, "last_native_inputs": run.last_native_inputs,
                             "cumulative_irrigation_mm": run.cumulative_irrigation_mm,
                             "cumulative_fertilizer_kg": run.cumulative_fertilizer_kg,
                             "cumulative_n_kg_ha": run.cumulative_n_kg_ha,
                             **({"cumulative_external_soil_n_delta_kg_ha": run.cumulative_external_soil_n_delta_kg_ha,
                                 "soil_nitrogen_changes": [change for entry in run.journal
                                     for change in entry.get("soil_nitrogen_changes", [])]
                                     + [record["change"] for record in self._pending_soil_nitrogen.get(rid, [])],
                                 "soil_nitrogen": self.native_soil_nitrogen([rid])[rid]}
                                if self._soil_nitrogen_events else {}),
                             **({"cumulative_external_runon_mm": run.cumulative_external_runon_mm,
                                 "cumulative_native_management_effective_irrigation_mm": run.cumulative_native_management_effective_irrigation_mm,
                                 "native_TOTIRR_balance_error_mm": (float(run.pcse.get("TOTIRR") or 0) * 10
                                     - run.cumulative_native_management_effective_irrigation_mm - run.cumulative_external_runon_mm)}
                                if self.config.allow_external_runon else {})}
                             for rid, run in self._runs.items()}, "pending_native_inputs": self._pending,
                           "preplant_inputs": self._preplant_totals,
                           **({"preplant_external_runon_inputs": self._preplant_external_runon_inputs}
                              if self.config.allow_external_runon else {})})

    def export_state(self) -> dict[str, Any]:
        state = {"schema": 1, "pcse_version": self._runtime["pcse"].__version__,
                           "crop_data_sha256": self._data_provenance["sha256"],
                           "config": asdict(self.config), "last_day": self._last_day,
                           "soil_signature": self._soil_signature, "pending": self._pending,
                           "preplant_totals": self._preplant_totals,
                           "runs": {rid: {"specification": run.specification, "journal": run.journal}
                                    for rid, run in self._runs.items()}}
        if self._cultivar_profile is not None:
            state["cultivar_profile"] = self._cultivar_profile.provenance()
        if self._cultivar_profiles:
            state["cultivar_profiles"] = {
                seed: profile.provenance() for seed, profile in sorted(self._cultivar_profiles.items())}
        if self.config.allow_external_runon:
            state["preplant_external_runon_inputs"] = self._preplant_external_runon_inputs
        if self._soil_nitrogen_events:
            state["soil_nitrogen_events"] = self._soil_nitrogen_events
            state["pending_soil_nitrogen"] = self._pending_soil_nitrogen
        return _json_safe(state)

    @classmethod
    def from_state(cls, payload: Mapping[str, Any]) -> "WofostBackend":
        if payload.get("schema") != 1:
            raise ValueError("Unsupported WOFOST checkpoint schema")
        backend = cls(WofostConfig(**copy.deepcopy(payload["config"])))
        if payload.get("pcse_version") != backend._runtime["pcse"].__version__:
            raise ValueError("WOFOST checkpoint PCSE version does not match the installed native runtime")
        if payload.get("crop_data_sha256") != backend._data_provenance["sha256"]:
            raise ValueError("WOFOST checkpoint crop data does not match the bundled offline parameters")
        profile = backend._cultivar_profile.provenance() if backend._cultivar_profile is not None else None
        if payload.get("cultivar_profile") != profile:
            raise ValueError("WOFOST checkpoint cultivar profile does not match the bundled version "
                             "and research provenance")
        profiles = {seed: profile.provenance() for seed, profile in sorted(backend._cultivar_profiles.items())}
        if payload.get("cultivar_profiles", {}) != profiles:
            raise ValueError("WOFOST checkpoint per-seed cultivar profiles do not match bundled research provenance")
        backend._soil_signature = copy.deepcopy(payload.get("soil_signature", {}))
        for rid, saved in payload.get("runs", {}).items():
            journal = saved["journal"]
            if not journal:
                continue
            run = backend._create_run(saved["specification"], journal[0]["weather"], journal[0]["humidity_pct"])
            for entry in journal:
                backend._advance_native(run, entry)
            backend._runs[int(rid)] = run
        backend._pending = {int(rid): dict(values) for rid, values in payload.get("pending", {}).items()}
        backend._soil_nitrogen_events = copy.deepcopy(payload.get("soil_nitrogen_events", {}))
        backend._pending_soil_nitrogen = {
            int(rid): copy.deepcopy(events) for rid, events in payload.get("pending_soil_nitrogen", {}).items()
        }
        # A checkpoint can fall after an event became publicly observable but
        # before its physical day was integrated. Restore those live pool edits
        # now; the next growth call must not apply them a second time.
        for rid, records in backend._pending_soil_nitrogen.items():
            run = backend._runs[rid]
            entry = dict(day=run.model.day.isoformat(),
                soil_nitrogen_events=[record["event"] for record in records],
                soil_nitrogen_changes=[record["change"] for record in records])
            changes = backend._apply_soil_nitrogen_events(run, entry)
            run.pcse["NAVAIL"] = run.model.soil.nutrientbalance.states.NAVAIL
            run.cumulative_external_soil_n_delta_kg_ha += sum(change["external_n_delta_kg_ha"] for change in changes)
            run.last_soil_nitrogen_event_day = run.model.day
        backend._preplant_totals = {int(rid): dict(values) for rid, values in payload.get("preplant_totals", {}).items()}
        backend._preplant_external_runon_inputs = {
            int(rid): copy.deepcopy(rows) for rid, rows in payload.get("preplant_external_runon_inputs", {}).items()
        }
        if backend._preplant_external_runon_inputs and not backend.config.allow_external_runon:
            raise ValueError("Preplant external run-on checkpoint requires explicit source permission")
        backend._last_day = date.fromisoformat(payload["last_day"]) if payload.get("last_day") else None
        return backend

    def __deepcopy__(self, memo: dict[int, Any]) -> "WofostBackend":
        # Never copy a kiosk or dispatcher registration; each replay creates
        # fresh native objects scoped to a distinct PCSE sender.
        clone = self.from_state(self.export_state())
        memo[id(self)] = clone
        return clone
