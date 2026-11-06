"""Versioned crop-rotation inputs; reuses wheat weather and integrity contracts."""

from __future__ import annotations
from copy import copy, deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
from .winter_wheat_inputs import (
    WeatherSeries,
    verified_file,
    fingerprint,
    number,
    validate_wheat_parameters,
)
from ..sugarbeet.contracts import Calendar, CropCycle


class SugarBeetInputs:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.manifest = m = json.loads(
            (self.root / "manifest.json").read_text(encoding="utf-8")
        )
        if m.get("schema") != "fairy.sugarbeet.rotation.inputs.v1":
            raise ValueError("Unsupported sugarbeet manifest")
        self.season = Calendar(
            date.fromisoformat(m["start"]),
            date.fromisoformat(m["deadline"]),
            tuple(CropCycle.from_dict(x) for x in m["cycles"]),
            m.get("timezone", "Asia/Shanghai"),
        )
        self.cycles = self.season.cycles
        self.weather = WeatherSeries.from_csv(verified_file(self.root, m["weather"]))
        self.weather.require(
            self.season.start, self.season.deadline + timedelta(days=1)
        )
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
            raise ValueError("Explicit parameter calibration status required")
        if m["parameter_status"] == "locally_calibrated" and not m.get(
            "calibration_report"
        ):
            raise ValueError("Local calibration requires an actual report")
        if m.get("residue_policy") != "no_unmodelled_residue_n_credit":
            raise ValueError(
                "No unsupported residue/mineralization credit may be injected"
            )
        if not m.get("site_agronomy_status"):
            raise ValueError(
                "Site and rotation suitability must be explicitly qualified"
            )
        self.crop_files = {
            c.cycle_id: verified_file(self.root, m["crops"][c.cycle_id])
            for c in self.cycles
        }
        self.cultivar = self.cycles[0].cultivar
        self.identity = fingerprint(m)

    def with_soil_profile(self, *, soil=None, site=None, description):
        """Keep the forcing/crops and identify an explicit benchmark soil variant."""
        result = copy(self)
        result.manifest = deepcopy(self.manifest)
        result.manifest["native_soil_parameters"].update(soil or {})
        result.manifest["native_site_parameters"].update(site or {})
        result.manifest["soil_status"] = description
        result.identity = fingerprint(result.manifest)
        return result

    def load_parameters(self, yaml):
        result = {}
        for c in self.cycles:
            p = yaml.safe_load(self.crop_files[c.cycle_id].read_bytes())[
                "CropParameters"
            ]["Varieties"][c.cultivar]
            p = {k: deepcopy(v[0]) for k, v in p.items() if k != "Metadata"}
            record = self.manifest["crops"][c.cycle_id]
            overrides = record.get("parameter_overrides", {})
            if overrides and not record.get("override_provenance"):
                raise ValueError("Native parameter overrides need provenance")
            p.update(deepcopy(overrides))
            if c.crop == "winter_wheat":
                validate_wheat_parameters(p)
            else:
                required = {
                    "TSUMEM",
                    "TSUM1",
                    "TSUM2",
                    "TDWI",
                    "IDSL",
                    "DVSEND",
                    "NFIX_FR",
                    "NMAXSO",
                    "FOTB",
                }
                if required - set(p):
                    raise ValueError(
                        f"Incomplete WOFOST81 beet parameters: {required - set(p)}"
                    )
                if p["IDSL"] != 0 or p["NFIX_FR"] != 0:
                    raise ValueError(
                        "This reference beet adapter expects nonvernalizing, nonfixing parameters"
                    )
                for key in ("TSUMEM", "TSUM1", "TSUM2", "TDWI", "DVSEND"):
                    number(p[key], key, minimum=0.000001)
            result[c.cycle_id] = p
        return result
