"""Reference soybean labels enter real native models through the Agent's tools."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from fairy.agents.agent.agent import Agent
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.physics.wofost_profiles import REFERENCE_CULTIVAR_PROFILES, load_cultivar_profile
from fairy.scenarios.scenario import Scenario


def test_four_reference_seeds_admitted_by_shared_public_tools_and_native_models():
    pytest.importorskip("pcse")
    zone = ZoneInfo("Asia/Shanghai")
    start = datetime(2026, 5, 12, 7, tzinfo=zone).timestamp()
    weather = WeatherApp()
    weather.set_weather("2026-05-12", 22, 55, 2, 0, 240)
    worlds = {seed: FarmWorldApp(farm_id=seed.lower(), name=seed, num_ridges=1)
              for seed in REFERENCE_CULTIVAR_PROFILES}
    initial_seeds = 100_000
    warehouse = WarehouseApp(WarehouseStock(
        {seed: initial_seeds for seed in worlds}, 20, 100, 200,
    ))
    environment = FarmEnvironment(
        [FarmContext(world.farm_id, world, weather) for world in worlds.values()],
        weather, start_time=start, timezone_name="Asia/Shanghai", warehouse=warehouse,
    )
    tractor, system = SharedTractorApp(environment), SystemApp()
    for world in worlds.values():
        world.set_season_phase("full_season")
        world._ridges[0].soil_temp_c = 18
        world._ridges[0].soil_vwc = .25
        world.configure_crop_backend(
            "wofost", cultivar_profiles=REFERENCE_CULTIVAR_PROFILES,
            require_explicit_cultivar_parameters=True,
        )
    scene = Scenario(start_time=start, apps=[*worlds.values(), weather, warehouse, tractor, system])
    scene.farm_environment, scene.shared_equipment = environment, [tractor]
    Engine(None, scene)
    # Build the actual Agent catalog and dispatch its JSON-call adapters. No
    # external model request, private planting helper or forced crop state.
    agent = Agent("reference-seed-admission", None, messages=[], toolsets=scene.apps)
    schemas = {item["function"]["name"]: item["function"] for item in agent.tool_schemas}
    seed_choices = schemas["Tractor__load_seeds"]["parameters"]["properties"]["seed_type"]["enum"]
    assert set(seed_choices) == set(REFERENCE_CULTIVAR_PROFILES)

    def call(name, **arguments):
        result = agent.tools_map[name](**arguments)
        assert "error" not in result, (name, arguments, result)
        return result

    counts = {}
    for seed, world in worlds.items():
        target = world.farm_id
        call("Tractor__attach_implement", implement="grader")
        call("Tractor__level", farm_id=target)
        call("Tractor__detach_implement")
        # This one-ridge field is 1/64 of the reference full-field area.
        call("Tractor__load_fertilizer", kg=200 / 64)
        call("Tractor__base_fertilize", farm_id=target)
        call("Tractor__attach_implement", implement="furrower")
        call("Tractor__form_ridges", farm_id=target, ridge_width_m=world.ridge_width_m)
        call("Tractor__detach_implement")
        counts[seed] = world.plants_per_ridge_from_spacing(7.9)
        call("Tractor__load_seeds", seed_type=seed, count=counts[seed])
        call("Tractor__plant_seeds", farm_id=target, start_ridge=0, end_ridge=0,
             depth_cm=4, seed_spacing_cm=7.9)
        assert world.get_ridge(0).seed_type == seed
        assert tractor._seed_hopper == 0
    call("SystemApp__advance_time", days=2)

    backends, native_models = [], []
    for seed, world in worlds.items():
        backend = world.physics.crop_backend
        run = backend.snapshot()["ridges"]["0"]
        specification = run["specification"]
        expected = load_cultivar_profile(REFERENCE_CULTIVAR_PROFILES[seed])
        assert specification["seed_type"] == seed
        assert specification["cultivar_profile"] == expected.provenance()
        assert specification["cultivar_profile"]["profile_id"] == REFERENCE_CULTIVAR_PROFILES[seed]
        assert len(specification["crop_parameters"]) == 78
        for response in ("TMNFTB", "DEPNR"):
            assert specification["crop_parameters"][response] == expected.parameter_overrides[response]
        assert run["pcse"]["DVS"] is not None
        assert run["last_day"] == "2026-05-14"
        assert warehouse.stock.seed_stock[seed] == initial_seeds - counts[seed]
        backends.append(id(backend))
        native_models.append(id(backend._runs[0].model))
    assert len(set(backends)) == len(set(native_models)) == 4
    assert warehouse.stock.fertilizer_kg == 100 - 4 * 200 / 64
