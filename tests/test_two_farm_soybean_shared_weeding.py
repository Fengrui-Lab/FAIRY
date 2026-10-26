"""Verify the independent soybean weeding reference through real tool calls.

No scenario score or prescribed yield increase is used as execution evidence.
Both briefing modes and the saved replay must retain the same farm physics.
"""

import ast
from collections import Counter
from copy import deepcopy
from datetime import datetime, time
import inspect
import re
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from fairy.agents.agent.agent import Agent
from fairy.agents.agent.toolset_builder import build_toolset
from fairy.controllers.engine import Engine
from fairy.physics.profiles import get_profile
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.workflow import Workflow


SCENE = "scenario_two_farm_soybean_shared_weeding"
PROFILE = "harbin_baseline_2026_seed_101"
RIDGES = set(range(64))
TARGETS = {"farm_a": RIDGES, "farm_b": RIDGES}
GROUND_SAMPLES = {rid for start in (0, 20, 40, 60) for rid in range(start, start + 4)}
RECHECK_SAMPLES = set(range(4)) | set(range(60, 64))
VOLATILE_IDS = {"op_id", "action_id", "mission_id", "inspection_id"}
UUID_PATTERN = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def scene(**kwargs):
    value = get_scenario_class(SCENE)(**kwargs)
    value.setup()
    return value, Engine(None, value)


def comparable(value):
    """Normalize random identifiers without rounding physical values or time."""
    if isinstance(value, dict):
        return {key: comparable(item) for key, item in value.items() if key not in VOLATILE_IDS}
    if isinstance(value, (tuple, list)):
        return [comparable(item) for item in value]
    if isinstance(value, str):
        return UUID_PATTERN.sub("<uuid>", value)
    return value


def complete_state(value, engine):
    return comparable(
        deepcopy(
            {
                "clock": engine.time_manager.time(),
                "apps": {app.name: {"state": app.get_state(), "rng": app.rng.getstate()} for app in value.apps},
            }
        )
    )


def comparable_workflow(workflow):
    result = deepcopy(workflow.to_dict())
    for step in result.values():
        if step["tool_name"] == "AgentUserInterface__send_message_to_agent":
            step["tool_args"] = {"content": "<selected briefing>"}
            step["content"] = "<selected briefing>"
    return comparable(result)


def ground_steps(workflow, phase, farm_id):
    return [
        step
        for step in workflow.dag.values()
        if step.name.startswith(f"{phase}_{farm_id}_") and step.tool_name == "Robot0__inspect_crop_health"
    ]


class FirstTurnProbe(Agent):
    """Capture the real Agent input while substituting only the network reply."""

    def __init__(self, apps):
        super().__init__(
            "weeding-briefing-probe",
            SimpleNamespace(provider="openai"),
            system_message="Offline controller.",
            toolsets=apps,
        )

    def _chat_completion_with_retries(self, messages, tools=None):
        self.first_request = deepcopy(messages)
        return SimpleNamespace(content="Offline input captured.", tool_calls=[])


def test_scene_owns_initialization_and_workflow_without_a_task_validator():
    cls = get_scenario_class(SCENE)
    assert cls.__bases__ == (Scenario,)
    assert {"init_and_populate_apps", "build_events_flow"} <= cls.__dict__.keys()
    assert "validate" not in cls.__dict__
    assert cls.validate is Scenario.validate
    tree = ast.parse(inspect.getsource(inspect.getmodule(cls)))
    imported = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(module and module.startswith("fairy.scenarios.two_farm.") for module in imported)
    value, _ = scene()
    assert value.validate() is None


def test_initial_fields_have_whole_field_weeds_and_separate_fixed_installations():
    registered = get_profile(PROFILE)
    original = deepcopy(registered)
    value, engine = scene()
    assert registered == original
    assert value.farm_a.physics.profile is not registered
    assert value.farm_b.physics.profile is not registered
    assert value.farm_a.physics.profile is not value.farm_b.physics.profile
    assert not value.farm_a.physics.profile.biotic_outbreaks
    for farm, pressure in ((value.farm_a, 0.22), (value.farm_b, 0.19)):
        assert farm.crop_id == "soybean"
        assert farm.field_geometry.planted_area_m2 == pytest.approx(18867.2)
        assert farm.num_ridges == 64 and farm.rows_per_ridge == 2
        assert not farm.completed_prep_ops
        assert not any(ridge.planted or ridge.harvested for ridge in farm._ridges)
        for ridge in farm._ridges:
            assert ridge.nutrient_index == pytest.approx(0.82)
            assert farm.physics.biotic.states[ridge.ridge_id].weed_pressure == pytest.approx(pressure)
    for farm_id, world, sensor, irrigation in (
        ("farm_a", value.farm_a, value.sensor_a, value.irrigation_a),
        ("farm_b", value.farm_b, value.sensor_b, value.irrigation_b),
    ):
        context = value.farm_environment.get_farm(farm_id)
        assert context.world is world and context.sensors is sensor and context.irrigation is irrigation
        assert sensor.bound_farm_id == irrigation.bound_farm_id == farm_id
    assert value.sensor_a is not value.sensor_b
    assert value.irrigation_a is not value.irrigation_b
    assert value.sensor_a._soil_sensors is not value.sensor_b._soil_sensors
    assert value.farm_environment.warehouse is value.warehouse
    assert value.shared_equipment == [value.tractor, value.mavic, value.robot]
    assert all(sum(app is shared for app in value.apps) == 1 for shared in [value.warehouse, *value.shared_equipment])
    assert all(app.time_manager is engine.time_manager for app in value.apps)
    assert str(value.farm_environment.simulation_timezone) == "Asia/Shanghai"


def test_tools_identify_mobile_targets_and_keep_fixed_installations_local():
    value, _ = scene()
    functions = {entry["function"]["name"]: entry["function"] for entry in build_toolset(value.apps)[1]}
    for prefix, farm_id in (("FarmA", "farm_a"), ("FarmB", "farm_b")):
        for suffix in ("_Sensor__read_soil_sensors", "_Irrigation__irrigate"):
            tool = functions[prefix + suffix]
            assert "farm_id" not in tool["parameters"]["properties"]
            assert f"Bound farm: {farm_id}" in tool["description"]
    for name in (
        "Tractor__mechanical_weed_control",
        "Tractor__plant_seeds",
        "Tractor__harvest",
        "Mavic3M__fly_survey",
        "Robot0__inspect_crop_health",
    ):
        schema = functions[name]["parameters"]
        assert set(schema["properties"]["farm_id"]["enum"]) == set(TARGETS)
        assert "farm_id" in schema["required"]
    for name in ("Tractor__load_fertilizer", "Tractor__load_seeds", "Tractor__refuel", "Tractor__return_supplies"):
        assert "farm_id" not in functions[name]["parameters"]["properties"]


def test_briefing_selection_reaches_agent_without_basic_mode_recipe_leakage():
    requests = []
    for detail in (False, True):
        value, _ = scene(detailed_briefing=detail)
        probe = FirstTurnProbe(value.apps)
        Engine(probe, value).run_scenario_agent()
        users = [message["content"] for message in probe.first_request if message["role"] == "user"]
        assert users == [value.scenario_input]
        requests.append("\n".join(message["content"] for message in probe.first_request))
    for recipe in ("20–23", "40–43", "每趟4垄播种"):
        assert recipe not in requests[0]
        assert recipe in requests[1]
    for fact in ("HEINONG84", "1.88672ha", "farm_id", "北京时间", "地面", "共享"):
        assert fact in requests[0]
    assert get_scenario_class(SCENE)().detailed_briefing is True
    for invalid in (None, 0, 1, "false", "true", "fasle", [], {}):
        with pytest.raises(ValueError, match="JSON boolean"):
            get_scenario_class(SCENE)(detailed_briefing=invalid)
    for detail in (False, True):
        custom, engine = scene(detailed_briefing=detail, scenario_input="自定义：查看两场设备。")
        assert engine._resolve_agent_task() == custom.scenario_input == "自定义：查看两场设备。"


def test_export_is_side_effect_free_and_detail_modes_have_identical_tools_and_plan():
    basic, basic_engine = scene(detailed_briefing=False)
    detailed, detailed_engine = scene(detailed_briefing=True)
    initial = complete_state(basic, basic_engine)
    assert initial == complete_state(detailed, detailed_engine)
    assert build_toolset(basic.apps)[1] == build_toolset(detailed.apps)[1]
    exports = [engine.run_scenario_oracle(False) for engine in (basic_engine, detailed_engine)]
    assert comparable_workflow(exports[0]) == comparable_workflow(exports[1])
    assert complete_state(basic, basic_engine) == complete_state(detailed, detailed_engine) == initial
    seen = set()
    for step in exports[0].dag.values():
        assert step.name not in seen
        assert set(step.depends_on) <= seen
        if seen:
            assert step.depends_on
        seen.add(step.name)


@pytest.fixture(scope="module")
def executions(tmp_path_factory):
    basic, basic_engine = scene(detailed_briefing=False)
    detailed, detailed_engine = scene(detailed_briefing=True)
    initial = complete_state(basic, basic_engine)
    effects = []
    original_operation = basic.tractor._operate_mechanical_weed_control

    def capture_effect(farm, **arguments):
        before = deepcopy({world.farm_id: world.physics.biotic.states for world in (basic.farm_a, basic.farm_b)})
        before_time = basic_engine.time_manager.time()
        result = original_operation(farm, **arguments)
        after = deepcopy({world.farm_id: world.physics.biotic.states for world in (basic.farm_a, basic.farm_b)})
        effects.append((farm.farm_id, arguments, before, after, before_time, basic_engine.time_manager.time()))
        return result

    with patch.object(basic.tractor, "_operate_mechanical_weed_control", side_effect=capture_effect):
        basic_oracle = basic_engine.run_scenario_oracle(True)
    detailed_oracle = detailed_engine.run_scenario_oracle(True)
    assert comparable_workflow(basic_oracle) == comparable_workflow(detailed_oracle)
    assert complete_state(basic, basic_engine) == complete_state(detailed, detailed_engine)
    path = tmp_path_factory.mktemp("soybean_shared_weeding") / "oracle.json"
    detailed_oracle.save_workflow(str(path))
    fresh, replay_engine = scene(detailed_briefing=True)
    replay = replay_engine.replay_workflow(Workflow.load_workflow(str(path)))
    assert comparable_workflow(detailed_oracle) == comparable_workflow(replay)
    assert complete_state(detailed, detailed_engine) == complete_state(fresh, replay_engine)
    for workflow in (basic_oracle, detailed_oracle, replay):
        failures = [
            (step.name, step.content)
            for step in workflow.dag.values()
            if step.error_stage
            or isinstance(step.content, dict)
            and ("error" in step.content or step.content.get("status") in {"partial", "failed"})
        ]
        assert failures == []
    return initial, fresh, replay_engine, replay, effects


def test_real_oracles_and_exact_replay_finish_traceable_safe_harvest(executions):
    initial, value, engine, workflow, _ = executions
    batches = list(value.warehouse.grain_batches.values())
    assert len(batches) == 32
    for farm in (value.farm_a, value.farm_b):
        assert sum(ridge.harvested for ridge in farm._ridges) == 64
        own = [batch for batch in batches if batch.origin_farm_id == farm.farm_id]
        assert len(own) == 16
        assert Counter(ridge for batch in own for ridge in batch.ridge_ids) == Counter(range(64))
        assert all(
            batch.status == "stored"
            and batch.quantity_kg > 0
            and batch.moisture_pct <= 13.5
            and batch.crop_id == "soybean"
            and batch.cultivar_ids == ["HEINONG84"]
            for batch in own
        )
        assert (
            farm.simulation_date()
            == datetime.fromtimestamp(engine.time_manager.time(), ZoneInfo("Asia/Shanghai")).date()
        )
        assert farm._management_regime.fertilizer_used_kg == pytest.approx(200)
        assert farm._management_regime.irrigation_used_mm_total == 0
    machine = value.tractor.get_state()
    assert all(machine[key] == 0 for key in ("seed_hopper", "grain_bin_kg", "fertilizer_spreader_kg"))
    assert value.tractor.grain_origin_farm_id is None
    stock = value.warehouse.stock
    before = initial["apps"]["Warehouse"]["state"]["stock"]
    assert before["seed_stock"]["HEINONG84"] - stock.seed_stock["HEINONG84"] == 857600
    assert before["fertilizer_kg"] - stock.fertilizer_kg == pytest.approx(400)
    assert stock.pesticide_liters == before["pesticide_liters"] == 40
    assert stock.fuel_liters >= 0
    assert not any(
        step.tool_name.endswith(("__apply_fertigation", "__apply_fertilizer", "__apply_herbicide"))
        or "__irrigate" in step.tool_name
        for step in workflow.dag.values()
    )


def test_rain_is_checked_and_waited_out_before_flying_and_cultivating(executions):
    _, _, _, workflow, _ = executions
    names = list(workflow.dag)
    rainy = workflow.dag["weeding_rainy_weather"]
    clear = workflow.dag["weeding_weather"]
    wait = workflow.dag["wait_rain_and_field_drainage"]
    assert rainy.content["rainfall_mm"] > 0
    assert clear.content["rainfall_mm"] == 0
    assert rainy.time_after <= wait.time_before < wait.time_after <= clear.time_before
    between = list(workflow.dag.values())[names.index(rainy.name) : names.index(clear.name)]
    assert not any(step.tool_name in {"Mavic3M__fly_survey", "Tractor__mechanical_weed_control"} for step in between)
    for farm_id in TARGETS:
        assert names.index(f"weeding_rainy_{farm_id}_soil") < names.index(wait.name)
        assert names.index(clear.name) < names.index(f"weeding_{farm_id}_soil")


def test_two_fields_share_drone_charge_and_robot_battery_in_one_window(executions):
    _, _, _, workflow, _ = executions
    names = list(workflow.dag)
    a_flight = workflow.dag["weeding_farm_a_flight"]
    a_charge = workflow.dag["weeding_farm_a_charge_drone"]
    a_ground = ground_steps(workflow, "weeding", "farm_a")
    b_ready = workflow.dag["weeding_farm_b_drone_ready"]
    b_flight = workflow.dag["weeding_farm_b_flight"]
    b_ground = ground_steps(workflow, "weeding", "farm_b")
    assert len(a_ground) == len(b_ground) == 4
    assert a_flight.content["battery_remaining_pct"] == pytest.approx(36)
    assert b_ready.content["battery_pct"] == pytest.approx(100)
    assert b_ready.content["charging"] is False
    assert a_charge.time_before == a_charge.time_after
    assert a_charge.time_after <= a_ground[0].time_before < a_ground[-1].time_after <= b_flight.time_before
    assert a_ground[-1].time_after >= a_charge.content["charge_complete_at"]
    for observations in (a_ground, b_ground):
        assert [step.content["battery_remaining_pct"] for step in observations] == [80, 60, 40, 20]
    robot_charges = [
        step
        for step in workflow.dag.values()
        if step.tool_name == "Robot0__charge" and a_ground[-1].time_after <= step.time_before < b_ground[0].time_before
    ]
    assert len(robot_charges) == 1
    assert b_ground[0].time_before >= robot_charges[0].content["charge_complete_at"]
    # The drone can survey B while the same robot recharges after its A transects.
    assert robot_charges[0].time_after <= b_flight.time_before < robot_charges[0].content["charge_complete_at"]
    intervening = list(workflow.dag.values())[names.index(a_charge.name) : names.index(b_flight.name)]
    assert not any(step.tool_name == "SystemApp__advance_time" for step in intervening)
    for flight in (a_flight, b_flight):
        assert set(flight.content["surveyed_ridges"]) == RIDGES
        start = datetime.fromtimestamp(flight.time_before, ZoneInfo("Asia/Shanghai"))
        end = datetime.fromtimestamp(flight.time_after, ZoneInfo("Asia/Shanghai"))
        assert start.date() == end.date()
        assert time(7) <= start.time() < end.time() <= time(18)
    assert (
        datetime.fromtimestamp(a_ground[0].time_before, ZoneInfo("Asia/Shanghai")).date()
        == datetime.fromtimestamp(b_ground[-1].time_after, ZoneInfo("Asia/Shanghai")).date()
    )


def test_cross_field_samples_precede_complete_cultivation_and_later_rechecks(executions):
    _, value, _, workflow, _ = executions
    treatments = [step for step in workflow.dag.values() if step.tool_name == "Tractor__mechanical_weed_control"]
    assert [step.tool_args["farm_id"] for step in treatments] == ["farm_a"] * 7 + ["farm_b"] * 7
    assert all(left.time_after <= right.time_before for left, right in zip(treatments, treatments[1:]))
    assert workflow.dag["weeding_attach_cultivator"].tool_args == {"implement": "cultivator"}
    assert workflow.dag["weeding_attach_cultivator"].time_after <= treatments[0].time_before
    for farm in (value.farm_a, value.farm_b):
        farm_id = farm.farm_id
        own_treatments = [step for step in treatments if step.tool_args["farm_id"] == farm_id]
        for suffix in ("before", "soil", "canopy", "flight"):
            assert workflow.dag[f"weeding_{farm_id}_{suffix}"].time_after <= treatments[0].time_before
        ground = ground_steps(workflow, "weeding", farm_id)
        assert len(ground) == 4
        assert Counter(rid for step in ground for rid in step.content["covered_ridges"]) == Counter(GROUND_SAMPLES)
        assert GROUND_SAMPLES < RIDGES  # Representative ground checks are not a whole-field inspection.
        for step in ground:
            assert step.time_after <= treatments[0].time_before
            content = step.content
            assert len(content["covered_ridges"]) == 4 and content["uncovered_ridges"] == []
            assert {int(rid) for rid in content["observations"]} == set(content["covered_ridges"])
            assert any(
                obs["weed_present"] and obs["weed_confidence"] >= 0.7 for obs in content["observations"].values()
            )
        assert Counter(rid for step in own_treatments for rid in step.content["treated_ridges"]) == Counter(RIDGES)
        assert all(1 <= len(step.content["treated_ridges"]) <= 10 for step in own_treatments)
        stages = {ridge["growth_stage"] for ridge in workflow.dag[f"weeding_{farm_id}_before"].content["ridges"]}
        assert stages <= {"V1", "V2", "V3", "V4+"}
        rechecks = ground_steps(workflow, "recheck", farm_id)
        assert len(rechecks) == 2
        assert Counter(rid for step in rechecks for rid in step.content["covered_ridges"]) == Counter(RECHECK_SAMPLES)
        for recheck in rechecks:
            assert recheck.time_before >= own_treatments[-1].time_after + 86400
            assert len(recheck.content["covered_ridges"]) == 4
            assert set(recheck.content["covered_ridges"]) < RIDGES
            assert not recheck.content["uncovered_ridges"]
            assert all(obs["weed_pressure_band"] == "low" for obs in recheck.content["observations"].values())
        actions = [action for action in farm.physics.action_log if action.action_type == "mechanical_weed_control"]
        assert len(actions) == 7
        assert Counter(rid for action in actions for rid in action.ridge_ids) == Counter(RIDGES)
        assert all(action.direct_effect_summary["treatment_type"] == "MECHANICAL_WEED" for action in actions)
        assert all(action.direct_effect_summary["residual_window_opened"] is False for action in actions)


def test_real_cultivation_changes_only_its_target_weeds_without_chemical_residual(executions):
    _, _, _, _, effects = executions
    assert len(effects) == 14
    for farm_id in TARGETS:
        assert Counter(
            rid
            for own_farm, arguments, *_ in effects
            if own_farm == farm_id
            for rid in range(arguments["start_ridge"], arguments["end_ridge"] + 1)
        ) == Counter(RIDGES)
    for farm_id, arguments, before, after, start, end in effects:
        current_ridges = set(range(arguments["start_ridge"], arguments["end_ridge"] + 1))
        assert 1 <= len(current_ridges) <= 10
        assert start < end
        assert (
            datetime.fromtimestamp(start, ZoneInfo("Asia/Shanghai")).date()
            == datetime.fromtimestamp(end, ZoneInfo("Asia/Shanghai")).date()
        )
        for observed_farm, old_states in before.items():
            for rid, old in old_states.items():
                new = after[observed_farm][rid]
                if observed_farm == farm_id and rid in current_ridges:
                    assert 0 <= new.weed_pressure < old.weed_pressure
                    assert new.herbicide_residual_days_left == old.herbicide_residual_days_left == 0
                    assert new.insect_pressure == old.insect_pressure
                    assert new.disease_pressure == old.disease_pressure
                    assert new.last_daily_update_day == old.last_daily_update_day
                else:
                    # Per-update diagnostic tags can clear after an earlier
                    # pass; pressure, residuals, totals and date must not change.
                    assert {key: item for key, item in vars(new).items() if key != "tags"} == {
                        key: item for key, item in vars(old).items() if key != "tags"
                    }
