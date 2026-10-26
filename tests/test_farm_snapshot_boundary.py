"""A field view cannot rebind installed geometry or partially rewind native crops."""
from copy import deepcopy

import pytest

from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.scenarios.farm_world_fullseason_v2.farm_checkpoint_state import restore_farm_checkpoint_state


def shared_world():
    world, weather = FarmWorldApp(farm_id="north", num_ridges=3), WeatherApp()
    warehouse = WarehouseApp(WarehouseStock({"STANDARD": 1000}, 10, 20, 30))
    FarmEnvironment([FarmContext("north", world, weather)], weather,
                    start_time=1778540400, warehouse=warehouse)
    return world, warehouse


@pytest.mark.parametrize("change", ["missing", "incomplete", "identity", "length", "width", "crop"])
def test_bound_field_config_must_match_before_any_mutation(change):
    world, warehouse = shared_world()
    before, stock_before = world.get_state(), warehouse.get_state()
    incoming = deepcopy(before)
    incoming["sim_date"] = "2030-01-01"
    incoming["ridges"][0]["soil_vwc"] = 0.99
    if change == "missing":
        incoming.pop("farm_config")
    elif change == "incomplete":
        incoming["farm_config"].pop("field_length_m")
    else:
        key, value = {"identity": ("farm_id", "south"), "length": ("field_length_m", 100),
                      "width": ("ridge_width_m", 2), "crop": ("crop_type", "maize")}[change]
        incoming["farm_config"][key] = value
    with pytest.raises(ValueError, match="complete farm/warehouse configuration"):
        world.load_state(incoming)
    assert world.get_state() == before
    assert warehouse.get_state() == stock_before


@pytest.mark.parametrize("current_native", [False, True])
def test_flat_native_view_restore_rejected_atomically(current_native):
    world, warehouse = shared_world()
    before, stock_before = world.get_state(), warehouse.get_state()
    incoming = deepcopy(before)
    incoming["sim_date"] = "2030-01-01"
    if current_native:
        # The guard must also reject old views without backend provenance
        # when a later native engine already belongs to the destination.
        world.physics.crop_backend_name = "wofost"
    else:
        incoming["crop_backend"] = {"backend": "wofost"}
    physics_before = world._physics
    with pytest.raises(ValueError, match="full physics checkpoint"):
        world.load_state(incoming)
    assert world._physics is physics_before
    assert world.get_state() == before
    assert warehouse.get_state() == stock_before


def test_incomplete_full_native_checkpoint_rejected_before_field_mutation():
    world = FarmWorldApp(num_ridges=1)
    before = world.get_state()
    incoming = deepcopy(before)
    incoming["sim_date"] = "2030-01-01"
    incoming["crop_backend"] = {"backend": "wofost"}
    with pytest.raises(ValueError, match="missing native model history"):
        restore_farm_checkpoint_state(farm_world=world, weather_app=None,
                                      checkpoint_state={"farm_world_state": incoming,
                                                        "physics_state": {"crop_backend_name": "wofost"}})
    assert world.get_state() == before
    assert world._physics is None
