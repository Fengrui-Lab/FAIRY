"""Only environment plumbing and accounting; all management steps are in four scene files."""

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world.equipment import TractorEquipment, DEFAULT_TRACTOR_IMPLEMENTS
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.irrigation_app import IrrigationApp
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.system import SystemApp
from fairy.scenarios.scenario import Scenario
from .evaluation.oracle_comparison import biological_grain_kg, recovered_grain_kg
from .runtime import (
    EpisodeState,
    PlanningFarm,
    PlanningTractor,
    SeasonPlanning,
    SeedMarket,
)
from .validation import ExtensionValidation
from .china_market_prices import (
    CONTRACTS,
    dollars_to_cents,
    operating_prices,
    usd_cents,
)


class FullSeasonExtension(ExtensionValidation, Scenario):
    def __post_init__(self):
        super().__post_init__()
        self.start_time = datetime(
            2019, 5, 1, 7, tzinfo=ZoneInfo("Europe/Paris")
        ).timestamp()
        self.duration = 213 * 86400
        self.expects_agent_harvest = True
        self.crop_backend = "wofost"

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("Fixed full-season scene has no overrides")
        self.init_and_populate_apps()
        self.build_events_flow()

    def initialize_world(
        self,
        *,
        crop,
        history,
        report,
        offers,
        seed_stock,
        fertilizer_kg,
        fuel_liters,
        num_ridges,
        field_length_m,
        ridge_width_m,
        seed_budget_minor,
        rain_free_october=False,
    ):
        self.prices = operating_prices()
        self.expected_crop = crop
        self.rotation = bool(history)
        self.production_budget_minor = usd_cents(
            CONTRACTS["legacy_total_budget_cny"][crop]
        )
        episode = EpisodeState(
            season_history=deepcopy(history),
            soil_report=deepcopy(report),
            budget_initial_minor=seed_budget_minor,
            rain_free_october=rain_free_october,
        )
        self.farm = PlanningFarm(
            selected_crop=None if self.rotation else crop,
            episode=episode,
            num_ridges=num_ridges,
            field_length_m=field_length_m,
            ridge_width_m=ridge_width_m,
            management_objective={
                "minimum_stored_grain_kg": 0.99 * self.best_tested_yield_kg,
                "maximum_production_cost_minor": self.oracle_cost_minor,
                "currency": "USD",
                "minor_units_per_usd": 100,
                "deadline": datetime.fromtimestamp(
                    self.start_time + self.duration, ZoneInfo("Europe/Paris")
                ).isoformat(),
            },
        )
        self.weather, self.system, self.aui = (
            WeatherApp(),
            SystemApp(),
            AgentUserInterface(),
        )
        self.sensor = SensorApp(self.farm, name="Sensor")
        self.irrigation = IrrigationApp(self.farm, self.weather, name="Irrigation")
        self.warehouse = WarehouseApp(
            WarehouseStock(
                deepcopy(seed_stock),
                pesticide_liters=0.0,
                fertilizer_kg=fertilizer_kg,
                fuel_liters=fuel_liters,
            ),
            storage_capacity_kg=20000.0,
            drying_capacity_kg_per_day=20000.0,
            max_storage_moisture_pct=14.0,
        )
        self.farm_environment = FarmEnvironment(
            [
                FarmContext(
                    "field", self.farm, self.weather, self.sensor, self.irrigation
                )
            ],
            self.weather,
            warehouse=self.warehouse,
            start_time=self.start_time,
            timezone_name="Europe/Paris",
        )
        self.tractor = PlanningTractor(
            self.farm_environment,
            equipment=TractorEquipment(
                implements=(*DEFAULT_TRACTOR_IMPLEMENTS, "seeder"),
                ridging_implement="furrower",
            ),
        )
        self.planning = SeasonPlanning(self.farm, prices=self.prices)
        self.market = SeedMarket(
            self.farm,
            self.warehouse,
            offers,
            cost_reader=self.production_cost_minor,
            prices=self.prices,
            production_budget_minor=self.production_budget_minor,
        )
        self.apps = [
            self.aui,
            self.farm,
            self.weather,
            self.sensor,
            self.warehouse,
            self.tractor,
            self.irrigation,
            self.system,
            self.planning if self.rotation else self.market,
        ]
        self.system.attach_farm_environment(self.farm_environment)
        for app in self.apps:
            app.register_time_manager(self.farm_environment.time_manager)
            app.rng.seed(0)
        self.weather.set_weather(
            date="2019-05-01",
            temp_c=12.0,
            humidity_pct=65.0,
            wind_speed_ms=2.0,
            rainfall_mm=0.0,
            solar_radiation=15 / 0.0864,
            avg_soil_vwc=0.26,
        )
        self._initial_stock = deepcopy(self.warehouse.stock.seed_stock)
        self._initial_fertilizer = self.warehouse.stock.fertilizer_kg
        self._initial_fuel = (
            self.warehouse.stock.fuel_liters + self.tractor._fuel_tank_l
        )
        self.additional_system_prompt = self.scenario_input

    def production_accounts(self):
        """Value actual consumed inputs in USD; seed cash receipts remain integer cents."""
        fertilizer = (
            self._initial_fertilizer
            - self.warehouse.stock.fertilizer_kg
            - self.tractor._fertilizer_spreader_kg
        )
        fuel = (
            self._initial_fuel
            - self.warehouse.stock.fuel_liters
            - self.tractor._fuel_tank_l
        )
        water_m3 = (
            self.farm._management_regime.irrigation_used_mm_total
            * self.farm.field_area_m2
            / 1000
        )
        dry_kg = sum(self.warehouse._drying_usage_by_date.values())
        seed_cost = self.farm.episode.spent / 100
        seed_used = {}
        for seed, initial in self._initial_stock.items():
            receipts = sum(
                o["quantity"]
                for o in self.farm.episode.orders.values()
                if o["seed_type"] == seed
            )
            hopper = self.tractor._seed_hopper if self.tractor.seed_type == seed else 0
            seed_used[seed] = (
                initial + receipts - self.warehouse.stock.seed_stock[seed] - hopper
            )
        if self.rotation:
            seed_cost = sum(
                self.prices["seed_per_unit"][k] * v for k, v in seed_used.items()
            )
        costs = {
            "seed": seed_cost,
            "fertilizer": fertilizer * self.prices["fertilizer_per_kg"],
            "fuel": fuel * self.prices["fuel_per_liter"],
            "water": water_m3 * self.prices["water_per_m3"],
            "drying": dry_kg * self.prices["drying_per_kg"],
        }
        # The legacy budget/feasibility rule settles the total to US cents once.
        cents = dollars_to_cents(sum(costs.values()))
        stored = sum(
            v.quantity_kg
            for v in self.warehouse.grain_batches.values()
            if v.status == "stored"
        )
        crop = self.farm.crop_id
        value = stored * self.prices["crop_per_kg"][crop]
        return {
            "currency": "USD",
            "price_book_id": self.prices["price_book_id"],
            "cny_per_usd": self.prices["cny_per_usd"],
            "prices": self.prices,
            "production_cost": cents / 100,
            "production_cost_minor": cents,
            "cost_components": costs,
            "accounting_rounding": cents / 100 - sum(costs.values()),
            "fuel_liters": fuel,
            "water_m3": water_m3,
            "drying_throughput_kg": dry_kg,
            "fertilizer_product_kg": fertilizer,
            "consumed_seeds": seed_used,
            "biological_kg_by_crop": {crop: biological_grain_kg(self.farm)},
            "recovered_kg_by_crop": {crop: recovered_grain_kg(self.farm)},
            "stored_kg_by_crop": {crop: stored},
            "stored_grain_kg": stored,
            "stored_grain_value": value,
            "net_operating_margin": value - cents / 100,
        }

    def production_cost_minor(self):
        """Total actual-consumption cost, rounded once to US cents (100 = 1 USD)."""
        return self.production_accounts()["production_cost_minor"]


def capture_step(previous, event, name, reason):
    """Attach a literal public call to the captured graph; never execute or choose actions."""
    captured = event.oracle().with_id(name).depends_on(previous)
    captured.workflow_metadata = {"oracle_reason": reason}
    return captured


def finish_capture(scene, events):
    for event in events:
        event.record_runtime_timing = True
    scene.events = list(events)
    return scene.events
