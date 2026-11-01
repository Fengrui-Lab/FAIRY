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
from .runtime import EpisodeState, PlanningFarm, PlanningTractor, SeasonPlanning, SeedMarket, SEEDS
from .validation import ExtensionValidation


class FullSeasonExtension(ExtensionValidation, Scenario):
    def __post_init__(self):
        super().__post_init__()
        self.start_time = datetime(2019, 5, 1, 7, tzinfo=ZoneInfo("Europe/Paris")).timestamp()
        self.duration = 213*86400
        self.expects_agent_harvest = True
        self.crop_backend = "wofost"

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("Fixed full-season scene has no overrides")
        self.init_and_populate_apps()
        self.build_events_flow()

    def initialize_world(self, *, crop, history, report, offers, seed_stock, fertilizer_kg, fuel_liters,
                         num_ridges, field_length_m, ridge_width_m, seed_budget_minor, rain_free_october=False):
        self.expected_crop = crop
        self.rotation = bool(history)
        self.production_budget_minor = seed_budget_minor
        episode = EpisodeState(season_history=deepcopy(history), soil_report=deepcopy(report),
            budget_initial_minor=seed_budget_minor, rain_free_october=rain_free_october)
        self.farm = PlanningFarm(selected_crop=None if self.rotation else crop, episode=episode,
            num_ridges=num_ridges, field_length_m=field_length_m, ridge_width_m=ridge_width_m,
            management_objective={"minimum_stored_grain_kg": .99*self.best_tested_yield_kg,
                "maximum_production_cost_minor": self.oracle_cost_minor,
                "currency": "DEMO", "minor_units_per_demo": 100} if self.rotation else None)
        self.weather, self.system, self.aui = WeatherApp(), SystemApp(), AgentUserInterface()
        self.sensor = SensorApp(self.farm, name="Sensor")
        self.irrigation = IrrigationApp(self.farm, self.weather, name="Irrigation")
        self.warehouse = WarehouseApp(WarehouseStock(
            deepcopy(seed_stock), pesticide_liters=0., fertilizer_kg=fertilizer_kg, fuel_liters=fuel_liters),
            storage_capacity_kg=20000., drying_capacity_kg_per_day=20000., max_storage_moisture_pct=14.)
        self.farm_environment = FarmEnvironment([FarmContext("field", self.farm, self.weather, self.sensor, self.irrigation)],
            self.weather, warehouse=self.warehouse, start_time=self.start_time, timezone_name="Europe/Paris")
        self.tractor = PlanningTractor(self.farm_environment, equipment=TractorEquipment(
            implements=(*DEFAULT_TRACTOR_IMPLEMENTS, "seeder"), ridging_implement="furrower"))
        self.planning = SeasonPlanning(self.farm)
        self.market = SeedMarket(self.farm, self.warehouse, offers, cost_reader=self.production_cost_minor)
        self.apps = [self.aui, self.farm, self.weather, self.sensor, self.warehouse, self.tractor, self.irrigation,
                     self.system, self.planning if self.rotation else self.market]
        self.system.attach_farm_environment(self.farm_environment)
        for app in self.apps:
            app.register_time_manager(self.farm_environment.time_manager)
            app.rng.seed(0)
        self.weather.set_weather(date="2019-05-01", temp_c=12., humidity_pct=65., wind_speed_ms=2.,
            rainfall_mm=0., solar_radiation=15/.0864, avg_soil_vwc=.26)
        self._initial_stock = deepcopy(self.warehouse.stock.seed_stock)
        self._initial_fertilizer = self.warehouse.stock.fertilizer_kg
        self._initial_fuel = self.warehouse.stock.fuel_liters + self.tractor._fuel_tank_l
        self.scenario_input += (" 初始仓库种子的补货机会成本：每1000粒玉米65 DEMO，每6000粒大豆45 DEMO；"
            f"采购现金按实付扣款；全季投入核算另受{self.production_budget_minor/100:.2f} DEMO总预算上限约束，不能重复计算采购。"
            "产量基准来自本规模重新测试的最佳候选，不是当前或旧场景的产量；有限集合最优不称田间全局最优。")
        if not self.rotation:
            self.scenario_input += (f" 本场安全入库目标至少{.99*self.best_tested_yield_kg:.6f}kg，"
                f"总核算成本不超过{self.oracle_cost_minor/100:.2f} DEMO。")
        self.additional_system_prompt = self.scenario_input

    def production_cost_minor(self):
        """Explicit DEMO prices: seed + fertilizer + consumed fuel + water + drying.

        50 cents/kg fertilizer product, 100 cents/L fuel, 2 cents/m3 water,
        10 cents/kg dried grain. Seed budget remains the procurement account;
        these additional costs are outcome accounting, not new budget debits.
        """
        fertilizer = self._initial_fertilizer-self.warehouse.stock.fertilizer_kg-self.tractor._fertilizer_spreader_kg
        fuel = self._initial_fuel-self.warehouse.stock.fuel_liters-self.tractor._fuel_tank_l
        water_m3 = self.farm._management_regime.irrigation_used_mm_total*self.farm.field_area_m2/1000
        dry_kg = sum(b.quantity_kg for b in self.warehouse.grain_batches.values() if b.dried)
        seed_cost = self.farm.episode.spent
        if self.rotation:
            seed_cost = 0.
            for seed, lot_count, lot_price in (("MAIZE_201", 1000, 6500), ("SOYBEAN_901", 6000, 4500)):
                in_hopper = self.tractor._seed_hopper if self.tractor.seed_type == seed else 0
                consumed = self._initial_stock[seed]-self.warehouse.stock.seed_stock[seed]-in_hopper
                seed_cost += lot_price*consumed/lot_count
        return round(seed_cost+50*fertilizer+100*fuel+2*water_m3+10*dry_kg)


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
