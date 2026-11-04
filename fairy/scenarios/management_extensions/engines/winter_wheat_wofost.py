"""Native PCSE6/WOFOST8.1 winter wheat with queued daily management.

Reuse FAIRY's deferred-rate factory to align native rates with explicit actions.
Growth uses the original Wofost81_NWLP_CWB_CNB model; there is no synthetic fallback.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import json
import math
from pathlib import Path

from .winter_wheat_inputs import (
    Season,
    WeatherSeries,
    fingerprint,
    json_safe,
    number,
    stage_from_native,
    validate_wheat_parameters,
    verified_file,
)

STATE_VARS = (
    "DVS",
    "TSUM",
    "TSUME",
    "LAI",
    "TAGP",
    "TWSO",
    "TWLV",
    "TWST",
    "TWRT",
    "RD",
    "SM",
    "NAVAIL",
    "NuptakeTotal",
    "NfixTotal",
    "DOE",
    "DOA",
    "DOM",
    "VERN",
    "ISVERNALISED",
    "DOV",
    "TOTIRR",
    "TSR",
    "PERCT",
    "LOSST",
)
SOIL_VARS = {"SM", "NAVAIL", "TOTIRR", "TSR", "PERCT", "LOSST"}


class InputBundle:
    def __init__(self, root: str | Path, *, late_harvest: bool = False):
        self.root = Path(root).resolve()
        self.manifest = json.loads(
            (self.root / "manifest.json").read_text(encoding="utf-8")
        )
        if self.manifest.get("schema") != "fairy.winter_wheat.inputs.v1":
            raise ValueError("Unsupported wheat input manifest")
        m = self.manifest
        extension = m.pop("late_harvest", None)
        self.weather = WeatherSeries.from_csv(verified_file(self.root, m["weather"]))
        if late_harvest:
            if extension is None:
                raise ValueError("The wheat inputs have no late-harvest weather")
            extra_weather = WeatherSeries.from_csv(
                verified_file(self.root, extension["weather"])
            )
            self.weather = WeatherSeries(
                [*self.weather.rows.values(), *extra_weather.rows.values()]
            )
            m["season"]["deadline"] = extension["deadline"]
            m["late_harvest"] = extension
        self.season = Season(
            **{
                k: date.fromisoformat(v) if k != "timezone" else v
                for k, v in m["season"].items()
            }
        )
        self.weather.require(
            self.season.start, self.season.deadline + timedelta(days=1)
        )
        self.crop_file = verified_file(self.root, m["crop"])
        self.cultivar = m["crop"]["cultivar"]
        self.identity = fingerprint(m)
        self.latitude = number(
            m["site"]["latitude"], "latitude", minimum=-89, maximum=89
        )
        self.longitude = number(
            m["site"]["longitude"], "longitude", minimum=-180, maximum=180
        )
        self.elevation = number(
            m["site"]["elevation_m"], "elevation", minimum=-400, maximum=5000
        )
        if m.get("parameter_status") not in {
            "uncalibrated_reference",
            "locally_calibrated",
        }:
            raise ValueError("Explicit parameter calibration status is required")
        if m["parameter_status"] == "locally_calibrated" and not m.get(
            "calibration_report"
        ):
            raise ValueError(
                "Locally calibrated parameters require a declared calibration report"
            )


class WinterWheatBackend:
    """One management block, one cross-year crop, continuous soil and daily inputs."""

    def __init__(self, bundle: InputBundle):
        from fairy.physics.wofost_backend import _load_runtime

        self.bundle = bundle
        self.runtime = r = _load_runtime()
        self.version = str(r["pcse"].__version__)
        raw = r["yaml"].safe_load(bundle.crop_file.read_bytes())
        varieties = raw["CropParameters"]["Varieties"]
        if bundle.cultivar not in varieties:
            raise ValueError(f"Unknown wheat variety: {bundle.cultivar}")
        self.parameters = {
            k: deepcopy(v[0])
            for k, v in varieties[bundle.cultivar].items()
            if k != "Metadata"
        }
        overrides = bundle.manifest["crop"].get("parameter_overrides", {})
        if overrides and not bundle.manifest["crop"].get("override_provenance"):
            raise ValueError(
                "Parameter overrides require provenance, not a calibration claim"
            )
        self.parameters.update(deepcopy(overrides))
        validate_wheat_parameters(self.parameters)
        self.parameter_hash = fingerprint(self.parameters)
        site = r["SiteProvider"](**bundle.manifest["native_site_parameters"])
        provider = r["ParameterProvider"](
            cropdata=self.parameters,
            soildata=deepcopy(bundle.manifest["native_soil_parameters"]),
            sitedata=site,
        )
        self.weather_provider = r["WeatherDataProvider"]()
        for day in sorted(bundle.weather.rows):
            self.weather_provider._store_WeatherDataContainer(
                self._weather_container(day), day
            )
        # Keep a later campaign: otherwise crop_finish terminates soil simulation.
        # Actual crop_start is sent on the AGENT'S sowing date, not baked into agro.
        season = bundle.season
        agro = [
            {
                season.start: {
                    "CropCalendar": None,
                    "TimedEvents": None,
                    "StateEvents": None,
                }
            },
            {season.deadline + timedelta(days=366): None},
        ]
        self.model = r["Model"](
            provider,
            self.weather_provider,
            agro,
            output_vars=list(STATE_VARS),
            summary_vars=list(STATE_VARS),
        )
        self.next_day = season.start
        if self.model.day != self.next_day:
            raise RuntimeError("Native/model calendar initialization mismatch")
        self.pending: list[dict] = []
        self.journal: list[dict] = []
        self.receipts: dict[str, dict] = {}
        self.sown = False
        self.maturity: dict | None = None
        self.failed: str | None = None
        self.values = self._read_values()
        self.efficiency = number(
            bundle.manifest["management"]["irrigation_efficiency"],
            "efficiency",
            minimum=0.001,
            maximum=1,
        )
        self.n_recovery = number(
            bundle.manifest["management"]["nitrogen_recovery_fraction"],
            "N recovery",
            minimum=0.001,
            maximum=1,
        )

    def _weather_container(self, day: date):
        w, b, r = self.bundle.weather[day], self.bundle, self.runtime
        vap = 6.108 * math.exp(17.27 * w.tmean_c / (w.tmean_c + 237.3)) * w.rh_pct / 100
        args = dict(
            DAY=day,
            LAT=b.latitude,
            ELEV=b.elevation,
            TMIN=w.tmin_c,
            TMAX=w.tmax_c,
            IRRAD=w.radiation_mj_m2 * 1e6,
            VAP=max(0.06, vap),
            WIND=w.wind_2m_m_s,
        )
        e0, es0, et0 = r["reference_ET"](**args, ANGSTA=0.29, ANGSTB=0.49, ETMODEL="PM")
        return r["WeatherDataContainer"](
            **args,
            LON=b.longitude,
            TEMP=w.tmean_c,
            RAIN=w.rain_mm / 10,
            E0=e0 / 10,
            ES0=es0 / 10,
            ET0=et0 / 10,
        )

    def _read_values(self) -> dict:
        return json_safe({k: self.model.get_variable(k) for k in STATE_VARS})

    def queue(self, operation_id: str, kind: str, amount: float = 0.0) -> dict:
        if self.failed:
            raise RuntimeError(f"Backend invalid after native error: {self.failed}")
        if kind not in {"sow", "irrigate", "fertilize"}:
            raise ValueError("Unsupported native wheat action")
        amount = number(amount, "amount", minimum=0)
        item = {
            "id": operation_id,
            "kind": kind,
            "amount": amount,
            "day": self.next_day.isoformat(),
        }
        if operation_id in self.receipts:
            previous = self.receipts[operation_id]
            if previous["kind"] != kind or previous["amount"] != amount:
                raise ValueError("Operation ID reused with different content")
            return deepcopy(previous)
        if self.maturity is not None and kind == "sow":
            raise ValueError("This one-crop block has already completed its crop")
        if kind == "sow":
            self.bundle.season.check_sowing(self.next_day)
            if self.sown or any(a["kind"] == "sow" for a in self.pending):
                raise ValueError("This field has already been sown")
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("A nonempty operation ID is required")
        if (kind == "sow" and amount != 0) or (kind != "sow" and amount <= 0):
            raise ValueError(
                "Sowing takes no dose; water and nitrogen doses must be positive"
            )
        self.pending.append(item)
        self.receipts[operation_id] = item
        return deepcopy(item)

    def advance_day(self) -> dict:
        if self.failed:
            raise RuntimeError(f"Invalid backend: {self.failed}")
        day = self.next_day
        if day > self.bundle.season.deadline:
            raise ValueError("Season deadline exceeded")
        self.bundle.weather.require(day, day + timedelta(days=1))
        if self.model.day != day:
            raise RuntimeError("Native clock drift; refusing to integrate twice")
        actions = deepcopy(self.pending)
        try:
            self.model.drv = self.model._get_driving_variables(day)
            signals = self.runtime["signals"]
            if any(a["kind"] == "sow" for a in actions):
                self.model._send_signal(
                    signal=signals.crop_start,
                    day=day,
                    crop_name="wheat",
                    variety_name=self.bundle.cultivar,
                    crop_start_type="sowing",
                    crop_end_type="maturity",
                )
                self.sown = True
            # PCSE event handlers store a daily rate; send each kind ONCE to
            # prevent the last of several same-day actions overwriting the rest.
            water = sum(a["amount"] for a in actions if a["kind"] == "irrigate")
            nitrogen = sum(a["amount"] for a in actions if a["kind"] == "fertilize")
            if water:
                self.model._send_signal(
                    signal=signals.irrigate,
                    amount=water / 10,
                    efficiency=self.efficiency,
                )
            if nitrogen:
                self.model._send_signal(
                    signal=signals.apply_n,
                    N_amount=nitrogen,
                    N_recovery=self.n_recovery,
                )
            self.model.calculate_current_day()
            self.model.run(days=1)
            if self.model.day != day + timedelta(days=1):
                raise RuntimeError(
                    "Native model stopped early or integrated the wrong interval"
                )
            values = self._read_values()
            if self.maturity is None and values.get("DOM") is not None:
                self.maturity = deepcopy(values)
            if self.sown and self.model.crop is None and self.maturity is None:
                raise RuntimeError("Crop terminated without a native maturity record")
            if self.maturity:
                for key in STATE_VARS:
                    if key not in SOIL_VARS:
                        values[key] = self.maturity.get(key)
            self.values = values
            self.next_day += timedelta(days=1)
            self.journal.append({"day": day.isoformat(), "actions": actions})
            self.pending.clear()
            return self.snapshot()
        except Exception as exc:
            # Do not silently reuse partially mutated PCSE state after failure.
            self.failed = f"{type(exc).__name__}: {exc}"
            raise

    def snapshot(self) -> dict:
        return {
            "backend": "Wofost81_NWLP_CWB_CNB",
            "pcse_version": self.version,
            "state_at_start_of": self.next_day.isoformat(),
            "stage": stage_from_native(self.values, sown=self.sown),
            "values": deepcopy(self.values),
            "pending_actions": deepcopy(self.pending),
            "input_fingerprint": self.bundle.identity,
            "parameter_sha256": self.parameter_hash,
            "parameter_status": self.bundle.manifest["parameter_status"],
            "native_error": self.failed,
        }

    def export_state(self) -> dict:
        return {
            "schema": "fairy.winter_wheat.native_checkpoint.v1",
            "input_fingerprint": self.bundle.identity,
            "pcse_version": self.version,
            "journal": deepcopy(self.journal),
            "pending": deepcopy(self.pending),
            "snapshot_sha256": fingerprint(self.snapshot()),
        }

    @classmethod
    def restore(cls, bundle: InputBundle, state: dict) -> "WinterWheatBackend":
        if state.get("schema") != "fairy.winter_wheat.native_checkpoint.v1":
            raise ValueError("Unsupported native checkpoint")
        if state["input_fingerprint"] != bundle.identity:
            raise ValueError("Checkpoint input mismatch")
        result = cls(bundle)
        if result.version != state["pcse_version"]:
            raise ValueError("Replay requires the same PCSE version")
        for entry in state["journal"]:
            if entry["day"] != result.next_day.isoformat():
                raise ValueError("Checkpoint day missing or duplicated")
            for a in entry["actions"]:
                if a["day"] != entry["day"]:
                    raise ValueError("Checkpoint action date mismatch")
                result.queue(a["id"], a["kind"], a["amount"])
            result.advance_day()
        for a in state["pending"]:
            if a["day"] != result.next_day.isoformat():
                raise ValueError("Pending checkpoint action date mismatch")
            result.queue(a["id"], a["kind"], a["amount"])
        if fingerprint(result.snapshot()) != state["snapshot_sha256"]:
            raise RuntimeError(
                "Native deterministic replay did not reproduce saved state"
            )
        return result
