"""Explicit experimental SCN population overlay on continuous official WOFOST.

SCN host/non-host biology is sourced; numerical reproduction, persistence and
assimilation-response parameters are declared assumptions, not field calibration.
The overlay changes native daily gross assimilation, never harvested kilograms.
Every population transition and factor is journalled for exact reconstruction.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass
from math import isclose, isfinite

from .crop_rotation_wofost import CropRotationBackend


@dataclass(frozen=True)
class ScnParameters:
    initial_eggs_per_100cc: float = 2000.0
    host_multiplier_per_120_days: float = 6.0
    nonhost_survival_per_120_days: float = 0.5
    fallow_annual_survival: float = 0.85
    assimilation_slope: float = 0.2
    egg_scale: float = 10000.0

    def __post_init__(self):
        if any(
            not isfinite(v) or v < 0 or (v == 0 and k != "initial_eggs_per_100cc")
            for k, v in asdict(self).items()
        ):
            raise ValueError(
                "SCN parameters must be finite; initial eggs nonnegative and rate parameters positive"
            )
        if self.host_multiplier_per_120_days < 1 or not (
            self.nonhost_survival_per_120_days <= 1 and self.fallow_annual_survival <= 1
        ):
            raise ValueError(
                "SCN host reproduction and nonhost survival are inconsistent"
            )


class SoybeanCystNematodeBackend(CropRotationBackend):
    def __init__(self, configuration=None, *, scn_parameters=None):
        super().__init__(configuration)
        self.scn_parameters = scn_parameters or ScnParameters()
        self.scn_population = {}

    def _specification(self, physics, rid, day, density):
        specification = super()._specification(physics, rid, day, density)
        specification["scn_ridge_id"] = int(rid)
        specification["scn_parameters"] = asdict(self.scn_parameters)
        return specification

    def _create_run(self, specification, *args, **kwargs):
        params = ScnParameters(**specification["scn_parameters"])
        if self.scn_population and params != self.scn_parameters:
            raise ValueError("SCN parameters changed between native ridges")
        self.scn_parameters = params
        return super()._create_run(specification, *args, **kwargs)

    def _advance_native(self, run, entry, *, soil_nitrogen_preapplied=False):
        entry = deepcopy(entry)
        spec = entry.get("season_start", run.specification)
        rid = int(spec["scn_ridge_id"])
        crop = spec["rotation_configuration"]["crop_name"]
        # A live crop can have just been authorized by the continuous adapter;
        # during reconstruction that same transition is in season_start.
        transition = "season_start" in entry or any(
            self._runs.get(r) is run and "specification" in queued
            for r, queued in self._next_seasons.items()
        )
        active = not entry.get("harvested", False) and (
            transition or run.maturity_snapshot is None
        )
        p = self.scn_parameters
        before = self.scn_population.get(rid, p.initial_eggs_per_100cc)
        if active and crop == "soybean":
            multiplier = p.host_multiplier_per_120_days ** (1 / 120)
            factor = 1 / (1 + p.assimilation_slope * before / p.egg_scale)
        elif active and crop == "maize":
            multiplier = p.nonhost_survival_per_120_days ** (1 / 120)
            factor = 1.0
        else:
            multiplier = p.fallow_annual_survival ** (1 / 365)
            factor = 1.0
        after = before * multiplier
        saved = entry.get("scn")
        base_factor = (
            saved["base_growth_factor"] if saved else entry["external_growth_factor"]
        )
        record = {
            "schema": 1,
            "crop": crop,
            "active": active,
            "eggs_before_per_100cc": before,
            "eggs_after_per_100cc": after,
            "assimilation_factor": factor,
            "base_growth_factor": base_factor,
        }
        if saved:
            for key, expected in record.items():
                actual = saved[key]
                matches = (
                    isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-10)
                    if type(expected) is float
                    else actual == expected
                )
                if not matches:
                    raise ValueError(f"SCN native journal mismatch: {key}")
            if not isclose(
                entry["external_growth_factor"], base_factor * factor, abs_tol=1e-12
            ):
                raise ValueError("SCN assimilation factor differs from its journal")
        entry["scn"] = record
        entry["external_growth_factor"] = base_factor * factor
        super()._advance_native(
            run, entry, soil_nitrogen_preapplied=soil_nitrogen_preapplied
        )
        self.scn_population[rid] = after

    def snapshot(self):
        result = super().snapshot()
        result["provenance"]["scn_overlay"] = {
            "schema": 1,
            "scope": "Experimental external assimilation factor, separate from disabled generic biotic coupling; official crop coefficients unchanged",
            "parameter_status": "Declared simulation assumptions; not a calibrated SCN yield-loss model",
            "parameters": asdict(self.scn_parameters),
            "eggs_per_100cc_by_ridge": dict(self.scn_population),
            "source": "https://extension.umn.edu/agriculture/crop-production/soybean/soybean-cyst-nematode-management-guide",
        }
        return result

    def export_state(self):
        state = super().export_state()
        state["scn_model"] = {
            "schema": 1,
            "parameters": asdict(self.scn_parameters),
            "population": {str(k): v for k, v in self.scn_population.items()},
        }
        return state

    @classmethod
    def from_state(cls, payload):
        model = payload.get("scn_model", {})
        if model.get("schema") != 1:
            raise ValueError("SCN checkpoint marker is required")
        backend = super().from_state(payload)
        parameters = ScnParameters(**model["parameters"])
        population = {int(k): float(v) for k, v in model["population"].items()}
        if backend._runs and parameters != backend.scn_parameters:
            raise ValueError("SCN checkpoint changes journalled parameters")
        if set(population) != set(backend.scn_population) or any(
            not isclose(
                population[r], backend.scn_population[r], rel_tol=1e-12, abs_tol=1e-10
            )
            for r in population
        ):
            raise ValueError("SCN checkpoint population differs from native replay")
        backend.scn_parameters = parameters
        return backend
