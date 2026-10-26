"""Public observations and restricted catalogs used for multi-farm seasons."""
import pytest

from fairy.apps.farm_world import FarmWorldApp, SensorApp, RobotApp, WeatherApp
from fairy.scenarios.farm_world_diverse.full_season import ScenarioMultiCropFullSeasonMixed


def test_root_zone_probe_is_explicit_and_does_not_mislabel_surface_readings():
    farm = FarmWorldApp(num_ridges=3)
    sensor = SensorApp(farm)
    assert "error" in sensor.read_root_zone_sensors()
    farm.configure_physics_profile("root_zone_test")
    farm.sync_initial_physics_state()
    for state in farm.physics.soil.states.values():
        state.top_vwc, state.root_vwc = 0.15, 0.28
    data = sensor.read_root_zone_sensors()
    assert data["source"] == "simulated_root_zone_probes"
    assert [r["ridge_start"] for r in data["root_zone_sensors"]] == [0, 1, 2]
    assert all(abs(r["root_vwc"]-0.28) <= 0.0051 for r in data["root_zone_sensors"])
    assert all("root_vwc" not in r for r in sensor.read_soil_sensors()["soil_sensors"])


def test_health_scouting_reports_local_ordinal_leaf_nutrition():
    farm = FarmWorldApp(num_ridges=2)
    weather = WeatherApp()
    robot = RobotApp(farm, weather)
    for ridge in farm._ridges:
        ridge.planted, ridge.seed_type, ridge.growth_stage = True, "STANDARD", "V1"
        ridge.days_since_planted = 20
    farm._ridges[0].nutrient_index = 0.5
    farm._ridges[1].nutrient_index = 1.0
    farm.configure_physics_profile("leaf_nutrition_test")
    result = robot.inspect_crop_health(0, 1)
    assert result["observations"][0]["leaf_nutrition_band"] == "deficient"
    assert result["observations"][1]["leaf_nutrition_band"] == "adequate"
    assert "nutrient_index" not in result["observations"][0]


def test_leaf_diagnosis_is_unavailable_before_emergence():
    farm = FarmWorldApp(num_ridges=1)
    robot = RobotApp(farm, WeatherApp())
    farm.configure_physics_profile("unplanted_leaf_test")
    result = robot.inspect_crop_health(0, 0)
    assert result["observations"][0]["leaf_nutrition_band"] == "unavailable"


def test_tool_allowlist_is_opt_in_and_rejects_typographical_errors():
    farm = FarmWorldApp()
    original = {tool.name for tool in farm.get_tools()}
    assert "store_grain" in original
    farm.tool_allowlist = {"get_farm_overview"}
    assert [tool.name for tool in farm.get_tools()] == ["get_farm_overview"]
    farm.tool_allowlist = {"missing_tool"}
    with pytest.raises(ValueError, match="Unknown exposed tools"):
        farm.get_tools()
    farm.tool_allowlist = None
    assert {tool.name for tool in farm.get_tools()} == original


def test_mixed_full_season_catalog_includes_root_probes_and_stays_compact():
    scenario = ScenarioMultiCropFullSeasonMixed()
    scenario.setup()
    tools = [tool for app in scenario.apps for tool in app.get_tools()]
    assert len(tools) <= 128
    assert len({(tool.app_name, tool.name) for tool in tools}) == len(tools)
    schemas = {tool.to_open_ai()["function"]["name"]: tool.to_open_ai()["function"] for tool in tools}
    assert "World__describe_environment" in schemas
    assert "Sensor__read_root_zone_sensors" in schemas
    root_parameters = schemas["Sensor__read_root_zone_sensors"]["parameters"]["properties"]
    assert set(root_parameters["farm_id"]["enum"]) == {plan.farm_id for plan in scenario.farm_plans}
    planting_parameters = schemas["Tractor__plant_seeds"]["parameters"]["properties"]
    assert planting_parameters["asset_id"]["enum"] == ["tractor_shared"]
    assert not any(name.startswith(("SoyTractor__", "MaizeTractor__", "RiceTractor__")) for name in schemas)
    for site in scenario.fleet.sites:
        assert "read_root_zone_sensors" in {tool.name for tool in site.sensor.get_tools()}
        assert site.tractor._completed_prep_ops == []
        assert all(not ridge.planted for ridge in site.farm._ridges)
