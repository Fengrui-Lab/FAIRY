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
from .crop_profiles import get_crop_profile, maize_yield_parameters

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
    variety_name: str | None = None
    cultivar_map: dict[str, str] = field(default_factory=dict)
    # Named literature transfer, scoped to the seed labels listed in its file.
    # Omission preserves the existing European default for every cultivar.
    cultivar_profile: str | None = None
    # Keys are FAIRY SeedType values (or '*' for all seeds), values native PCSE
    # crop parameters. No legacy GDD/stress coefficients are auto-converted.
    parameter_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Migration guard: an explicit assignment is not proof of calibration,
    # but prevents distinct FAIRY seed labels silently sharing the default.
    require_explicit_cultivar_parameters: bool = False
    fertilizer_n_fraction: float = 0.46
    fertilizer_n_recovery: float = 0.7
    irrigation_efficiency: float = 0.92
    reference_density_plants_m2: float | None = None
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
    external_biotic_coupling: bool | None = None

    def __post_init__(self) -> None:
        profile = get_crop_profile(self.crop_name)
        if self.variety_name is None:
            self.variety_name = "Grain_maize_201" if self.crop_name == "maize" else "Soybean_901"
        if self.reference_density_plants_m2 is None:
            self.reference_density_plants_m2 = (profile.reference_density_plants_m2
                                                if self.crop_name == "maize" else 40.0)
        if self.external_biotic_coupling is None:
            self.external_biotic_coupling = self.crop_name == "soybean"
        if self.crop_name == "maize":
            if self.cultivar_profile is not None:
                raise ValueError("Soybean cultivar profiles cannot be applied to maize")
            if self.variety_name != "Grain_maize_201":
                raise ValueError("Maize v1 requires variety_name='Grain_maize_201'")
            if self.external_biotic_coupling:
                raise ValueError("Maize v1 requires external_biotic_coupling=False; soybean pests are not adapted")
            if any(seed not in {"*", "MAIZE_201"} for seed in (*self.cultivar_map, *self.parameter_overrides)):
                raise ValueError("Maize configuration only accepts seed MAIZE_201")
            if any(variety != "Grain_maize_201" for variety in self.cultivar_map.values()):
                raise ValueError("Maize v1 only supports Grain_maize_201")
        elif "MAIZE_201" in self.cultivar_map or "MAIZE_201" in self.parameter_overrides:
            raise ValueError("Seed MAIZE_201 does not match WOFOST crop 'soybean'")
        if not isinstance(self.require_explicit_cultivar_parameters, bool):
            raise ValueError("require_explicit_cultivar_parameters must be a boolean")
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

        def __call__(self, day, drv):
            # Empirical pest/weed/disease coupling changes current assimilation
            # before native respiration/partitioning, preserving carbon balance.
            return super().__call__(day, drv) * self.external_factor

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
    last_day: date | None = None


class WofostBackend:
    def __init__(self, config: WofostConfig | Mapping[str, Any] | None = None) -> None:
        self.config = copy.deepcopy(config if isinstance(config, WofostConfig)
                                    else WofostConfig(**dict(config or {})))
        self._cultivar_profile = (load_cultivar_profile(self.config.cultivar_profile)
                                  if self.config.cultivar_profile is not None else None)
        if self._cultivar_profile is not None:
            for seed in self._cultivar_profile.supported_seed_types:
                explicit = self.config.cultivar_map.get(seed)
                if explicit is not None and explicit != self._cultivar_profile.base_variety:
                    raise ValueError(f"cultivar_map[{seed!r}] conflicts with cultivar_profile "
                                     f"base_variety {self._cultivar_profile.base_variety!r}; "
                                     "use parameter_overrides for explicit native parameter changes")
        self._runtime = _load_runtime()
        provenance_file = "maize.provenance.json" if self.config.crop_name == "maize" else "provenance.json"
        self._data_provenance = json.loads((_DATA / provenance_file).read_text())
        content = (_DATA / f"{self.config.crop_name}.yaml").read_bytes()
        if hashlib.sha256(content).hexdigest() != self._data_provenance["sha256"]:
            raise RuntimeError(f"Bundled WOFOST {self.config.crop_name} data failed its SHA-256 integrity check")
        self._varieties = self._runtime["yaml"].safe_load(content)["CropParameters"]["Varieties"]
        self._crop_parameters(self.config.variety_name, "*")  # fail early on invalid configuration
        for seed, variety in self.config.cultivar_map.items():
            self._crop_parameters(variety, seed)
        for seed in self.config.parameter_overrides:
            self._crop_parameters(self._variety_for_seed(seed), seed)
        if self._cultivar_profile is not None:
            for seed in self._cultivar_profile.supported_seed_types:
                self._crop_parameters(self._variety_for_seed(seed), seed)
        self._runs: dict[int, _RidgeRun] = {}
        self._pending: dict[int, dict[str, float]] = {}
        self._preplant_totals: dict[int, dict[str, float]] = {}
        self._last_day: date | None = None
        self._soil_signature: dict[str, Any] = {}

    @property
    def has_started(self) -> bool:
        return self._last_day is not None or bool(self._runs)

    @property
    def last_day(self) -> date | None:
        return self._last_day

    def bind_physics(self, physics: Any) -> None:
        """Record static soil assumptions before any action (for oracle hashes)."""
        if self.config.crop_name == "maize":
            physics.yield_recovery.params = maize_yield_parameters()
        signature = {"parameters": _json_safe(asdict(physics.soil.params)),
                     "hydraulic_modifiers": _json_safe({rid: asdict(value) for rid, value in
                                                        physics.soil.hydraulic_modifiers.items()})}
        if self._soil_signature and signature != self._soil_signature and self.has_started:
            raise ValueError("Cannot change WOFOST soil assumptions after native simulation starts")
        self._soil_signature = signature

    def _require_explicit_cultivar(self, seed: str) -> None:
        if not self.config.require_explicit_cultivar_parameters or seed == "*":
            return
        if ((self._cultivar_profile is not None and self._cultivar_profile.applies_to(seed))
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
        if seed != "*" and (seed == "MAIZE_201") != (self.config.crop_name == "maize"):
            raise ValueError(f"Seed {seed!r} does not match WOFOST crop {self.config.crop_name!r}")
        self._require_explicit_cultivar(seed)
        if self._cultivar_profile is not None and self._cultivar_profile.applies_to(seed):
            return self._cultivar_profile.base_variety
        return self.config.cultivar_map.get(seed, self.config.variety_name)

    def _crop_parameters(self, variety: str, seed: str) -> dict[str, Any]:
        self._require_explicit_cultivar(seed)
        if variety not in self._varieties:
            raise ValueError(f"Unknown bundled WOFOST {self.config.crop_name} variety {variety!r}; "
                             f"available: {', '.join(sorted(self._varieties))}")
        parameters = {key: copy.deepcopy(value[0]) for key, value in self._varieties[variety].items()
                      if key != "Metadata"}
        profile_overrides = (self._cultivar_profile.parameter_overrides
                             if self._cultivar_profile is not None
                             and self._cultivar_profile.applies_to(seed) else {})
        if (self._cultivar_profile is not None and self._cultivar_profile.applies_to(seed)
                and self._cultivar_profile.provenance().get("parameter_set_kind")
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
        agro = [{start: {"CropCalendar": {"crop_name": self.config.crop_name, "variety_name": specification["variety"],
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
        stand = float(physics.management.states[rid].stand_fraction or 1.0)
        crop["TDWI"] *= density / self.config.reference_density_plants_m2 * max(0, min(1, stand))
        p = physics.soil.params_for_ridge(rid)
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
                    NOTINF=1 - p.rainfall_capture_efficiency, SSI=0., SSMAX=0., IFUNRN=0)
        site.update(self.config.site_overrides)
        preplant = self._preplant_totals.get(rid, self._empty_inputs())
        # Preplant fertilizer is sent as a single native apply_n event on the
        # first native day. Do not force it into NAVAILI, whose PCSE provider
        # permits <=250 kg/ha even though real management inputs may exceed it.
        site = dict(self._runtime["SiteProvider"](**site))
        profile = (self._cultivar_profile.provenance() if self._cultivar_profile is not None
                   and self._cultivar_profile.applies_to(seed) else None)
        specification = {"start_date": day.isoformat(), "planting_date": _json_safe(phen.planting_date or day),
                "seed_type": seed, "variety": variety, "crop_parameters": crop,
                "soil_parameters": soil, "site_parameters": site,
                "density_plants_m2": density, "initial_stand_fraction": stand,
                "preplant_inputs": copy.deepcopy(preplant),
                "cultivar_mapping": ("literature_transfer" if profile else
                                     "explicit" if seed in self.config.cultivar_map else "uncalibrated_default"),
                "calibration": "uncalibrated", "density_method": "TDWI_initial_biomass_scaling_only"}
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
        if self.config.crop_name == "maize":
            specification["crop_name"] = "maize"
            specification["cultivar_mapping"] = "explicit_reference_cultivar"
        return specification

    def _advance_native(self, run: _RidgeRun, entry: dict[str, Any]) -> None:
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
        if entry.get("harvested") and model.crop is not None:
            model._send_signal(signal=self._runtime["signals"].crop_finish,
                               day=day, finish_type="harvest", crop_delete=True)
        inputs = entry["inputs"]
        preplant_n = (run.specification.get("preplant_inputs", {}).get("n_kg_ha", 0.0)
                      if not run.journal else 0.0)
        if inputs["irrigation_mm"]:
            model._send_signal(signal=self._runtime["signals"].irrigate,
                               amount=inputs["irrigation_mm"] / 10,
                               efficiency=self.config.irrigation_efficiency)
        if inputs["n_kg_ha"] + preplant_n:
            model._send_signal(signal=self._runtime["signals"].apply_n,
                               N_amount=inputs["n_kg_ha"] + preplant_n,
                               N_recovery=self.config.fertilizer_n_recovery)
        if model.crop is not None:
            model.crop.assim.external_factor = entry["external_growth_factor"]
        model.calculate_current_day()
        # Soil WTRA survives the boundary day's crop deletion; crop TRA may
        # already be absent here. Cache soil fluxes before integration resets rates.
        rates = {name: model.get_variable(name) for name in ("RFTRA", "RFRGRL", "TRA", "WTRA", "EVS", "EVW", "RIRR", "DTSR", "LOSS")}
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
        self.queue_actions(actions_by_ridge or {}, ridge_area_m2)
        values = {name: getattr(weather, name) for name in ("air_temp_min_c", "air_temp_max_c",
                  "air_temp_mean_c", "rain_mm", "solar_rad_mj_m2", "wind_ms")}
        humidity = self.config.relative_humidity_pct if humidity_pct is None else float(humidity_pct)
        for rid, phen in physics.phenology.states.items():
            run = self._runs.get(rid)
            if run is None and phen.planted:
                spec = self._specification(physics, rid, day, (density_by_ridge or {}).get(
                    rid, self.config.reference_density_plants_m2))
                run = self._create_run(spec, values, humidity)
                self._runs[rid] = run
            if run is None:
                inputs = self._pending.pop(rid, self._empty_inputs())
                totals = self._preplant_totals.setdefault(rid, self._empty_inputs())
                for key, value in inputs.items():
                    totals[key] += value
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
            factor = (max(0.35, 1 - 0.28 * biotic.weed_pressure - 0.32 * biotic.insect_pressure
                          - 0.45 * biotic.disease_pressure) if self.config.external_biotic_coupling else 1.0)
            entry = {"day": day.isoformat(), "weather": values, "humidity_pct": humidity,
                     "inputs": self._pending.pop(rid, self._empty_inputs()),
                     "external_growth_factor": factor, "harvested": not phen.planted}
            self._advance_native(run, entry)
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
            if self.config.crop_name == "maize":
                phen.stage = (SoybeanStage.MATURE if values.get("DOM") is not None else
                              SoybeanStage.REPRODUCTIVE if dvs >= 1 else
                              SoybeanStage.VEGETATIVE if dvs >= 0 else
                              SoybeanStage.PLANTED_PRE_EMERGENCE)
            else:
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
            stage_tag = ("native_maize_coarse_stages" if self.config.crop_name == "maize"
                         else "DVS_to_soybean_stage_approximation")
            phen.tags = list(dict.fromkeys(phen.tags + ["wofost_native_DVS", "wofost_thermal_time_not_legacy_gdd",
                                                       stage_tag, "uncalibrated_cultivar"]))
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
        if self.config.crop_name == "maize":
            provenance["external_biotic_coupling"] = "disabled; soybean biotic models are not adapted to maize"
        provenance["config_fingerprint"] = hashlib.sha256(json.dumps(provenance, sort_keys=True,
                                                                      separators=(",", ":")).encode()).hexdigest()
        return _json_safe({"backend": "wofost", "config": config, "provenance": provenance,
                           "assumptions": [("Selected cultivar profile is an unvalidated literature transfer; "
                                            "local cultivar calibration has not been established"
                                            if self._cultivar_profile is not None else
                                            "European maize reference cultivar; not calibrated for Northeast China"
                                            if self.config.crop_name == "maize" else
                                            "European soybean defaults; Chinese seed labels uncalibrated unless explicitly configured"),
                             "Density changes TDWI initial biomass only; no individual plants or row geometry",
                             ("Coarse maize stages: emergence, DVS=1 reproductive transition, native DOM maturity; no leaf-number inference"
                              if self.config.crop_name == "maize" else
                              "DVS-to-VE/R-stage mapping is approximate; DVSEND=2 is required"),
                             "CWB root-zone SM is also exposed as top_vwc; no native seed-zone moisture",
                             "Preplant soil/temperature use labeled auxiliary models; preplant N enters native pool at sowing",
                             "Fertilizer defaults to 46% N and 70% recovery; configure actual product",
                             ("Soybean pests, diseases and weeds are disabled for maize v1"
                              if self.config.crop_name == "maize" else
                              "Biotic stress empirically scales native PGASS before carbon allocation"),
                             "Native crop yield freezes at maturity; FAIRY late-harvest/storage losses remain downstream",
                             "Events are exposed on completed forcing day; PCSE integration boundary is the next day"],
                           "last_day": self._last_day,
                           "ridges": {rid: {"dvs": run.pcse.get("DVS"), "pcse": run.pcse,
                             "specification": run.specification, "last_day": run.last_day,
                             "native_model_day": run.model.day,
                             "maturity_snapshot": run.maturity_snapshot, "last_native_inputs": run.last_native_inputs,
                             "cumulative_irrigation_mm": run.cumulative_irrigation_mm,
                             "cumulative_fertilizer_kg": run.cumulative_fertilizer_kg,
                             "cumulative_n_kg_ha": run.cumulative_n_kg_ha}
                             for rid, run in self._runs.items()}, "pending_native_inputs": self._pending,
                           "preplant_inputs": self._preplant_totals})

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
        backend._preplant_totals = {int(rid): dict(values) for rid, values in payload.get("preplant_totals", {}).items()}
        backend._last_day = date.fromisoformat(payload["last_day"]) if payload.get("last_day") else None
        return backend

    def __deepcopy__(self, memo: dict[int, Any]) -> "WofostBackend":
        # Never copy a kiosk or dispatcher registration; each replay creates
        # fresh native objects scoped to a distinct PCSE sender.
        clone = self.from_state(self.export_state())
        memo[id(self)] = clone
        return clone
