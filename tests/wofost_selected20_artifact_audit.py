"""Saved-artifact audit for the selected scenes; never used by production farming.

Uses the declared geometry rather than assuming the older 1.88672ha field.
Checks raw timezone-aware timestamps without rewriting evidence.
"""
from collections import Counter
from datetime import datetime
import math
import pytest


def _ridges(arguments):
    return range(arguments.get('start_ridge',arguments.get('start')),
                 arguments.get('end_ridge',arguments.get('end'))+1)


def _ground_ridges(arguments):
    return {arguments['ridge_id']} if 'ridge_id' in arguments else set(_ridges(arguments))


def assert_selected20_replay_contract(plan, replay, report, simulation_timezone, world, *,
                                 minimum_drone_battery_pct=20.):
    """Independent artifact audit after one case's real CLI execution.

    Geometry comes from the scene WORLD, including the 14.08ha long-field case. It
    does not load another scenario or run physics, and makes no yield-fit claim.
    """
    from test_wofost_formal10_scenarios import assert_public_replay_storage_contract
    assert list(plan) == list(replay) and plan
    fields = ("name", "tool_name", "tool_args", "depends_on", "op_type", "time")
    harvested, stored = [], []
    sensor_days, flights, ground_samples = set(), [], []
    last_epoch = report["start_time"]
    for name, step in replay.items():
        assert plan[name]["content"] is None
        assert all(plan[name].get(field) == step.get(field) for field in fields)
        before, after = step["time_before"], step["time_after"]
        assert math.isfinite(before) and math.isfinite(after) and last_epoch <= before <= after
        last_epoch = after
        assert datetime.fromtimestamp(after, simulation_timezone) == datetime.fromisoformat(step["time"])
        content = step.get("content")
        if isinstance(content, dict):
            assert not content.get("error") and content.get("status") not in {"partial", "error", "failed"}
            app, method = step["tool_name"].split("__", 1)
            day = datetime.fromtimestamp(before, simulation_timezone).date()
            if app == "SensorApp" and method in {"read_root_zone_sensors", "read_canopy_sensors"}:
                sensor_days.add(day)
            elif app == "SurveyDrone" and method == "fly_survey":
                coverage = list(_ridges(step["tool_args"]))
                assert day in sensor_days, "Aerial survey must follow a same-day coarse sensor reading"
                assert content["status"] == "ok" and content["surveyed_ridges"] == coverage
                assert Counter(row["ridge_id"] for row in content["observations"]) == Counter(coverage)
                assert minimum_drone_battery_pct <= content["battery_remaining_pct"] <= 100.
                assert after > before and content["duration_minutes"] > 0
                flights.append((day, after, set(coverage)))
            elif app.startswith("Robot") and method in {"inspect_crop_health", "inspect_ridge"}:
                ground_ids = _ground_ridges(step["tool_args"])
                if method == "inspect_crop_health":
                    assert set(content["covered_ridges"]) == ground_ids
                else:
                    assert {content["result"]["ridge_id"]} == ground_ids
                ground_samples.append((day, before, ground_ids))
            if step["tool_name"].endswith("__harvest"):
                harvested.extend(content["harvested_ridges"])
            elif step["tool_name"].endswith("__store_grain"):
                stored.extend(content["batch_ridge_ids"])
    assert Counter(harvested) == Counter(stored) == Counter(range(world.num_ridges))
    assert flights, "The replay must actually execute the scene's aerial diagnostic mission"
    assert all(any(ground_day == day and ground_before >= flight_after and ground_ids <= coverage
                   for ground_day, ground_before, ground_ids in ground_samples)
               for day, flight_after, coverage in flights), \
        "Aerial observations require subsequent same-day covered ground confirmation"
    assert_public_replay_storage_contract(replay, num_ridges=world.num_ridges)
    validation = report["evaluation"]["validation"]
    assert report["status"] == "completed" and validation["success"] is True
    assert validation["metadata"]["harvested_ridges"] == world.num_ridges
    assert validation["metadata"]["field_area_m2"] == pytest.approx(world.num_ridges * world.field_length_m * world.ridge_width_m)
    assert report["metrics"]["workflow_steps"] == len(replay)
