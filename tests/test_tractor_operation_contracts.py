"""Tool discovery and invocation consume the same operation and crop rules."""
from __future__ import annotations

from dataclasses import replace
import inspect
from types import SimpleNamespace

import pytest

from fairy.apps.app import App
from fairy.apps.farm_world.equipment import DEFAULT_TRACTOR_IMPLEMENTS, TractorEquipment
from fairy.apps.farm_world.tractor_tool_contracts import TractorContractContext, tractor_operation_contract
from fairy.crops.catalog import MAIZE, SOYBEAN, get_crop_definition, register_crop_definition
from fairy.crops.rules import HarvestRules, PlantingRules, ScalarRange
from fairy.tool_contracts import OperationContract, ParameterContract
from fairy.tool_utils import app_tool
from fairy.utils.type_utils import type_check


def field(definition, farm_id="field"):
    """Contract-only field, without inventing a biological model for a test crop."""
    area = 100 * definition.default_ridge_width_m
    return SimpleNamespace(
        crop_id=definition.crop_id, crop_definition=definition,
        farm_id=farm_id, name=farm_id, num_ridges=12,
        field_length_m=100.0, rows_per_ridge=definition.default_rows_per_ridge,
        field_geometry=SimpleNamespace(ridge_area_m2=area, ridge_width_m=definition.default_ridge_width_m),
        plants_per_ridge_from_spacing=lambda spacing: round(10000 / spacing) * definition.default_rows_per_ridge,
    )


class ContractTractor(App):
    """Actual-signature tool client isolating contract extensibility."""
    require_explicit_tool_docs = True
    validate_tool_arguments = True

    def __init__(self, world, equipment=None):
        super().__init__()
        self.world = world
        self.equipment = equipment or TractorEquipment()
        self.effects = []
        self.context = TractorContractContext(
            farms=lambda: {self.world.farm_id: self.world},
            equipment=lambda: self.equipment,
            seed_types=lambda: self.world.crop_definition.seed_types,
        )

    def get_tool_contract(self, method_name):
        return tractor_operation_contract(self.context, method_name)

    @type_check
    @app_tool()
    def plant_seeds(self, start_ridge: int, end_ridge: int, depth_cm: float, seed_spacing_cm: float):
        """Plant the selected local ridges.

        Args:
            start_ridge: First local ridge.
            end_ridge: Last local ridge.
            depth_cm: Sowing depth.
            seed_spacing_cm: In-row spacing.
        """
        self.effects.append((start_ridge, end_ridge, depth_cm, seed_spacing_cm))
        return {"status": "ok"}

    @type_check
    @app_tool()
    def attach_implement(self, implement: str):
        """Mount the named owned attachment.

        Args:
            implement: Owned attachment.
        """
        self.effects.append(implement)
        return {"status": "ok"}

    @type_check
    @app_tool()
    def harvest(self, start_ridge: int, end_ridge: int):
        """Harvest local mature ridges.

        Args:
            start_ridge: First local ridge.
            end_ridge: Last local ridge.
        """
        return {"status": "ok"}

    @type_check
    @app_tool()
    def replant_seeds(self, start_ridge: int, end_ridge: int, depth_cm: float,
                      spacing_cm: float, full_replant: bool = False):
        """Replant according to the crop's replacement-operation rules.

        Args:
            start_ridge: First local ridge.
            end_ridge: Last local ridge.
            depth_cm: Replacement sowing depth.
            spacing_cm: Replacement in-row spacing.
            full_replant: Whether to restart the entire target ridge.
        """
        self.effects.append((start_ridge, end_ridge, depth_cm, spacing_cm, full_replant))
        return {"status": "ok"}


class SharedContractTractor(App):
    require_explicit_tool_docs = True
    validate_tool_arguments = True

    def __init__(self, farms):
        super().__init__()
        self.farms = farms
        self.effects = []
        self.equipment = TractorEquipment()
        self.context = TractorContractContext(
            farms=lambda: self.farms, equipment=lambda: self.equipment,
            seed_types=lambda: tuple(dict.fromkeys(
                seed for world in self.farms.values() for seed in world.crop_definition.seed_types
            )), has_farm_selector=True,
        )

    def get_tool_contract(self, method_name):
        return tractor_operation_contract(self.context, method_name)

    @type_check
    @app_tool()
    def plant_seeds(self, farm_id: str, start_ridge: int, end_ridge: int, depth_cm: float, seed_spacing_cm: float):
        """Plant a registered farm.

        Args:
            farm_id: Target farm.
            start_ridge: First local ridge.
            end_ridge: Last local ridge.
            depth_cm: Sowing depth.
            seed_spacing_cm: In-row spacing.
        """
        self.effects.append(farm_id)
        return {"status": "ok", "farm_id": farm_id}


def tool(app, name):
    return next(value for value in app.get_tools() if value.name == name)


@pytest.fixture
def third_crop(monkeypatch):
    from fairy.crops import catalog
    monkeypatch.setattr(catalog, "_DEFINITIONS", dict(catalog._DEFINITIONS))
    definition = replace(
        MAIZE, crop_id="contract_test_grain", cultivar_id="TEST_GRAIN_1", seed_types=("TEST_GRAIN_1",),
        planting_rules=PlantingRules(
            depth_cm=ScalarRange(1.0, 2.0), soil_vwc=ScalarRange(.15, .29),
            soil_temperature_c=ScalarRange(12.0), required_implement="test_grain_planter",
            supported_replant_modes=("full",),
        ),
        harvest_rules=HarvestRules(("TEST_RIPE",), 17.0, "test_grain_header"),
    )
    register_crop_definition(definition)
    return get_crop_definition("contract_test_grain")


def test_new_registered_crop_changes_schema_and_runtime_without_app_changes(third_crop):
    app = ContractTractor(field(third_crop))
    planting = tool(app, "plant_seeds")
    schema = planting.to_open_ai()["function"]
    assert "contract_test_grain" in schema["description"]
    assert "1–2 cm" in schema["description"]
    assert "test_grain_planter" in schema["description"]
    assert schema["parameters"]["properties"]["depth_cm"]["minimum"] == 1
    assert schema["parameters"]["properties"]["depth_cm"]["maximum"] == 2
    assert "TEST_RIPE" in tool(app, "harvest").function_description
    assert "17%" in tool(app, "harvest").function_description
    assert list(inspect.signature(planting.function).parameters) == [
        "self", "start_ridge", "end_ridge", "depth_cm", "seed_spacing_cm",
    ]
    for call in (app.plant_seeds, planting):
        assert "error" in call(0, 3, 5.0, 25.0)
        assert app.effects == []
        assert call(0, 3, 2.0, 25.0)["status"] == "ok"
        app.effects.clear()


def test_configured_wet_harvest_schema_matches_real_machine_gate():
    from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp
    from fairy.time_manager import SimulationTimeManager

    world, weather = FarmWorldApp(num_ridges=1), WeatherApp()
    tractor = TractorApp(world, weather)
    clock = SimulationTimeManager()
    clock.reset(1_800_000_000)
    for app in (world, weather, tractor):
        app.register_time_manager(clock)
    weather.set_weather("2027-01-15", 22, 55, 2, 0, 300)
    ridge = world.get_ridge(0)
    ridge.planted, ridge.seed_type, ridge.growth_stage = True, "STANDARD", "R8"
    ridge.grain_moisture_pct = 22

    assert "<= 18%" in tool(tractor, "harvest").function_description
    before = (tractor._fuel_tank_l, clock.time(), ridge.harvested)
    assert "moisture" in tractor.harvest(0, 0)["error"].lower()
    assert (tractor._fuel_tank_l, clock.time(), ridge.harvested) == before

    tractor.configure_harvest(max_grain_moisture_pct=25)
    assert "<= 25%" in tool(tractor, "harvest").function_description
    assert "mature stage R8" in tool(tractor, "harvest").function_description
    assert tractor.harvest(0, 0)["status"] == "ok"
    assert ridge.harvested

    tractor.reset()
    assert "<= 18%" in tool(tractor, "harvest").function_description


def test_crop_does_not_invent_equipment_and_explicit_device_configuration_is_used(third_crop):
    app = ContractTractor(field(third_crop))
    attach = tool(app, "attach_implement")
    assert next(arg for arg in attach.args if arg.name == "implement").choices == list(DEFAULT_TRACTOR_IMPLEMENTS)
    assert "error" in attach(implement="test_grain_planter")
    assert app.effects == []
    app.equipment = TractorEquipment(implements=(*DEFAULT_TRACTOR_IMPLEMENTS, "test_grain_planter"))
    assert tool(app, "attach_implement")(implement="test_grain_planter")["status"] == "ok"


def test_shared_tool_schema_uses_envelope_but_execution_uses_selected_farm(third_crop):
    app = SharedContractTractor({"soy": field(SOYBEAN, "soy"), "third": field(third_crop, "third")})
    planting = tool(app, "plant_seeds")
    schema = planting.to_open_ai()["function"]
    assert schema["parameters"]["properties"]["farm_id"]["enum"] == ["soy", "third"]
    assert schema["parameters"]["properties"]["depth_cm"]["minimum"] == 1
    assert schema["parameters"]["properties"]["depth_cm"]["maximum"] == 5
    assert "soy (soybean)" in schema["description"]
    assert "third (contract_test_grain)" in schema["description"]
    for call in (app.plant_seeds, planting):
        assert "error" in call("third", 0, 3, 5.0, 25.0)
        assert "error" in call("soy", 0, 3, 1.0, 25.0)
        assert "error" in call("missing", 0, 3, 2.0, 25.0)
        assert app.effects == []
        assert call("third", 0, 3, 2.0, 25.0)["farm_id"] == "third"
        assert call("soy", 0, 3, 5.0, 25.0)["farm_id"] == "soy"
        app.effects.clear()


@pytest.mark.parametrize("depth,spacing", [(float("nan"), 25), (float("inf"), 25), (1.5, float("nan")), (1.5, 0)])
def test_contract_invalid_numeric_parameters_never_reach_effects(third_crop, depth, spacing):
    app = ContractTractor(field(third_crop))
    for call in (app.plant_seeds, tool(app, "plant_seeds")):
        assert "error" in call(0, 3, depth, spacing)
        assert app.effects == []


def test_source_documentation_strictness_does_not_control_runtime_validation(third_crop):
    app = ContractTractor(field(third_crop))
    app.require_explicit_tool_docs = False
    assert "error" in app.plant_seeds(0.5, 3, 1.5, 25)
    assert "error" in tool(app, "plant_seeds")(0.5, 3, 1.5, 25)
    assert app.effects == []


def test_nonopted_in_app_keeps_existing_canonical_legacy_gate():
    class OtherApp(App):
        def __init__(self):
            super().__init__()
            self.calls = []

        @type_check
        @app_tool()
        def echo(self, value: int):
            self.calls.append(value)
            return value
    app = OtherApp()
    # No crop-operation opt-in is required for the pre-existing source-type
    # gate. Its accepted calls and primitive return shape remain unchanged.
    for call in (app.echo, tool(app, "echo")):
        invalid = call("wrong type")
        assert invalid["error_code"] == "INVALID_ARGUMENT"
        assert invalid["error_details"]["partial_effects"] is False
        assert app.calls == []
        assert call(3) == 3
        assert app.calls == [3]
        app.calls.clear()


def test_contract_cannot_invent_function_arguments():
    class BrokenApp(ContractTractor):
        def get_tool_contract(self, method_name):
            return OperationContract("Invalid contract", {"invented": ParameterContract("No such Python argument")})
    with pytest.raises(ValueError, match="unknown arguments.*invented"):
        BrokenApp(field(SOYBEAN)).get_tools()


def test_seed_specific_temperature_rules_preserve_legacy_soybean_boundaries():
    rules = SOYBEAN.planting_rules
    assert rules.validate_conditions("EARLY_COLD", 8.0, .25) is None
    assert rules.validate_conditions("STANDARD", 10.0, .25) is not None
    assert rules.validate_conditions("STANDARD", 10.001, .25) is None
    description = tool(ContractTractor(field(SOYBEAN)), "plant_seeds").function_description
    assert "EARLY_COLD: >= 8 °C" in description
    assert "soil temperature > 10 °C" in description


def test_configured_device_pass_limit_is_used_in_description_and_validation(third_crop):
    app = ContractTractor(field(third_crop), TractorEquipment(planting_max_ridges_per_pass=2))
    planting = tool(app, "plant_seeds")
    assert "up to 2 contiguous ridges" in planting.function_description
    assert "error" in planting(0, 2, 1.5, 25)
    assert app.effects == []


def test_real_bound_tractor_only_owns_configured_equipment_and_reset_preserves_it():
    from fairy.apps.farm_world.farm_world_app import FarmWorldApp
    from fairy.apps.farm_world.tractor_app import TractorApp
    from fairy.apps.farm_world.weather_app import WeatherApp

    world, weather = FarmWorldApp(crop_id="maize"), WeatherApp()
    default = TractorApp(world, weather)
    before = default.get_state()
    assert default.get_status()["available_implements"] == list(DEFAULT_TRACTOR_IMPLEMENTS)
    assert "error" in tool(default, "attach_implement")(implement="maize_planter")
    assert default.get_state() == before
    equipment = TractorEquipment(implements=(*DEFAULT_TRACTOR_IMPLEMENTS, "maize_planter", "maize_header"))
    configured = TractorApp(world, weather, equipment=equipment)
    assert configured.attach_implement("maize_planter")["status"] == "ok"
    configured.reset()
    assert configured.get_status()["available_implements"] == list(equipment.implements)
    saved = configured.get_state()
    saved["attached_implement"] = "unowned_attachment"
    before = configured.get_state()
    with pytest.raises(ValueError, match="not owned"):
        configured.load_state(saved)
    assert configured.get_state() == before


def test_real_shared_seed_loading_is_a_warehouse_operation_and_field_checks_crop():
    from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
    from fairy.apps.farm_world.farm_world_app import FarmWorldApp
    from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
    from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
    from fairy.apps.farm_world.weather_app import WeatherApp

    weather = WeatherApp()
    worlds = [FarmWorldApp(farm_id=farm_id) for farm_id in ("a", "b")]
    warehouse = WarehouseApp(stock=WarehouseStock(
        seed_stock={"STANDARD": 100, "WAREHOUSE_ONLY_SEED": 100},
        pesticide_liters=0, fertilizer_kg=0, fuel_liters=0,
    ))
    env = FarmEnvironment([FarmContext(world.farm_id, world, weather) for world in worlds],
                          weather, start_time=1778800000, warehouse=warehouse)
    tractor = SharedTractorApp(env)
    loading = tool(tractor, "load_seeds")
    schema = loading.to_open_ai()["function"]["parameters"]
    assert "farm_id" not in schema["properties"]
    assert schema["properties"]["seed_type"]["enum"] == ["STANDARD", "WAREHOUSE_ONLY_SEED"]
    assert loading(seed_type="WAREHOUSE_ONLY_SEED", count=100)["status"] == "ok"
    before = tractor.get_state()
    now = env.time_manager.time()
    for farm_id in ("a", "b"):
        result = tool(tractor, "plant_seeds")(
            farm_id=farm_id, start_ridge=0, end_ridge=0, depth_cm=4, seed_spacing_cm=5,
        )
        assert "not supported" in result["error"]
        assert tractor.get_state() == before
        assert env.time_manager.time() == now


def test_replant_contract_uses_its_own_rules_and_preserves_soybean_compatibility(third_crop):
    crop = replace(third_crop, replanting_rules=PlantingRules(
        depth_cm=ScalarRange(4.0, 7.0), soil_vwc=ScalarRange(),
        soil_temperature_c=ScalarRange(), required_implement=None,
        required_preparation=(), respect_scenario_window=False,
    ))
    app = ContractTractor(field(crop))
    replanting = tool(app, "replant_seeds")
    depth = replanting.to_open_ai()["function"]["parameters"]["properties"]["depth_cm"]
    assert (depth["minimum"], depth["maximum"]) == (4, 7)
    assert "no preparation prerequisite" in replanting.function_description
    assert "No scenario planting-window restriction" in replanting.function_description
    assert "target-block average" in replanting.function_description
    for call in (app.replant_seeds, replanting):
        assert "error" in call(0, 3, 1.5, 25)
        assert app.effects == []
        assert call(0, 3, 6.0, 25)["status"] == "ok"
        app.effects.clear()
    soy = SOYBEAN.replanting_rules
    assert soy is not None
    assert soy.required_preparation == () and soy.respect_scenario_window is False
    assert soy.validate_conditions("STANDARD", 5.0, .1) is None
