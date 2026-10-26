"""An explicit complete cultivar must not fall back to upstream crop values."""
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.physics import PlantingConfig, SeedType, SoilWeatherInput
from fairy.physics.wofost_backend import WofostBackend, WofostConfig
from fairy.physics.wofost_profiles import load_cultivar_profile

PROFILE = "heilongjiang_heinong84_complete_v1"
ROOT = Path(__file__).resolve().parents[1]


def test_complete_profile_is_explicit_and_preserves_field_validation_boundary():
    profile = load_cultivar_profile(PROFILE)
    doc = profile.provenance()
    assert doc["parameter_set_kind"] == "complete_native_parameters"
    assert doc["native_variety_name"] == "Heinong84_PublicReference_v1"
    assert len(profile.parameter_overrides) == 78
    assert profile.parameter_overrides["TSUM1"] == 500
    assert profile.parameter_overrides["TSUM2"] == 1100
    assert doc["calibration"]["yield_used_in_selection"] is False
    assert doc["calibration"]["field_observation_validation"] is False
    assert doc["validation_status"] == "unvalidated"


def test_complete_profile_rejects_missing_value_instead_of_inheriting_upstream():
    profile = load_cultivar_profile(PROFILE)
    missing = copy.deepcopy(profile.provenance())
    missing["parameter_overrides"].pop("TSUM2")

    class Incomplete:
        parameter_overrides = missing["parameter_overrides"]
        def applies_to(self, seed):
            return seed == "HEINONG84"
        def provenance(self):
            return missing

    backend = object.__new__(WofostBackend)
    backend.config = WofostConfig(cultivar_profile=PROFILE)
    backend._cultivar_profile = Incomplete()
    backend._cultivar_profiles = {}
    backend._varieties = {"Soybean_901": {key: [value] for key,value in profile.parameter_overrides.items()}}
    with pytest.raises(ValueError, match="missing native parameters.*TSUM2"):
        backend._crop_parameters("Soybean_901", "HEINONG84")


def test_native_complete_identity_and_locked_parameters_survive_checkpoint():
    pytest.importorskip("pcse")
    config = json.loads((ROOT/"configs/wofost/complete_harbin_heinong84_v1.json").read_text())
    backend = WofostBackend(config["crop_backend_options"])
    physics = FarmPhysicsState(num_ridges=1)
    start = date(2017, 5, 5)
    physics.phenology.plant_ridges([0], PlantingConfig(planting_date=start,seed_type=SeedType.HEINONG84))
    physics.management.states[0].stand_fraction = 1.0
    backend.advance_day(physics=physics, day=start,
        weather=SoilWeatherInput(day=start,air_temp_mean_c=18,air_temp_min_c=12,
            air_temp_max_c=24,rain_mm=0,solar_rad_mj_m2=20,wind_ms=2),
        density_by_ridge={0:23},ridge_area_m2=294.8,humidity_pct=73.25)
    spec = backend._runs[0].specification
    assert spec["variety"] == "Heinong84_PublicReference_v1"
    assert spec["upstream_base_variety"] == "Soybean_901"
    assert spec["calibration"] == "public_reference_constrained"
    assert spec["crop_parameters"] == load_cultivar_profile(PROFILE).parameter_overrides
    restored = WofostBackend.from_state(json.loads(json.dumps(backend.export_state())))
    assert restored.snapshot() == backend.snapshot()
