"""Offline transplant-start WOFOST adapter with a continuous paddy water ledger."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path

from fairy.physics.simulation_unit import SimulationUnit

DATA = Path(__file__).with_name("data") / "wofost" / "rice"
SCHEMA = 2
CROP_VARIABLES = ("DVS", "LAI", "TAGP", "TWSO", "TWLV", "TWST", "TWRT", "RD", "DOE", "DOA", "DOM")


def json_safe(value):
    return json.loads(json.dumps(value, default=lambda x: x.isoformat()))


def load_rice_parameters():
    try:
        import pcse
        import yaml
    except ImportError as exc:
        raise RuntimeError("Rice requires PCSE 6.0.x: pip install -e '.[wofost]'") from exc
    if not pcse.__version__.startswith("6.0."):
        raise RuntimeError("Rice adapter requires PCSE 6.0.x")
    source = json.loads((DATA / "provenance.json").read_text())
    raw = (DATA / "rice.yaml").read_bytes()
    if hashlib.sha256(raw).hexdigest() != source["sha256"]:
        raise ValueError("Bundled rice parameter checksum mismatch")
    tree = yaml.safe_load(raw)["CropParameters"]
    variety = tree["Varieties"]["Rice_IR72"]
    crop = {key: copy.deepcopy(value[0]) for key, value in variety.items() if key != "Metadata"}
    raw_completion = (DATA / "ir72_wofost81_completion_v1.json").read_bytes()
    completion = json.loads(raw_completion)
    # Make the derivation executable and reject unnoticed upstream changes.
    if set(crop["AMAXTB"][1::2]) != {completion["parameters"]["AMAX_REF"]}:
        raise ValueError("IR72 assimilation-cap derivation no longer matches upstream")
    if tree["EcoTypes"]["rice_eu"]["KN"][0] != completion["parameters"]["KN"]:
        raise ValueError("Rice KN transfer no longer matches its declared source")
    crop.update(completion["parameters"])
    source["completion"] = {**completion, "sha256": hashlib.sha256(raw_completion).hexdigest()}
    return crop, source


def weather_container(day, values, latitude=14.2, longitude=121.2):
    from pcse.base import WeatherDataContainer
    from pcse.util import reference_ET
    tmin, tmax = values["tmin_c"], values["tmax_c"]
    rh = values["humidity_pct"]
    if not all(math.isfinite(v) for v in values.values()) or not 0 < rh <= 100 or tmin > tmax:
        raise ValueError("Invalid rice daily weather")
    if min(values["rain_mm"], values["radiation_mj_m2"], values["wind_ms"]) < 0:
        raise ValueError("Rain, radiation and wind must be nonnegative")
    temp = (tmin + tmax) / 2
    vap = 6.108 * math.exp(17.27 * temp / (temp + 237.3)) * rh / 100
    rad = values["radiation_mj_m2"] * 1e6
    e0, es0, et0 = reference_ET(DAY=day, LAT=latitude, ELEV=20, TMIN=tmin,
        TMAX=tmax, IRRAD=rad, VAP=vap, WIND=values["wind_ms"], ANGSTA=.29, ANGSTB=.49, ETMODEL="PM")
    return WeatherDataContainer(DAY=day, LAT=latitude, LON=longitude, ELEV=20,
        TMIN=tmin, TMAX=tmax, TEMP=temp, IRRAD=rad, VAP=vap,
        RAIN=values["rain_mm"] / 10, WIND=values["wind_ms"],
        E0=e0 / 10, ES0=es0 / 10, ET0=et0 / 10)


class RiceWofostBackend:
    """One native engine per hydraulic plot; soil runs before transplanting.

    Recorded metering/preparation/transplant/daily events are the checkpoint.
    No pickle or partial DVS-only state restoration is supported.
    """
    def __init__(self, unit: SimulationUnit, start_date: str, soil: dict, first_weather: dict,
                 parameter_overrides: dict | None = None):
        crop, source = load_rice_parameters()
        overrides = copy.deepcopy(parameter_overrides or {})
        if set(overrides) - {"AMAX_REF", "KN"} or any(not math.isfinite(v) or v <= 0 for v in overrides.values()):
            raise ValueError("Rice sensitivity overrides support positive AMAX_REF and KN only")
        crop.update(overrides)
        import pcse
        from pcse import signals
        from pcse.base import ParameterProvider, WeatherDataProvider
        from pcse.engine import Engine
        from pcse.crop.assimilation import WOFOST81_Assimilation
        from pcse.traitlets import Float

        class RiceStressAssimilation(WOFOST81_Assimilation):
            external_factor = Float(1.)

            def __call__(self, day, drv):
                return super().__call__(day, drv) * self.external_factor

        class DeferredModel(Engine):
            def calc_rates(self, day, drv):
                pass

            def calculate_current_day(self):
                super().calc_rates(self.day, self.drv)

        self.unit, self.source = unit, source
        self.specification = {"unit": vars(unit), "start_date": start_date,
                              "soil": copy.deepcopy(soil), "first_weather": copy.deepcopy(first_weather),
                              "parameter_overrides": overrides}
        self.signals = signals
        self.journal = []
        self.transplant_date = None
        self.maturity = None
        self.crop_values = {}
        self.last_rates = {}
        self.external_factor = 1.
        self._assimilation_class = RiceStressAssimilation
        day = date.fromisoformat(start_date)
        sm = soil["initial_vwc"]
        if not 0 <= soil["SMW"] < soil["SMFCF"] < soil["SM0"] <= 1 or not soil["SMW"] <= sm <= soil["SM0"]:
            raise ValueError("Invalid paddy soil moisture parameters")
        for key in ("SOPE", "KSUB", "RDMSOL"):
            if not math.isfinite(soil[key]) or soil[key] <= 0:
                raise ValueError(f"Invalid soil {key}")
        if (soil["RDMSOL"] < crop["RDI"] or not math.isfinite(soil["bund_height_mm"])
                or soil["bund_height_mm"] <= 0):
            raise ValueError("Soil depth must accommodate initial roots; bund must be positive")
        site = {"WAV": (sm - soil["SMW"]) * soil["RDMSOL"], "SMLIM": sm,
                "SSI": 0., "SSMAX": soil["bund_height_mm"] / 10,
                "IFUNRN": 0, "NOTINF": 0., "CO2": 420.}
        for key, default in {"NAVAILI": 30., "NSOILBASE": 40., "NSOILBASE_FR": .005, "BG_N_SUPPLY": .05}.items():
            value = soil.get(key, default)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid soil nitrogen {key}")
            site[key] = value
        self.provider = WeatherDataProvider()
        self.provider._store_WeatherDataContainer(weather_container(day, first_weather), day)
        self.parameters = ParameterProvider(cropdata=crop,
            soildata={k: v for k, v in soil.items() if k not in {
                "initial_vwc", "bund_height_mm", "NAVAILI", "NSOILBASE", "NSOILBASE_FR", "BG_N_SUPPLY"}},
            sitedata=site)
        self.model = DeferredModel(self.parameters, self.provider,
            [{day: {"CropCalendar": None, "TimedEvents": None, "StateEvents": None}},
             {day + timedelta(days=730): None}], config=str(DATA / "Paddy81.conf"))
        self.provenance = {"backend": "wofost", "model": "Wofost81_NWLP_PADDY",
            "pcse_version": pcse.__version__, "adapter_schema": SCHEMA,
            "crop_data": source, "nutrients": "native_classic_N_bucket; empirical_transport_v1",
            "nitrogen_loss": "fertilizer_recovery_0.7; transport=min(0.1,outgoing_mm*0.0005)*NAVAIL",
            "external_stress": "empirical_stand_and_biotic_PGASS_multiplier_v1",
            "crop_start_type": "emergence",
            "hydrology": "ponded_two_zone_CWB_extension", "density_response": "not_modelled",
            "stage_mapping": "management_proxy_v1", "calibration": "uncalibrated_transfer",
            "parameter_overrides": overrides}

    @property
    def water(self):
        return self.model.soil.waterbalance

    @property
    def nitrogen(self):
        return self.model.soil.nutrientbalance

    def apply(self, kind, **values):
        """Replayable model mutation; daily forcing is required in sequence."""
        if kind == "water":
            before = self.water.ledger()["overflow_mm"]
            result = self.water.meter_water(values["amount_mm"], drain=values.get("drain", False),
                                            leak=values.get("leak", False))
            outgoing = result if values.get("drain", False) else self.water.ledger()["overflow_mm"] - before
            self.nitrogen.transport(outgoing)
        elif kind == "fertilize":
            self.nitrogen.fertilize(values["n_kg_ha"], values.get("recovery", .7))
            result = self.nitrogen.audit()
        elif kind == "stress":
            factor = values["factor"]
            if not math.isfinite(factor) or not 0 <= factor <= 1:
                raise ValueError("External rice stress factor must be in [0,1]")
            self.external_factor = factor
            result = None
        elif kind == "puddle":
            self.water.puddle(values["sope_cm_day"], values["ksub_cm_day"])
            result = None
        elif kind == "transplant":
            if self.transplant_date is not None:
                raise ValueError("A paddy plot supports one transplant per season")
            if date.fromisoformat(values["day"]) != self.model.day:
                raise ValueError("Transplant must use the current model date")
            self.model._send_signal(self.signals.crop_start, day=self.model.day,
                crop_name="rice", variety_name="Rice_IR72", crop_start_type="emergence",
                crop_end_type="maturity")
            self.transplant_date = values["day"]
            self.model.crop.assim = self._assimilation_class(self.model.day, self.model.kiosk, self.parameters)
            self._read_crop()
            result = None
        elif kind == "day":
            day = date.fromisoformat(values["day"])
            if day != self.model.day:
                raise ValueError("Rice WOFOST requires consecutive daily forcing")
            drv = weather_container(day, values["weather"])
            self.provider._store_WeatherDataContainer(drv, day)
            tomorrow = day + timedelta(days=1)
            self.provider._store_WeatherDataContainer(weather_container(tomorrow, values["weather"]), tomorrow)
            self.model.drv = self.model._get_driving_variables(day)
            if self.model.crop is not None:
                self.model.crop.assim.external_factor = self.external_factor
            before = self.water.ledger()
            self.model.calculate_current_day()
            self.last_rates = {key: self.model.get_variable(key) for key in ("RFTRA", "TRA", "EVS", "EVW", "NamountLV", "WLV", "RFRGRL")}
            self.model.run(days=1)
            after = self.water.ledger()
            self.nitrogen.transport(sum(after[k] - before[k] for k in ("seepage_mm", "overflow_mm")))
            self.nitrogen.audit()
            self._read_crop()
            result = self.water.audit()
        else:
            raise ValueError(f"Unknown rice model event: {kind}")
        self.journal.append({"kind": kind, **copy.deepcopy(values)})
        return result

    def _read_crop(self):
        if self.maturity is not None:
            self.crop_values = copy.deepcopy(self.maturity)
            return
        if self.model.crop is not None:
            self.crop_values = json_safe({key: self.model.get_variable(key) for key in CROP_VARIABLES})
            if self.crop_values.get("DOM") is not None:
                self.maturity = copy.deepcopy(self.crop_values)

    def snapshot(self):
        return {"unit": vars(self.unit), "model_day": self.model.day.isoformat(),
                "transplant_date": self.transplant_date, "native_DOE_meaning": "transplant_model_start",
                "crop": copy.deepcopy(self.crop_values), "rates": copy.deepcopy(self.last_rates),
                "mature": self.maturity is not None, "water": self.water.audit(),
                "nitrogen": self.nitrogen.audit(), "external_factor": self.external_factor}

    def export_state(self):
        return {"schema": SCHEMA, "provenance": self.provenance,
                "specification": copy.deepcopy(self.specification), "journal": copy.deepcopy(self.journal)}

    @classmethod
    def from_state(cls, payload):
        if payload.get("schema") != SCHEMA:
            raise ValueError("Unsupported rice checkpoint schema")
        spec = copy.deepcopy(payload["specification"])
        spec["unit"] = SimulationUnit(**spec["unit"])
        result = cls(**spec)
        if payload["provenance"] != result.provenance:
            raise ValueError("Rice checkpoint model/parameter provenance mismatch")
        for event in payload["journal"]:
            event = copy.deepcopy(event)
            result.apply(event.pop("kind"), **event)
        return result
