"""Normal maize management, observation-backed water decisions and controls."""
from copy import deepcopy
import ast
import inspect

import pytest

from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.workflow import Workflow
from fairy.scenarios.maize.scenario_single_farm_maize_normal_management import (
    CULTIVAR_ID, INITIAL_NUTRIENT_INDEX, INITIAL_SOIL_VWC, IRRIGATION_QUOTA_MM,
    ScenarioSingleFarmMaizeNormalManagement,
)


def fresh():
    scene = ScenarioSingleFarmMaizeNormalManagement()
    scene.setup()
    return scene, Engine(None, scene)


def cleaned(value):
    if isinstance(value, dict):
        return {key: cleaned(item) for key, item in value.items()
                if key not in {"action_id", "op_id", "mission_id", "inspection_id"}}
    if isinstance(value, list):
        return [cleaned(item) for item in value]
    return value


def final_state(scene):
    return deepcopy(cleaned({"world": scene.farm_world.get_state(),
                             "time": scene.farm_environment.time_manager.time()}))


def test_scene_is_a_complete_independent_file_with_normal_initial_conditions():
    scene, _ = fresh()
    assert ScenarioSingleFarmMaizeNormalManagement.__bases__ == (Scenario,)
    for name in ("init_and_populate_apps", "_reference_actions", "build_events_flow", "oracle_solution", "validate"):
        assert name in ScenarioSingleFarmMaizeNormalManagement.__dict__
    source = inspect.getsource(inspect.getmodule(ScenarioSingleFarmMaizeNormalManagement))
    imports = [node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)]
    assert not any(module and "scenario_single_farm_maize_full_season" in module for module in imports)
    farm = scene.farm_world
    assert farm.field_geometry.planted_area_m2 == pytest.approx(11148.8)
    assert farm.rows_per_ridge == 1 and farm.plants_per_ridge_from_spacing(25.0) == 1072
    assert {ridge.nutrient_index for ridge in farm._ridges} == {INITIAL_NUTRIENT_INDEX}
    assert all(abs(ridge.soil_vwc - INITIAL_SOIL_VWC) <= 0.00401 for ridge in farm._ridges)
    assert farm._management_regime.irrigation_quota_mm_total == IRRIGATION_QUOTA_MM
    assert not farm.physics.profile.biotic_outbreaks
    assert not farm.physics.profile.weather_events
    before = final_state(scene)
    scene.oracle_solution(run_oracle=False)
    assert final_state(scene) == before


@pytest.fixture(scope="module")
def managed():
    scene, engine = fresh()
    engine.run_scenario_oracle(run_oracle=True)
    return scene, engine


def test_normal_management_uses_observations_not_calendar_alone(managed):
    scene, engine = managed
    result = engine.evaluate()
    assert result.success, result.message
    assert result.metadata["harvested_ridges"] == 64
    assert result.metadata["seed_use"] == 68608
    assert result.metadata["water_used_mm"] == 20.0
    steps = scene.workflow.dag
    assert all(ridge["growth_stage"] == "V6" for ridge in steps["vegetative_state"].content["ridges"])
    before_nutrition = steps["vegetative_state"].content["ridges"]
    after_nutrition = steps["vegetative_after_fertilizer"].content["ridges"]
    assert all(after["nutrient_index"] >= before["nutrient_index"] + 0.05
               for before, after in zip(before_nutrition, after_nutrition))
    # R1 is marginally moist with limited forecast rain: one measured irrigation.
    assert all(ridge["growth_stage"] == "R1_SILKING" for ridge in steps["silking_state"].content["ridges"])
    rain_r1 = sum(row["rainfall_mm"] for row in steps["silking_forecast"].content["forecast"])
    assert rain_r1 < 10
    irrigation = [step for step in steps.values() if step.tool_name.endswith("__irrigate")]
    assert [step.name for step in irrigation] == ["silking_water"]
    assert irrigation[0].time_after - irrigation[0].time_before == 4 * 3600 + 300
    # R3 has a real wet forecast, so the reference waits for rain without irrigation.
    rain_r3 = sum(row["rainfall_mm"] for row in steps["grain_fill_forecast"].content["forecast"][:2])
    assert rain_r3 >= 15
    before_rain = steps["grain_fill_soil"].content["soil_sensors"]
    after_rain = steps["grain_fill_next_day_soil"].content["soil_sensors"]
    assert sum(row["vwc"] for row in after_rain) / 6 > sum(row["vwc"] for row in before_rain) / 6 + 0.03
    assert not any(step.tool_name.endswith(("__apply_fungicide", "__spray_pesticide", "__apply_herbicide"))
                   for step in steps.values())
    assert all(not step.error_stage and "error" not in step.content and step.content.get("status") != "partial"
               for step in steps.values())
    farm = scene.farm_world
    assert farm._inventory.seed_stock[CULTIVAR_ID] == 80000 - 68608
    assert farm._inventory.fertilizer_kg == pytest.approx(900 - 200 - 64 * 6)
    assert farm._inventory.harvest_grain_kg == 0 and scene.tractor._grain_bin_kg == 0
    assert all(ridge.harvested for ridge in farm._ridges)
    assert all(state.grain_moisture_frac <= 0.14 for state in farm.physics.yield_recovery.states.values())


def test_complete_oracle_saved_workflow_replays_from_fresh_initial_state(tmp_path, managed):
    original, _ = managed
    path = tmp_path / "normal_maize.json"
    original.workflow.save_workflow(str(path))
    replayed, engine = fresh()
    engine.replay_workflow(Workflow.load_workflow(str(path)))
    assert engine.evaluate().success
    assert final_state(replayed) == final_state(original)


def test_captured_events_execute_the_same_normal_management(managed):
    original, _ = managed
    captured, engine = fresh()
    engine._run_captured_oracle_events(True)
    assert engine.evaluate().success
    assert final_state(captured) == final_state(original)
    assert len(captured.workflow) == len(original.workflow) + 1  # briefing has no farm effect


def test_unjustified_real_apply_pesticide_cannot_pass_the_healthy_normal_task():
    scene, engine = fresh()
    # An explicit extra supply allows an actually successful treatment, so this
    # checks the validator rather than relying on the default empty drug stock.
    scene.farm_world._inventory.pesticide_liters = 8.0
    actions = []
    for action in scene._reference_actions():
        actions.append(action)
        if action[0] == "plant_0_3":
            actions.extend([
                ("unjustified_load", scene.tractor, "load_pesticide", {"liters": 8.0}, "Counterexample supply."),
                ("unjustified_insecticide", scene.tractor, "apply_pesticide",
                 {"start_ridge": 0, "end_ridge": 0},
                 "Counterexample: no confirmed pest trigger."),
            ])
    scene._reference_actions = lambda: actions
    engine.run_scenario_oracle(run_oracle=True)
    assert scene.workflow.dag["unjustified_insecticide"].content["status"] == "ok"
    assert any(op["operation"] == "apply_pesticide" for op in scene.tractor.get_state()["operation_log"])
    result = engine.evaluate()
    assert not result.success
    assert "no confirmed chemical-treatment trigger" in result.message


@pytest.mark.parametrize("omission", ["topdressing", "key_stage_irrigation"])
def test_omitting_key_management_is_worse_at_the_same_timestamps(managed, omission):
    original, _ = managed
    control, engine = fresh()
    original_steps = original.workflow.dag
    control_actions = []
    for step, app, method, arguments, reason in control._reference_actions():
        omitted = ((omission == "topdressing" and step.startswith("topdress_"))
                   or (omission == "key_stage_irrigation" and step == "silking_water"))
        if omitted:
            duration = original_steps[step].time_after - original_steps[step].time_before
            method, arguments = (("advance_time", {"seconds": duration}) if duration > 0
                                 else ("get_current_time", {}))
            control_actions.append((step, control.system, method, arguments,
                                    f"Counterfactual: omit {omission}; preserve the reference's actual elapsed time."))
        elif step == "report":
            control_actions.append((step, app, method, {"content": f"管理对照：省略{omission}，没有执行对应作业。"}, reason))
        else:
            control_actions.append((step, app, method, arguments, reason))
    control._reference_actions = lambda: control_actions
    engine.run_scenario_oracle(run_oracle=True)
    assert all((step.time_before, step.time_after) ==
               (original_steps[name].time_before, original_steps[name].time_after)
               for name, step in control.workflow.dag.items())
    assert all(ridge.harvested for ridge in control.farm_world._ridges)
    assert original.farm_world._inventory.warehouse_grain_kg > control.farm_world._inventory.warehouse_grain_kg + 100
    # A positive harvest alone cannot pass the normal-management contract.
    result = engine.evaluate()
    assert not result.success
    assert "topdressing" in result.message if omission == "topdressing" else "key-stage water" in result.message
