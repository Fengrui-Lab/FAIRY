"""World assembly for scenario-owned multi-farm WOFOST experiments.

This module defines no farming policy. Each leaf declares its fields, common
supplies, regional weather interventions, local pressure events and full plan.
Regional interventions are applied once to the pinned common weather BEFORE
any physics runs; the existing local event installer handles pressure only.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world import FarmWorldApp, WeatherApp, SensorApp
from fairy.apps.farm_world.equipment import DEFAULT_TRACTOR_IMPLEMENTS, TractorEquipment
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.irrigation_app import IrrigationApp
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.shared_drone_app import SharedDroneApp
from fairy.apps.farm_world.shared_robot_app import SharedRobotApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.system import SystemApp
from fairy.physics.weather_engine import WeatherGenerator, default_harbin_soybean_config
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.scenarios.wofost_events import DroughtEvent, WeatherWindowEvent, install_scenario_events
from fairy.scenarios.wofost_farm import load_official_reference

DATA = Path(__file__).resolve().parents[1] / 'physics/data/wofost/research'


@dataclass(frozen=True)
class WofostField:
    farm_id: str
    crop_name: str
    seed_type: str
    variety_name: str
    sowing_date: date
    num_ridges: int
    field_length_m: float
    ridge_width_m: float
    rows_per_ridge: int
    density_plants_m2: float
    irrigation_quota_mm: float
    fertilizer_quota_kg: float
    initial_vwc: float = .26
    initial_soil_temperature_c: float = 12.
    soil_depth_m: float = 1.2
    wilting_point_vwc: float = .10
    field_capacity_vwc: float = .30
    saturation_vwc: float = .45
    infiltration_mm_day: float = 50.
    initial_available_n_kg_ha: float = 50.
    base_soil_n_kg_ha: float = 50.
    soil_n_mineralization_fraction: float = .025
    base_fertilizer_kg: float = 0.
    active_ingredient_cap_kg: float | None = None
    management_regime: str = 'conventional'

    @property
    def seed_spacing_cm(self):
        return 100 * self.rows_per_ridge / (self.ridge_width_m * self.density_plants_m2)

    @property
    def area_ha(self):
        return self.num_ridges * self.field_length_m * self.ridge_width_m / 10000

    def __post_init__(self):
        if self.crop_name not in ('soybean', 'maize') or self.num_ridges < 1:
            raise ValueError('Declare a supported crop and positive field size')
        if not 0 <= self.wilting_point_vwc < self.initial_vwc <= self.field_capacity_vwc < self.saturation_vwc <= 1:
            raise ValueError('Inconsistent initial water and hydraulic limits')
        if min(self.field_length_m, self.ridge_width_m, self.rows_per_ridge, self.density_plants_m2) <= 0:
            raise ValueError('Geometry and density must be positive')


def regional_reference(reference_id):
    if reference_id != 'thionville':
        row, daily = load_official_reference(reference_id)
        return row, daily, {('soybean', row['variety'], 'SOYBEAN_' + row['variety'].split('_')[-1])}
    directory = DATA / 'thionville_nasa2019_v1'
    manifest = json.loads((directory / 'manifest.json').read_text())
    for path, digest in ((manifest['weather_path'], manifest['weather_sha256']),
                         (manifest['raw_path'], manifest['raw_sha256']),
                         *((r['crop_path'], r['crop_sha256']) for r in manifest['crop_references'])):
        if hashlib.sha256((directory / path).read_bytes()).hexdigest() != digest:
            raise ValueError('Pinned regional input checksum mismatch: ' + path)
    return manifest, json.loads((directory / manifest['weather_path']).read_text())['daily'], {
        (r['crop_name'], r['variety_name'], r['seed_type']) for r in manifest['crop_references']}


class WofostMultiFarmScenario(Scenario):
    """Independent native fields; one clock/weather/warehouse and mobile fleet."""
    FARMS: tuple[WofostField, ...]
    SUPPLIES: WarehouseStock
    REGIONAL_EVENTS = ()
    FIELD_EVENTS = ()
    END_DATE = date(2019, 11, 15)
    timezone_name = 'Europe/Paris'
    INITIAL_TRACTOR_FUEL_L = 100.
    STORAGE_CAPACITY_KG = 150000.
    DRYING_CAPACITY_KG_PER_DAY = 150000.

    def __post_init__(self):
        super().__post_init__()
        if self.crop_backend_options:
            raise ValueError('Each field declares its fixed native configuration')
        if len(self.FARMS) < 2 or len({f.farm_id for f in self.FARMS}) != len(self.FARMS):
            raise ValueError('Multi-farm scenes need distinct field IDs')
        self.crop_backend = 'wofost'
        self.simulation_timezone = ZoneInfo(self.timezone_name)
        self.start_time = datetime.combine(self.START_DATE, time(7), self.simulation_timezone).timestamp()
        self.duration = datetime.combine(self.END_DATE, time(18), self.simulation_timezone).timestamp() - self.start_time
        self.queue_based_loop, self.time_increment_in_seconds = True, 60
        if not self.scenario_input:
            fields = '\n'.join(f'{f.farm_id}: {f.crop_name}/{f.seed_type}/{f.variety_name}，{f.num_ridges}垄，'
                f'{f.field_length_m:g}×{f.ridge_width_m:g}m，每垄{f.rows_per_ridge}行，{f.area_ha:.5f}ha；'
                f'计划{f.sowing_date}播种，密度{f.density_plants_m2:g}株/m²，株距{f.seed_spacing_cm:.9f}cm；'
                f'土层{f.soil_depth_m:g}m，初始VWC{f.initial_vwc:g}、土温{f.initial_soil_temperature_c:g}°C，'
                f'萎蔫/田持/饱和{f.wilting_point_vwc:g}/{f.field_capacity_vwc:g}/{f.saturation_vwc:g}，'
                f'入渗{f.infiltration_mm_day:g}mm/day；有效/储备N={f.initial_available_n_kg_ha:g}/{f.base_soil_n_kg_ha:g}kgN/ha，'
                f'日矿化比例{f.soil_n_mineralization_fraction:g}；水额{f.irrigation_quota_mm:g}mm，'
                f'肥料产品额{f.fertilizer_quota_kg:g}kg，化学活性成分额{f.active_ingredient_cap_kg}kg。' for f in self.FARMS)
            self.scenario_input = self.BRIEFING + '\n\n' + fields + '\n共有库存：' + str(asdict(self.SUPPLIES)) + (
                '\n一个Tractor/Drone/Robot共用油箱、电池和载荷，移动作业须指定farm_id；固定Sensor和Irrigation按场命名。'
                '各场水额不能转借，5mm/h；仓库只有一份种子、燃油、肥料和化学工作液。'
                '拖拉机初始100L油、其他载荷空；种箱30万粒、粮箱2t、播收每趟最多4垄、施肥施药最多10垄。'
                '机器人一次最多实际8垄、内部每4垄观测；样本不等于全田，核对covered_ridges。'
                '机器人5%电/垄、充电1h；无人机5m/s、7垄/航带、1%电/垄、保留20%、充电30min。'
                '共同时间推进一次，两场同时生长；作业、充电和等待都有真实耗时。'
                '土壤/投入/天气事件是模型场景设定；官方作物原始参数不覆盖，TDWI按实际密度相对适配基准初始化。'
                '大豆基准40株/m²，玉米6.6667株/m²，均不称田间最优。肥料46%N、有效回收0.7。'
                '病虫草是FAIRY外部耦合，仅大豆支持；玉米不安排植保题。营养及部分表层水分是代理，不能据此直接确诊缺N。'
                '传感器→无人机定位→机器人定点确认；共享天气为2019固定NASA POWER，人工变更全区一致且可在预报中看见。'
                '大豆R8且粮水≤18%，玉米MATURE且≤25%，无雨且土壤可通行才收；换场前卸清并保留来源。'
                '分别干燥到大豆13%、玉米14%并安全入库。仓库容量和每日干燥容量各150t，干燥为即时抽象，不制造虚构时间瓶颈。')

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError('This fixed scenario has no setup overrides')
        self.init_and_populate_apps()
        self.build_events_flow()

    def init_and_populate_apps(self):
        self.reference, daily, official = regional_reference(self.REFERENCE_ID)
        if any((f.crop_name, f.variety_name, f.seed_type) not in official for f in self.FARMS):
            raise ValueError('Field cultivar does not match the pinned official regional reference')
        if date.fromisoformat(daily[0]['date']) > self.START_DATE or date.fromisoformat(daily[-1]['date']) < self.END_DATE + timedelta(days=7):
            raise ValueError('Pinned weather does not cover season and forecasts')
        changed = {date.fromisoformat(r['date']): dict(r) for r in daily}
        changes, occupied = [], set()
        for event in self.REGIONAL_EVENTS:
            if not isinstance(event, (DroughtEvent, WeatherWindowEvent)) or event.farm_id != 'region':
                raise ValueError('Regional weather events explicitly target region')
            day = event.start
            while day < event.end:
                r = changed[day]
                updates = {'rain_mm': r['rain_mm'] * event.rain_multiplier} if isinstance(event, DroughtEvent) else {
                    k: v for k, v in [('rain_mm', event.rain_mm), ('wind_2m_m_s', event.wind_ms)] if v is not None}
                for key, value in updates.items():
                    if (day, key) in occupied:
                        raise ValueError('Overlapping regional weather declarations')
                    occupied.add((day, key))
                    changes.append({'event_id': event.event_id, 'day': str(day), 'field': key, 'before': r[key], 'after': value})
                    r[key] = value
                day += timedelta(days=1)
        generator = WeatherGenerator(default_harbin_soybean_config(), seed=0)
        for day, r in changed.items():
            generator.set_day_override(day, air_temp_min_c=r['tmin_c'], air_temp_max_c=r['tmax_c'],
                air_temp_mean_c=(r['tmin_c']+r['tmax_c'])/2, rain_mm=r['rain_mm'], wind_ms=r['wind_2m_m_s'],
                solar_rad_mj_m2=r['shortwave_mj_m2_day'], relative_humidity_pct=r['relative_humidity_pct'],
                weather_tags=['pinned_nasa_power', *[e.event_id for e in self.REGIONAL_EVENTS if e.start <= day < e.end]])
        self.regional_weather_changes = changes
        self.aui, self.weather, self.system = AgentUserInterface(), WeatherApp(), SystemApp()
        self.warehouse = WarehouseApp(deepcopy(self.SUPPLIES), storage_capacity_kg=self.STORAGE_CAPACITY_KG,
            drying_capacity_kg_per_day=self.DRYING_CAPACITY_KG_PER_DAY, max_storage_moisture_pct=14.)
        self.farms, self.sensors, self.irrigations = {}, {}, {}
        contexts = []
        for f in self.FARMS:
            prep = ('level', 'base_fertilize', 'form_ridges') if f.base_fertilizer_kg else ('level', 'form_ridges')
            farm = FarmWorldApp(name=f.farm_id + '_Farm', farm_id=f.farm_id, num_ridges=f.num_ridges,
                field_length_m=f.field_length_m, ridge_width_m=f.ridge_width_m, rows_per_ridge=f.rows_per_ridge,
                crop_type=f.crop_name, required_field_preparation_ops=prep)
            sensor = SensorApp(farm, name=f.farm_id + '_Sensor')
            irrigation = IrrigationApp(farm, self.weather, name=f.farm_id + '_Irrigation')
            self.farms[f.farm_id], self.sensors[f.farm_id], self.irrigations[f.farm_id] = farm, sensor, irrigation
            contexts.append(FarmContext(f.farm_id, farm, self.weather, sensor, irrigation))
        self.farm_environment = FarmEnvironment(contexts, self.weather, warehouse=self.warehouse,
            start_time=self.start_time, timezone_name=self.timezone_name)
        location = self.reference['location']
        for f in self.FARMS:
            farm = self.farms[f.farm_id]
            farm._sim_date = self.START_DATE.isoformat()
            farm.set_season_phase('full_season')
            for ridge in farm._ridges:
                ridge.soil_vwc, ridge.soil_temp_c, ridge.stand_fraction = f.initial_vwc, f.initial_soil_temperature_c, 1.
                ridge.pest_pressure = ridge.pest_pressure_base = ridge.disease_pressure = ridge.disease_pressure_base = 0.
            p = farm.physics
            p.latitude_deg = location['latitude']
            p.soil.params = replace(p.soil.params, root_depth_m=f.soil_depth_m,
                wilting_point_vwc=f.wilting_point_vwc, field_capacity_vwc=f.field_capacity_vwc,
                saturation_vwc=f.saturation_vwc, max_infiltration_mm_day=f.infiltration_mm_day, rainfall_capture_efficiency=1.)
            p.biotic.params = replace(p.biotic.params, recruitment_fraction=0.)
            p.biotic.set_pressure(list(range(f.num_ridges)), weed_pressure=0., insect_pressure=0., disease_pressure=0.)
            p.weather_generator = generator
            p.scenario_metadata = {'daily_settlement': 'completed_calendar_day', 'reference_id': self.REFERENCE_ID,
                'weather_sha256': self.reference['weather_sha256'], 'parameter_overrides': {}, 'field_trial_validation': False,
                'regional_weather_events': json.loads(json.dumps([asdict(e) for e in self.REGIONAL_EVENTS], default=str)), 'regional_weather_changes': deepcopy(changes),
                'soil_source': 'Explicit scenario assumptions', 'biotic_source': 'FAIRY external soybean coupling, not native pathology'}
            farm.configure_management_regime(irrigation_quota_mm_total=f.irrigation_quota_mm,
                fertilizer_quota_kg=f.fertilizer_quota_kg, active_ingredient_cap_kg=f.active_ingredient_cap_kg,
                regime=f.management_regime, max_machine_passes=None)
            farm.configure_crop_backend('wofost', crop_name=f.crop_name, variety_name=f.variety_name,
                cultivar_map={f.seed_type: f.variety_name}, require_explicit_cultivar_parameters=True,
                latitude_deg=location['latitude'], longitude_deg=location['longitude'], elevation_m=location['elevation_m'],
                reference_density_plants_m2=40. if f.crop_name == 'soybean' else 1/(.75*.20),
                initial_available_n_kg_ha=f.initial_available_n_kg_ha, base_soil_n_kg_ha=f.base_soil_n_kg_ha,
                soil_n_mineralization_fraction=f.soil_n_mineralization_fraction, fertilizer_n_fraction=.46,
                fertilizer_n_recovery=.7, external_biotic_coupling=f.crop_name == 'soybean')
            if f.crop_name == 'soybean':
                p.yield_recovery.params.grain_moisture_mode = 'soybean_equilibrium'
            farm.configure_postharvest_market(market_moisture_pct=13. if f.crop_name == 'soybean' else 14.,
                max_storage_moisture_pct=13.5 if f.crop_name == 'soybean' else 14., storage_capacity_kg=self.STORAGE_CAPACITY_KG)
            farm.crop_definition = replace(farm.crop_definition,
                planting_rules=replace(farm.crop_definition.planting_rules, required_implement=f.crop_name + '_planter'),
                harvest_rules=replace(farm.crop_definition.harvest_rules, required_implement='harvester' if f.crop_name == 'soybean' else 'maize_header'))
            p.observation_model.rng.seed(int.from_bytes(hashlib.sha256(f'{self.seed}:{f.farm_id}:observations'.encode()).digest()[:8], 'big'))
        self.tractor = SharedTractorApp(self.farm_environment, name='Tractor', equipment=TractorEquipment(
            implements=(*DEFAULT_TRACTOR_IMPLEMENTS, 'soybean_planter', 'maize_planter', 'maize_header'), ridging_implement='furrower'))
        self.tractor._fuel_tank_l = self.INITIAL_TRACTOR_FUEL_L
        self.drone = SharedDroneApp(self.farm_environment, name='Drone')
        self.robot = SharedRobotApp(self.farm_environment, name='Robot')
        self.system.attach_farm_environment(self.farm_environment)
        self.shared_equipment = [self.tractor, self.drone, self.robot]
        self.apps = [self.aui, *self.farms.values(), self.weather, self.warehouse, *self.sensors.values(),
                     *self.irrigations.values(), *self.shared_equipment, self.system]
        for app in self.apps:
            app.register_time_manager(self.farm_environment.time_manager)
            app.seed = int.from_bytes(hashlib.sha256(f'{self.seed}:{app.name}'.encode()).digest()[:8], 'big')
            app.rng.seed(app.seed)
        self._initial_stock = deepcopy(self.warehouse.stock)
        install_scenario_events(self, self.FIELD_EVENTS)
        from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs
        _build_weather_inputs(self.weather, self.START_DATE, physics=next(iter(self.farms.values())).physics, advance_weather=False)

    def validate(self, env=None):
        self.farm_environment.sync()
        errors, totals, used_seeds = [], {}, Counter()
        batches = list(self.warehouse.grain_batches.values())
        for f in self.FARMS:
            farm = self.farms[f.farm_id]
            runs = farm.physics.crop_backend._runs
            own = [b for b in batches if b.origin_farm_id == f.farm_id]
            if set(runs) != set(range(f.num_ridges)) or any(float(r.pcse.get('DVS') or 0) < 2 for r in runs.values()):
                errors.append(f.farm_id + ': native maturity incomplete')
            if not all(r.harvested for r in farm._ridges) or Counter(r for b in own for r in b.ridge_ids) != Counter(range(f.num_ridges)):
                errors.append(f.farm_id + ': missing/duplicate harvested or stored ridges')
            if any(b.status != 'stored' or b.quantity_kg <= 0 or b.crop_id != f.crop_name or b.cultivar_ids != [f.seed_type]
                   or b.moisture_pct is None or b.moisture_pct > farm._postharvest_market.max_storage_moisture_pct for b in own):
                errors.append(f.farm_id + ': unsafe/wrong-source grain')
            regime = farm._management_regime
            for used, cap in ((regime.irrigation_used_mm_total, regime.irrigation_quota_mm_total),
                              (regime.fertilizer_used_kg, regime.fertilizer_quota_kg),
                              (regime.active_ingredient_used_kg, regime.active_ingredient_cap_kg)):
                if cap is not None and used > cap + 1e-8:
                    errors.append(f.farm_id + ': quota exceeded')
            planted = [op for op in self.tractor.get_state()['operation_log'] if op['operation'] == 'plant_seeds' and op.get('farm_id') == f.farm_id]
            used_seeds[f.seed_type] += sum(op['seeds_used'] for op in planted)
            totals[f.farm_id] = {'area_ha': f.area_ha, 'stored_grain_kg': sum(b.quantity_kg for b in own),
                'native_dm_kg': sum(float(r.pcse.get('TWSO') or 0) * f.area_ha/f.num_ridges for r in runs.values()),
                'irrigation_mm': regime.irrigation_used_mm_total, 'fertilizer_kg': regime.fertilizer_used_kg,
                'active_ingredient_kg': regime.active_ingredient_used_kg}
        for seed, initial in self._initial_stock.seed_stock.items():
            if initial != self.warehouse.stock.seed_stock[seed] + used_seeds[seed]:
                errors.append(seed + ': seed accounting mismatch')
        machine = self.tractor.get_state()
        if machine['grain_bin_kg'] or machine['seed_hopper']:
            errors.append('Equipment retains grain/seeds')
        used_fertilizer = sum(f._management_regime.fertilizer_used_kg for f in self.farms.values())
        used_chemical = sum(f._management_regime.active_ingredient_used_kg for f in self.farms.values()) * 1000
        if abs(self._initial_stock.fertilizer_kg - self.warehouse.stock.fertilizer_kg - machine['fertilizer_spreader_kg'] - used_fertilizer) > 1e-5:
            errors.append('Shared fertilizer conservation failed')
        if abs(self._initial_stock.pesticide_liters - self.warehouse.stock.pesticide_liters - machine['pesticide_tank_l'] - machine['fungicide_tank_l'] - used_chemical) > 1e-5:
            errors.append('Shared chemical conservation failed')
        return ScenarioValidationResult(success=not errors, message='; '.join(errors) if errors else 'All farms harvested and safely stored with independent quotas and common stock conserved.', metadata=totals)
