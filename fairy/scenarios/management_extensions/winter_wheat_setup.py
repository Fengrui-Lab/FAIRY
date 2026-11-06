"""Wheat-specific wiring of existing farm Apps; no scenario selection or policy."""

from dataclasses import asdict
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo
from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.system import SystemApp
from .apps.winter_wheat_accounts_app import WinterWheatAccounts
from .apps.winter_wheat_farm_app import WinterWheatFarm, WinterWheatSensors
from .apps.winter_wheat_tractor_app import WinterWheatTractor
from .apps.winter_wheat_irrigation_app import WinterWheatIrrigation
from .engines.winter_wheat_wofost import InputBundle
from .engines.winter_wheat_inputs import fingerprint


def configure_wheat_calendar(scene, input_dir, late_harvest):
    """Use the pinned season for the farm clock and the operating deadline."""
    scene.input_dir = (
        Path(input_dir)
        if input_dir is not None
        else Path(__file__).parent / "data/winter_wheat_ncp_2019_2020"
    )
    if late_harvest is None:
        late_harvest = input_dir is None and scene.default_late_harvest
    if type(late_harvest) is not bool:
        raise ValueError("late_harvest must be a JSON boolean")
    scene.input_bundle = InputBundle(scene.input_dir, late_harvest=late_harvest)
    season = scene.input_bundle.season
    scene.timezone_name = season.timezone
    scene.simulation_timezone = zone = ZoneInfo(season.timezone)
    scene.start_time = datetime.combine(season.start, time(7), zone).timestamp()
    end = datetime.combine(season.deadline, time(23, 59, 59), zone).timestamp()
    scene.duration = end - scene.start_time


def initialize_wheat_farm(
    scene,
    *,
    farm_class=WinterWheatFarm,
    irrigation_factory=WinterWheatIrrigation,
    warehouse_factory=WarehouseApp,
    tractor_factory=WinterWheatTractor,
    accounts_factory=WinterWheatAccounts,
):
    """Create one block-managed native field with the common clock and warehouse."""
    r = scene.resources
    scene.farm = farm_class(scene.input_bundle, r)
    scene.world = scene.farm
    scene.farms = [scene.farm]
    scene.weather, scene.system, scene.aui = (
        WeatherApp(),
        SystemApp(),
        AgentUserInterface(),
    )
    scene.sensor = WinterWheatSensors(scene.farm)
    scene.irrigation = irrigation_factory(scene.farm, scene.weather)
    scene.warehouse = warehouse_factory(
        WarehouseStock(
            scene.farm.seed_inventory(),
            0.0,
            r.fertilizer_stock_kg,
            r.fuel_stock_liters,
        ),
        name="Warehouse",
        storage_capacity_kg=r.warehouse_capacity_kg,
        drying_capacity_kg_per_day=r.warehouse_capacity_kg,
        max_storage_moisture_pct=r.storage_moisture_pct,
    )
    scene.farm_environment = FarmEnvironment(
        [
            FarmContext(
                scene.farm.farm_id, scene.farm, scene.weather, scene.sensor, scene.irrigation
            )
        ],
        scene.weather,
        warehouse=scene.warehouse,
        start_time=scene.start_time,
        timezone_name=scene.timezone_name,
    )
    scene.tractor = tractor_factory(scene.farm_environment)
    scene.accounts = accounts_factory(
        resources=r,
        farms=scene.farms,
        warehouse=scene.warehouse,
        tractor=scene.tractor,
        initial_machine_fuel=scene.tractor._fuel_tank_l,
        water_capacity_m3=r.water_stock_m3,
        operation_deadline=datetime.fromtimestamp(
            scene.start_time + scene.duration, scene.simulation_timezone
        ).isoformat(),
    )
    scene.prices = scene.accounts.prices
    scene.apps = [
        scene.aui,
        scene.farm,
        scene.weather,
        scene.sensor,
        scene.warehouse,
        scene.tractor,
        scene.irrigation,
        scene.system,
        scene.accounts,
    ]
    scene.system.attach_farm_environment(scene.farm_environment)
    for app in scene.apps:
        app.register_time_manager(scene.farm_environment.time_manager)
        app.rng.seed(scene.seed)
    scene.farm_environment.sync()


def wheat_fingerprint(scene):
    return fingerprint(
        dict(
            native=scene.farm.crop_backend_provenance(),
            resources=asdict(scene.resources),
            prices=asdict(scene.prices),
            operational_rules="flat_blocks_shared_equipment_v1",
            machine_recovery=0.95,
        )
    )
