"""Survey observations must describe the farm at the returned mission time."""
from datetime import date, datetime

import pytest

from fairy.scenarios.registry import get_scenario_class


@pytest.mark.parametrize(
    "battery,covered,duration,status",
    [(100, 14, 136, "ok"), (29, 7, 83, "partial"), (20, 0, 30, "partial")],
)
def test_survey_samples_after_its_actual_duration_even_across_midnight(
    monkeypatch, battery, covered, duration, status
):
    monkeypatch.setattr("fairy.time_manager.time.time", lambda: 0.0)
    scene = get_scenario_class("scenario_two_farm_full_season_hn84_normal")()
    scene.setup()
    environment = scene.farm_environment
    environment.advance_time(16 * 3600 + 59 * 60)
    start = environment.time_manager.time()
    assert scene.system.get_current_time()["current_datetime"] == "2026-05-05 23:59:00+08:00"
    scene.mavic.load_state({"battery_pct": battery})

    samples = []
    model = scene.farm_a.physics.observation_model
    for method_name in ("observe_uav_multispectral", "observe_uav_thermal"):
        original = getattr(model, method_name)

        def observe(*args, _original=original, **kwargs):
            samples.append((environment.time_manager.time(), kwargs["day"]))
            return _original(*args, **kwargs)

        monkeypatch.setattr(model, method_name, observe)

    result = scene.mavic.fly_survey("farm_a", 0, 13)
    end = start + duration
    expected_day = environment.get_farm("farm_a").world.simulation_date(end)
    assert result["status"] == status
    assert result["surveyed_ridges"] == list(range(covered))
    assert len(result["observations"]) == covered
    assert environment.time_manager.time() == end
    assert all(timestamp == end and day == expected_day for timestamp, day in samples)
    assert len(samples) == (covered // 7) * 2
    assert scene.mavic.get_state()["mission_log"][-1]["duration_s"] == duration
    system_time = scene.system.get_current_time()["current_datetime"]
    assert datetime.fromisoformat(system_time).timestamp() == end
    for context in environment.farms.values():
        assert context.world.physics.last_physics_sim_time == end
        assert date.fromisoformat(context.world._sim_date) == expected_day
