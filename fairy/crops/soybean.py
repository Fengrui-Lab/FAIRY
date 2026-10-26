"""The existing soybean models, kept together without changing coefficients.

This module owns crop engines only. Environmental engines, tool resources,
scenario clocks and compatibility projections belong to the integration layer.
"""
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import date
from enum import Enum

from fairy.physics import (
    CanopyBiomassGrowthEngine, ThermalTimePhenologyEngine, YieldRecoveryEngine,
)


class SoybeanCropModel:
    def __init__(self, num_ridges: int = 64) -> None:
        self.phenology = ThermalTimePhenologyEngine(num_ridges=num_ridges)
        self.canopy = CanopyBiomassGrowthEngine(num_ridges=num_ridges)
        self.yield_recovery = YieldRecoveryEngine(num_ridges=num_ridges)

    def get_state(self) -> dict:
        """Keep custom cultivar coefficients with their native crop states."""
        def encode(value):
            if is_dataclass(value):
                return encode(asdict(value))
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, date):
                return value.isoformat()
            if isinstance(value, dict):
                return {str(encode(key)): encode(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [encode(item) for item in value]
            return value
        return encode({
            "version": 1,
            "phenology": {"parameters": self.phenology.params,
                          "seed_parameters": self.phenology.seed_type_params,
                          "states": self.phenology.states},
            "canopy": {"parameters": self.canopy.params,
                       "seed_parameters": self.canopy.seed_params,
                       "states": self.canopy.states},
            "yield_recovery": {"parameters": self.yield_recovery.params,
                               "states": self.yield_recovery.states},
        })

    def load_state(self, snapshot: dict) -> None:
        from fairy.physics.phenology_engine import (
            PhenologyParameters, PhenologyState, SeedType, SeedTypeParameters, SoybeanStage,
        )
        from fairy.physics.canopy_biomass_engine import (
            CanopyBiomassParameters, CanopyBiomassState, SeedGrowthParameters,
            SeedType as CanopySeedType,
        )
        from fairy.physics.yield_recovery_engine import YieldRecoveryParameters, YieldRecoveryState

        if snapshot.get("version") != 1:
            raise ValueError("Unsupported soybean crop snapshot")
        expected = set(self.phenology.states)
        restored = {}
        for name, state_type, enum_fields in (
            ("phenology", PhenologyState, {"stage": SoybeanStage, "seed_type": SeedType}),
            ("canopy", CanopyBiomassState, {"seed_type": CanopySeedType}),
            ("yield_recovery", YieldRecoveryState, {}),
        ):
            states = {}
            for key, raw in snapshot[name]["states"].items():
                values = deepcopy(raw)
                for field, value in values.items():
                    if value is None:
                        continue
                    if field in enum_fields:
                        values[field] = enum_fields[field](value)
                    elif field in {"planting_date", "emergence_date", "maturity_date", "harvest_date", "last_daily_update_day"}:
                        values[field] = date.fromisoformat(value)
                rid = int(key)
                if values["ridge_id"] != rid:
                    raise ValueError("Crop snapshot ridge identity does not match")
                states[rid] = state_type(**values)
            if set(states) != expected:
                raise ValueError("Crop snapshot does not cover the complete field")
            restored[name] = states
        phen_params = deepcopy(snapshot["phenology"]["parameters"])
        phen_params["stage_fraction_thresholds"] = {
            SoybeanStage(key): value for key, value in phen_params["stage_fraction_thresholds"].items()
        }
        parameters = (PhenologyParameters(**phen_params),
                      CanopyBiomassParameters(**snapshot["canopy"]["parameters"]),
                      YieldRecoveryParameters(**snapshot["yield_recovery"]["parameters"]))
        phen_seeds = {SeedType(key): SeedTypeParameters(**value)
                      for key, value in snapshot["phenology"]["seed_parameters"].items()}
        canopy_seeds = {CanopySeedType(key): SeedGrowthParameters(**value)
                        for key, value in snapshot["canopy"]["seed_parameters"].items()}
        for name, params in zip(("phenology", "canopy", "yield_recovery"), parameters):
            engine = getattr(self, name)
            engine.params, engine.states = params, restored[name]
        self.phenology.seed_type_params = phen_seeds
        self.canopy.seed_params = canopy_seeds
