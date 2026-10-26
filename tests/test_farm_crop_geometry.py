from __future__ import annotations

import copy
import json

import pytest

from fairy.apps.farm_world.crop_profiles import get_crop_profile
from fairy.apps.farm_world.farm_world_app import FarmWorldApp, plants_per_ridge_from_spacing
from fairy.apps.farm_world.field_ops_app import FieldOpsApp
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.apps.farm_world.weather_app import WeatherApp


@pytest.mark.parametrize("kwargs", [
    {"num_ridges": 0}, {"num_ridges": True}, {"num_ridges": 2.5},
    {"field_length_m": float("nan")}, {"ridge_width_m": -1},
    {"farm_id": ""}, {"crop_type": "corn"},
])
def test_invalid_farm_configuration_rejected(kwargs):
    with pytest.raises(ValueError):
        FarmWorldApp(**kwargs)


def test_crop_geometry_round_trip_and_reset_preserves_identity():
    original = FarmWorldApp(farm_id="rice_south", num_ridges=5, field_length_m=80,
                            ridge_width_m=1.2, crop_type="rice")
    original._ridges[4].soil_vwc = 0.37
    serialized = json.loads(json.dumps(original.get_state()))
    restored = FarmWorldApp()
    restored.load_state(serialized)
    assert restored.configuration() == original.configuration()
    assert len(restored._ridges) == 5
    assert restored.field_area_m2 == 480
    assert restored.get_ridge(4).soil_vwc == 0.37
    restored.reset()
    assert restored.configuration() == original.configuration()
    assert restored.get_ridge(4).soil_vwc == 0.22
    assert restored._postharvest_market.max_storage_moisture_pct == 14


def test_old_state_infers_ridge_count_and_invalid_ridge_ids_rejected():
    state = FarmWorldApp(num_ridges=3).get_state()
    state.pop("farm_config")
    restored = FarmWorldApp()
    restored.load_state(state)
    assert restored.num_ridges == 3
    bad = copy.deepcopy(state)
    bad["ridges"][1]["ridge_id"] = 99
    with pytest.raises(ValueError, match="Ridge IDs"):
        restored.load_state(bad)


@pytest.mark.parametrize("crop,expected", [("soybean", 2000), ("maize", 1000), ("rice", 4000)])
def test_seed_count_uses_actual_length_and_crop_rows(crop, expected):
    farm = FarmWorldApp(num_ridges=7, field_length_m=100, crop_type=crop)
    assert farm.plants_per_ridge_from_spacing(10) == expected
    assert plants_per_ridge_from_spacing(8) == 6700


def test_native_proxy_assumptions_visible_to_agent_without_debug_access():
    farm = FarmWorldApp(crop_type="rice")
    assert any("non-flooded" in item for item in farm.get_farm_overview()["model_assumptions"])
    assert farm.get_state()["model_assumptions"] == farm.get_farm_overview()["model_assumptions"]


def test_profile_payload_is_json_compatible():
    for crop in ("soybean", "maize", "rice"):
        json.dumps(get_crop_profile(crop).to_dict(), allow_nan=False)


@pytest.mark.parametrize("crop", ["maize", "rice"])
def test_wofost_never_silently_runs_soybean_for_other_crops(crop):
    farm = FarmWorldApp(crop_type=crop)
    with pytest.raises(ValueError, match="soybean only"):
        farm.configure_crop_backend("wofost")
    assert farm._physics is None


def test_seed_loading_does_not_relabel_hopper_or_consume_wrong_crop_stock():
    farm = FarmWorldApp(crop_type="maize")
    tractor = TractorApp(farm, WeatherApp())
    initial = farm.get_inventory()
    assert "error" in tractor.load_seeds("STANDARD", 100)
    assert tractor.seed_type is None
    assert tractor._seed_hopper == 0
    assert farm.get_inventory() == initial
    assert tractor.load_seeds("MAIZE_STANDARD", 100)["status"] == "ok"
    state = tractor.get_state()
    tractor.reset()
    tractor.load_state(state)
    assert tractor.seed_type == "MAIZE_STANDARD"
    assert tractor._seed_hopper == 100


@pytest.mark.parametrize("crop,mature", [("soybean", "R8"), ("maize", "R6"), ("rice", "maturity")])
def test_legacy_clock_progression_has_crop_specific_maturity(crop, mature):
    farm = FarmWorldApp(crop_type=crop)
    farm.set_ridge_planted(0, farm.crop_profile.seed_type)
    farm.time_manager.add_offset(150 * 86400)
    assert farm.get_ridge(0).growth_stage == mature
    assert farm.get_ridge(0).grain_moisture_pct == farm.crop_profile.harvest_moisture_min_pct


@pytest.mark.parametrize("crop,moisture", [("maize", 22.0), ("rice", 23.0)])
def test_harvest_snapshot_uses_crop_gate_area_and_local_batch_storage(crop, moisture):
    farm = FarmWorldApp(farm_id=crop, num_ridges=3, field_length_m=100,
                        ridge_width_m=1.2, crop_type=crop)
    tractor = TractorApp(farm, WeatherApp())
    ridge = farm.get_ridge(0)
    ridge.planted, ridge.seed_type, ridge.growth_stage = True, farm.crop_profile.seed_type, "R8"
    ridge.grain_moisture_pct = moisture
    assert "error" in tractor.harvest(0, 0)  # Soybean maturity cannot harvest maize or rice.
    ridge.growth_stage = farm.crop_profile.mature_stage
    result = tractor.harvest(0, 0)
    assert result["status"] == "ok"
    expected = round(farm.ridge_area_m2 * farm.crop_profile.yield_kg_m2, 2)
    assert result["grain_kg_added"] == expected
    assert tractor.unload_grain()["status"] == "ok"
    assert farm._trailer_grain_moisture_pct() > farm._postharvest_market.max_storage_moisture_pct
    assert farm.dry_grain(13)["status"] == "ok"
    assert farm.store_grain()["status"] == "ok"
    assert farm._inventory.warehouse_grain_kg == expected


def test_rice_irrigation_gate_differs_from_soybean():
    soybean, rice = FarmWorldApp(), FarmWorldApp(crop_type="rice")
    soybean.get_ridge(0).soil_vwc = rice.get_ridge(0).soil_vwc = 0.33
    assert "error" in FieldOpsApp(soybean, WeatherApp()).irrigate_ridge(0, 0.5)
    assert FieldOpsApp(rice, WeatherApp()).irrigate_ridge(0, 0.5)["status"] == "irrigation_started"


def test_prep_and_machine_travel_scale_with_farm_geometry():
    large = TractorApp(FarmWorldApp(), WeatherApp())
    small = TractorApp(FarmWorldApp(num_ridges=4, field_length_m=134), WeatherApp())
    assert small._base_fertilize_kg == pytest.approx(large._base_fertilize_kg / 32)
    assert small._fuel_per_pass == pytest.approx(large._fuel_per_pass / 2)
    assert small._pass_duration(1) == 164
    assert small._full_field_duration(4.4, 1) == 164
