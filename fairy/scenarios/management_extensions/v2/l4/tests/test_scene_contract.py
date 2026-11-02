import pytest
from fairy.scenarios.management_extensions.v2.l4.scene import TwoYearMaizeScenario


def test_cannot_close_unharvested_crop_or_open_unclosed_season():
    scene = TwoYearMaizeScenario()
    scene.setup()
    with pytest.raises(ValueError, match="actually be harvested"):
        scene.cycle.close_season(2026)
    with pytest.raises(ValueError, match="Close the first season"):
        scene.cycle.open_next_season(2027)
    assert scene.validate().success is False


def test_explicit_briefing_overrides_survive_setup():
    scene = TwoYearMaizeScenario(
        scenario_input="Custom task", additional_system_prompt="Custom system"
    )
    scene.setup()
    assert scene.scenario_input == "Custom task"
    assert scene.additional_system_prompt == "Custom system"
    short = TwoYearMaizeScenario(detailed_briefing=False)
    short.setup()
    assert "合成气候" in short.scenario_input
    assert "冻土" in short.scenario_input
    assert "1200kg" in short.scenario_input
    assert short.input_fingerprint == scene.input_fingerprint


def test_briefing_requires_boolean_flag():
    with pytest.raises(ValueError, match="boolean"):
        TwoYearMaizeScenario(detailed_briefing="false")


def test_backend_override_cannot_replace_the_continuous_adapter():
    with pytest.raises(ValueError, match="non-default crop_backend_options"):
        TwoYearMaizeScenario(crop_backend_options={"initial_available_n_kg_ha": 999.0})
    scene = TwoYearMaizeScenario(crop_backend_options={"crop_name": "maize"})
    scene.setup()
    from fairy.scenarios.management_extensions.v2.l4.backend import (
        ContinuousSeasonBackend,
    )
    from fairy.apps.farm_world import FarmWorldApp

    assert isinstance(
        scene.get_typed_app(FarmWorldApp).physics.crop_backend, ContinuousSeasonBackend
    )
