"""Exercise native maize and soybean through the same real shared fleet."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario


def test_native_maize_and_soybean_use_one_warehouse_and_one_tractor():
    pytest.importorskip("pcse")
    zone = ZoneInfo("Asia/Shanghai")
    start = datetime(2026, 5, 12, 7, tzinfo=zone).timestamp()
    weather = WeatherApp()
    weather.set_weather("2026-05-12", 22, 55, 2, 0, 240)
    soybean = FarmWorldApp(farm_id="soy", name="Soy", num_ridges=4, field_length_m=20)
    maize = FarmWorldApp(farm_id="corn", name="Corn", num_ridges=4,
                         field_length_m=20, ridge_width_m=.75, crop_type="maize")
    stock = WarehouseApp(stock=WarehouseStock(
        seed_stock={"SOYBEAN_901": 10000, "MAIZE_201": 10000},
        fertilizer_kg=100, fuel_liters=500, pesticide_liters=20,
    ))
    env = FarmEnvironment([FarmContext(w.farm_id, w, weather) for w in (soybean, maize)],
                          weather, warehouse=stock, start_time=start,
                          timezone_name="Asia/Shanghai")
    for world in (soybean, maize):
        world.set_season_phase("full_season")
        for ridge in world._ridges:
            ridge.soil_temp_c, ridge.soil_vwc = 18, .25
    soybean.configure_crop_backend("wofost", cultivar_map={"SOYBEAN_901": "Soybean_901"})
    maize.configure_crop_backend("wofost", crop_name="maize")
    tractor, system = SharedTractorApp(env), SystemApp()
    scenario = Scenario(start_time=start, apps=[soybean, maize, weather, stock, tractor, system])
    scenario.farm_environment, scenario.shared_equipment = env, [tractor]
    engine = Engine(None, scenario)
    for world, seed, spacing in ((soybean, "SOYBEAN_901", 8.), (maize, "MAIZE_201", 20.)):
        assert tractor.attach_implement("grader")["status"] == "ok"
        assert tractor.level(world.farm_id)["status"] == "ok"
        tractor.detach_implement()
        base = 200. * world.field_area_m2 / (64 * 268. * 1.1)
        assert tractor.load_fertilizer(base)["status"] == "ok"
        assert tractor.base_fertilize(world.farm_id)["status"] == "ok"
        tractor.attach_implement("furrower")
        assert tractor.form_ridges(world.farm_id, world.ridge_width_m)["status"] == "ok"
        tractor.detach_implement()
        count = world.plants_per_ridge_from_spacing(spacing) * world.num_ridges
        assert tractor.load_seeds(seed, count)["status"] == "ok"
        # The loaded material is shared, but it must match the selected farm.
        other = "corn" if world is soybean else "soy"
        before = (engine.time_manager.time(), tractor.get_state(), stock.get_state())
        rejected = tractor.plant_seeds(other, 0, 3, 4., spacing)
        assert "error" in rejected
        assert (engine.time_manager.time(), tractor.get_state(), stock.get_state()) == before
        planted = tractor.plant_seeds(world.farm_id, 0, 3, 4., spacing)
        assert planted.get("status") == "ok", planted
        assert stock.stock.seed_stock[seed] == 10000 - count

    system.advance_time(days=3)
    for world in (soybean, maize):
        backend = world.physics.crop_backend
        assert backend.config.crop_name == world.crop_type
        assert set(backend.snapshot()["ridges"]) == {"0", "1", "2", "3"}
        assert world.physics.last_physics_sim_time == engine.time_manager.time()
    assert soybean.physics.crop_backend is not maize.physics.crop_backend
    assert maize.ridge_width_m == .75 and soybean.ridge_width_m == 1.1
    outcome = engine.outcome_summary()
    assert set(outcome["farms"]) == {"soy", "corn"}
    assert all("inventory" not in field for field in outcome["farms"].values())
