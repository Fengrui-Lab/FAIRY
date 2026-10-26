from __future__ import annotations

import json
from datetime import date

import pytest

from fairy.physics.wofost_backend import WofostBackend, WofostConfig
from fairy.physics.wofost_profiles import load_cultivar_profile


PROFILE_ID = "heilongjiang_heinong84_complete_v1"


def _parameter_backend(config: WofostConfig) -> WofostBackend:
    """Exercise real parameter resolution without the optional PCSE runtime."""
    backend = object.__new__(WofostBackend)
    backend.config = config
    backend._cultivar_profiles = {}
    backend._cultivar_profile = (
        load_cultivar_profile(config.cultivar_profile)
        if config.cultivar_profile else None
    )
    reference = load_cultivar_profile(PROFILE_ID).parameter_overrides
    backend._varieties = {
        "Soybean_901": {name: [value] for name, value in reference.items()}
    }
    return backend


def test_scoped_heinong84_profile_satisfies_guard():
    backend = _parameter_backend(WofostConfig(
        cultivar_profile=PROFILE_ID,
        require_explicit_cultivar_parameters=True,
    ))

    variety = backend._variety_for_seed("HEINONG84")
    assert backend._crop_parameters(variety, "HEINONG84") == (
        load_cultivar_profile(PROFILE_ID).parameter_overrides
    )


@pytest.mark.parametrize("seed", ["HEIHE50", "HEINONG58"])
@pytest.mark.parametrize("profile", [None, PROFILE_ID])
def test_other_seed_cannot_inherit_default_or_out_of_scope_profile(seed, profile):
    backend = _parameter_backend(WofostConfig(
        cultivar_profile=profile,
        parameter_overrides={"*": {"TSUM1": 650.0}},
        require_explicit_cultivar_parameters=True,
    ))

    with pytest.raises(ValueError, match=f"seed '{seed}'.*requires explicit cultivar"):
        backend._variety_for_seed(seed)
    # Direct native-parameter access must not bypass seed scope validation.
    with pytest.raises(ValueError, match="'\\*' overrides do not establish cultivar adaptation"):
        backend._crop_parameters("Soybean_901", seed)


@pytest.mark.parametrize("explicit", [
    {"parameter_overrides": {"HEIHE50": {"TSUM1": 650.0}}},
    {"cultivar_map": {"HEIHE50": "Soybean_901"}},
])
def test_explicit_seed_assignment_satisfies_guard_without_claiming_calibration(explicit):
    backend = _parameter_backend(WofostConfig(
        require_explicit_cultivar_parameters=True, **explicit,
    ))

    variety = backend._variety_for_seed("HEIHE50")
    assert variety == "Soybean_901"
    parameters = backend._crop_parameters(variety, "HEIHE50")
    if "parameter_overrides" in explicit:
        assert parameters["TSUM1"] == 650.0


def test_empty_seed_overrides_do_not_satisfy_guard():
    backend = _parameter_backend(WofostConfig(
        parameter_overrides={"HEIHE50": {}},
        require_explicit_cultivar_parameters=True,
    ))

    with pytest.raises(ValueError, match="HEIHE50.*requires explicit cultivar"):
        backend._variety_for_seed("HEIHE50")


def test_internal_wildcard_parameter_validation_remains_allowed():
    backend = _parameter_backend(WofostConfig(
        parameter_overrides={"*": {"TSUM1": 650.0}},
        require_explicit_cultivar_parameters=True,
    ))

    assert backend._crop_parameters(backend._variety_for_seed("*"), "*")["TSUM1"] == 650.0


def test_default_false_keeps_legacy_seed_fallback():
    backend = _parameter_backend(WofostConfig())

    assert backend.config.require_explicit_cultivar_parameters is False
    assert backend._variety_for_seed("HEIHE50") == "Soybean_901"
    assert backend._crop_parameters("Soybean_901", "HEINONG58")["TSUM1"] > 0


def test_guard_requires_boolean_configuration():
    with pytest.raises(ValueError, match="must be a boolean"):
        WofostConfig(require_explicit_cultivar_parameters="false")


def test_native_checkpoint_preserves_guard_and_existing_scope():
    pytest.importorskip("pcse")
    from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
    from fairy.physics import PlantingConfig, SeedType, SoilWeatherInput

    backend = WofostBackend(WofostConfig(
        cultivar_profile=PROFILE_ID,
        require_explicit_cultivar_parameters=True,
    ))
    physics = FarmPhysicsState(num_ridges=1)
    day = date(2017, 5, 5)
    physics.phenology.plant_ridges(
        [0], PlantingConfig(planting_date=day, seed_type=SeedType.HEINONG84)
    )
    physics.management.states[0].planted = True
    physics.management.states[0].stand_fraction = 1.0
    backend.advance_day(
        physics=physics, day=day,
        weather=SoilWeatherInput(
            day=day, air_temp_mean_c=18.0, air_temp_min_c=12.0,
            air_temp_max_c=24.0, rain_mm=0.0, solar_rad_mj_m2=20.0,
            wind_ms=2.0,
        ),
        density_by_ridge={0: 23.0}, ridge_area_m2=294.8,
    )
    payload = json.loads(json.dumps(backend.export_state()))
    restored = WofostBackend.from_state(payload)

    assert payload["config"]["require_explicit_cultivar_parameters"] is True
    assert restored.config.require_explicit_cultivar_parameters is True
    assert restored.snapshot()["ridges"] == backend.snapshot()["ridges"]
    assert restored._variety_for_seed("HEINONG84") == "Soybean_901"
    with pytest.raises(ValueError, match="HEIHE50.*requires explicit cultivar"):
        restored._variety_for_seed("HEIHE50")


def test_old_native_checkpoint_without_guard_flag_restores_default_false():
    pytest.importorskip("pcse")
    backend = WofostBackend()
    payload = json.loads(json.dumps(backend.export_state()))
    payload["config"].pop("require_explicit_cultivar_parameters")

    restored = WofostBackend.from_state(payload)

    assert restored.config.require_explicit_cultivar_parameters is False
    assert restored._variety_for_seed("HEIHE50") == "Soybean_901"
