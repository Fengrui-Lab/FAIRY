"""Decisions must follow public state refreshed after actual treatment time."""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest

from scripts.adaptive_management_runner import AdaptiveManagementCompiler
from scripts.compile_wofost_observed_oracle import TZ


class Clock:
    def __init__(self, now):
        self.now = now

    def time(self):
        return self.now


def crop_runner():
    value = AdaptiveManagementCompiler.__new__(AdaptiveManagementCompiler)
    start = datetime(2026, 6, 1, tzinfo=TZ).timestamp()
    value.engine = SimpleNamespace(start_time=start, time_manager=Clock(start + 40 * 86400 + 86340))
    value.farm = SimpleNamespace(num_ridges=12)
    value.crop_parameters = {"root_zone_adequate_vwc": .25}
    value.crop_history, value.decisions = [], []
    value._previous_crop_observation = None
    value._tool = lambda method: "Robot__" + method
    value.battery = lambda *args: None
    state = {"stage": "R1", "rain": 0, "stock": 1000., "regime": {}, "reads": 0}

    def observe(label):
        state["reads"] += 1
        return {"overview": {"sim_date": datetime.fromtimestamp(value.engine.time_manager.time(), TZ).date().isoformat(),
                             "farm_id": "east", "num_ridges": 12},
                "ridges": {"ridges": [{"ridge_id": rid, "planted": True, "harvested": False,
                    "growth_stage": state["stage"], "nutrient_index": .9,
                    "pesticide_applied_days_ago": -1} for rid in range(12)]},
                "root_zone": {"root_zone_sensors": [{"ridge_start": 0, "ridge_end": 11, "root_vwc": .3}]},
                "surface": {}, "forecast": {"forecast": []}}

    def read(label, method, args=None):
        if method == "get_inventory":
            return {"pesticide_liters": state["stock"], "fertilizer_kg": 1000,
                    "management_regime": deepcopy(state["regime"])}
        if method == "get_current_weather":
            return {"rainfall_mm": state["rain"], "wind_speed_ms": 2}
        if method == "get_status":
            return {"fungicide_tank_l": 0, "pesticide_tank_l": 0, "fuel_tank_l": 100}
        pytest.fail("Unexpected public read: " + method)

    def scout(label, tool, args):
        ids = list(range(args["start_ridge"], args["end_ridge"] + 1))
        return {"status": "ok", "covered_ridges": ids, "observations": {str(rid): {
            "ridge_id": rid, "disease_present": True, "disease_confidence": .9,
            "pest_present": False, "pest_confidence": .9,
            "weed_present": False, "weed_confidence": .9,
            "leaf_nutrition_band": "adequate"} for rid in ids}}

    value._observe_water, value._read, value.call = observe, read, scout
    return value, state


def execute_success(value, proposal):
    value.crop_history.append({"day": (value.engine.time_manager.time() - value.engine.start_time) / 86400,
        "operation": proposal["operation"], "start": proposal["start"], "end": proposal["end"],
        "dose": proposal["dose"], "response": {"status": "ok"}})


@pytest.mark.parametrize("changed", ["stage", "weather", "stock", "diagnosis_age", "application_day_cap"])
def test_next_pass_redecides_from_changed_public_state_and_actual_clock(changed):
    value, state = crop_runner()
    if changed == "application_day_cap":
        state["regime"]["max_fungicide_applications"] = 1
    executed = []

    def execute(label, proposal):
        executed.append(deepcopy(proposal))
        before_day = datetime.fromtimestamp(value.engine.time_manager.time(), TZ).date().isoformat()
        value.engine.time_manager.now += 3600
        execute_success(value, proposal)
        if changed == "stage": state["stage"] = "R7"
        if changed == "weather": state["rain"] = 4
        if changed == "stock": state["stock"] = 0
        if changed == "diagnosis_age": value.engine.time_manager.now += 4 * 86400
        if changed == "application_day_cap":
            state["regime"].update(fungicide_applications_used=1, last_fungicide_application_day=before_day)

    value._execute_crop = execute
    value._review_crop("review", value._observe_water("initial"))
    assert [(p["start"], p["end"]) for p in executed] == [(0, 9)]
    assert state["reads"] == 3
    first, latest = [d["observations"] for d in value.decisions]
    assert latest["now_day"] > first["now_day"]
    assert latest["date"] != first["date"]
    assert latest["ground_observations"] == first["ground_observations"]
    assert value.decisions[-1]["decision"]["proposals"] == []


def test_successful_pass_history_prevents_duplicate_dose_on_next_decision():
    value, state = crop_runner()
    executed = []

    def execute(label, proposal):
        executed.append(deepcopy(proposal))
        value.engine.time_manager.now += 60
        execute_success(value, proposal)

    value._execute_crop = execute
    value._review_crop("review", value._observe_water("initial"))
    assert [(p["start"], p["end"]) for p in executed] == [(0, 9), (10, 11)]
    assert len(value.crop_history) == 2
    assert state["reads"] == 4
    assert value.decisions[-1]["decision"]["proposals"] == []


def test_zero_effect_refusal_is_attempted_once_and_does_not_create_success_history():
    value, state = crop_runner()
    attempts = []
    value._execute_crop = lambda label, proposal: attempts.append((proposal["start"], proposal["end"]))
    value._review_crop("review", value._observe_water("initial"))
    assert attempts == [(0, 9), (10, 11)]
    assert value.crop_history == []
    assert state["reads"] == 4


def test_partial_ground_coverage_aborts_before_treatment():
    value, _ = crop_runner()
    value.call = lambda *args, **kwargs: {"status": "partial", "covered_ridges": [0, 1]}
    value._execute_crop = lambda *args: pytest.fail("Treatment without the requested diagnosis coverage")
    with pytest.raises(RuntimeError, match="did not cover"):
        value._review_crop("review", value._observe_water("initial"))


def test_executor_loads_only_missing_correct_chemical_and_records_actual_time():
    value, _ = crop_runner()
    status = {"fungicide_tank_l": 12., "pesticide_tank_l": 50., "fuel_tank_l": 100.}
    value._read = lambda *args: deepcopy(status)
    calls = []

    def execute(label, tool, args):
        calls.append((tool.rsplit("__", 1)[-1], deepcopy(args)))
        if tool.endswith("__load_fungicide"):
            status["fungicide_tank_l"] += args["liters"]
        else:
            value.engine.time_manager.now += 120
            status["fungicide_tank_l"] -= args["liters_per_ridge"] * 4
        return {"status": "ok"}

    value._execute_guarded = execute
    before = value.engine.time_manager.time()
    proposal = {"operation": "apply_fungicide", "start": 0, "end": 3, "dose": {"liters_per_ridge": 3.8}}
    value._execute_crop("treat", proposal)
    assert calls[0][0] == "load_fungicide"
    assert calls[0][1]["liters"] == pytest.approx(3.2)
    assert calls[1] == ("apply_fungicide", {"start_ridge": 0, "end_ridge": 3, "liters_per_ridge": 3.8})
    assert status["pesticide_tank_l"] == 50.
    assert value.crop_history[0]["day"] == pytest.approx((before + 120 - value.engine.start_time) / 86400)
    assert value.crop_history[0]["response"] == {"status": "ok"}


def test_executor_preserves_fertilizer_and_carrier_dose_without_chemical_loading():
    value, _ = crop_runner()
    calls = []
    value._read = lambda *args: pytest.fail("Fertigation does not use the tractor's chemical or fuel tank")
    value._execute_guarded = lambda label, tool, args: calls.append((tool, deepcopy(args))) or {"status": "ok"}
    value._execute_crop("feed", {"operation": "apply_fertigation", "start": 2, "end": 3,
                                "dose": {"nutrient_amount": .12, "water_mm": 1.5}})
    assert calls == [("Robot__apply_fertigation", {"start_ridge": 2, "end_ridge": 3,
                                                 "nutrient_amount": .12, "water_mm": 1.5})]
    assert len(value.crop_history) == 1
