"""Formal WOFOST farm construction from pinned official inputs.

Each scene declares FarmDefinition, events and its complete Oracle policy in
its own module. This module only builds the world shared by Agent, Oracle and
replay. Soil and initial nutrient values are explicit model assumptions; the
reference data bundle is not a measured field-trial replication.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
import hashlib
import json
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo

from fairy.scenarios.scenario import Scenario

DATA = Path(__file__).resolve().parents[1] / 'physics/data/wofost/research/official_soybean_nasa2019_v1'


def load_official_reference(reference_id):
    manifest = json.loads((DATA / 'manifest.json').read_text())
    row = next((r for r in manifest['rows'] if r['id'] == reference_id), None)
    if row is None:
        raise ValueError(f"Unknown official reference {reference_id!r}")
    for path_key, hash_key in [('weather_path', 'weather_sha256'), ('source_path', 'source_sha256')]:
        if hashlib.sha256((DATA / row[path_key]).read_bytes()).hexdigest() != row[hash_key]:
            raise ValueError(f"Reference integrity check failed: {row[path_key]}")
    crop = DATA / manifest['crop_source']['path']
    if hashlib.sha256(crop.read_bytes()).hexdigest() != manifest['crop_source']['sha256']:
        raise ValueError('Official crop parameter checksum mismatch')
    weather = json.loads((DATA / row['weather_path']).read_text())
    return row, weather['daily']


@dataclass(frozen=True)
class FarmDefinition:
    reference_id: str
    seed_type: str
    timezone_name: str
    sowing_date: date
    end_date: date
    farm_id: str = 'farm'
    num_ridges: int = 24
    field_length_m: float = 268.
    ridge_width_m: float = 1.1
    initial_vwc: float = .26
    initial_soil_temperature_c: float = 12.
    soil_depth_m: float = 1.2
    wilting_point_vwc: float = .10
    field_capacity_vwc: float = .30
    saturation_vwc: float = .45
    infiltration_mm_day: float = 50.
    initial_available_n_kg_ha: float = 50.
    base_soil_n_kg_ha: float = 50.
    base_fertilizer_kg: float = 20.
    seed_stock: int = 1_000_000
    warehouse_fertilizer_kg: float = 300.
    warehouse_pesticide_l: float = 500.
    warehouse_fuel_l: float = 1000.
    tractor_fuel_l: float = 100.
    irrigation_quota_mm: float | None = None
    active_ingredient_cap_kg: float | None = None
    max_machine_passes: int | None = None
    management_regime: str = 'conventional'
    max_insecticide_applications: int | None = None
    max_fungicide_applications: int | None = None
    max_mechanical_weed_ridges: int | None = None
    external_biotic_coupling: bool = True
    grain_moisture_mode: str = 'soybean_equilibrium'
    planting_density_plants_m2: float = 40.
    required_field_preparation_ops: tuple[str, ...] = ('level', 'base_fertilize', 'form_ridges')

    def __post_init__(self):
        from fairy.apps.farm_world.farm_world_app import validate_required_field_preparation_ops
        object.__setattr__(self, 'required_field_preparation_ops',
                           validate_required_field_preparation_ops(self.required_field_preparation_ops))
        if not 0 <= self.wilting_point_vwc < self.initial_vwc <= self.field_capacity_vwc < self.saturation_vwc <= 1:
            raise ValueError('Initial soil moisture and hydraulic limits are inconsistent')
        if self.sowing_date >= self.end_date or self.num_ridges < 1:
            raise ValueError('Farm needs a valid season and at least one physical ridge')
        if (isinstance(self.planting_density_plants_m2, bool)
                or not isfinite(self.planting_density_plants_m2)
                or self.planting_density_plants_m2 <= 0):
            raise ValueError('The explicit target planting density must be finite and positive')


class WofostFarmScenario(Scenario):
    """A formal scene whose ordinary runtime always constructs native WOFOST."""
    WORLD: FarmDefinition
    DETAILED_BRIEFING: str = ''

    def __post_init__(self):
        super().__post_init__()
        from fairy.apps.farm_world.crop_profiles import OFFICIAL_WOFOST_SEED_VARIETIES
        world = self.WORLD
        reference, daily = load_official_reference(world.reference_id)
        if OFFICIAL_WOFOST_SEED_VARIETIES.get(world.seed_type) != reference['variety']:
            raise ValueError('The scene seed does not match its official reference variety')
        self.reference, self.daily_weather = reference, daily
        self.simulation_timezone = ZoneInfo(world.timezone_name)
        self.timezone_name = world.timezone_name
        self.start_time = datetime.combine(world.sowing_date, time(7), self.simulation_timezone).timestamp()
        end = datetime.combine(world.end_date, time(7), self.simulation_timezone).timestamp()
        self.duration = end - self.start_time
        first, last = date.fromisoformat(daily[0]['date']), date.fromisoformat(daily[-1]['date'])
        if first > world.sowing_date or last < world.end_date + timedelta(days=7):
            raise ValueError('Pinned daily weather must cover the season and seven forecast days')
        options = {
            'variety_name': reference['variety'],
            'cultivar_map': {world.seed_type: reference['variety']},
            'require_explicit_cultivar_parameters': True,
            # Adapter normalization: the actual WORLD density is sown by the
            # explicit workflow; TDWI scales from this fixed biomass reference.
            'reference_density_plants_m2': 40.,
            'latitude_deg': reference['location']['latitude'],
            'longitude_deg': reference['location']['longitude'],
            'elevation_m': reference['location']['elevation_m'],
            'initial_available_n_kg_ha': world.initial_available_n_kg_ha,
            'base_soil_n_kg_ha': world.base_soil_n_kg_ha,
            'external_biotic_coupling': world.external_biotic_coupling,
        }
        if self.crop_backend_options and self.crop_backend_options != options:
            raise ValueError('This fixed reference scene declares its native configuration in WORLD')
        self.crop_backend, self.crop_backend_options = 'wofost', options
        self.queue_based_loop, self.time_increment_in_seconds = True, 60

    def init_and_populate_apps(self):
        from fairy.apps.agent_user_interface import AgentUserInterface
        from fairy.apps.farm_world import FarmWorldApp, WeatherApp, SensorApp, RobotApp, TractorApp
        from fairy.apps.farm_world.field_ops_app import FieldOpsApp
        from fairy.apps.system import SystemApp
        from fairy.physics.weather_engine import WeatherGenerator, default_harbin_soybean_config
        world = self.WORLD
        farm = FarmWorldApp(farm_id=world.farm_id, num_ridges=world.num_ridges,
            field_length_m=world.field_length_m, ridge_width_m=world.ridge_width_m,
            required_field_preparation_ops=world.required_field_preparation_ops)
        weather, system = WeatherApp(), SystemApp()
        farm.simulation_timezone = weather.simulation_timezone = self.simulation_timezone
        farm.attach_weather_app(weather)
        farm.attach_system_app(system)
        farm._sim_date = world.sowing_date.isoformat()
        farm.set_season_phase('full_season')
        stock = farm._inventory
        stock.seed_stock = {world.seed_type: world.seed_stock}
        stock.fertilizer_kg, stock.pesticide_liters, stock.fuel_liters = (
            world.warehouse_fertilizer_kg, world.warehouse_pesticide_l, world.warehouse_fuel_l)
        farm.configure_management_regime(irrigation_quota_mm_total=world.irrigation_quota_mm,
            active_ingredient_cap_kg=world.active_ingredient_cap_kg,
            max_machine_passes=world.max_machine_passes, regime=world.management_regime,
            max_insecticide_applications=world.max_insecticide_applications,
            max_fungicide_applications=world.max_fungicide_applications,
            max_mechanical_weed_ridges=world.max_mechanical_weed_ridges)
        physics = farm.physics
        physics.latitude_deg = self.reference['location']['latitude']
        physics.soil.params = replace(physics.soil.params,
            root_depth_m=world.soil_depth_m, wilting_point_vwc=world.wilting_point_vwc,
            field_capacity_vwc=world.field_capacity_vwc, saturation_vwc=world.saturation_vwc,
            max_infiltration_mm_day=world.infiltration_mm_day, rainfall_capture_efficiency=1.)
        physics.biotic.params = replace(physics.biotic.params, recruitment_fraction=0.)
        physics.yield_recovery.params.grain_moisture_mode = world.grain_moisture_mode
        physics.biotic.set_pressure(list(range(world.num_ridges)), weed_pressure=0.,
            insect_pressure=0., disease_pressure=0.)
        physics.scenario_metadata = {
            'daily_settlement': 'completed_calendar_day',
            'reference_id': world.reference_id, 'variety': self.reference['variety'],
            'weather_sha256': self.reference['weather_sha256'],
            'native_parameters_sha256': self.reference['native_parameters_sha256'],
            'parameter_overrides': {}, 'field_trial_validation': False,
            'soil_source': 'Explicit model-reference assumptions, not measured trial soil',
            'biotic_source': 'Declared FAIRY events and existing engineering coupling, not native WOFOST pathology',
            'grain_moisture_mode': world.grain_moisture_mode,
            'planting_density_target_plants_m2': world.planting_density_plants_m2,
            'density_initialization': 'Official TDWI scaled by realized density/40 and stand. The40plants/m² baseline is an adapter normalization, not an official or field-validated optimum.',
        }
        generator = WeatherGenerator(default_harbin_soybean_config(), seed=0)
        for row in self.daily_weather:
            generator.set_day_override(date.fromisoformat(row['date']),
                air_temp_mean_c=(row['tmin_c']+row['tmax_c'])/2,
                air_temp_min_c=row['tmin_c'], air_temp_max_c=row['tmax_c'],
                rain_mm=row['rain_mm'], wind_ms=row['wind_2m_m_s'],
                solar_rad_mj_m2=row['shortwave_mj_m2_day'],
                relative_humidity_pct=row['relative_humidity_pct'],
                weather_tags=['pinned_public_nasa_power'])
        physics.weather_generator = generator
        for ridge in farm._ridges:
            ridge.soil_vwc, ridge.soil_temp_c = world.initial_vwc, world.initial_soil_temperature_c
            ridge.pest_pressure = ridge.pest_pressure_base = 0.
            ridge.disease_pressure = ridge.disease_pressure_base = 0.
            ridge.stand_fraction = 1.
        tractor = TractorApp(farm, weather)
        tractor._fuel_tank_l = world.tractor_fuel_l
        self.apps = [AgentUserInterface(), farm, weather, SensorApp(farm),
            RobotApp(farm, weather, name='Robot0'), tractor, FieldOpsApp(farm, weather), system]
        # Use exactly the same pinned day for the initial weather and forecast.
        from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs
        _build_weather_inputs(weather, world.sowing_date, physics=physics, advance_weather=False)

    def reference_briefing(self):
        world = self.WORLD
        briefing = (f"{self.DESCRIPTION}\n地点 {self.reference['location']['name']}，"
            f"官方品种 {self.reference['variety']}（种子 {world.seed_type}）。"
            f"季节 {world.sowing_date} 至 {world.end_date}，{world.timezone_name}。"
            f"{world.num_ridges} 垄，每垄 {world.field_length_m}×{world.ridge_width_m} m，"
            f"合计 {world.num_ridges*world.field_length_m*world.ridge_width_m/10000:.4f} ha。"
            f"目标播种密度 {world.planting_density_plants_m2:g} 株/m²；"
            "此目标依据当前模型的密度对照，官方TDWI基准按实际株数初始化。"
            "按观测管理，确认成熟及可作业后收获、卸粮、必要干燥并安全入库。"
            "营养读数提示：当前nutrient_index是幼苗叶面积生长相关代理，花期不可仅据此低值判断需要追氮。"
            "天气为固定公开网格气象，土壤是本场景明确假设；该场景不声称复现原田间试验产量。")
        # Keep each scene's public instructions in the first agent message.
        # The Oracle calendar and hidden disturbances are not task context.
        if self.detailed_briefing is True and self.DETAILED_BRIEFING:
            return briefing + '\n\n' + self.DETAILED_BRIEFING
        return briefing

    def validate(self, environment):
        """Validate completion and resource accounting, independently of policy choices."""
        from fairy.apps.farm_world import FarmWorldApp, TractorApp
        from fairy.scenarios.validation_result import ScenarioValidationResult
        farm, tractor = self.get_typed_app(FarmWorldApp), self.get_typed_app(TractorApp)
        physics = farm.physics
        backend = physics.crop_backend
        errors = []
        if physics.crop_backend_name != 'wofost' or backend is None:
            errors.append('The formal world is not running native WOFOST')
        if backend is not None and (len(backend._runs) != farm.num_ridges
                or any(float(run.pcse.get('DVS') or 0) < 2 for run in backend._runs.values())):
            errors.append('Some native crops have not reached maturity')
        if not all(r.harvested for r in farm._ridges):
            errors.append('Some physical ridges have not been harvested')
        if farm._inventory.harvest_grain_kg > .01 or tractor._grain_bin_kg > .01:
            errors.append('Grain remains outside long-term storage')
        if farm._inventory.warehouse_grain_kg <= 0:
            errors.append('No grain has been stored')
        stored_ridges = set()
        for step in environment.workflow.dag.values():
            content = step.content or {}
            if isinstance(content, dict) and content.get('error'):
                errors.append(f'Tool failed: {step.name}')
            if (step.tool_name or '').endswith('__store_grain') and content.get('moved_kg', 0) > 0:
                stored_ridges.update(content.get('batch_ridge_ids', []))
                if content.get('warning') or content.get('storage_grain_moisture_pct', 100) > 13.5:
                    errors.append(f'Unsafe storage batch: {step.name}')
        if stored_ridges != set(range(farm.num_ridges)):
            errors.append('Safe-storage receipts do not cover every harvested ridge')
        regime = farm._management_regime
        for cap, used in [('irrigation_quota_mm_total', 'irrigation_used_mm_total'),
                          ('active_ingredient_cap_kg', 'active_ingredient_used_kg'),
                          ('max_machine_passes', 'machine_passes_used')]:
            limit, amount = getattr(regime, cap), getattr(regime, used)
            if limit is not None and amount > limit + 1e-7:
                errors.append(f'Resource allowance exceeded: {used}')
        if environment.time_manager.time() > self.start_time + self.duration:
            errors.append('Scene deadline exceeded')
        return ScenarioValidationResult(success=not errors,
            message='; '.join(errors) if errors else 'Native crops matured and all grain was legally harvested and safely stored.',
            metadata={'errors': errors, 'reference_id': self.WORLD.reference_id,
                'native_variety': self.reference['variety'], 'harvested_ridges': sum(r.harvested for r in farm._ridges),
                'warehouse_grain_kg': farm._inventory.warehouse_grain_kg,
                'field_area_m2': farm.field_area_m2, 'resource_usage': regime.to_dict(),
                'field_trial_validation': False})


# Compatibility for the model-parity tests and preserved calibration records.
WofostReferenceScenario = WofostFarmScenario
