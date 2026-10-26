"""Cross-layer contracts for maize identity, checkpoints and agent entrypoints."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("pcse")

from fairy.apps.farm_world import FarmWorldApp, WeatherApp
from fairy.controllers.agent_builder import build_controller_agent
from fairy.controllers.agent_config import get_farm_world_system_prompt
from fairy.controllers.engine import Engine
from fairy.physics import ManagementAction, ManagementActionType, PlantingConfig, SeedType
from fairy.scenarios.farm_world_fullseason_v2.farm_checkpoint_state import (
    export_farm_checkpoint_state, restore_farm_checkpoint_state,
)
from fairy.scenarios.fos.provenance import crop_backend_provenance, validate_baseline_provenance
from fairy.scenarios.registry import get_scenario_class


START = date(2026, 5, 1)


def _timestamp(day):
    return datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp()


def _maize_farm():
    farm = FarmWorldApp(num_ridges=1, ridge_width_m=.75)
    farm._weather_app = WeatherApp()
    farm.configure_crop_backend("wofost", crop_name="maize", variety_name="Grain_maize_201")
    farm.physics.phenology.plant_ridges(
        [0], PlantingConfig(planting_date=START, seed_type=SeedType.MAIZE_201)
    )
    farm.physics.management.states[0].planted = True
    farm.physics.management.states[0].stand_fraction = 1.0
    ridge = farm._ridges[0]
    ridge.planted, ridge.seed_type, ridge.seeds_planted = True, "MAIZE_201", 1340
    ridge.seed_spacing_cm = 20.0
    return farm


def _advance(farm, day):
    farm._weather_app.set_weather(
        date=day.isoformat(), temp_c=22., humidity_pct=55., wind_speed_ms=2.,
        rainfall_mm=10., solar_radiation=20. / .0864,
    )
    farm.advance_physics_time(_timestamp(day))


@pytest.mark.parametrize("days", [12, 110])
def test_maize_checkpoint_preserves_identity_stages_and_pending_water(days):
    farm = _maize_farm()
    for offset in range(days):
        _advance(farm, START + timedelta(days=offset))
    farm.physics.queue_management_action(
        0, ManagementAction(ManagementActionType.IRRIGATION, amount=18.)
    )
    saved = json.loads(json.dumps(export_farm_checkpoint_state(
        farm_world=farm, weather_app=farm._weather_app,
        scenario_id="maize_checkpoint_test", checkpoint_label="pending_water",
    )))
    restored = FarmWorldApp()
    restored.num_ridges = 1
    restored._ridges = restored._ridges[:1]
    restored._weather_app = WeatherApp()
    restore_farm_checkpoint_state(
        farm_world=restored, weather_app=restored._weather_app, checkpoint_state=saved,
    )
    assert restored.crop_name == "maize"
    assert restored.rows_per_ridge == 1
    assert restored.ridge_width_m == .75
    assert restored.physics.yield_recovery.params.market_moisture_frac == .14
    assert restored.physics.phenology.states[0].stage == farm.physics.phenology.states[0].stage
    assert restored.physics.crop_backend.snapshot() == farm.physics.crop_backend.snapshot()
    for candidate in (farm, restored):
        _advance(candidate, START + timedelta(days=days))
    assert restored.physics.crop_backend.snapshot() == farm.physics.crop_backend.snapshot()
    assert vars(restored.physics.yield_recovery.states[0]) == vars(farm.physics.yield_recovery.states[0])
    assert restored.physics.crop_backend.snapshot()["ridges"]["0"]["cumulative_irrigation_mm"] == 18.


def test_soybean_checkpoint_without_crop_fields_uses_historical_defaults():
    original = FarmWorldApp()
    saved = export_farm_checkpoint_state(
        farm_world=original, weather_app=None,
        scenario_id="old_soybean", checkpoint_label="initial",
    )
    for key in ("crop_name", "variety_name", "rows_per_ridge"):
        saved["farm_world_state"].pop(key, None)
    restored = FarmWorldApp()
    restore_farm_checkpoint_state(farm_world=restored, weather_app=None, checkpoint_state=saved)
    assert restored.crop_name == "soybean"
    assert restored.rows_per_ridge == 2


def test_maize_rejects_soybean_yield_baseline():
    maize = _maize_farm()
    soybean = FarmWorldApp()
    soybean.configure_crop_backend("wofost")
    with pytest.raises(ValueError, match="provenance mismatch"):
        validate_baseline_provenance(
            {"crop_backend_provenance": crop_backend_provenance(soybean)},
            crop_backend_provenance(maize), "soybean_baseline.json",
        )


def test_maize_checkpoint_retains_future_synthetic_weather_and_events():
    from dataclasses import asdict
    from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs

    scenario = get_scenario_class("scenario_maize_l3_water_limit")()
    scenario.setup()
    farm = scenario.get_typed_app(FarmWorldApp)
    weather = scenario.get_typed_app(WeatherApp)
    start = date.fromisoformat(scenario.spec.start_date)
    _build_weather_inputs(weather, start + timedelta(days=10), physics=farm.physics)
    saved = json.loads(json.dumps(export_farm_checkpoint_state(
        farm_world=farm, weather_app=weather, scenario_id=scenario.scenario_id,
        checkpoint_label="weather_before_harvest_window",
    )))
    restored, restored_weather = FarmWorldApp(), WeatherApp()
    restore_farm_checkpoint_state(
        farm_world=restored, weather_app=restored_weather, checkpoint_state=saved,
    )
    assert asdict(restored.physics.profile) == asdict(farm.physics.profile)
    assert restored.physics.weather_generator.config == farm.physics.weather_generator.config
    for offset in (20, 135, 170):
        day = start + timedelta(days=offset)
        original = _build_weather_inputs(weather, day, physics=farm.physics)
        resumed = _build_weather_inputs(restored_weather, day, physics=restored.physics)
        assert asdict(original["soil"]) == asdict(resumed["soil"])
        if offset == 135:
            assert original["soil"].rain_mm == 0


def test_maize_controller_uses_live_tools_and_crop_context():
    for mode in ("fairy", "are"):
        prompt = get_farm_world_system_prompt(mode, crop="maize", parallel_tool_calls=False)
        assert "maize" in prompt and "soybean" not in prompt and "R8" not in prompt
        assert "Only ONE tool call is allowed per turn." in prompt

    class ScriptedLLM:
        provider, model = "openai", "scripted-maize-test"

        def __init__(self):
            self.calls = 0

        def chat_completion(self, messages, tools=None):
            assert "maize" in messages[0]["content"]
            assert "soybean farm" not in messages[0]["content"]
            self.calls += 1
            if self.calls == 1:
                call = NS(id="inventory", type="function", function=NS(
                    name="FarmWorldApp__get_inventory", arguments="{}"))
                message = NS(content=None, tool_calls=[call])
            else:
                assert "MAIZE_201" in str(messages)
                message = NS(content="Inventory checked.", tool_calls=None)
            return NS(choices=[NS(message=message)], usage=None)

    scenario = get_scenario_class("scenario_maize_l3_normal")()
    scenario.setup()
    agent = build_controller_agent("farm_baseline_react", ScriptedLLM(), toolsets=scenario.apps)
    engine = Engine(agent, scenario)
    workflow = engine.run_scenario_agent(max_tool_calls=5, timeout_seconds=30, setup_scenario=False)
    inventory_steps = [s for s in workflow.dag.values()
                       if s.tool_name == "FarmWorldApp__get_inventory"]
    assert len(inventory_steps) == 1
    assert inventory_steps[0].op_type != "TOOL_ERROR"
