"""Public-data, budget, timing and observation boundaries of adaptive water use."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math

import pytest

from scripts.adaptive_irrigation_policy import PolicyParameters, decide_irrigation


ZONE = timezone(timedelta(hours=8))


def clock(hour=8, *, days=0):
    local = datetime(2026, 7, 15, hour, tzinfo=ZONE) + timedelta(days=days)
    return {"current_timestamp": local.timestamp(), "current_datetime": local.strftime("%Y-%m-%d %H:%M:%S")}


def observations(vwc=.20, stage="R5_BEGINNING_SEED", *, first=0, last=7, quota=8, used=0):
    return {
        "clock": clock(), "overview": {"farm_id": "east", "num_ridges": 64, "crop_type": "soybean"},
        "ridges": {"ridges": [{"farm_id": "east", "ridge_id": rid, "planted": True,
                                "harvested": False, "growth_stage": stage, "irrigation_pending": False}
                               for rid in range(first, last + 1)]},
        "management": {"management_regime": {"irrigation_quota_mm_total": quota, "irrigation_used_mm_total": used}},
        "forecast": {"forecast": [{"date": "2026-07-16", "rainfall_mm": 0},
                                   {"date": "2026-07-17", "rainfall_mm": 0}]},
        "root_zone": {"root_zone_sensors": [{"sensor_id": "R1", "ridge_start": first, "ridge_end": last, "root_vwc": vwc}],
                      "measurement_noise_vwc": .005},
        "surface": {"farm_id": "east", "soil_sensors": [{"sensor_id": "S1", "ridge_start": first, "ridge_end": last, "vwc": .25}]},
        "capabilities": {"application_mm_per_hour": 5.0, "root_zone_registered": True},
    }


def receipt(finished, *, first=0, last=7, ready=None, status="irrigation_started"):
    return {"started_at": finished - 6060, "finished_at": finished,
            "tool_args": {"start": first, "end": last, "hours": 1.6},
            "response": {"status": status, "farm_id": "east", "irrigated_ridges": list(range(first, last + 1)),
                         "effect_ready_at": finished if ready is None else ready,
                         "field_equivalent_irrigation_mm": 1.0}}


def test_nominal_depth_and_field_equivalent_use_total_farm_geometry():
    result = decide_irrigation(observations())
    assert result["action"] == "irrigate"
    assert result["farm_id"] == "east"
    assert result["target"] == {"start": 0, "end": 7}
    assert result["hours"] == 1.6
    assert result["mm_per_ridge"] == 8
    assert result["field_equivalent_mm"] == 1
    assert "no_inferred_root_deficit" in result["audit"]["water_method"]


def test_no_mutation_and_no_response_to_private_or_scenario_information():
    data = observations()
    original = deepcopy(data)
    baseline = decide_irrigation(data)
    assert data == original
    data.update(native={"SM": .01, "TWSO": 99999}, scenario_id="drought_tomorrow", future_events=["rain"])
    assert decide_irrigation(data) == baseline


def test_wet_observed_root_zone_does_not_spend_unused_quota():
    result = decide_irrigation(observations(.30))
    assert result["action"] == "wait"
    assert result["field_equivalent_mm"] == 0


def test_pod_seed_stage_gets_priority_over_drier_nonemergency_vegetative_zone():
    data = observations(.21, "V4", last=15)
    for row in data["ridges"]["ridges"][8:]:
        row["growth_stage"] = "R3_BEGINNING_POD"
    data["root_zone"]["root_zone_sensors"] = [
        {"ridge_start": 0, "ridge_end": 7, "root_vwc": .19},
        {"ridge_start": 8, "ridge_end": 15, "root_vwc": .23},
    ]
    assert decide_irrigation(data)["target"] == {"start": 8, "end": 15}


def test_severe_early_dryness_can_override_reproductive_priority():
    data = observations(.21, "V4", last=15)
    for row in data["ridges"]["ridges"][8:]:
        row["growth_stage"] = "R5"
    data["root_zone"]["root_zone_sensors"] = [
        {"ridge_start": 0, "ridge_end": 7, "root_vwc": .16},
        {"ridge_start": 8, "ridge_end": 15, "root_vwc": .20},
    ]
    assert decide_irrigation(data)["target"] == {"start": 0, "end": 7}


def test_pre_pod_reserve_is_preserved_but_severe_seedling_dryness_can_use_it():
    data = observations(.20, "VE", used=5)
    assert decide_irrigation(data)["action"] == "wait"
    data["root_zone"]["root_zone_sensors"][0]["root_vwc"] = .16
    result = decide_irrigation(data)
    assert result["action"] == "irrigate"
    assert result["audit"]["ranked_candidates"][0]["held_for_future_pod_seed_field_mm"] == 0


def test_missing_quota_is_observe_and_explicit_unlimited_quota_is_supported():
    data = observations()
    data["management"] = {}
    assert decide_irrigation(data)["action"] == "observe"
    assert decide_irrigation(observations(quota=None))["hours"] == 1.6
    assert decide_irrigation(observations(quota=0))["action"] == "wait"


def test_four_decimal_quota_margin_prevents_tool_rounding_overrun():
    result = decide_irrigation(observations(used=7.7499))
    assert result["action"] == "irrigate"
    assert result["mm_per_ridge"] == pytest.approx(2)
    assert result["field_equivalent_mm"] <= 8 - 7.7499
    assert decide_irrigation(observations(used=7.75))["action"] == "wait"


@pytest.mark.parametrize("count", [1, 3, 8, 11, 32, 64])
def test_real_field_equivalent_never_exceeds_public_remaining_allowance(count):
    data = observations(last=count - 1, quota=.8)
    result = decide_irrigation(data)
    if result["action"] == "irrigate":
        assert result["field_equivalent_mm"] == result["hours"] * 5 * count / 64
        assert result["field_equivalent_mm"] <= .8
        assert result["hours"] * 5 <= 8


def test_near_term_forecast_rain_defers_normal_pulse_but_emergency_is_bounded():
    data = observations()
    data["forecast"]["forecast"][0]["rainfall_mm"] = 8
    assert decide_irrigation(data)["action"] == "wait"
    data["root_zone"]["root_zone_sensors"][0]["root_vwc"] = .16
    result = decide_irrigation(data)
    assert result["action"] == "irrigate"
    assert result["mm_per_ridge"] == 4


def test_forecast_uses_only_returned_next_two_days_and_marks_missing_as_unknown():
    data = observations()
    data["forecast"]["forecast"] = [{"date": "2026-07-15", "rainfall_mm": 30},
                                       {"date": "2026-07-18", "rainfall_mm": 50}]
    result = decide_irrigation(data)
    assert result["action"] == "irrigate"
    assert result["audit"]["forecast"]["valid_entries"] == 0
    assert result["audit"]["forecast"]["missing_forecast_is_not_proof_of_no_rain"]


def test_unregistered_root_response_is_ignored_and_surface_probe_is_small_pulse():
    data = observations(.01)
    data["capabilities"]["root_zone_registered"] = False
    assert decide_irrigation(data)["action"] == "wait"
    data["surface"]["soil_sensors"][0]["vwc"] = .16
    result = decide_irrigation(data)
    assert result["action"] == "irrigate"
    assert result["mm_per_ridge"] == 4
    assert result["audit"]["probe_source"] == "surface"


def test_registered_root_tool_failure_does_not_relabel_surface_as_root_moisture():
    data = observations()
    data["root_zone"] = {"error": "not available"}
    data["surface"]["soil_sensors"][0]["vwc"] = .10
    assert decide_irrigation(data)["action"] == "observe"


def test_target_excludes_mature_unplanted_harvested_and_pending_ridges():
    data = observations()
    rows = data["ridges"]["ridges"]
    rows[0]["growth_stage"] = "R7_BEGINNING_MATURITY"
    rows[1]["planted"] = False
    rows[2]["harvested"] = True
    rows[3]["irrigation_pending"] = True
    # Pending splits the eligible stage segment and cannot block other dry ridges.
    result = decide_irrigation(data)
    assert result["target"] == {"start": 4, "end": 7}


def test_r7_and_unknown_stage_cannot_trigger_irrigation():
    assert decide_irrigation(observations(.10, "R7"))["action"] == "wait"
    assert decide_irrigation(observations(.10, "UNKNOWN"))["action"] == "wait"


def test_actual_receipt_pending_time_is_respected_before_new_observation():
    data = observations()
    now = data["clock"]["current_timestamp"]
    result = decide_irrigation(data, history=[receipt(now - 100, ready=now + 7200)])
    assert result["action"] == "wait"
    assert result["recheck_after_timestamp"] == now + 7200


def test_fresh_post_delivery_probe_is_required_even_after_repeat_interval():
    data = observations()
    now = data["clock"]["current_timestamp"]
    history = [receipt(now - 3 * 86400)]
    assert decide_irrigation(data, history=history)["action"] == "observe"
    data["observed_at"] = {"root_zone": clock(days=-4)}
    assert decide_irrigation(data, history=history)["action"] == "observe"
    data["observed_at"] = {"root_zone": data["clock"]}
    assert decide_irrigation(data, history=history)["action"] == "irrigate"


def test_wet_reading_still_needs_evidence_that_it_was_acquired_after_delivery():
    data = observations(.30)
    now = data["clock"]["current_timestamp"]
    history = [receipt(now - 3 * 86400)]
    assert decide_irrigation(data, history=history)["action"] == "observe"
    data["observed_at"] = {"root_zone": data["clock"]}
    assert decide_irrigation(data, history=history)["action"] == "wait"


def test_fresh_probe_does_not_bypass_repeat_interval_or_double_subtract_quota():
    data = observations(used=1)
    now = data["clock"]["current_timestamp"]
    data["observed_at"] = {"root_zone": data["clock"]}
    result = decide_irrigation(data, history=[receipt(now - 86400)])
    assert result["action"] == "wait"
    result = decide_irrigation(data, history=[receipt(now - 3 * 86400)])
    assert result["audit"]["budget"]["remaining_field_mm"] == 7
    assert result["action"] == "irrigate"


def test_severe_rescue_still_has_at_least24hour_repeat_interval():
    data = observations(.16)
    now = data["clock"]["current_timestamp"]
    data["observed_at"] = {"root_zone": data["clock"]}
    assert decide_irrigation(data, history=[receipt(now - 23 * 3600)])["action"] == "wait"
    assert decide_irrigation(data, history=[receipt(now - 24 * 3600)])["action"] == "irrigate"


def test_daily_bound_uses_public_local_day_not_utc_day_and_ignores_failed_calls():
    data = observations()
    data["clock"] = clock(hour=1)
    now = data["clock"]["current_timestamp"]
    history = [receipt(now - 600, first=20, last=27), receipt(now - 1200, first=30, last=37)]
    assert decide_irrigation(data, history=history)["action"] == "wait"
    history[0]["response"] = {"error": "quota exceeded"}
    assert decide_irrigation(data, history=history)["action"] == "irrigate"
    history = [receipt(now - 7200, first=20, last=27), receipt(now - 10800, first=30, last=37)]
    assert decide_irrigation(data, history=history)["action"] == "irrigate"


def test_service_envelopes_keep_same_result_as_legacy_response_shape():
    data = observations()
    expected = decide_irrigation(data)
    for key in ("clock", "overview", "ridges", "management", "forecast", "root_zone", "surface"):
        data[key] = {"status": "ok", "data": data[key]}
    assert decide_irrigation(data) == expected


@pytest.mark.parametrize("key", ["ridges", "root_zone", "surface", "management", "forecast"])
def test_observations_cannot_be_routed_to_another_farm(key):
    data = observations()
    data[key]["farm_id"] = "west"
    with pytest.raises(ValueError, match="different farm"):
        decide_irrigation(data)


def test_foreign_farm_receipt_and_unclocked_success_are_rejected():
    data = observations()
    operation = receipt(data["clock"]["current_timestamp"] - 3 * 86400)
    operation["response"]["farm_id"] = "west"
    with pytest.raises(ValueError, match="different farm"):
        decide_irrigation(data, history=[operation])
    operation["response"]["farm_id"] = "east"
    operation.pop("finished_at")
    with pytest.raises(ValueError, match="finished_at"):
        decide_irrigation(data, history=[operation])


def test_capabilities_are_explicit_and_unknown_crop_has_no_soybean_inference():
    data = observations()
    data["capabilities"]["application_mm_per_hour"] = 10
    assert decide_irrigation(data)["action"] == "observe"
    data = observations()
    data["overview"]["crop_type"] = "rice"
    assert decide_irrigation(data)["action"] == "observe"


def test_only_declared_explainable_parameter_changes_control_thresholds():
    data = observations(.23)
    assert decide_irrigation(data)["action"] == "irrigate"
    assert decide_irrigation(data, parameters={"root_trigger_vwc": .20})["action"] == "wait"
    with pytest.raises(TypeError):
        decide_irrigation(data, parameters={"native_yield_multiplier": 5})


@pytest.mark.parametrize("values", [
    {"root_trigger_vwc": math.nan}, {"pulse_mm": 1000}, {"pre_pod_reserve_fraction": 1},
    {"emergency_vwc": .30}, {"min_interval_hours": 0}, {"max_daily_operations": 99},
    {"max_daily_operations": 1.5}, {"pulse_mm": True},
])
def test_parameters_cannot_remove_bounded_physical_or_execution_limits(values):
    with pytest.raises(ValueError):
        PolicyParameters(**values)


def test_invalid_or_ambiguous_sensor_data_is_not_silently_used():
    data = observations()
    data["root_zone"]["root_zone_sensors"][0]["root_vwc"] = math.nan
    with pytest.raises(ValueError, match="VWC"):
        decide_irrigation(data)
    data = observations()
    data["root_zone"]["root_zone_sensors"].append({"ridge_start": 7, "ridge_end": 8, "root_vwc": .1})
    with pytest.raises(ValueError, match="Overlapping"):
        decide_irrigation(data)
