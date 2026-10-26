"""Candidate-only recovery from authoritative, zero-mutation soil guards."""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from scripts.adaptive_management_runner import AdaptiveManagementCompiler
from scripts.compile_wofost_observed_oracle import clean


def harness(tmp_path, *, reason="dry", quota=8., mutation=None, fuel_after_wait=100.,
            pulse_effect_ready=True):
    from fairy.scenarios.workflow import Workflow, WorkflowStep
    value = AdaptiveManagementCompiler.__new__(AdaptiveManagementCompiler)
    start = datetime(2026, 6, 1, 7, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    clock = SimpleNamespace(value=start)
    clock.time = lambda: clock.value
    value.engine = SimpleNamespace(time_manager=clock, start_time=start)
    value.output, value.deadline = tmp_path, start+10*86400
    value.farm = SimpleNamespace(name="Farm", farm_id="f", num_ridges=64)
    value.system = SimpleNamespace(name="SystemApp")
    value._source_steps, value._source_phases = {}, {}
    value._in_management_review = False
    value.trace, value.rejected_guards, value.changes = [], [], []
    value.decisions, value.policy_history = [], []
    value.workflow, value.counter, value.last = Workflow(), 0, None
    value.i = {"WorkflowStep": WorkflowStep}
    state = {"seeds": 0, "fuel": 100., "used": 0., "attempts": 0,
             "vwc": .192, "ready": False, "pending": None}
    events = []
    value.review_management = lambda label: events.append("post_plant_review")
    messages = {"dry": "Soil VWC 0.192 must be within 0.20–0.35 for soybean planting",
                "wet": "Soil VWC 0.370 must be within 0.20–0.35 for soybean planting",
                "cold": "Soil temperature 8.0°C must exceed 10°C for soybean planting",
                "window": "Planting window not open for target ridges 20-23: earliest_date=2026-06-03, today=2026-06-01",
                "unknown": "Field preparation incomplete"}

    def seed_payload(*args):
        events.append("prepare_seed")
        state["seeds"] = 100

    def plant(**args):
        state["attempts"] += 1
        events.append("plant")
        if state["ready"]:
            state["seeds"] -= 4
            clock.value += 222
            return {"status": "ok", "planted_ridges": [20, 21, 22, 23]}
        if mutation == "resource":
            state["seeds"] -= 1
        if mutation == "time":
            clock.value += 1
        return {"error": messages[reason]}

    def status():
        events.append("status")
        return {"fuel_tank_l": state["fuel"]}

    def refuel(**args):
        events.append("refuel")
        state["fuel"] = 100.
        return {"status": "ok"}

    value.tools = {"Tractor__plant_seeds": plant, "Tractor__get_status": status,
                   "Tractor__refuel": refuel}
    value._ensure_seed_payload = seed_payload
    value._harvest_guard_signature = lambda *args: {
        "clock": clock.time(), "seeds": state["seeds"], "fuel": state["fuel"],
        "used": state["used"], "planted": state["ready"]}
    value._tool = lambda method: "FieldOps__irrigate" if method == "irrigate" else None
    value._read = lambda label, method, args=None: ({"management_regime": {
        "irrigation_quota_mm_total": quota, "irrigation_used_mm_total": state["used"]}}
        if method == "get_inventory" else {"public": method, "vwc": state["vwc"]})
    value.gate = lambda *args: events.append("public_gate")

    def water(label, tool, args):
        assert label.startswith("adaptive_seedbed_") and "r1" not in label and "r5" not in label
        assert args == {"start": 20, "end": 23, "hours": .8}
        events.append("irrigation")
        clock.value += 3180
        state["used"] += .25
        state["pending"] = clock.time()+7200
        return {"status": "irrigation_started", "estimated_water_mm_per_ridge": 4.,
                "field_equivalent_irrigation_mm": .25, "effect_ready_at": state["pending"]}

    def advance(label, target, manage=True):
        assert target > clock.time()
        events.extend(["wait", "managed_wait" if manage else "reserved_wait"])
        clock.value = target
        ready = pulse_effect_ready or manage
        state.update(ready=ready, vwc=.23 if ready else .192, fuel=fuel_after_wait)

    value._execute_guarded, value.advance_until = water, advance
    return value, state, events


ARGS = {"start_ridge": 20, "end_ridge": 23, "depth_cm": 4., "seed_spacing_cm": 7.9}


def test_already_committed_water_is_rechecked_without_an_invented_delay(tmp_path):
    value, state, events = harness(tmp_path)
    original = value._execute_guarded
    reads = []
    original_read = value._read

    def water(label, tool, args):
        receipt = original(label, tool, args)
        receipt["effect_ready_at"] = value.engine.time_manager.time()
        return receipt

    def read(label, method, args=None):
        reads.append(method)
        return original_read(label, method, args)

    value._execute_guarded, value._read = water, read
    assert value._seedbed_water("source_guard", ARGS)
    assert "wait" not in events
    assert value.engine.time_manager.time() == value.engine.start_time + 3180
    assert state["used"] == .25 and len(value.policy_history) == 1
    assert reads[-2:] == ["read_soil_sensors", "read_root_zone_sensors"]


def test_water_receipt_with_past_confirmation_is_rejected_without_clock_rewind(tmp_path):
    value, state, events = harness(tmp_path)
    original = value._execute_guarded

    def water(label, tool, args):
        receipt = original(label, tool, args)
        receipt["effect_ready_at"] = value.engine.time_manager.time() - 1
        return receipt

    value._execute_guarded = water
    with pytest.raises(RuntimeError, match="in the past"):
        value._seedbed_water("source_guard", ARGS)
    assert "wait" not in events
    assert value.engine.time_manager.time() == value.engine.start_time + 3180
    assert events.count("irrigation") == 1 and state["used"] == .25


def test_dry_guard_prepares_seed_first_waits_for_water_and_records_success_once(tmp_path):
    value, state, events = harness(tmp_path)
    result = value.call("o_r5_late_plant", "Tractor__plant_seeds", ARGS, op="WRITE")
    assert result["status"] == "ok" and state["attempts"] == 2
    assert events.index("prepare_seed") < events.index("plant")
    assert events.index("irrigation") < events.index("wait") < events.index("public_gate")
    assert state["used"] == .25 and len(value.policy_history) == 1
    assert value.policy_history[0]["purpose"] == "seedbed_guard_repair"
    assert len(value.rejected_guards) == 1
    assert value.rejected_guards[0]["zero_mutation_verified"]
    assert not any(row.get("content", {}).get("error") for row in value.trace)
    assert len([row for row in value.trace if row["tool_name"].endswith("__plant_seeds")]) == 1
    assert value.engine.time_manager.time() == value.engine.start_time+3180+7200+222
    assert value._in_management_review is False


@pytest.mark.parametrize("mutation", ["resource", "time"])
def test_planter_refusal_with_any_resource_or_clock_effect_is_not_discarded(tmp_path, mutation):
    value, state, events = harness(tmp_path, mutation=mutation)
    with pytest.raises(RuntimeError):
        value.call("source_plant", "Tractor__plant_seeds", ARGS)
    assert value.rejected_guards == []
    assert "irrigation" not in events and "wait" not in events
    assert any(row.get("content", {}).get("error") for row in value.trace)
    assert state["attempts"] == 1


@pytest.mark.parametrize("reason", ["wet", "cold"])
def test_wet_or_cold_seedbed_waits_without_irrigation(tmp_path, reason):
    value, state, events = harness(tmp_path, reason=reason)
    result = value.call("source_plant", "Tractor__plant_seeds", ARGS)
    assert result["status"] == "ok" and state["attempts"] == 2
    assert "managed_wait" in events and "irrigation" not in events
    assert state["used"] == 0 and value.policy_history == []
    assert value.engine.time_manager.time() == value.engine.start_time+86400+222


def test_exhausted_water_quota_falls_back_to_wait_without_fabricated_supply(tmp_path):
    value, state, events = harness(tmp_path, quota=.2)
    assert value.call("source_plant", "Tractor__plant_seeds", ARGS)["status"] == "ok"
    assert "irrigation" not in events and "managed_wait" in events
    assert state["used"] == 0 and value.policy_history == []
    assert "Insufficient" in value.decisions[0]["fallback"]


def test_effect_confirmation_does_not_allow_second_pulse_before_daily_commit(tmp_path):
    value, state, events = harness(tmp_path, pulse_effect_ready=False)
    result = value.call("source_plant", "Tractor__plant_seeds", ARGS)
    assert result["status"] == "ok" and state["attempts"] ==3
    assert events.count("irrigation") ==1
    assert events.count("reserved_wait") ==1
    assert events.count("managed_wait") ==1
    assert len(value.policy_history) ==1 and state["used"] ==.25
    assert value.engine.time_manager.time() == value.engine.start_time+3180+86400+222
    assert any(r["kind"] == "seedbed_wait_for_prior_daily_water_commit" for r in value.changes)


def test_retry_rechecks_fuel_after_wait_before_public_guard_signature(tmp_path):
    value, state, events = harness(tmp_path, reason="wet", fuel_after_wait=5.)
    assert value.call("source_plant", "Tractor__plant_seeds", ARGS)["status"] == "ok"
    assert events.index("wait") < events.index("refuel")
    assert events.count("prepare_seed") == 2
    assert len(value.rejected_guards) == 1


def test_unknown_planter_rejection_remains_a_blocked_attempt(tmp_path):
    value, state, events = harness(tmp_path, reason="unknown")
    with pytest.raises(RuntimeError, match="Field preparation incomplete"):
        value.call("source_plant", "Tractor__plant_seeds", ARGS)
    assert value.rejected_guards == [] and state["attempts"] == 1
    assert "wait" not in events and "irrigation" not in events


def public_gate_harness(tmp_path, *, vwc=.192, temperature=18., **options):
    value, state, events = harness(tmp_path, **options)
    state["vwc"] = vwc
    value.sensors = {"Farm": SimpleNamespace(name="Sensor")}
    value._ensure_target_phase = lambda *args: None
    value.current_weather = lambda label: {"rainfall_mm": 0., "temp_c": 20.}
    value.ridges = lambda *args: [{"ridge_id": rid, "planted": False} for rid in range(20, 24)]
    value.tools["Sensor__read_soil_sensors"] = lambda: {"soil_sensors": [{
        "ridge_start": 20, "ridge_end": 23, "vwc": state["vwc"],
        "temp_c": 18. if state["ready"] else temperature}]}
    return value, state, events


def test_public_dry_soil_prepares_seedbed_before_any_failed_plant_attempt(tmp_path):
    value, state, events = public_gate_harness(tmp_path)
    AdaptiveManagementCompiler.gate(value, "plant_seeds", ARGS, "source_plant", "Tractor")
    assert state["attempts"] == 0
    assert events.count("irrigation") == 1 and state["used"] == .25
    assert len(value.policy_history) == 1 and not value.rejected_guards
    assert value.decisions[0]["dry"] and not value.decisions[0]["wet"]


@pytest.mark.parametrize("vwc,temperature", [(.37, 18.), (.192, 8.)])
def test_public_wet_or_cold_gate_awaits_natural_change_without_watering(tmp_path, vwc, temperature):
    reason = "wet" if vwc > .35 else "cold"
    value, state, events = public_gate_harness(tmp_path, vwc=vwc, temperature=temperature, reason=reason)
    AdaptiveManagementCompiler.gate(value, "plant_seeds", ARGS, "source_plant", "Tractor")
    assert "wait" not in events  # The broad probe alone cannot veto this pass.
    value.call("source_plant", "Tractor__plant_seeds", ARGS)
    assert "irrigation" not in events and "managed_wait" in events
    assert state["used"] == 0 and not value.policy_history


@pytest.mark.parametrize("vwc", [float("nan"), -0.1, 1.1])
def test_invalid_public_water_reading_cannot_trigger_seedbed_management(tmp_path, vwc):
    value, state, events = public_gate_harness(tmp_path, vwc=vwc)
    with pytest.raises(RuntimeError, match="finite"):
        AdaptiveManagementCompiler.gate(value, "plant_seeds", ARGS, "source_plant", "Tractor")
    assert "irrigation" not in events and "wait" not in events


def test_public_gate_waits_for_prior_water_daily_commit_without_stacking_pulses(tmp_path):
    value, state, events = public_gate_harness(tmp_path, pulse_effect_ready=False)
    AdaptiveManagementCompiler.gate(value, "plant_seeds", ARGS, "source_plant", "Tractor")
    value.call("source_plant", "Tractor__plant_seeds", ARGS)
    assert events.count("irrigation") == 1 and events.count("managed_wait") == 1
    assert state["used"] == .25 and len(value.policy_history) == 1
    assert value.engine.time_manager.time() == value.engine.start_time + 3180 + 86400 + 222


@pytest.mark.parametrize("missing_tool", [False, True])
def test_public_gate_with_no_available_water_waits_and_manages_established_crop(tmp_path, missing_tool):
    value, state, events = public_gate_harness(tmp_path, quota=.2)
    if missing_tool:
        value._tool = lambda method: None
    AdaptiveManagementCompiler.gate(value, "plant_seeds", ARGS, "source_plant", "Tractor")
    value.call("source_plant", "Tractor__plant_seeds", ARGS)
    assert events.count("managed_wait") == 1 and "irrigation" not in events
    assert state["used"] == 0


def test_untreated_neighbours_do_not_cause_repeat_watering_of_a_ready_target(tmp_path):
    value, state, events = public_gate_harness(tmp_path, pulse_effect_ready=False)
    # This broad probe remains dry because it includes untreated neighbours.
    value.tools["Sensor__read_soil_sensors"] = lambda: {"soil_sensors": [{
        "ridge_start": 16, "ridge_end": 31, "vwc": .18, "temp_c": 18.}]}
    value.gate = AdaptiveManagementCompiler.gate.__get__(value)
    value.gate("plant_seeds", ARGS, "source_plant", "Tractor")
    value.call("source_plant", "Tractor__plant_seeds", ARGS)
    assert state["ready"] and state["attempts"] == 2
    assert events.count("irrigation") == 1 and state["used"] == .25
    assert events.count("managed_wait") == 1
    assert value._plant_guard_active is False


def test_coarse_wet_probe_does_not_prevent_a_valid_target_from_planting(tmp_path):
    value, state, events = public_gate_harness(tmp_path, vwc=.37)
    state["ready"] = True
    AdaptiveManagementCompiler.gate(value, "plant_seeds", ARGS, "source_plant", "Tractor")
    value.call("source_plant", "Tractor__plant_seeds", ARGS)
    assert state["attempts"] == 1 and "wait" not in events and "irrigation" not in events


def test_public_planting_window_rejection_waits_until_open_without_early_sowing(tmp_path):
    value, state, events = harness(tmp_path, reason="window")
    result = value.call("source_plant", "Tractor__plant_seeds", ARGS)
    opens = datetime(2026, 6, 3, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    assert result["status"] == "ok" and value.engine.time_manager.time() == opens + 222
    assert "irrigation" not in events and "managed_wait" in events
    assert len(value.rejected_guards) == 1
    assert value.rejected_guards[0]["soil_rejection"] == "window_not_open"


def test_registered_seedbed_pulse_reaches_soil_and_native_initial_water_with_exact_replay(tmp_path):
    pytest.importorskip("pcse")
    from fairy.apps.farm_world import FarmWorldApp, SensorApp, WeatherApp
    from fairy.apps.farm_world.field_ops_app import FieldOpsApp
    from fairy.apps.farm_world.tractor_app import TractorApp
    from fairy.apps.system import SystemApp
    from fairy.agents.agent.toolset_builder import build_toolset
    from fairy.controllers.engine import Engine
    from fairy.physics.weather_engine import MonthlyClimate, WeatherGenerator, WeatherGeneratorConfig
    from fairy.scenarios.scenario import Scenario
    from fairy.scenarios.workflow import Workflow, WorkflowStep

    class DrySeedbedScene(Scenario):
        start_time = datetime(2026, 6, 1, 7, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        duration = 5*86400

        def init_and_populate_apps(self):
            farm, weather = FarmWorldApp(num_ridges=4), WeatherApp()
            weather.set_weather("2026-06-01", 20, 55, 2, 0, 250)
            farm.attach_weather_app(weather)
            farm.set_season_phase("full_season")
            farm._sim_date = "2026-06-01"
            for row in farm._ridges:
                row.soil_vwc, row.soil_temp_c = .192, 18.
            farm.configure_management_regime(irrigation_quota_mm_total=8.)
            farm.physics.engines_active = True
            farm.physics.weather_generator = WeatherGenerator(WeatherGeneratorConfig(
                monthly={month: MonthlyClimate(20, 0, .4, 20) for month in range(1, 13)}), seed=17)
            farm.physics.profile = SimpleNamespace(weather_events=[])
            tractor = TractorApp(farm, weather)
            tractor.seed_type = "HEINONG84"
            # Explicit initial establishment state; no tool or guard is mocked.
            tractor._completed_prep_ops = ["level", "base_fertilize", "form_ridges"]
            self.apps = [farm, weather, tractor, FieldOpsApp(farm, weather), SensorApp(farm), SystemApp()]

    imports = {"FarmWorldApp": FarmWorldApp, "WeatherApp": WeatherApp,
               "SensorApp": SensorApp, "SystemApp": SystemApp, "Engine": Engine,
               "Workflow": Workflow, "WorkflowStep": WorkflowStep, "build_toolset": build_toolset,
               "get_scenario_class": lambda sid: DrySeedbedScene}
    value = AdaptiveManagementCompiler("dry_seedbed", {"cultivar_profile": "heilongjiang_heinong84_complete_v1"},
                                      tmp_path, imports, manage_crop=False)
    args = {"start_ridge": 0, "end_ridge": 3, "depth_cm": 4., "seed_spacing_cm": 7.9}
    started = value.engine.time_manager.time()
    # Test actual registered water delivery independently of the noisy public
    # readiness gate. Fake-clock tests above exercise the planter retry loop.
    assert value._seedbed_water("source_guard", args)
    value.advance_until("preplant_water_daily_commit", started+86400, manage=False)
    receipt = value.call("o_late_zone_plant", "TractorApp__plant_seeds", args, op="WRITE")
    assert receipt["planted_ridges"] == [0, 1, 2, 3]
    assert value.engine.time_manager.time() >= started+3180+7200
    assert value.farm._management_regime.irrigation_used_mm_total == 4.
    assert len(value.policy_history) == 1
    assert value.policy_history[0]["response"]["field_equivalent_irrigation_mm"] == 4.
    assert all(r["zero_mutation_verified"] for r in value.rejected_guards)
    # Advance to create actual native crop objects. Preplant water enters
    # native initial SM/WAV rather than a duplicate native irrigation signal.
    value.advance_until("native_first_day", value.engine.time_manager.time()+86400, manage=False)
    before = clean(value.snapshot_unrecorded(value.scenario, value.engine))
    for run in before["farms"]["FarmWorldApp"]["native_backend"]["ridges"].values():
        assert run["specification"]["preplant_inputs"]["irrigation_mm"] == 4.
        assert run["cumulative_irrigation_mm"] == 4.
    fresh, engine = value.fresh()
    replayed = engine.replay_workflow(value.workflow)
    assert clean(value.snapshot_unrecorded(fresh, engine)) == before
    assert [(s.tool_args, clean(s.content), s.time_before, s.time_after) for s in replayed.dag.values()] == [
        (s.tool_args, clean(s.content), s.time_before, s.time_after) for s in value.workflow.dag.values()]
