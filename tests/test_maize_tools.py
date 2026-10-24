"""Crop identity, tool accounting and native maturity on the shared farm apps."""
from datetime import date, datetime, timezone

import pytest

from fairy.apps.farm_world import FarmWorldApp, WeatherApp
from fairy.apps.farm_world.farm_world_app import FIELD_LENGTH_M, plants_per_ridge_from_spacing
from fairy.apps.farm_world.physics_orchestrator import _ridge_planting_density_plants_m2
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.physics import SoybeanStage
from fairy.time_manager import TimeManager


@pytest.fixture
def maize_tools():
    pytest.importorskip("pcse")
    farm = FarmWorldApp()
    farm.num_ridges = 1
    farm._ridges = farm._ridges[:1]
    farm.configure_crop_backend("wofost", crop_name="maize")
    weather = WeatherApp()
    weather.set_weather(date="2026-05-01", temp_c=22.0, humidity_pct=55.0,
                        wind_speed_ms=2.0, rainfall_mm=0.0, solar_radiation=240.0)
    tractor = TractorApp(farm, weather, name="TractorApp")
    clock = TimeManager()
    clock.reset(datetime(2026, 5, 1, 8, tzinfo=timezone.utc).timestamp())
    for app in (farm, weather, tractor):
        app.register_time_manager(clock)
    ridge = farm._ridges[0]
    ridge.soil_vwc = .27
    ridge.soil_temp_c = 20.0
    tractor._completed_prep_ops = ["level", "base_fertilize", "form_ridges"]
    tractor.configure_harvest(max_grain_moisture_pct=25)
    return farm, weather, tractor, clock


def test_maize_crop_seed_and_backend_guards_do_not_consume_stock(maize_tools):
    farm, _, tractor, _ = maize_tools
    before = farm.get_inventory()
    assert "MAIZE_201" in tractor.load_seeds("STANDARD", 2000)["error"]
    assert farm.get_inventory() == before
    assert tractor.seed_type is None
    with pytest.raises(ValueError, match="requires the WOFOST"):
        farm.configure_crop_backend("legacy")
    soybean = FarmWorldApp()
    other = TractorApp(soybean, WeatherApp())
    assert "require" in other.load_seeds("MAIZE_201", 2000)["error"]


def test_maize_seed_inventory_matches_one_row_density(maize_tools):
    farm, _, tractor, _ = maize_tools
    assert "error" not in tractor.load_seeds("MAIZE_201", 2000)
    result = tractor.plant_seeds(0, 0, depth_cm=4, seed_spacing_cm=20)
    assert "error" not in result
    assert result["seeds_used"] == 1340
    assert tractor._seed_hopper == 660
    assert farm._inventory.seed_stock["MAIZE_201"] == 998000
    assert farm._ridges[0].seeds_planted == 1340
    assert _ridge_planting_density_plants_m2(farm, 0) == pytest.approx(6.6666666667)
    # Older snapshots without an explicit plant count must use the same geometry.
    farm._ridges[0].seeds_planted = 0
    assert _ridge_planting_density_plants_m2(farm, 0) == pytest.approx(6.6666666667)
    assert plants_per_ridge_from_spacing(20) == 2680  # unchanged soybean default
    assert farm._ridges[0].growth_stage == "PLANTED_PRE_EMERGENCE"


def test_maize_state_records_identity_and_old_state_defaults_to_soybean(maize_tools):
    farm, _, _, _ = maize_tools
    state = farm.get_state()
    restored = FarmWorldApp()
    restored.load_state(state)
    assert restored.crop_name == "maize"
    assert restored.variety_name == "Grain_maize_201"
    assert restored.rows_per_ridge == 1
    assert restored.ridge_width_m == .75
    old_state = FarmWorldApp().get_state()
    assert "crop_name" not in old_state
    restored.load_state(old_state)
    assert restored.crop_name == "soybean"
    assert restored.rows_per_ridge == 2
    assert restored.ridge_width_m == 1.1


def _mature_crop(farm, *, moisture=.24):
    ridge = farm._ridges[0]
    ridge.planted = True
    ridge.seed_type = "MAIZE_201"
    ridge.growth_stage = "MATURE"
    ridge.grain_moisture_pct = moisture * 100
    physics = farm.physics
    phen = physics.phenology.states[0]
    phen.planted = True
    phen.emerged = True
    phen.stage = SoybeanStage.MATURE
    phen.maturity_date = date(2026, 5, 1)
    physics.canopy.states[0].yield_potential_g_m2 = 800
    physics.canopy.states[0].aboveground_biomass_g_m2 = 1600
    recovery = physics.yield_recovery.states[0]
    recovery.r8_reached = True  # legacy internal field shared by the recovery engine
    recovery.maturity_date = phen.maturity_date
    recovery.grain_moisture_frac = moisture
    recovery.biological_yield_g_m2 = 800


def test_maize_harvest_uses_native_maturity_and_equipment_limit(maize_tools):
    farm, _, tractor, _ = maize_tools
    _mature_crop(farm, moisture=.251)
    assert "moisture too high" in tractor.harvest(0, 0)["error"]
    farm._ridges[0].grain_moisture_pct = 24
    farm.physics.phenology.states[0].maturity_date = None
    # A display label alone cannot bypass native maturity.
    assert "not mature" in tractor.harvest(0, 0)["error"]
    assert tractor._grain_bin_kg == 0


def test_maize_harvest_and_drying_preserve_dry_matter_at_14_percent_basis(maize_tools):
    farm, _, tractor, _ = maize_tools
    _mature_crop(farm)
    result = tractor.harvest(0, 0)
    assert "error" not in result
    recovery = farm.physics.yield_recovery.states[0]
    dry_g_m2 = (recovery.biological_yield_g_m2
                * (1-recovery.field_loss_fraction)
                * (1-recovery.machine_loss_fraction))
    expected_dry_kg = dry_g_m2 * FIELD_LENGTH_M * .75 / 1000
    expected_market_kg = expected_dry_kg / .86
    assert result["grain_kg_added"] == pytest.approx(expected_market_kg, abs=.01)
    assert "error" not in tractor.unload_grain()
    before = farm._inventory.harvest_grain_kg
    assert before * .86 == pytest.approx(expected_dry_kg, abs=.01)
    assert "error" not in farm.dry_grain(target_moisture_pct=14)
    assert recovery.grain_moisture_frac == .14
    assert farm._inventory.harvest_grain_kg == before
    assert "warning" not in farm.store_grain()
    assert farm._inventory.warehouse_grain_kg * .86 == pytest.approx(expected_dry_kg, abs=.01)
    assert farm.get_inventory()["market_moisture_pct"] == pytest.approx(14)


def test_maize_native_stage_progression_skips_soybean_biotic_dynamics(maize_tools):
    farm, _, tractor, clock = maize_tools
    tractor.load_seeds("MAIZE_201", 2000)
    assert "error" not in tractor.plant_seeds(0, 0, depth_cm=4, seed_spacing_cm=20)
    biotic_before = vars(farm.physics.biotic.states[0]).copy()
    assert biotic_before["insect_pressure"] == 0.0
    assert biotic_before["disease_pressure"] == 0.0
    assert biotic_before["weed_pressure"] == 0.0
    clock.add_offset(20 * 86400)
    farm.advance_physics_time()
    ridge = farm._ridges[0]
    assert ridge.growth_stage == "VEGETATIVE"
    assert vars(farm.physics.biotic.states[0]) == biotic_before
    assert farm.physics.canopy.states[0].initialized
    assert farm.get_farm_overview()["crop_name"] == "maize"
    assert "oracle" not in {tool.name for tool in tractor.get_tools()}


def test_maize_reset_retains_crop_and_rejects_partial_crosscrop_restore(maize_tools):
    farm, _, tractor, clock = maize_tools
    tractor.load_seeds("MAIZE_201", 2000)
    tractor.plant_seeds(0, 0, depth_cm=4, seed_spacing_cm=20)
    clock.add_offset(5 * 86400)
    farm.advance_physics_time()
    old_backend = farm.physics.crop_backend
    farm.reset()
    tractor.reset()
    assert farm.crop_name == "maize"
    assert farm.physics.crop_backend is not old_backend
    assert farm.physics.crop_backend.last_day is None
    assert not farm._ridges[0].planted
    assert not farm.physics.phenology.states[0].planted
    assert farm._inventory.seed_stock == {"MAIZE_201": 1000000}
    assert farm._postharvest_market.market_moisture_pct == pytest.approx(14)
    assert tractor._harvest_moisture_limit_pct == 25
    assert tractor._seed_hopper == 0
    with pytest.raises(ValueError, match="fresh farm"):
        farm.configure_crop_backend("wofost", crop_name="soybean")
    # load_state alone cannot hydrate a different native engine. Reject tool use
    # until the complete checkpoint loader has restored the corresponding backend.
    legacy = FarmWorldApp().get_state()
    farm.load_state(legacy)
    before = farm.get_state()
    assert "does not match" in tractor.load_seeds("STANDARD", 2000)["error"]
    assert farm.get_state() == before
    assert tractor._seed_hopper == 0


def test_maize_robot_observes_real_emergence_and_marks_biotics_unmodeled(maize_tools):
    from fairy.apps.farm_world.robot_app import RobotApp

    farm, weather, tractor, clock = maize_tools
    robot = RobotApp(farm, weather)
    robot.register_time_manager(clock)
    tractor.load_seeds("MAIZE_201", 2000)
    tractor.plant_seeds(0, 0, depth_cm=4, seed_spacing_cm=20)
    before = robot.inspect_emergence(0, 0)["observations"][0]
    assert before["emerged"] is False
    assert before["growth_stage"] == "PLANTED_PRE_EMERGENCE"
    assert before["stand_fraction"] == 0
    assert before["biotic_status"] == "not_simulated"
    assert before["pest_present"] is None
    clock.add_offset(20 * 86400)
    health = robot.inspect_crop_health(0, 0)["observations"][0]
    assert health["emerged"] is True
    assert health["growth_stage"] == "VEGETATIVE"
    assert health["stand_fraction"] > 0
    assert isinstance(health["spad_proxy"], float)
    assert "not a calibrated maize" in health["measurement_note"]
    assert health["disease_present"] is None
    single = robot.inspect_ridge(0)["result"]
    assert single["growth_stage"] == "VEGETATIVE"
    assert single["pest_type"] is None
    assert single["biotic_status"] == "not_simulated"
    farm.physics.yield_recovery.states[0].harvested = True
    harvested = robot.inspect_crop_health(0, 0)["observations"][0]
    assert harvested["harvested"] is True
    assert harvested["stand_fraction"] == 0
    assert harvested["growth_stage"] == "bare"
    assert harvested["spad_proxy"] is None


def test_maize_native_bin_capacity_and_rejected_seed_load_are_atomic(maize_tools):
    farm, _, tractor, clock = maize_tools
    assert "error" not in tractor.load_seeds("MAIZE_201", 1000)
    before_stock = farm._inventory.seed_stock.copy()
    before_hopper = tractor._seed_hopper
    before_seed = tractor.seed_type
    for bad_seed, count in [("STANDARD", 1000), ("MAIZE_201", 0)]:
        assert "error" in tractor.load_seeds(bad_seed, count)
        assert farm._inventory.seed_stock == before_stock
        assert tractor._seed_hopper == before_hopper
        assert tractor.seed_type == before_seed
    _mature_crop(farm)
    # The native crop can exceed the historical soybean 245kg/ridge bound.
    farm.physics.canopy.states[0].yield_potential_g_m2 = 1600
    tractor._grain_bin_kg = 1700
    fuel = tractor._fuel_tank_l
    now = clock.time()
    assert "overflow" in tractor.harvest(0, 0)["error"]
    assert tractor._grain_bin_kg == 1700
    assert tractor._fuel_tank_l == fuel
    assert clock.time() == pytest.approx(now, abs=0.01, rel=0)
    assert farm._ridges[0].planted
