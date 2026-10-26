from copy import deepcopy

import pytest

from scripts.adaptive_crop_management_policy import decide_crop_management


def snapshot(count=4):
    return {
        "now_day": 40, "date": "2026-06-14", "farm_id": "a", "num_ridges": count,
        "ridges": [{"ridge_id": rid, "planted": True, "harvested": False,
                    "growth_stage": "R1", "nutrient_index": 0.83,
                    "pesticide_applied_days_ago": -1} for rid in range(count)],
        "ground_observed_day": 40,
        "ground_observations": {rid: {
            "disease_present": False, "disease_confidence": 0.9,
            "pest_present": False, "pest_confidence": 0.9,
            "weed_present": False, "weed_confidence": 0.9,
            "leaf_nutrition_band": "adequate",
        } for rid in range(count)},
        "weather": {"rainfall_mm": 0, "wind_speed_ms": 2},
        "inventory": {"pesticide_liters": 1000, "fertilizer_kg": 1000},
        "equipment_status": {"fungicide_tank_l": 0, "pesticide_tank_l": 0},
        "management_regime": {"regime": "conventional", "fungicide_applications_used": 0,
                              "insecticide_applications_used": 0, "active_ingredient_used_kg": 0,
                              "fertilizer_used_kg": 0, "irrigation_used_mm_total": 0,
                              "machine_passes_used": 0, "mechanical_weed_ridges_treated": 0},
        "water_status": {"adequate": True, "ridge_ids": list(range(count)), "observed_day": 40},
    }


def symptoms(obs, signal, ids=None, confidence=0.9):
    for rid in ids if ids is not None else obs["ground_observations"]:
        obs["ground_observations"][rid][signal + "_present"] = True
        obs["ground_observations"][rid][signal + "_confidence"] = confidence


def nutrition(obs):
    previous = deepcopy(obs)
    previous["now_day"] = 37
    for row in obs["ridges"]:
        row["nutrient_index"] = 0.65
        obs["ground_observations"][row["ridge_id"]]["leaf_nutrition_band"] = "deficient"
    previous["ridges"] = deepcopy(obs["ridges"])
    obs["previous_observations"] = [previous]


def test_no_management_inferred_from_hidden_pressure_or_aerial_anomaly_alone():
    obs = snapshot()
    obs["ground_observations"] = {}
    for row in obs["ridges"]:
        row.update(disease_pressure=1.0, pest_pressure=1.0, ndvi_proxy=0.1)
    result = decide_crop_management(obs)
    assert result["proposals"] == []
    assert result["skipped"]
    assert any("SPAD" in reason for reason in result["unsupported"])


def test_only_fresh_confident_covered_symptomatic_ridges_are_targeted():
    obs = snapshot()
    symptoms(obs, "disease", [0, 1, 2])
    obs["ground_observations"] = {"data": {"covered_ridges": [0, 1],
        "observations": {str(k): v for k, v in obs["ground_observations"].items()}}}
    result = decide_crop_management(obs)
    assert [(p["operation"], p["start"], p["end"], p["dose"]) for p in result["proposals"]] == [
        ("apply_fungicide", 0, 1, {"liters_per_ridge": 3.8})]


@pytest.mark.parametrize("change", ["low_confidence", "stale", "future", "already_harvested", "R7"])
def test_no_stale_low_confidence_or_mature_crop_chemical_proposals(change):
    obs = snapshot(1)
    symptoms(obs, "pest")
    if change == "low_confidence": obs["ground_observations"][0]["pest_confidence"] = 0.59
    if change == "stale": obs["ground_observed_day"] = 36
    if change == "future": obs["ground_observed_day"] = 41
    if change == "already_harvested": obs["ridges"][0]["harvested"] = True
    if change == "R7": obs["ridges"][0]["growth_stage"] = "R7"
    assert decide_crop_management(obs)["proposals"] == []


def test_ranges_do_not_treat_unobserved_gaps_or_exceed_ten_ridges():
    obs = snapshot(25)
    symptoms(obs, "disease", [*range(12), *range(20, 25)])
    proposals = decide_crop_management(obs)["proposals"]
    assert [(p["start"], p["end"]) for p in proposals] == [(0, 9), (10, 11), (20, 24)]


def test_policy_interval_is_per_ridge_and_failed_receipt_is_not_completed_management():
    obs = snapshot(2)
    symptoms(obs, "disease")
    history = [{"day": 35, "operation": "apply_fungicide", "start": 0, "end": 0}]
    assert [(p["start"], p["end"]) for p in decide_crop_management(obs, history)["proposals"]] == [(1, 1)]
    history[0]["receipt"] = {"error": "Weather refused", "status": "error"}
    assert [(p["start"], p["end"]) for p in decide_crop_management(obs, history)["proposals"]] == [(0, 1)]


def test_public_pesticide_age_also_prevents_an_unrecorded_repeat():
    obs = snapshot(1)
    symptoms(obs, "pest")
    obs["ridges"][0]["pesticide_applied_days_ago"] = 3
    assert decide_crop_management(obs)["proposals"] == []


def test_runner_response_receipt_does_not_count_a_failed_treatment():
    obs = snapshot(1);symptoms(obs, "disease")
    history = [{"day": 39, "operation": "apply_fungicide", "start": 0, "end": 0,
                "response": {"error": "Weather refused", "status": "error"}}]
    assert len(decide_crop_management(obs, history)["proposals"]) == 1
    history[0]["response"] = {"status": "ok"}
    assert decide_crop_management(obs, history)["proposals"] == []


def test_shared_stock_is_reserved_across_chemical_classes():
    obs = snapshot(10)
    symptoms(obs, "disease");symptoms(obs, "pest")
    obs["inventory"]["pesticide_liters"] = 100
    proposals = decide_crop_management(obs)["proposals"]
    assert [p["operation"] for p in proposals] == ["apply_fungicide"]
    assert sum(p["resource_requirements"]["chemical_liters"] for p in proposals) == 38


@pytest.mark.parametrize("constraint", ["stock", "ingredient", "application_cap", "rain", "wind"])
def test_chemical_stock_weather_and_local_caps_are_checked(constraint):
    obs = snapshot(1);symptoms(obs, "disease")
    if constraint == "stock": obs["inventory"]["pesticide_liters"] = 0
    if constraint == "ingredient": obs["management_regime"]["active_ingredient_cap_kg"] = 0.003
    if constraint == "application_cap": obs["management_regime"]["max_fungicide_applications"] = 0
    if constraint == "rain": obs["weather"]["rainfall_mm"] = 1
    if constraint == "wind": obs["weather"]["wind_speed_ms"] = 6.5
    assert decide_crop_management(obs)["proposals"] == []


def test_same_day_disjoint_passes_share_one_application_day_but_not_chemical_dose():
    obs = snapshot(12);symptoms(obs, "disease")
    obs["management_regime"].update(max_fungicide_applications=1, fungicide_applications_used=1,
                                    last_fungicide_application_day=obs["date"])
    proposals = decide_crop_management(obs)["proposals"]
    assert len(proposals) == 2
    assert sum(p["resource_requirements"]["chemical_liters"] for p in proposals) == pytest.approx(45.6)
    obs["management_regime"]["last_fungicide_application_day"] = "2026-06-13"
    assert decide_crop_management(obs)["proposals"] == []


def test_organic_weed_path_reserves_only_implemented_mechanical_budgets():
    obs = snapshot(12);symptoms(obs, "weed")
    obs["management_regime"].update(regime="organic", max_machine_passes=1,
                                    max_mechanical_weed_ridges=10)
    proposals = decide_crop_management(obs)["proposals"]
    assert [(p["operation"], p["start"], p["end"]) for p in proposals] == [("mechanical_weed_control", 0, 9)]
    assert proposals[0]["resource_requirements"]["machine_passes"] == 1
    symptoms(obs, "disease")
    assert all(p["operation"] == "mechanical_weed_control" for p in decide_crop_management(obs)["proposals"])


@pytest.mark.parametrize("cap,used", [(0, 0), (.25, .25), (.2, .3)])
def test_exhausted_public_chemical_allowance_selects_permitted_mechanical_weed_control(cap, used):
    obs = snapshot(12);symptoms(obs, "weed")
    obs["management_regime"].update(regime="low_chemical", active_ingredient_cap_kg=cap,
                                    active_ingredient_used_kg=used,
                                    max_machine_passes=7, max_mechanical_weed_ridges=64)
    obs["soil_sensors"] = {"soil_sensors": [{"vwc": .3}]}
    proposals = decide_crop_management(obs)["proposals"]
    assert [(p["operation"], p["start"], p["end"]) for p in proposals] == [
        ("mechanical_weed_control", 0, 9), ("mechanical_weed_control", 10, 11)]
    assert all(any("allowance is zero" in r for r in p["reasons"]) for p in proposals)


@pytest.mark.parametrize("block", ["stage", "passes", "ridges", "wet_surface", "rain", "interval"])
def test_zero_chemical_allowance_does_not_override_mechanical_safety_or_budget(block):
    obs = snapshot(2);symptoms(obs, "weed")
    obs["management_regime"]["active_ingredient_cap_kg"] = 0
    history = []
    if block == "stage":
        for row in obs["ridges"]: row["growth_stage"] = "R5"
    if block == "passes": obs["management_regime"]["max_machine_passes"] = 0
    if block == "ridges": obs["management_regime"]["max_mechanical_weed_ridges"] = 1
    if block == "wet_surface": obs["soil_sensors"] = {"data": {"soil_sensors": [{"vwc": .36}]}}
    if block == "rain": obs["weather"]["rainfall_mm"] = 1
    if block == "interval": history = [{"operation": "mechanical_weed_control", "start": 0, "end": 1, "day": 39}]
    assert decide_crop_management(obs, history)["proposals"] == []


@pytest.mark.parametrize("trigger", ["wet_surface", "explicit_preference"])
def test_registered_manual_path_uses_two_ridge_passes_and_backpack_reference(trigger):
    obs = snapshot(5);symptoms(obs, "pest")
    obs["capabilities"] = {"manual_pesticide_registered": True}
    if trigger == "wet_surface":
        obs["soil_sensors"] = {"data": {"soil_sensors": [{"vwc": .2}, {"vwc": .36}]}}
    else:
        obs["capabilities"]["prefer_manual_pesticide"] = True
    proposals = decide_crop_management(obs)["proposals"]
    assert [(p["operation"], p["start"], p["end"], p["dose"]) for p in proposals] == [
        ("apply_pesticide_manual", 0, 1, {"liters_per_ridge": 3.0}),
        ("apply_pesticide_manual", 2, 3, {"liters_per_ridge": 3.0}),
        ("apply_pesticide_manual", 4, 4, {"liters_per_ridge": 3.0})]
    assert sum(p["resource_requirements"]["chemical_liters"] for p in proposals) == 15
    assert all(p["resource_requirements"]["chemical_source"] == "common_warehouse_only" for p in proposals)


def test_manual_spray_cannot_borrow_chemical_from_tractor_tanks():
    obs = snapshot(4);symptoms(obs, "pest")
    obs["capabilities"] = {"manual_pesticide_registered": True, "prefer_manual_pesticide": True}
    obs["inventory"]["pesticide_liters"] = 6
    obs["equipment_status"]["pesticide_tank_l"] = 100
    proposals = decide_crop_management(obs)["proposals"]
    assert [(p["start"], p["end"]) for p in proposals] == [(0, 1)]
    obs["inventory"]["pesticide_liters"] = 0
    assert decide_crop_management(obs)["proposals"] == []


@pytest.mark.parametrize("block", ["quota", "ingredient", "weather", "organic", "boom_history", "manual_history"])
def test_manual_path_obeys_same_insecticide_rules_and_shared_interval(block):
    obs = snapshot(2);symptoms(obs, "pest")
    obs["capabilities"] = {"manual_pesticide_registered": True, "prefer_manual_pesticide": True}
    history = []
    if block == "quota": obs["management_regime"]["max_insecticide_applications"] = 0
    if block == "ingredient": obs["management_regime"]["active_ingredient_cap_kg"] = .005
    if block == "weather": obs["weather"]["rainfall_mm"] = 1
    if block == "organic": obs["management_regime"]["regime"] = "organic"
    if block in {"boom_history", "manual_history"}:
        history = [{"operation": "spray_pesticide" if block == "boom_history" else "apply_pesticide_manual",
                    "day": 39, "start": 0, "end": 1}]
    assert decide_crop_management(obs, history)["proposals"] == []


def test_manual_preference_never_invents_an_unregistered_capability():
    obs = snapshot(2);symptoms(obs, "pest")
    obs["capabilities"] = {"manual_pesticide_registered": False, "prefer_manual_pesticide": True}
    assert [p["operation"] for p in decide_crop_management(obs)["proposals"]] == ["spray_pesticide"]


def test_fertilizer_requires_visible_persistent_nutrition_water_and_biotic_exclusion():
    obs = snapshot(2);nutrition(obs)
    before = deepcopy(obs)
    proposals = decide_crop_management(obs)["proposals"]
    assert obs == before
    assert [(p["operation"], p["start"], p["end"]) for p in proposals] == [("apply_fertigation", 0, 1)]
    assert proposals[0]["dose"] == {"nutrient_amount": 0.12, "water_mm": 0.0}
    assert proposals[0]["resource_requirements"]["fertilizer_product_kg"] == pytest.approx(7.2)
    assert any("fixation" in risk for risk in proposals[0]["risks"])


def test_raw_registered_root_zone_response_needs_an_explicit_policy_threshold():
    obs = snapshot(2);nutrition(obs)
    obs.pop("water_status")
    obs["root_zone"] = {"data": {"root_zone_sensors": [
        {"ridge_start": 0, "ridge_end": 0, "root_vwc": 0.3},
        {"ridge_start": 1, "ridge_end": 1, "root_vwc": 0.2}]}}
    assert decide_crop_management(obs)["proposals"] == []
    proposals = decide_crop_management(obs, config={"root_zone_adequate_vwc": 0.25})["proposals"]
    assert [(p["operation"], p["start"], p["end"]) for p in proposals] == [("apply_fertigation", 0, 0)]


@pytest.mark.parametrize("missing", ["visible", "persistent", "water", "negative_biotic", "stage", "stock", "quota"])
def test_no_fertilizer_from_ambiguous_or_unfunded_proxy(missing):
    obs = snapshot(1);nutrition(obs)
    if missing == "visible": obs["ground_observations"][0]["leaf_nutrition_band"] = "adequate"
    if missing == "persistent": obs["previous_observations"] = []
    if missing == "water": obs["water_status"] = {}
    if missing == "negative_biotic": obs["ground_observations"][0]["disease_confidence"] = 0.1
    if missing == "stage": obs["ridges"][0]["growth_stage"] = "R5"
    if missing == "stock": obs["inventory"]["fertilizer_kg"] = 0
    if missing == "quota": obs["management_regime"]["fertilizer_quota_kg"] = 1
    assert not any(p["operation"] == "apply_fertigation" for p in decide_crop_management(obs)["proposals"])


def test_fertilizer_carrier_consumes_shared_water_quota_and_repeats_are_bounded():
    obs = snapshot(2);nutrition(obs)
    obs["management_regime"]["irrigation_quota_mm_total"] = 0.5
    assert decide_crop_management(obs, config={"fertilizer_water_mm": 1})["proposals"] == []
    history = [{"day": 30, "operation": "apply_fertigation", "start": 0, "end": 1}]
    assert decide_crop_management(obs, history)["proposals"] == []
    history = [{"day": 1, "operation": "apply_fertigation", "start": 0, "end": 1},
               {"day": 20, "operation": "apply_fertigation", "start": 0, "end": 1}]
    assert decide_crop_management(obs, history)["proposals"] == []


def test_invalid_success_history_and_nonfinite_clock_fail_explicitly():
    with pytest.raises(ValueError, match="history"):
        decide_crop_management(snapshot(), [{"operation": "apply_fungicide", "start": 0, "end": 1}])
    obs = snapshot();obs["now_day"] = float("nan")
    with pytest.raises(ValueError, match="now_day"):
        decide_crop_management(obs)


@pytest.mark.parametrize("finite", [True, False])
def test_low_band_herbicide_is_rechecked_only_when_shared_chemical_allowance_is_finite(finite):
    obs = snapshot(4);symptoms(obs, "weed")
    for diagnosis in obs["ground_observations"].values():
        diagnosis["weed_pressure_band"] = "low"
    if finite:
        obs["management_regime"]["active_ingredient_cap_kg"] = .35
    result = decide_crop_management(obs)
    if finite:
        assert result["proposals"] == []
        assert all("reinspection" in reason["reason"] for reason in result["skipped"])
    else:
        assert [p["operation"] for p in result["proposals"]] == ["apply_herbicide"]


def mechanical_field(count=64, *, passes=7):
    obs = snapshot(count)
    obs["management_regime"].update(regime="low_chemical", active_ingredient_cap_kg=0,
        max_machine_passes=passes, max_mechanical_weed_ridges=count)
    obs["soil_sensors"] = {"soil_sensors": [{"vwc": .28}]}
    return obs


def set_weed_band(obs, ids, band="high"):
    symptoms(obs, "weed", ids)
    for rid in ids:
        obs["ground_observations"][rid]["weed_pressure_band"] = band


def test_fully_observed_widespread_high_weeds_use_seven_continuous_passes_for64_ridges():
    obs = mechanical_field()
    negative = {1, 7, 10, 15, 29, 39, 49, 50, 59, 63}
    set_weed_band(obs, sorted(set(range(64)) - negative))
    result = decide_crop_management(obs)
    proposals = result["proposals"]
    assert len(proposals) == 7
    assert sorted((p["start"], p["end"]) for p in proposals) == [
        (0, 9), (10, 19), (20, 29), (30, 39), (40, 49), (50, 59), (60, 63)]
    assert sum(p["resource_requirements"]["mechanically_treated_ridges"] for p in proposals) == 64
    assert {rid for p in proposals for rid in p["audit"]["observed_single_inspection_negative_ridges"]} == negative
    assert all(p["audit"]["eligible"] and all(p["audit"]["checks"].values()) for p in proposals)
    assert all(any("no unobserved ridges" in reason for reason in p["reasons"]) for p in proposals)


def test_scarce_passes_prioritize_positive_fraction_then_high_count_then_ridge_id():
    obs = mechanical_field(30, passes=2)
    set_weed_band(obs, range(0, 6), "medium")
    set_weed_band(obs, range(10, 16), "high")
    set_weed_band(obs, range(20, 26), "high")
    proposals = decide_crop_management(obs)["proposals"]
    assert [(p["start"], p["end"]) for p in proposals] == [(10, 19), (20, 29)]
    set_weed_band(obs, range(6, 8), "medium")
    proposals = decide_crop_management(obs)["proposals"]
    assert [(p["start"], p["end"]) for p in proposals] == [(0, 9), (10, 19)]


def test_local_confirmed_spots_remain_after_higher_prevalence_complete_windows():
    obs = mechanical_field(20, passes=2)
    set_weed_band(obs, [1])
    set_weed_band(obs, range(10, 18), "medium")
    proposals = decide_crop_management(obs)["proposals"]
    assert [(p["start"], p["end"]) for p in proposals] == [(10, 19), (1, 1)]
    assert proposals[0]["audit"]["kind"] == "continuous_observed_machine_window"
    assert proposals[1]["audit"]["kind"] == "exact_confirmed_fragment"
    assert proposals[1]["audit"]["includes_observed_negative_ridges"] is False


@pytest.mark.parametrize("bad", ["unobserved", "stale", "late_stage", "harvested", "unplanted", "recent_treatment"])
def test_full_machine_window_requires_every_ridge_observed_fresh_early_and_not_recently_treated(bad):
    obs = mechanical_field(10)
    set_weed_band(obs, range(10))
    history = []
    if bad == "unobserved": obs["ground_observations"].pop(3)
    if bad == "stale": obs["ground_observations"][3]["observed_day"] = 36
    if bad == "late_stage": obs["ridges"][3]["growth_stage"] = "R5"
    if bad == "harvested": obs["ridges"][3]["harvested"] = True
    if bad == "unplanted": obs["ridges"][3]["planted"] = False
    if bad == "recent_treatment":
        history = [{"operation": "mechanical_weed_control", "day": 39, "start": 3, "end": 3}]
    result = decide_crop_management(obs, history)
    assert result["mechanical_planning_audit"][0]["eligible"] is False
    assert not any(p["audit"]["kind"] == "continuous_observed_machine_window" for p in result["proposals"])
    assert all(not p["start"] <= 3 <= p["end"] for p in result["proposals"])


def test_tail_window_uses_actual_geometry_and_does_not_loosen_the_V1_start():
    obs = mechanical_field(14, passes=2)
    set_weed_band(obs, range(14), "medium")
    result = decide_crop_management(obs)
    assert [(p["start"], p["end"]) for p in result["proposals"]] == [(0, 9), (10, 13)]
    for row in obs["ridges"]: row["growth_stage"] = "VE"
    assert decide_crop_management(obs)["proposals"] == []


def reserve_observation(count=4):
    obs = snapshot(count);symptoms(obs, "disease")
    obs["capabilities"] = {"manual_pesticide_registered": True, "prefer_manual_pesticide": True}
    obs["management_regime"].update(active_ingredient_cap_kg=.1, active_ingredient_used_kg=.06)
    return obs


def test_explicit_manual_objective_reserves_a_searchable_fraction_without_charging_quota():
    obs = reserve_observation()
    result = decide_crop_management(obs)
    assert result["proposals"] == []
    audit = result["chemical_budget_audit"]
    assert audit["planned_reserve_kg"] == pytest.approx(.025)
    assert audit["projected_active_ingredient_used_kg"] == .06
    assert audit["planning_only_not_physical_quota_deduction"] is True
    assert any("planning reserve" in s["reason"] for s in result["skipped"])
    assert len(decide_crop_management(obs, config={"planned_insecticide_reserve_fraction": 0})["proposals"]) == 1


@pytest.mark.parametrize("disabled", ["unlimited", "no_manual_objective"])
def test_reserve_does_not_change_unlimited_or_non_manual_task_candidates(disabled):
    obs = reserve_observation()
    if disabled == "unlimited": obs["management_regime"]["active_ingredient_cap_kg"] = None
    if disabled == "no_manual_objective": obs["capabilities"]["prefer_manual_pesticide"] = False
    result = decide_crop_management(obs)
    assert [p["operation"] for p in result["proposals"]] == ["apply_fungicide"]
    assert result["chemical_budget_audit"]["reserve_enabled"] is False
    assert result["chemical_budget_audit"]["planned_reserve_kg"] == 0


def test_failed_insecticide_receipt_does_not_release_reserve():
    obs = reserve_observation()
    history = [{"day": 20, "operation": "apply_pesticide_manual", "start": 0, "end": 1,
                "dose": {"liters_per_ridge": 3}, "response": {"error": "Rain refused"}}]
    result = decide_crop_management(obs, history)
    assert result["proposals"] == []
    assert result["chemical_budget_audit"]["credited_insecticide_used_kg"] == 0
    assert result["chemical_budget_audit"]["remaining_reserve_before_proposals_kg"] == pytest.approx(.025)


def test_real_successful_insecticide_receipt_releases_only_its_actual_dose():
    obs = reserve_observation()
    history = [{"day": 20, "operation": "apply_pesticide_manual", "start": 0, "end": 1,
                "dose": {"liters_per_ridge": 8}, "response": {"status": "ok", "pesticide_used_liters": 6}}]
    result = decide_crop_management(obs, history)
    assert [p["operation"] for p in result["proposals"]] == ["apply_fungicide"]
    audit = result["chemical_budget_audit"]
    assert audit["known_successful_insecticide_used_kg"] == pytest.approx(.006)
    assert audit["remaining_reserve_before_proposals_kg"] == pytest.approx(.019)
    assert audit["projected_active_ingredient_used_kg"] == pytest.approx(.0752)


def test_unknown_legacy_insecticide_dose_does_not_silently_unlock_reserve():
    obs = reserve_observation()
    history = [{"day": 20, "operation": "spray_pesticide", "start": 0, "end": 1,
                "response": {"status": "ok"}}]
    result = decide_crop_management(obs, history)
    assert result["proposals"] == []
    audit = result["chemical_budget_audit"]
    assert audit["insecticide_history_entries_without_known_dose"] == 1
    assert audit["credited_insecticide_used_kg"] == 0


def test_old_requested_dose_without_success_confirmation_does_not_unlock_reserve():
    obs = reserve_observation()
    history = [{"day": 20, "operation": "spray_pesticide", "start": 0, "end": 1,
                "dose": {"liters_per_ridge": 8}}]
    result = decide_crop_management(obs, history)
    assert result["proposals"] == []
    assert result["chemical_budget_audit"]["credited_insecticide_used_kg"] == 0


def test_legacy_registered_manual_args_and_success_receipt_are_normalized():
    obs = reserve_observation()
    history = [{"day": 20, "tool_name": "FieldOpsApp__apply_pesticide_manual",
                "tool_args": {"ridge_id": 0, "ridge_count": 2, "liters_per_ridge": 3, "advance_time": True},
                "response": {"status": "ok", "pesticide_used_liters": 6}}]
    result = decide_crop_management(obs, history)
    assert result["chemical_budget_audit"]["credited_insecticide_used_kg"] == pytest.approx(.006)
    assert [p["operation"] for p in result["proposals"]] == ["apply_fungicide"]


def test_explicit_success_dose_without_receipt_quantity_can_release_reserve_but_not_beyond_public_use():
    obs = reserve_observation()
    obs["management_regime"]["active_ingredient_used_kg"] = .006
    history = [{"day": 20, "operation": "spray_pesticide", "start": 0, "end": 1,
                "dose": {"liters_per_ridge": 8}, "response": {"status": "ok"}}]
    audit = decide_crop_management(obs, history)["chemical_budget_audit"]
    assert audit["known_successful_insecticide_used_kg"] == pytest.approx(.016)
    assert audit["credited_insecticide_used_kg"] == pytest.approx(.006)
    assert audit["remaining_reserve_before_proposals_kg"] == pytest.approx(.019)


def test_insecticide_can_use_reserved_budget_and_all_chemical_proposals_share_the_real_total_cap():
    obs = snapshot(64)
    symptoms(obs, "disease");symptoms(obs, "pest", range(24));symptoms(obs, "weed")
    for row in obs["ground_observations"].values(): row["weed_pressure_band"] = "high"
    obs["capabilities"] = {"manual_pesticide_registered": True, "prefer_manual_pesticide": True}
    obs["management_regime"]["active_ingredient_cap_kg"] = .35
    result = decide_crop_management(obs)
    proposals = result["proposals"]
    manual = [p for p in proposals if p["operation"] == "apply_pesticide_manual"]
    assert sum(p["end"] - p["start"] + 1 for p in manual) == 24
    assert sum(p["resource_requirements"]["modeled_active_ingredient_kg"] for p in proposals) == pytest.approx(.3152)
    audit = result["chemical_budget_audit"]
    assert audit["planned_reserve_kg"] == pytest.approx(.0875)
    assert audit["remaining_reserve_after_proposals_kg"] == pytest.approx(.0155)
    assert audit["projected_active_ingredient_used_kg"] == pytest.approx(.3152)
    assert audit["projected_active_ingredient_used_kg"] <= .35
    assert all(any("planning constraint" in reason for reason in p["reasons"]) for p in proposals)


def test_boom_insecticide_can_use_reserved_budget_when_manual_capability_is_unavailable():
    obs = snapshot(3);symptoms(obs, "disease");symptoms(obs, "pest");symptoms(obs, "weed")
    for row in obs["ground_observations"].values(): row["weed_pressure_band"] = "high"
    obs["capabilities"] = {"manual_pesticide_registered": False, "prefer_manual_pesticide": True}
    obs["management_regime"].update(active_ingredient_cap_kg=.1, active_ingredient_used_kg=.075)
    result = decide_crop_management(obs)
    assert [(p["operation"], p["dose"]) for p in result["proposals"]] == [
        ("spray_pesticide", {"liters_per_ridge": 8.0})]
    assert result["chemical_budget_audit"]["projected_active_ingredient_used_kg"] == pytest.approx(.099)
    assert result["chemical_budget_audit"]["remaining_reserve_after_proposals_kg"] == pytest.approx(.001)


@pytest.mark.parametrize("bad", [-.1, 1.1, None, True])
def test_invalid_reserve_fraction_rejected(bad):
    with pytest.raises(ValueError, match="planned_insecticide_reserve_fraction"):
        decide_crop_management(snapshot(), config={"planned_insecticide_reserve_fraction": bad})


def test_misspelled_crop_policy_parameter_is_rejected_instead_of_ignored():
    with pytest.raises(ValueError, match="Unknown crop policy parameters"):
        decide_crop_management(snapshot(), config={"planned_insecticide_resrve_fraction": .25})
