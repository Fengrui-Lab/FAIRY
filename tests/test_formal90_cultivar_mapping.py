"""Six original formal90 identities have explicit, scoped native references."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.physics import PlantingConfig, SeedType, SoilWeatherInput
from fairy.physics.wofost_backend import WofostBackend, WofostConfig
from fairy.physics.wofost_profiles import load_cultivar_profile


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "configs/wofost/formal90_cultivar_mapping_v1.json").read_text())


def test_mapping_preserves_six_original_identities_without_wildcards():
    assert set(CONFIG["cultivar_profiles"]) == {
        "HEINONG84", "HEINONG58", "HEINONG60", "HEIHE50", "HEIHE43", "HEIKE71"}
    assert CONFIG["require_explicit_cultivar_parameters"] is True
    base = load_cultivar_profile("heilongjiang_heinong84_complete_v1")
    for seed, profile_id in CONFIG["cultivar_profiles"].items():
        profile = load_cultivar_profile(profile_id)
        assert profile.supported_seed_types == (seed,)
        assert len(profile.parameter_overrides) == 78
        doc = profile.provenance()
        assert doc["validation_status"] == "unvalidated"
        if seed == "HEINONG84":
            continue
        parameters = profile.parameter_overrides
        changed = {name for name, value in base.parameter_overrides.items() if value != parameters[name]}
        assert changed == {"TSUM1", "TSUM2"}
        assert parameters["TSUM1"] / parameters["TSUM2"] == pytest.approx(5 / 11)
        assert doc["calibration"]["TSUM1_and_TSUM2_independently_identified"] is False
        assert doc["calibration"]["selection_uses_yield"] is False
        assert doc["calibration"]["selection_uses_oracle_or_risk_windows"] is False


@pytest.mark.parametrize("seed", sorted(CONFIG["cultivar_profiles"]))
def test_actual_named_seed_starts_native_with_its_own_profile(seed):
    pytest.importorskip("pcse")
    physics = FarmPhysicsState(num_ridges=1)
    start = date(2026, 5, 5)
    physics.phenology.plant_ridges([0], PlantingConfig(planting_date=start, seed_type=SeedType(seed)))
    physics.management.states[0].planted = True
    physics.management.states[0].stand_fraction = 1.0
    backend = WofostBackend(WofostConfig(**CONFIG))
    backend.advance_day(physics=physics, day=start,
        weather=SoilWeatherInput(day=start, air_temp_mean_c=18.0,
            air_temp_min_c=12.0, air_temp_max_c=24.0, rain_mm=0.0,
            solar_rad_mj_m2=20.0, wind_ms=2.0),
        density_by_ridge={0: 23.0}, ridge_area_m2=294.8)
    specification = backend._runs[0].specification
    profile = load_cultivar_profile(CONFIG["cultivar_profiles"][seed])
    assert specification["seed_type"] == seed
    assert specification["cultivar_profile"]["profile_id"] == profile.profile_id
    assert specification["cultivar_profile"]["sha256"] == profile.sha256
    assert specification["crop_parameters"] == profile.parameter_overrides
