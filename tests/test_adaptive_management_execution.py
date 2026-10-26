"""Adaptive execution constraints with fake clocks/tools, without native crops."""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest

from scripts import adaptive_management_runner as runner
from scripts.compile_wofost_observed_oracle import ObservedCompiler, TZ


class Clock:
    def __init__(self, value):
        self.value = value

    def time(self):
        return self.value


def stamp(text):
    return datetime.fromisoformat(text).replace(tzinfo=TZ).timestamp()


def compiler(now=None):
    now = stamp("2026-07-15T06:00:00") if now is None else now
    value = runner.AdaptiveManagementCompiler.__new__(runner.AdaptiveManagementCompiler)
    value.engine = SimpleNamespace(time_manager=Clock(now), start_time=now)
    value.deadline = now + 10 * 86400
    value.system = SimpleNamespace(name="SystemApp")
    value._in_management_review = False
    value._source_steps = {}
    value.review_management = lambda label: None
    return value


def fake_waits(monkeypatch, value):
    calls = []

    def call(self, label, tool, args, **kwargs):
        before = self.engine.time_manager.time()
        assert tool == "SystemApp__advance_time"
        assert args["seconds"] > 0
        self.engine.time_manager.value += args["seconds"]
        calls.append({"before": before, "after": self.engine.time_manager.time(), "args": args})
        return {"status": "ok", "current_timestamp": self.engine.time_manager.time()}

    monkeypatch.setattr(ObservedCompiler, "call", call)
    return calls


def test_absolute_wait_keeps_daily0700_checkpoints(monkeypatch):
    value = compiler()
    calls = fake_waits(monkeypatch, value)
    reviews = []
    value.review_management = lambda label: reviews.append(value.engine.time_manager.time())
    target = stamp("2026-07-17T08:00:00")
    value.advance_until("growth", target)
    assert [row["args"]["seconds"] for row in calls] == [3600, 86400, 86400, 3600]
    assert value.engine.time_manager.time() == target
    assert reviews == [stamp(text) for text in ["2026-07-15T06:00:00", "2026-07-15T07:00:00",
        "2026-07-16T07:00:00", "2026-07-17T07:00:00", "2026-07-17T08:00:00"]]


def test_real_management_duration_can_pass_target_without_extra_wait(monkeypatch):
    value = compiler()
    calls = fake_waits(monkeypatch, value)
    reviews = []

    def review(label):
        reviews.append(value.engine.time_manager.time())
        if len(reviews) == 1:
            value.engine.time_manager.value += 2 * 3600

    value.review_management = review
    value.advance_until("growth", stamp("2026-07-15T07:00:00"))
    assert calls == []
    assert value.engine.time_manager.time() == stamp("2026-07-15T08:00:00")


def test_past_target_never_rewinds_or_adds_source_relative_day(monkeypatch):
    value = compiler()
    before = value.engine.time_manager.time()
    calls = fake_waits(monkeypatch, value)
    value.advance_until("already_reached", before - 86400)
    assert calls == []
    assert value.engine.time_manager.time() == before


def test_nested_effect_wait_cannot_reenter_policy_review(monkeypatch):
    value = compiler()
    value._in_management_review = True
    value.review_management = lambda label: pytest.fail("Recursive management review")
    calls = fake_waits(monkeypatch, value)
    before = value.engine.time_manager.time()
    value.wait("receipt_followup", 7200)
    assert sum(row["args"]["seconds"] for row in calls) == 7200
    assert value.engine.time_manager.time() == before + 7200


def test_original_deadline_is_checked_before_any_wait(monkeypatch):
    value = compiler()
    calls = fake_waits(monkeypatch, value)
    before = value.engine.time_manager.time()
    with pytest.raises(RuntimeError, match="original scenario duration"):
        value.advance_until("late", value.deadline + 1)
    assert calls == []
    assert value.engine.time_manager.time() == before


def test_integer_second_tool_does_not_silently_overshoot_fractional_deadline(monkeypatch):
    value = compiler()
    calls = fake_waits(monkeypatch, value)
    before = value.engine.time_manager.time()
    value.deadline = before + .5
    with pytest.raises(RuntimeError, match="Integer-second"):
        value.advance_until("fractional_end", value.deadline)
    assert calls == []
    assert value.engine.time_manager.time() == before


def test_management_overrun_retains_real_clock_and_is_infeasible(monkeypatch):
    value = compiler()
    before = value.engine.time_manager.time()
    value.deadline = before + 3 * 3600
    calls = fake_waits(monkeypatch, value)
    value.review_management = lambda label: setattr(value.engine.time_manager, "value", before + 4 * 3600)
    with pytest.raises(RuntimeError, match="Management work exceeded"):
        value.advance_until("late_work", before + 2 * 3600)
    assert calls == []
    assert value.engine.time_manager.time() == before + 4 * 3600


def test_calendar_wait_uses_original_absolute_time_not_fresh_relative_days():
    value = compiler()
    value._source_steps = {"old_wait": SimpleNamespace(time="2026-07-15 07:00:00")}
    targets = []
    value.advance_until = lambda label, target, manage=True: targets.append((target, manage))
    value._calendar_wait("old_wait", "SystemApp__advance_time", {"seconds": 86400}, "WRITE", False)
    assert targets == [(stamp("2026-07-15T07:00:00"), True)]


@pytest.mark.parametrize("arguments, expected_seconds", [
    ({"days": 1}, 86400), ({"hours": 2}, 7200),
    ({"minutes": 3}, 180), ({"seconds": 4}, 4),
    ({"days": 1, "hours": 2, "minutes": 3, "seconds": 4}, 93784),
])
def test_source_relative_wait_accepts_every_registered_time_unit(arguments, expected_seconds):
    value = compiler()
    before = value.engine.time_manager.time()
    relative = []
    value.wait = lambda label, seconds=86400: relative.append(seconds)
    value.call("source_relative", "SystemApp__advance_time", arguments)
    assert relative == [expected_seconds]
    targets = []
    value._source_steps["calendar_without_absolute_time"] = SimpleNamespace(time=None)
    value.advance_until = lambda label, target, manage=True: targets.append(target)
    value._calendar_wait("calendar_without_absolute_time", "SystemApp__advance_time", arguments, "WRITE", False)
    assert targets == [before + expected_seconds]


def test_crossday_operation_commits_receipt_before_new_review(monkeypatch):
    value = compiler(stamp("2026-07-15T23:30:00"))
    events = []

    def operation(self, label, tool, args, **kwargs):
        events.append("operation_started")
        self.engine.time_manager.value += 3600
        events.append("resource_registration_committed")
        return {"status": "ok"}

    monkeypatch.setattr(runner.FrozenWeatherCompiler, "call", operation)
    value.review_management = lambda label: events.append("management_review")
    result = value.call("water", "FieldOps__irrigate", {"start": 0, "end": 7, "hours": 1})
    assert result == {"status": "ok"}
    assert events == ["operation_started", "resource_registration_committed", "management_review"]
    value._in_management_review = True
    events.clear()
    value.call("nested", "FieldOps__irrigate", {"start": 0, "end": 7, "hours": 1})
    assert events == ["operation_started", "resource_registration_committed"]


class Workflow:
    def __init__(self):
        self.dag = {}

    def add_node(self, step):
        self.dag[step.name] = step


def workflow(operations):
    value = Workflow()
    for index, method in enumerate(operations):
        value.add_node(SimpleNamespace(name=f"s{index}", tool_name="App__" + method,
            tool_args={"sentinel": index}, depends_on=["previous"], time="2026-07-15 07:00:00"))
    return value


def test_fixed_growth_prescriptions_removed_but_establishment_replant_and_harvest_kept():
    operations = ["load_fertilizer", "base_fertilize", "plant_seeds", "get_ridge_range_state",
        "load_fertilizer", "apply_fertilizer", "apply_fertigation", "load_fungicide", "apply_fungicide",
        "refill_pesticide_tank", "spray_pesticide", "apply_herbicide", "mechanical_weed_control",
        "irrigate", "replant_seeds", "harvest", "dry_grain", "store_grain"]
    source = workflow(operations)
    original = deepcopy(source.dag)
    kept, removed = runner.without_fixed_growth_management(source, Workflow)
    assert [s.tool_name.rsplit("__", 1)[-1] for s in kept.dag.values()] == [
        "load_fertilizer", "base_fertilize", "plant_seeds", "get_ridge_range_state", "replant_seeds", "harvest", "dry_grain", "store_grain"]
    assert len(removed) == len(operations) - len(kept.dag)
    assert source.dag == original
    prior = None
    for step in kept.dag.values():
        assert step.depends_on == ([prior] if prior else [])
        prior = step.name


def test_staggered_block_can_keep_later_establishment_fertilizer_load():
    source = workflow(["plant_seeds", "load_fertilizer", "base_fertilize", "plant_seeds",
                       "load_fertilizer", "apply_fertilizer", "harvest"])
    kept, _ = runner.without_fixed_growth_management(source, Workflow)
    assert [s.tool_name.rsplit("__", 1)[-1] for s in kept.dag.values()] == [
        "plant_seeds", "load_fertilizer", "base_fertilize", "plant_seeds", "harvest"]


@pytest.mark.parametrize("has_management_tool", [False, True])
def test_water_observation_falls_back_to_registered_inventory_and_only_reads_registered_root(has_management_tool):
    value = compiler()
    methods = ["get_current_time", "get_farm_overview", "get_ridge_range_state", "get_inventory",
               "get_forecast", "read_soil_sensors"]
    if has_management_tool:
        methods += ["get_management_status", "read_root_zone_sensors"]
    value.tools = {"Public__" + method: None for method in methods}
    calls = []
    limit = {"management_regime": {"irrigation_quota_mm_total": 8, "irrigation_used_mm_total": 0}}

    def public_call(label, tool, args, **kwargs):
        method = tool.rsplit("__", 1)[-1]
        calls.append((method, deepcopy(args)))
        if method == "get_current_time":
            return {"current_timestamp": value.engine.time_manager.time(), "current_datetime": "2026-07-15 06:00:00"}
        if method == "get_farm_overview":
            return {"farm_id": "east", "num_ridges": 64}
        if method in {"get_management_status", "get_inventory"}:
            return limit
        if method == "get_ridge_range_state":
            return {"ridges": []}
        return {"public_response": method}

    value.call = public_call
    result = value._observe_water("test")
    assert result["management"] == limit
    assert result["capabilities"]["root_zone_registered"] is has_management_tool
    assert result["observed_at"]["root_zone"] == result["clock"]
    assert ("get_ridge_range_state", {"start": 0, "end": 63}) in calls
    if has_management_tool:
        assert any(method == "get_management_status" for method, _ in calls)
        assert any(method == "read_root_zone_sensors" for method, _ in calls)
    else:
        assert any(method == "get_inventory" for method, _ in calls)
        assert not any(method == "read_root_zone_sensors" for method, _ in calls)
        assert result["root_zone"] is None


def test_review_refreshes_water_budget_and_probes_after_each_real_receipt(tmp_path):
    value = compiler(stamp("2026-07-15T08:00:00"))
    # Restore the real review method overwritten by the minimal clock fixture.
    value.review_management = runner.AdaptiveManagementCompiler.review_management.__get__(value)
    value.output = tmp_path
    value._last_review_day = None
    value.policy_history, value.crop_history, value.decisions = [], [], []
    value.irrigation_parameters = None
    value.manage_crop = False
    value._tool = lambda method: "FieldOps__irrigate" if method == "irrigate" else None
    observed_quota = []
    used = 0.0

    def observe(label):
        observed_quota.append(used)
        now = value.engine.time_manager.time()
        current = {"current_timestamp": now, "current_datetime": datetime.fromtimestamp(now, TZ).strftime("%Y-%m-%d %H:%M:%S")}
        return {"clock": current, "overview": {"farm_id": "east", "num_ridges": 64, "crop_type": "soybean"},
            "ridges": {"ridges": [{"ridge_id": rid, "planted": True, "harvested": False, "growth_stage": "R5"} for rid in range(16)]},
            "management": {"management_regime": {"irrigation_quota_mm_total": 8, "irrigation_used_mm_total": used}},
            "forecast": {"forecast": []},
            "root_zone": {"root_zone_sensors": [{"ridge_start": start, "ridge_end": start + 7, "root_vwc": .20} for start in (0, 8)]},
            "surface": None, "capabilities": {"application_mm_per_hour": 5, "root_zone_registered": True},
            "observed_at": {"root_zone": current}}

    def execute(label, tool, args):
        nonlocal used
        amount = args["hours"] * 5 * (args["end"] - args["start"] + 1) / 64
        used += amount
        value.engine.time_manager.value += 300 + int(args["hours"] * 3600)
        return {"status": "irrigation_started", "irrigated_ridges": list(range(args["start"], args["end"] + 1)),
                "field_equivalent_irrigation_mm": amount, "effect_ready_at": value.engine.time_manager.time()}

    value._observe_water = observe
    value._execute_guarded = execute
    value.review_management("test")
    assert len(value.policy_history) == 2
    assert observed_quota == [0, 1, 2]
    assert used == 2
    assert [row["tool_args"]["start"] for row in value.policy_history] == [0, 8]
    assert value.decisions[-1]["decision"]["action"] == "wait"
    assert value.decisions[-1]["decision"]["audit"]["successful_operations_today"] == 2
    assert all(row["finished_at"] > row["started_at"] for row in value.policy_history)
    assert not value._in_management_review


def test_rejected_guard_is_removed_from_replay_only_after_public_zero_mutation_proof():
    value = compiler()
    now = value.engine.time_manager.time()
    value.trace, value.rejected_guards = [], []
    value._guard_signature = lambda label: {"clock": now, "inventory": {"water": 1}}

    def reject(label, tool, args, **kwargs):
        value.trace.append({"discovery_only_rejected_guard": True, "time_before": now, "time_after": now})
        return {"error": "outside field quota"}

    value.call = reject
    assert value._execute_guarded("bad", "FieldOps__irrigate", {})["error"]
    assert value.trace == []
    assert value.rejected_guards[0]["zero_mutation_verified"]
    signatures = iter([{"inventory": 1}, {"inventory": 0}])
    value._guard_signature = lambda label: next(signatures)
    with pytest.raises(RuntimeError, match="mutated public state"):
        value._execute_guarded("bad_mutation", "FieldOps__irrigate", {})
    assert value.trace


def test_four_ridge_scout_charges_from20percent_before_inspection_and_keeps_return_reserve(monkeypatch):
    value = compiler(stamp("2026-07-15T08:00:00"))
    value.farm = SimpleNamespace(num_ridges=4)
    value.crop_parameters, value.crop_history, value.decisions = {}, [], []
    value._previous_crop_observation = None
    value._tool = lambda method: "RobotDog__inspect_crop_health" if method == "inspect_crop_health" else None
    battery = {"percent": 20.0, "charging": False}
    events, required_reserves, policy_inputs = [], [], []
    original_battery = ObservedCompiler.battery

    def reserve(prefix, required, label):
        required_reserves.append(required)
        original_battery(value, prefix, required, label)

    def public_call(label, tool, arguments, **kwargs):
        method = tool.rsplit("__", 1)[-1]
        events.append(method)
        if method == "check_status":
            return {"battery_pct": battery["percent"], "charging": battery["charging"]}
        if method == "charge":
            battery["charging"] = True
            return {"status": "charging"}
        assert method == "inspect_crop_health"
        # The public robot may return partial coverage to retain10% for return.
        requested = list(range(arguments["start_ridge"], arguments["end_ridge"] + 1))
        covered = requested[:max(0, int((battery["percent"] - 10) // 5))]
        battery["percent"] -= 5 * len(covered)
        value.engine.time_manager.value += 600 * len(covered)
        return {"status": "ok" if covered == requested else "partial", "covered_ridges": covered,
                "observations": {rid: {"ridge_id": rid, "pest_present": False} for rid in covered}}

    def charge_wait(label, seconds=86400):
        events.append("charge_wait")
        assert seconds == 3600
        value.engine.time_manager.value += seconds
        battery.update(percent=100.0, charging=False)

    water = {"overview": {"sim_date": "2026-07-15", "farm_id": "east", "num_ridges": 4},
             "ridges": {"ridges": [{"ridge_id": rid, "planted": True, "harvested": False,
                 "growth_stage": "R1"} for rid in range(4)]},
             "root_zone": None, "surface": None, "forecast": {"forecast": []}}
    value.battery, value.call, value.wait = reserve, public_call, charge_wait
    value._observe_water = lambda label: water
    value._read = lambda label, method, args=None: {}

    def crop_policy(observation, history, parameters):
        policy_inputs.append(deepcopy(observation))
        return {"proposals": []}

    monkeypatch.setattr(runner, "decide_crop_management", crop_policy)
    before = value.engine.time_manager.time()
    value._review_crop("real_regression", water)
    assert required_reserves == [40]
    assert events == ["check_status", "charge", "charge_wait", "inspect_crop_health"]
    assert set(policy_inputs[0]["ground_observations"]) == {0, 1, 2, 3}
    assert value.engine.time_manager.time() == before + 3600 + 4 * 600
    assert battery["percent"] == 80
    assert value._last_scout_timestamp == value.engine.time_manager.time()


def test_source_robot_charge_across_new_day_cannot_be_consumed_by_adaptive_scout(monkeypatch):
    """Regression for the real HN60 source48–51 partial-coverage failure.

    The charge wait previously ran a whole adaptive scout before returning to
    the original inspection. That scout left20%, so only2 requested ridges
    could be inspected while retaining the robot's10% return reserve.
    """
    value = compiler(stamp("2026-07-01T23:30:00"))
    battery = {"percent": 20., "complete_at": None}
    events, reviews = [], []

    def competing_review(label):
        reviews.append(value.engine.time_manager.time())
        battery["percent"] = 20.  # A full adaptive patrol would use the ready device.

    value.review_management = competing_review

    def registered_device(self, label, tool, args, **kwargs):
        method = tool.rsplit("__", 1)[-1]
        now = self.engine.time_manager.time()
        if battery["complete_at"] is not None and now >= battery["complete_at"]:
            battery.update(percent=100., complete_at=None)
        events.append((method, now, battery["percent"]))
        if method == "check_status":
            return {"battery_pct": battery["percent"],
                    "charging": battery["complete_at"] is not None}
        if method == "charge":
            battery["complete_at"] = now + 3600
            return {"status": "charging_started"}
        assert method == "inspect_crop_health"
        requested = list(range(args["start_ridge"], args["end_ridge"] + 1))
        covered = requested[:max(0, int((battery["percent"] - 10) // 5))]
        battery["percent"] -= len(covered) * 5
        self.engine.time_manager.value += len(covered) * 700
        return {"status": "ok" if covered == requested else "partial",
                "covered_ridges": covered, "battery_remaining_pct": battery["percent"]}

    monkeypatch.setattr(runner.FrozenWeatherCompiler, "call", registered_device)
    waits = fake_waits(monkeypatch, value)
    before = value.engine.time_manager.time()
    value.battery("Robot0", 40, "o_r1_ground_nutrient_check_48_51")
    assert value.engine.time_manager.time() == before + 3600
    assert datetime.fromtimestamp(value.engine.time_manager.time(), TZ).day == 2
    assert reviews == []
    assert [method for method, _, _ in events] == ["check_status", "charge", "check_status"]
    assert events[-1][2] == 100.  # The reserve is re-read, not inferred from elapsed time.
    receipt = value.call("o_r1_ground_nutrient_check_48_51", "Robot0__inspect_crop_health",
                         {"start_ridge": 48, "end_ridge": 51})
    assert receipt == {"status": "ok", "covered_ridges": [48, 49, 50, 51],
                       "battery_remaining_pct": 80.}
    assert reviews == []
    assert sum(row["args"]["seconds"] for row in waits) == 3600
    assert value.engine.time_manager.time() == before + 3600 + 4*700
    # Management can run after the reserved operation, without stealing its charge.
    value.review_management("after_reserved_inspection")
    assert len(reviews) == 1


def test_charge_wait_rechecks_public_reserve_until_device_is_actually_ready(monkeypatch):
    value = compiler()
    events = []
    readings = iter([{"battery_pct": 20., "charging": False},
                     {"battery_pct": 30., "charging": True},
                     {"battery_pct": 100., "charging": False}])

    def registered_device(self, label, tool, args, **kwargs):
        method = tool.rsplit("__", 1)[-1]
        events.append(method)
        return next(readings) if method == "check_status" else {"status": "charging"}

    monkeypatch.setattr(runner.FrozenWeatherCompiler, "call", registered_device)
    waits = fake_waits(monkeypatch, value)
    value.review_management = lambda label: pytest.fail("Charging cannot dispatch another patrol")
    value.battery("Robot0", 40, "source_inspection")
    assert events == ["check_status", "charge", "check_status", "charge", "check_status"]
    assert sum(row["args"]["seconds"] for row in waits) == 7200


@pytest.mark.parametrize("rows, expected", [
    ([{"ridge_id": rid, "planted": rid not in {0, 4, 11}, "harvested": rid == 7,
       "growth_stage": {1: "VE", 2: "V4", 3: "R6", 5: "R7", 6: "R8",
                        8: "R5", 9: "R4", 10: "R6"}.get(rid, "V4")}
      for rid in range(12)], [(1, 3), (8, 10)]),
    ([{"ridge_id": rid, "planted": rid != 6, "harvested": False,
       "growth_stage": "V3"} for rid in range(8)], [(0, 3), (4, 5), (7, 7)]),
])
def test_adaptive_scout_only_covers_public_active_crop_segments_and_keeps_battery_recheck(
        monkeypatch, rows, expected):
    value = compiler(stamp("2026-05-16T07:00:00"))
    value.farm = SimpleNamespace(num_ridges=12)
    value.crop_parameters, value.crop_history, value.decisions = {}, [], []
    value._previous_crop_observation = None
    value._tool = lambda method: "Robot0__inspect_crop_health" if method == "inspect_crop_health" else None
    battery = {"percent": 20., "charging": False}
    calls, checks, reserves, waits, policy_inputs = [], [], [], [], []
    value.review_management = lambda label: pytest.fail("Patrol charge cannot dispatch another review")

    def registered(label, tool, arguments, **kwargs):
        method = tool.rsplit("__", 1)[-1]
        if method == "check_status":
            checks.append(battery["percent"])
            return {"battery_pct": battery["percent"], "charging": battery["charging"]}
        if method == "charge":
            battery["charging"] = True
            return {"status": "charging_started"}
        assert method == "inspect_crop_health"
        first, last = arguments["start_ridge"], arguments["end_ridge"]
        calls.append((first, last))
        covered = list(range(first, last+1))
        assert battery["percent"] >= len(covered)*5+10
        battery["percent"] -= len(covered)*5
        value.engine.time_manager.value += len(covered)*700
        return {"status": "ok", "covered_ridges": covered,
                "observations": {rid: {"ridge_id": rid} for rid in covered}}

    def advance(self, label, tool, arguments, **kwargs):
        assert tool == "SystemApp__advance_time"
        waits.append(arguments["seconds"])
        self.engine.time_manager.value += arguments["seconds"]
        battery.update(percent=100., charging=False)
        return {"status": "ok"}

    def reserve(prefix, required, label):
        reserves.append(required)
        runner.AdaptiveManagementCompiler.battery(value, prefix, required, label)

    water = {"overview": {"sim_date": "2026-05-16", "farm_id": "a", "num_ridges": 12},
             "ridges": {"ridges": rows}, "root_zone": None,
             "surface": None, "forecast": {"forecast": []}}
    value.call, value.battery = registered, reserve
    value._observe_water = lambda label: water
    value._read = lambda label, method, args=None: {}
    monkeypatch.setattr(ObservedCompiler, "call", advance)
    monkeypatch.setattr(runner, "decide_crop_management",
        lambda observation, *args: policy_inputs.append(deepcopy(observation)) or {"proposals": []})
    started = value.engine.time_manager.time()
    value._review_crop("active_targets_only", water)
    expected_ids = {rid for first, last in expected for rid in range(first, last+1)}
    assert calls == expected
    assert all(last-first+1 <= 4 for first, last in calls)
    assert set(policy_inputs[0]["ground_observations"]) == expected_ids
    assert reserves == [40]*len(expected)
    assert checks[:2] == [20., 100.]
    assert sum(waits) == 3600
    assert value.engine.time_manager.time() == started+3600+len(expected_ids)*700


def test_adaptive_scout_skips_unplanted_harvested_and_mature_field_without_work():
    value = compiler()
    value.farm = SimpleNamespace(num_ridges=5)
    value.decisions, value.crop_history = [], []
    value._last_scout_timestamp = None
    value._tool = lambda method: "Robot0__inspect_crop_health"
    value.call = lambda *args, **kwargs: pytest.fail("No eligible crop may dispatch robot work")
    value._observe_water = lambda label: pytest.fail("No eligible patrol must consume extra observations")
    rows = [
        {"ridge_id": 0, "planted": False, "harvested": False, "growth_stage": "V4"},
        {"ridge_id": 1, "planted": True, "harvested": True, "growth_stage": "R6"},
        {"ridge_id": 2, "planted": True, "harvested": False, "growth_stage": "R7"},
        {"ridge_id": 3, "planted": True, "harvested": False, "growth_stage": "R8"},
        {"ridge_id": 4, "planted": True, "harvested": False, "growth_stage": "unknown"},
    ]
    before = value.engine.time_manager.time()
    value._review_crop("empty_eligible_set", {"ridges": {"ridges": rows}})
    assert value.engine.time_manager.time() == before
    assert value.decisions[-1]["kind"] == "crop_scout_skipped"
    assert value.crop_history == []
    assert value._last_scout_timestamp is None
