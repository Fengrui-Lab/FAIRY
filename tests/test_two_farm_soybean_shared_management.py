"""Execute the soybean scheduling reference without using a scene validator.

These checks inspect actual tool results, coverage, resources and timestamps.
A missing validator's default success flag is deliberately not evidence here.
"""

from collections import Counter
from copy import deepcopy
from datetime import datetime, time
import re
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from fairy.agents.agent.agent import Agent
from fairy.agents.agent.toolset_builder import build_toolset
from fairy.controllers.engine import Engine
from fairy.physics.profiles import get_profile
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.workflow import Workflow


SCENE = "scenario_two_farm_soybean_shared_management"
PROFILE = "harbin_baseline_2026_seed_101"
TARGETS = {"farm_a": set(range(20, 40)), "farm_b": set(range(40, 60))}
RIDGES = set(range(64))
VOLATILE_IDS = {"op_id", "action_id", "mission_id", "inspection_id"}
UUID_PATTERN = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def scene(**kwargs):
    value = get_scenario_class(SCENE)(**kwargs)
    value.setup()
    return value, Engine(None, value)


def comparable(value):
    """Normalize random identifiers, retaining all agronomic and time values."""
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


class FirstTurnProbe(Agent):
    """Exercise real task selection while replacing only the network response."""

    def __init__(self, apps):
        super().__init__(
            "briefing-probe", SimpleNamespace(provider="openai"), system_message="Test controller.", toolsets=apps
        )

    def _chat_completion_with_retries(self, messages, tools=None):
        self.first_request = deepcopy(messages)
        return SimpleNamespace(content="Offline input captured.", tool_calls=[])


def test_initial_fields_have_local_fertility_and_independent_fixed_installations():
    registered = get_profile(PROFILE)
    before = deepcopy(registered)
    value, engine = scene()
    assert value.farm_a.physics.profile is not value.farm_b.physics.profile
    assert value.farm_a.physics.profile is not registered
    assert value.farm_b.physics.profile is not registered
    assert registered == before
    assert value.farm_a.physics.profile == value.farm_b.physics.profile
    assert not value.farm_a.physics.profile.biotic_outbreaks
    for farm, nutrient in ((value.farm_a, 0.66), (value.farm_b, 0.72)):
        assert farm.crop_id == "soybean"
        assert farm.num_ridges == 64
        assert farm.field_geometry.planted_area_m2 == pytest.approx(18867.2)
        assert farm.rows_per_ridge == 2
        assert not farm.completed_prep_ops
        assert not any(ridge.planted or ridge.harvested for ridge in farm._ridges)
        for ridge in farm._ridges:
            expected = nutrient if ridge.ridge_id in TARGETS[farm.farm_id] else 0.82
            assert ridge.nutrient_index == pytest.approx(expected)
        assert farm._management_regime.irrigation_quota_mm_total == 20
        assert farm._management_regime.fertilizer_quota_kg == 300
    assert value.sensor_a is not value.sensor_b
    assert value.irrigation_a is not value.irrigation_b
    assert value.sensor_a._soil_sensors is not value.sensor_b._soil_sensors
    assert value.farm_environment.warehouse is value.warehouse
    assert value.shared_equipment == [value.tractor, value.mavic, value.robot]
    assert all(sum(app is shared for app in value.apps) == 1 for shared in [value.warehouse, *value.shared_equipment])
    assert all(app.time_manager is engine.time_manager for app in value.apps)
    assert str(value.farm_environment.simulation_timezone) == "Asia/Shanghai"
    assert type(value).validate is Scenario.validate
    assert value.validate() is None


def test_public_tools_distinguish_fixed_installations_from_one_mobile_fleet():
    value, _ = scene()
    functions = {entry["function"]["name"]: entry["function"] for entry in build_toolset(value.apps)[1]}
    for prefix, farm_id in (("FarmA", "farm_a"), ("FarmB", "farm_b")):
        for suffix in ("_Sensor__read_soil_sensors", "_Irrigation__irrigate"):
            tool = functions[prefix + suffix]
            assert "farm_id" not in tool["parameters"]["properties"]
            assert f"Bound farm: {farm_id}" in tool["description"]
    for name in (
        "Tractor__apply_fertilizer",
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


def test_detail_selection_reaches_real_agent_without_leaking_reference_recipe():
    first_requests = []
    for detail in (False, True):
        value, _ = scene(detailed_briefing=detail)
        probe = FirstTurnProbe(value.apps)
        Engine(probe, value).run_scenario_agent()
        users = [message["content"] for message in probe.first_request if message["role"] == "user"]
        assert users == [value.scenario_input]
        assert next(iter(probe.workflow.dag.values())).content == value.scenario_input
        assert "Use the shared Tractor for seasonal granular topdressing" in value.additional_system_prompt
        first_requests.append("\n".join(message["content"] for message in probe.first_request))
    for recipe in ("2kg/垄", "共80kg", "A20–39", "B40–59"):
        assert recipe not in first_requests[0]
        assert recipe in first_requests[1]
    for fact in ("1.88672ha", "HEINONG84", "Warehouse", "farm_id", "北京时间"):
        assert fact in first_requests[0]
    default = get_scenario_class(SCENE)()
    assert default.detailed_briefing is True
    assert default.scenario_input == get_scenario_class(SCENE)(detailed_briefing=True).scenario_input
    for invalid in (None, 0, 1, "false", "true", "fasle", [], {}):
        with pytest.raises(ValueError, match="JSON boolean"):
            get_scenario_class(SCENE)(detailed_briefing=invalid)
    for detail in (False, True):
        custom, engine = scene(detailed_briefing=detail, scenario_input="自定义：只查看两场。")
        assert engine._resolve_agent_task() == custom.scenario_input == "自定义：只查看两场。"


@pytest.fixture(scope="module")
def executions(tmp_path_factory):
    basic, basic_engine = scene(detailed_briefing=False)
    detailed, detailed_engine = scene(detailed_briefing=True)
    initial = complete_state(basic, basic_engine)
    assert initial == complete_state(detailed, detailed_engine)
    assert build_toolset(basic.apps)[1] == build_toolset(detailed.apps)[1]
    exports = [engine.run_scenario_oracle(False) for engine in (basic_engine, detailed_engine)]
    assert comparable_workflow(exports[0]) == comparable_workflow(exports[1])
    assert complete_state(basic, basic_engine) == initial
    assert complete_state(detailed, detailed_engine) == initial

    oracles = [engine.run_scenario_oracle(True) for engine in (basic_engine, detailed_engine)]
    assert comparable_workflow(oracles[0]) == comparable_workflow(oracles[1])
    assert complete_state(basic, basic_engine) == complete_state(detailed, detailed_engine)
    path = tmp_path_factory.mktemp("soybean_shared_management") / "oracle.json"
    oracles[1].save_workflow(str(path))
    fresh, replay_engine = scene(detailed_briefing=True)
    replay = replay_engine.replay_workflow(Workflow.load_workflow(str(path)))
    assert comparable_workflow(oracles[1]) == comparable_workflow(replay)
    assert complete_state(detailed, detailed_engine) == complete_state(fresh, replay_engine)
    for workflow in [*oracles, replay]:
        failures = [
            (step.name, step.content)
            for step in workflow.dag.values()
            if step.error_stage
            or isinstance(step.content, dict)
            and ("error" in step.content or step.content.get("status") == "partial")
        ]
        assert failures == []
    return initial, fresh, replay_engine, replay


def test_real_oracles_and_saved_replay_finish_all_ridges_in_traceable_safe_batches(executions):
    initial, value, engine, workflow = executions
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
    machine = value.tractor.get_state()
    assert all(machine[key] == 0 for key in ("seed_hopper", "grain_bin_kg", "fertilizer_spreader_kg"))
    assert value.tractor.grain_origin_farm_id is None
    stock = value.warehouse.stock
    initial_stock = initial["apps"]["Warehouse"]["state"]["stock"]
    assert initial_stock["seed_stock"]["HEINONG84"] - stock.seed_stock["HEINONG84"] == 857600
    assert initial_stock["fertilizer_kg"] - stock.fertilizer_kg == pytest.approx(480)
    assert stock.pesticide_liters == initial_stock["pesticide_liters"]
    assert stock.fuel_liters >= 0
    assert not any(
        step.tool_name.endswith("__apply_fertigation") or "__irrigate" in step.tool_name
        for step in workflow.dag.values()
    )


def test_rain_is_observed_then_waited_out_before_rechecking_and_using_equipment(executions):
    _, _, _, workflow = executions
    names = list(workflow.dag)
    rainy = workflow.dag["management_rainy_weather"]
    clear = workflow.dag["management_weather"]
    wait = workflow.dag["wait_rain_and_field_drainage"]
    assert rainy.content["rainfall_mm"] > 0
    assert clear.content["rainfall_mm"] == 0
    assert rainy.time_after <= wait.time_before < wait.time_after <= clear.time_before
    between = list(workflow.dag.values())[names.index(rainy.name) : names.index(clear.name)]
    assert not any(step.tool_name in {"Mavic3M__fly_survey", "Tractor__apply_fertilizer"} for step in between)
    for farm_id in TARGETS:
        assert names.index(f"management_rainy_{farm_id}_soil") < names.index(wait.name)
        assert names.index(clear.name) < names.index(f"management_{farm_id}_soil")


def test_shared_drone_recharges_during_real_ground_work_before_the_other_field(executions):
    _, _, _, workflow = executions
    names = list(workflow.dag)
    for phase in ("emergence", "management"):
        a_flight = workflow.dag[f"{phase}_farm_a_flight"]
        a_charge = workflow.dag[f"{phase}_farm_a_charge_drone"]
        ground_name = f"{phase}_farm_a_ground_0_3" if phase == "emergence" else f"{phase}_farm_a_health"
        a_ground = workflow.dag[ground_name]
        b_ready = workflow.dag[f"{phase}_farm_b_drone_ready"]
        b_flight = workflow.dag[f"{phase}_farm_b_flight"]
        assert a_flight.content["battery_remaining_pct"] == pytest.approx(36)
        assert b_ready.content["battery_pct"] == pytest.approx(100)
        assert b_ready.content["charging"] is False
        assert a_charge.time_before == a_charge.time_after
        assert a_charge.time_after <= a_ground.time_before < a_ground.time_after <= b_flight.time_before
        assert a_ground.time_after - a_ground.time_before == pytest.approx(2800)
        assert a_ground.time_after >= a_charge.content["charge_complete_at"]
        intervening = list(workflow.dag.values())[names.index(a_charge.name) : names.index(b_flight.name)]
        assert not any(step.tool_name == "SystemApp__advance_time" for step in intervening)
        for flight in (a_flight, b_flight):
            assert set(flight.content["surveyed_ridges"]) == RIDGES
            start = datetime.fromtimestamp(flight.time_before, ZoneInfo("Asia/Shanghai"))
            end = datetime.fromtimestamp(flight.time_after, ZoneInfo("Asia/Shanghai"))
            assert start.date() == end.date()
            assert time(7) <= start.time() < end.time() <= time(18)
    samples = [step for step in workflow.dag.values() if step.tool_name.startswith("Robot0__inspect_")]
    assert all(len(step.content["covered_ridges"]) == 4 and not step.content["uncovered_ridges"] for step in samples)


def test_both_fields_are_observed_before_local_treatment_and_nutrition_is_rechecked(executions):
    _, value, _, workflow = executions
    treatments = [step for step in workflow.dag.values() if step.tool_name == "Tractor__apply_fertilizer"]
    assert [step.tool_args["farm_id"] for step in treatments] == ["farm_a", "farm_a", "farm_b", "farm_b"]
    for farm_id in TARGETS:
        for suffix in ("before", "soil", "canopy", "flight", "health"):
            assert workflow.dag[f"management_{farm_id}_{suffix}"].time_after <= treatments[0].time_before
        own = [step for step in treatments if step.tool_args["farm_id"] == farm_id]
        assert Counter(ridge for step in own for ridge in step.content["fertilized_ridges"]) == Counter(
            TARGETS[farm_id]
        )
        assert sum(step.content["fertilizer_used_kg"] for step in own) == pytest.approx(40)
        before = workflow.dag[f"management_{farm_id}_before"]
        after = workflow.dag[f"management_{farm_id}_after"]
        for old, new in zip(before.content["ridges"], after.content["ridges"]):
            assert old["ridge_id"] == new["ridge_id"]
            if old["ridge_id"] in TARGETS[farm_id]:
                assert new["nutrient_index"] > old["nutrient_index"]
            else:
                assert new["nutrient_index"] == old["nutrient_index"]
        assert workflow.dag[f"recheck_{farm_id}_state"].time_before >= after.time_after + 86400
    assert all(a.time_after <= b.time_before for a, b in zip(treatments, treatments[1:]))
    assert workflow.dag["management_farm_a_remaining_payload"].content["fertilizer_spreader_kg"] == 40
    assert workflow.dag["management_farm_b_remaining_payload"].content["fertilizer_spreader_kg"] == 0
    for farm in (value.farm_a, value.farm_b):
        assert farm._management_regime.fertilizer_used_kg == pytest.approx(240)
        assert farm._management_regime.irrigation_used_mm_total == 0
