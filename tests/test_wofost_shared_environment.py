"""Native crop objects stay field-local while the actual tool fleet is shared."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp, plants_per_ridge_from_spacing
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario


@pytest.mark.parametrize("count", [2, 3])
def test_native_farms_share_clock_and_stock_without_sharing_crop_state(count):
    pytest.importorskip("pcse")
    zone = ZoneInfo("Asia/Shanghai")
    start = datetime(2026, 5, 12, 7, tzinfo=zone).timestamp()
    weather = WeatherApp()
    weather.set_weather("2026-05-12", 22, 55, 2, 0, 240)
    worlds = [FarmWorldApp(farm_id=f"f{i}", name=f"F{i}", num_ridges=4) for i in range(count)]
    stock = WarehouseApp(stock=WarehouseStock(
        seed_stock={"HEINONG84": 1_000_000}, fertilizer_kg=1000,
        pesticide_liters=100, fuel_liters=500,
    ))
    env = FarmEnvironment([FarmContext(w.farm_id, w, weather) for w in worlds], weather,
                          start_time=start, timezone_name="Asia/Shanghai", warehouse=stock)
    tractor, system = SharedTractorApp(env), SystemApp()
    for world in worlds:
        world.set_season_phase("full_season")
        for ridge in world._ridges:
            ridge.soil_temp_c = 18
            ridge.soil_vwc = .25
        world.configure_crop_backend("wofost", cultivar_profile="heilongjiang_heinong84_complete_v1",
                                     require_explicit_cultivar_parameters=True)
    scene = Scenario(start_time=start, apps=[*worlds, weather, stock, tractor, system])
    scene.farm_environment, scene.shared_equipment = env, [tractor]
    engine = Engine(None, scene)
    seed_count = plants_per_ridge_from_spacing(7.9) * 4
    for world in worlds:
        target = world.farm_id
        assert tractor.attach_implement("grader")["status"] == "ok"
        assert tractor.level(target)["status"] == "ok"
        tractor.detach_implement()
        tractor.load_fertilizer(12.5)
        assert tractor.base_fertilize(target)["status"] == "ok"
        tractor.attach_implement("furrower")
        assert tractor.form_ridges(target, 1.1)["status"] == "ok"
        tractor.detach_implement()
        tractor.load_seeds("HEINONG84", seed_count)
        assert tractor.plant_seeds(target, 0, 3, 4, 7.9)["status"] == "ok"
    assert stock.stock.seed_stock["HEINONG84"] == 1_000_000 - count * seed_count
    assert stock.stock.fertilizer_kg == 1000 - count * 12.5
    assert all(w._management_regime.fertilizer_used_kg == 12.5 for w in worlds)
    assert len({id(w.physics.crop_backend) for w in worlds}) == count
    # An operation and a wait evolve idle farms too; midnight follows the scene calendar.
    now = engine.time_manager.time()
    system.advance_time(days=2)
    assert engine.time_manager.time() == now + 2 * 86400
    assert all(w.physics.last_physics_sim_time == engine.time_manager.time() for w in worlds)
    expected_date = datetime.fromtimestamp(engine.time_manager.time(), zone).date().isoformat()
    assert all(w._sim_date == expected_date for w in worlds)
    assert system.get_current_time()["current_datetime"].startswith(expected_date)
    for world in worlds:
        assert set(world.physics.crop_backend.snapshot()["ridges"]) == {"0", "1", "2", "3"}
    worlds[0].physics.biotic.states[0].disease_pressure = .8
    assert all(w.physics.biotic.states[0].disease_pressure != .8 for w in worlds[1:])
    outcome = engine.outcome_summary()
    assert set(outcome["farms"]) == {w.farm_id for w in worlds}
    assert "inventory" not in outcome["farms"]["f0"]
    assert outcome["warehouse"]["inventory"]["seed_stock"]["HEINONG84"] == stock.stock.seed_stock["HEINONG84"]
