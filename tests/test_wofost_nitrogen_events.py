"""Real CNB pool edits remain observable and reproducible across daily boundaries."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world import FarmWorldApp
from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.physics import ManagementAction, ManagementActionType, PlantingConfig, SeedType, SoilWeatherInput
from fairy.scenarios.wofost_events import (
    SoilNitrogenEvent, apply_scenario_events_for_day, install_scenario_events, scenario_events_snapshot,
)


DAY = date(2026, 5, 1)
AREA = 100.0


@pytest.fixture
def native_api():
    pytest.importorskip("pcse")
    from fairy.physics.wofost_backend import WofostBackend, WofostConfig
    return WofostBackend, WofostConfig


def planted(count=3):
    physics = FarmPhysicsState(num_ridges=count)
    physics.phenology.plant_ridges(list(range(count)),
        PlantingConfig(planting_date=DAY, seed_type=SeedType.STANDARD))
    for state in physics.management.states.values():
        state.planted = True
        state.stand_fraction = 1.0
    return physics


def advance(backend, physics, day, actions=None):
    backend.advance_day(physics, day, SoilWeatherInput(day=day,
        air_temp_mean_c=22, air_temp_min_c=16, air_temp_max_c=28,
        rain_mm=2, solar_rad_mj_m2=20, wind_ms=2), actions_by_ridge=actions,
        ridge_area_m2=AREA, humidity_pct=55)


def test_live_edit_then_fertilizer_survives_pending_and_completed_checkpoints(native_api):
    backend_type, config_type = native_api
    backend, physics = backend_type(config_type()), planted()
    advance(backend, physics, DAY)
    second = DAY + timedelta(days=1)
    original_other = deepcopy(backend.native_soil_nitrogen([1, 2]))
    before = backend.native_soil_nitrogen([0])[0]
    assert before["available_n_kg_ha"] == pytest.approx(51.25)
    assert before["reserve_n_kg_ha"] == pytest.approx(48.75)

    assert backend.apply_soil_nitrogen_event(event_id="cut", day=second, ridge_ids=[0],
        available_n_kg_ha=0, reserve_n_kg_ha=0)
    assert backend.apply_soil_nitrogen_event(event_id="small_return", day=second, ridge_ids=[0],
        available_n_kg_ha=5)
    observed = backend.native_soil_nitrogen([0])[0]
    assert observed == dict(status="native", available_n_kg_ha=5, reserve_n_kg_ha=0,
        release_reference_n_kg_ha=50, native_effective_day=DAY.isoformat(),
        nitrogen_state_effective_day=second.isoformat())
    assert backend.native_soil_nitrogen([1, 2]) == original_other
    assert backend.snapshot()["ridges"]["0"]["pcse"]["NAVAIL"] == 5
    assert not backend.apply_soil_nitrogen_event(event_id="cut", day=second, ridge_ids=[0],
        available_n_kg_ha=0, reserve_n_kg_ha=0)
    assert backend.native_soil_nitrogen([0])[0]["available_n_kg_ha"] == 5

    # Save between the instant state change and that day's biological growth.
    payload = json.loads(json.dumps(backend.export_state(), allow_nan=False))
    restored = backend_type.from_state(payload)
    cloned = deepcopy(backend)
    for other in (restored, cloned):
        assert other.export_state() == payload
        assert other.native_soil_nitrogen([0, 1, 2]) == backend.native_soil_nitrogen([0, 1, 2])
        assert other.snapshot() == backend.snapshot()

    fertilizer = {0: [ManagementAction(ManagementActionType.FERTIGATION, amount=.1,
        metadata={"kg_per_ridge": 1.0})]}
    for candidate in (backend, restored, cloned):
        advance(candidate, deepcopy(physics), second, fertilizer)
    assert restored.snapshot() == cloned.snapshot() == backend.snapshot()
    ridge = backend.snapshot()["ridges"]["0"]
    assert ridge["pcse"]["NAVAIL"] == pytest.approx(5 + 46 * .7)
    assert ridge["cumulative_fertilizer_kg"] == 1
    assert ridge["cumulative_n_kg_ha"] == 46
    assert ridge["cumulative_external_soil_n_delta_kg_ha"] == pytest.approx(-95)
    changes = ridge["soil_nitrogen_changes"]
    assert [change["event_id"] for change in changes] == ["cut", "small_return"]
    assert changes[0]["before"] == dict(available_n_kg_ha=51.25, reserve_n_kg_ha=48.75)
    assert changes[0]["after"] == dict(available_n_kg_ha=0, reserve_n_kg_ha=0)
    assert changes[1]["before"] == changes[0]["after"]
    completed = backend_type.from_state(json.loads(json.dumps(backend.export_state(), allow_nan=False)))
    assert completed.snapshot() == backend.snapshot()
    assert completed.native_soil_nitrogen([0, 1, 2]) == backend.native_soil_nitrogen([0, 1, 2])


def test_reserve_edit_preserves_initial_release_rate_and_does_not_become_fertilizer(native_api):
    backend_type, config_type = native_api
    backend, physics = backend_type(config_type()), planted(1)
    advance(backend, physics, DAY)
    second = DAY + timedelta(days=1)
    backend.apply_soil_nitrogen_event(event_id="reserve", day=second, ridge_ids=[0],
        available_n_kg_ha=0, reserve_n_kg_ha=10)
    advance(backend, physics, second)
    pools = backend.native_soil_nitrogen([0])[0]
    assert pools["available_n_kg_ha"] == pytest.approx(1.25)
    assert pools["reserve_n_kg_ha"] == pytest.approx(8.75)
    assert pools["release_reference_n_kg_ha"] == 50
    assert backend.snapshot()["ridges"]["0"]["cumulative_fertilizer_kg"] == 0


def test_missing_native_run_and_zero_release_reference_fail_before_mutation(native_api):
    backend_type, config_type = native_api
    backend, physics = backend_type(config_type(base_soil_n_kg_ha=0)), planted(1)
    assert backend.native_soil_nitrogen([0])[0] == dict(status="not_started", available_n_kg_ha=None,
        reserve_n_kg_ha=None, release_reference_n_kg_ha=None, native_effective_day=None,
        nitrogen_state_effective_day=None)
    with pytest.raises(ValueError, match="already started"):
        backend.apply_soil_nitrogen_event(event_id="early", day=DAY, ridge_ids=[0], available_n_kg_ha=0)
    advance(backend, physics, DAY)
    before = backend.export_state()
    for options, match in ((dict(reserve_n_kg_ha=10), "zero initial"),
                           (dict(ridge_ids=[0, 1], available_n_kg_ha=0), "already started"),
                           (dict(day=DAY, available_n_kg_ha=0), "exact native")):
        arguments = dict(event_id="bad", day=DAY + timedelta(days=1), ridge_ids=[0], **{})
        arguments.update(options)
        with pytest.raises(ValueError, match=match):
            backend.apply_soil_nitrogen_event(**arguments)
        assert backend.export_state() == before


def test_scenario_event_is_local_once_ordered_and_reinstall_safe(native_api):
    backend_type, config_type = native_api
    east = FarmWorldApp(name="East", farm_id="east", num_ridges=3)
    west = FarmWorldApp(name="West", farm_id="west", num_ridges=3)
    for farm in (east, west):
        farm.simulation_timezone = ZoneInfo("Asia/Shanghai")
        farm._sim_date = DAY.isoformat()
        farm.physics.engines_active = True
        farm.physics.crop_backend = backend_type(config_type())
        physics = planted()
        farm.physics.phenology, farm.physics.management = physics.phenology, physics.management
    scenario = SimpleNamespace(apps=[east, west], start_time=datetime(2026, 5, 1, 7,
        tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
    second = DAY + timedelta(days=1)
    declarations = [SoilNitrogenEvent("cut", "east", 1, 2, second, 0, 0),
                    SoilNitrogenEvent("return", "east", 2, 2, second, 3)]
    install_scenario_events(scenario, declarations)
    for farm in (east, west):
        advance(farm.physics.crop_backend, farm.physics, DAY)
    west_before = west.physics.crop_backend.export_state()
    assert len(apply_scenario_events_for_day(east, second)) == 2
    pools = east.physics.crop_backend.native_soil_nitrogen([0, 1, 2])
    assert pools[0]["available_n_kg_ha"] == pytest.approx(51.25)
    assert pools[1]["available_n_kg_ha"] == 0
    assert pools[2]["available_n_kg_ha"] == 3
    assert west.physics.crop_backend.export_state() == west_before
    saved = deepcopy(scenario_events_snapshot(east))
    assert apply_scenario_events_for_day(east, second) == []
    install_scenario_events(scenario, declarations)
    assert scenario_events_snapshot(east) == saved
    assert apply_scenario_events_for_day(west, second) == []
    assert west.physics.crop_backend.export_state() == west_before


@pytest.mark.parametrize("options", [dict(available_n_kg_ha=-1), dict(available_n_kg_ha=float("nan")),
    dict(reserve_n_kg_ha=True), dict(), dict(ridge_end=-1, available_n_kg_ha=0)])
def test_invalid_event_values_are_rejected(options):
    arguments = dict(event_id="n", farm_id="farm", ridge_start=0, ridge_end=1, day=DAY)
    arguments.update(options)
    with pytest.raises(ValueError):
        SoilNitrogenEvent(**arguments)


def test_legacy_farm_rejects_native_n_event_before_installing_metadata():
    farm = FarmWorldApp(farm_id="farm", num_ridges=2)
    farm._sim_date = DAY.isoformat()
    farm.simulation_timezone = ZoneInfo("Asia/Shanghai")
    farm.physics.engines_active = True
    scenario = SimpleNamespace(apps=[farm], start_time=datetime(2026, 5, 1, 7,
        tzinfo=farm.simulation_timezone).timestamp())
    with pytest.raises(ValueError, match="native WOFOST"):
        install_scenario_events(scenario, [SoilNitrogenEvent("n", "farm", 0, 1,
            DAY + timedelta(days=1), available_n_kg_ha=0)])
    assert scenario_events_snapshot(farm) == {}


def test_completed_calendar_day_exposes_event_before_growth_and_full_checkpoint_restores_it(native_api):
    from fairy.physics.weather_engine import WeatherGenerator, WeatherGeneratorConfig, MonthlyClimate
    from fairy.scenarios.farm_world_fullseason_v2.farm_checkpoint_state import (
        export_farm_checkpoint_state, restore_farm_checkpoint_state,
    )
    from fairy.time_manager import SimulationTimeManager

    start = datetime(2026, 5, 1, 7, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    second = DAY + timedelta(days=1)
    declaration = SoilNitrogenEvent("cut", "east", 0, 0, second, 0, 0)

    def world():
        farm = FarmWorldApp(farm_id="east", num_ridges=2)
        farm.simulation_timezone = ZoneInfo("Asia/Shanghai")
        farm._sim_date = DAY.isoformat()
        farm.configure_crop_backend("wofost")
        farm.physics.scenario_metadata = {"daily_settlement": "completed_calendar_day"}
        generator = WeatherGenerator(WeatherGeneratorConfig(monthly={
            month: MonthlyClimate(20, 40, .4, 20) for month in range(1, 13)}), seed=11)
        for offset in range(5):
            generator.set_day_override(DAY + timedelta(days=offset), 22, 2, 2, 20,
                air_temp_min_c=16, air_temp_max_c=28, relative_humidity_pct=55)
        farm.physics.weather_generator = generator
        for ridge in farm._ridges:
            ridge.planted = True
            ridge.seed_type = SeedType.STANDARD.value
            ridge.seeds_planted = round(40 * farm.field_length_m * farm.ridge_width_m)
            ridge.days_since_planted = 0
        clock = SimulationTimeManager()
        clock.reset(start)
        farm.register_time_manager(clock)
        scene = SimpleNamespace(apps=[farm], start_time=start)
        install_scenario_events(scene, [declaration])
        return farm, clock, scene

    farm, clock, scene = world()
    farm.sync_initial_physics_state(start)
    clock.add_offset(86400)
    farm.advance_physics_time(clock.time())
    backend = farm.physics.crop_backend
    observed = backend.native_soil_nitrogen([0])[0]
    assert observed["available_n_kg_ha"] == observed["reserve_n_kg_ha"] == 0
    assert observed["native_effective_day"] == DAY.isoformat()
    assert observed["nitrogen_state_effective_day"] == second.isoformat()
    assert len(backend.export_state()["pending_soil_nitrogen"]["0"]) == 1
    warehouse_before = farm._inventory.fertilizer_kg

    # Repeated same-day synchronization cannot erase fertilizer or apply cut twice.
    farm.physics.queue_management_action(0, ManagementAction(ManagementActionType.FERTIGATION,
        amount=.1, metadata={"kg_per_ridge": 1.0}))
    farm.advance_physics_time(clock.time() + 60)
    assert backend.native_soil_nitrogen([0])[0]["available_n_kg_ha"] == 0
    assert farm._inventory.fertilizer_kg == warehouse_before
    payload = json.loads(json.dumps(export_farm_checkpoint_state(farm_world=farm, weather_app=None,
        scenario_id="nitrogen_event", checkpoint_label="event_then_pending_fertilizer"), allow_nan=False))
    restored, restored_clock, restored_scene = world()
    restored_clock.reset(clock.time())
    restore_farm_checkpoint_state(farm_world=restored, weather_app=None, checkpoint_state=payload)
    install_scenario_events(restored_scene, [declaration])
    assert restored.physics.crop_backend.native_soil_nitrogen([0, 1]) == backend.native_soil_nitrogen([0, 1])
    assert scenario_events_snapshot(restored) == scenario_events_snapshot(farm)

    clock.add_offset(86400)
    restored_clock.add_offset(86400)
    farm.advance_physics_time(clock.time())
    restored.advance_physics_time(restored_clock.time())
    final = backend.native_soil_nitrogen([0])[0]
    expected_n = .46 * .7 * 10000 / (farm.field_length_m * farm.ridge_width_m)
    assert final["available_n_kg_ha"] == pytest.approx(expected_n)
    assert restored.physics.crop_backend.snapshot() == backend.snapshot()
    assert len(backend.snapshot()["ridges"]["0"]["soil_nitrogen_changes"]) == 1
    assert backend.export_state()["pending_soil_nitrogen"] == {}
