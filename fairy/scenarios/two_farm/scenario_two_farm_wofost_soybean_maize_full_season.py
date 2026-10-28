"""相邻大豆/玉米两场的原生 WOFOST 全季任务。

本文件完整定义世界、资源归属、详细任务、静态 Oracle 与验收。
两场位于法国北部/卢森堡边境附近，使用同一份固定 NASA POWER 2019 天气：
Soybean_901 的官方适用地区为法国北部，Grain_maize_201 为卢森堡/德国。
官方作物参数不改；此处土壤、投入和管理是模型场景假设，不宣称田间校准。
各场64垄，长268m；大豆1.1m双行共1.88672ha，玉米0.75m单行共1.28640ha。
两种作物各自建立64个PCSE模型，只有时间、天气、仓库和移动设备共用。

运行：python -m fairy.cli -s scenario_two_farm_wofost_soybean_maize_full_season \
  --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/wofost-two-farm
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world.equipment import DEFAULT_TRACTOR_IMPLEMENTS, TractorEquipment
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.irrigation_app import IrrigationApp
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.apps.farm_world.shared_drone_app import SharedDroneApp
from fairy.apps.farm_world.shared_robot_app import SharedRobotApp
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.warehouse_app import WarehouseApp, WarehouseStock
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.system import SystemApp
from fairy.physics.weather_engine import WeatherGenerator, default_harbin_soybean_config
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.types import EventRegisterer


SCENARIO_ID = "scenario_two_farm_wofost_soybean_maize_full_season"
DATA = Path(__file__).resolve().parents[2] / "physics/data/wofost/research/thionville_nasa2019_v1"
NUM_RIDGES = 64
FIELD_LENGTH_M = 268.0
SOYBEAN_CULTIVAR = "SOYBEAN_901"
MAIZE_CULTIVAR = "MAIZE_201"
SOYBEAN_SPACING_CM = 100 * 2 / (1.1 * 40)  # 40株/m²；模型目标，不称田间最优。
MAIZE_SPACING_CM = 20.0                    # 单行0.75m×0.20m，约6.67株/m²。
# Measured waits to the written 07:00 local calendar, after the preceding real
# machine/inspection work. These are ordinary System tool arguments, not yield
# parameters. They keep Oracle and JSON replay on the same calendar. Recheck
# them if geometry, machinery speeds or the preceding workflow are changed.
ORACLE_WAIT_SECONDS = {
    "wait_establishment": 2647109,       # 06-01
    "wait_maize_nutrition": 769080,      # 06-10
    "wait_maize_july_01": 1810270,       # 07-01
    "wait_soybean_july_05": 237300,      # 07-05
    "wait_maize_july_15": 755700,        # 07-15
    "wait_soybean_july_20": 323700,      # 07-20
    "wait_maize_august_01": 928500,      # 08-01
    "wait_soybean_august_05": 237300,    # 08-05
    "wait_maize_august_15": 755700,      # 08-15
    "wait_late_fill": 323700,           # 08-20
    "wait_soybean_harvest": 1728000,    # 09-09
    "wait_maize_harvest": 943184,       # 09-20
}
FARMING_PLAN = (
    "5月1日无雨窗口依次播大豆、玉米；共享拖拉机逐场完成准备、换种和播种。",
    "苗期先看固定传感器，再无人机巡田，最后机器人抽查；样本不代表全田地面覆盖。",
    "玉米施基肥并在营养期追氮，大豆不例行追氮；两场分别判断营养与水分。",
    "生殖生长期安排整轮补水和次日复核，依据根区水分/预报，避免每日小水。",
    "两种作物分别确认成熟、无雨、通行性和籽粒水分，再按来源批次收储。",
)

BASIC_BRIEFING = """
管理法国北部/卢森堡边境附近相邻的 soybean_field 与 maize_field 两块农场，完成2019年全季管理和安全收储。
大豆SOYBEAN_901（官方Soybean_901），玉米MAIZE_201（官方Grain_maize_201）；两场都使用原生WOFOST。
每场64垄、长268m；大豆垄宽1.1m、双行、1.88672ha；玉米0.75m、单行、1.28640ha。
大豆目标40株/m²，株距约4.545cm；玉米目标约6.67株/m²，株距20cm。播深分别4cm、5cm。
固定传感器和灌溉各场独立；Warehouse、Tractor、Drone、Robot共用。田间移动工具必须指定farm_id。
按实际观测安排两种作物的播种、水肥与独立收获窗口；分别保留作物/来源/垄号并安全入库。
""".strip()

DETAILED_BRIEFING = BASIC_BRIEFING + "\n\n" + """
共同天气为49.4N、6.2E的NASA POWER 2019年固定逐日数据，使用Europe/Paris场景日历。
两个官方参数组的地区相邻；本任务是区域迁移后的模型场景，土壤和管理并非原校准试验实测。
两场共享同一时间：处理一场时另一场也生长，等待一次即可，不能逐场重复等待相同天数。

资源与设施：
1. 只有一个Warehouse保存种子、肥料、油、药和粮批；装料只转入设备，田间施用才记本场额度。
   共享种箱30万粒、油箱100L、粮箱2t；换种前清空或退回余种，跨场收获前清空粮箱。
2. Soybean_Sensor/Soybean_Irrigation只属于大豆，Maize_Sensor/Maize_Irrigation只属于玉米。
   大豆水额度120mm、玉米150mm，均为各自全田等效量；灌溉5mm/h，生效时间看回执，次日复查。
3. 本场肥料为46%N产品，模型有效回收比例0.7。玉米肥料产品额度450kg，参考基肥200kg、追肥200kg；
   大豆不预设追氮任务，不能把玉米剂量照搬给大豆。读取营养代理偏低不能直接认定花期缺氮。
4. 一套无人机和机器人跨场连续耗电。通常先固定传感器、再无人机缩小范围、最后机器人地面确认。
   航拍不是诊断，机器人每次抽查4垄；电量不足先充电并经过所需时间。
5. 本任务不额外注入病虫草事件。玉米当前WOFOST版本未模拟病虫草，不应安排玉米植保作业。

播种与收获：
先复核播床、天气和库存。两场从5月初窗口依次播种；冷春出苗较慢，应复查而非过早补播。每趟最多4垄。
共享设备有soybean_planter、maize_planter及对应割台，按目标作物换机具。
玉米和大豆分别读取实际生育期、根区水分和降雨预报，按关键阶段补整轮水并复查。
确认大豆R8且水分≤18%、玉米MATURE且水分≤25%，当天无雨且地面可通行才收获。
每趟收割最多4垄；同场多趟可在2t粮箱容量内合成一批，跨场前卸清并保留全部来源垄号。
大豆按13%标准水分、玉米按14%分别记粮重；
大豆安全入库上限13.5%、玉米14%。必要时按来源作物干燥，不把混合总kg当成统一单产。
最后核对两场各64垄均收获，所有批次入库，共享设备无遗留种子/粮食，水肥额度和资源账成立。
""".strip()


@register_scenario(SCENARIO_ID)
class ScenarioTwoFarmWofostSoybeanMaizeFullSeason(Scenario):
    start_time = datetime(2019, 5, 1, 7, tzinfo=ZoneInfo("Europe/Paris")).timestamp()
    duration = (datetime(2019, 11, 15, 18, tzinfo=ZoneInfo("Europe/Paris")).timestamp() - start_time)
    timezone_name = "Europe/Paris"
    crop_backend = "wofost"
    queue_based_loop = True
    time_increment_in_seconds = 60
    additional_system_prompt = (
        "Manage adjacent soybean_field and maize_field through one native WOFOST season. "
        "Read each field's crop capabilities and fixed sensors; use one shared Warehouse, "
        "Tractor, Drone and Robot. Every mobile field operation selects farm_id. Keep "
        "crop-specific seed, stage, water/N management and grain moisture rules separate. "
        "Use Europe/Paris time. Harvest and safely store both crops with traceable batches."
    )

    def __post_init__(self):
        super().__post_init__()
        if self.crop_backend_options:
            raise ValueError("This mixed scene declares separate soybean/maize WOFOST configurations in its file")
        self.crop_backend = "wofost"
        if not self.scenario_input:
            self.scenario_input = DETAILED_BRIEFING if self.detailed_briefing else BASIC_BRIEFING

    def setup(self, *args, **kwargs):
        # Base Scenario.setup applies one configuration to every farm. These
        # two species require distinct configurations, installed below.
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("This fixed two-farm scenario has no setup overrides")
        self.init_and_populate_apps()
        self.build_events_flow()

    def init_and_populate_apps(self):
        manifest = json.loads((DATA / "manifest.json").read_text())
        for path_key, hash_key in (("raw_path", "raw_sha256"), ("weather_path", "weather_sha256")):
            if hashlib.sha256((DATA / manifest[path_key]).read_bytes()).hexdigest() != manifest[hash_key]:
                raise ValueError(f"Fixed weather checksum mismatch: {path_key}")
        for crop in manifest["crop_references"]:
            if hashlib.sha256((DATA / crop["crop_path"]).read_bytes()).hexdigest() != crop["crop_sha256"]:
                raise ValueError(f"Official crop parameter checksum mismatch: {crop['crop_name']}")
        self.weather_manifest = manifest
        self.daily_weather = json.loads((DATA / manifest["weather_path"]).read_text())["daily"]
        self.aui, self.weather, self.system = AgentUserInterface(), WeatherApp(), SystemApp()
        self.soybean = FarmWorldApp(name="SoybeanFarm", farm_id="soybean_field", num_ridges=NUM_RIDGES,
            field_length_m=FIELD_LENGTH_M, ridge_width_m=1.1, rows_per_ridge=2,
            required_field_preparation_ops=("level", "form_ridges"))
        self.maize = FarmWorldApp(name="MaizeFarm", farm_id="maize_field", num_ridges=NUM_RIDGES,
            field_length_m=FIELD_LENGTH_M, ridge_width_m=.75, rows_per_ridge=1, crop_type="maize",
            required_field_preparation_ops=("level", "base_fertilize", "form_ridges"))
        self.soybean_sensor, self.maize_sensor = (SensorApp(self.soybean, name="Soybean_Sensor"),
                                                SensorApp(self.maize, name="Maize_Sensor"))
        self.soybean_irrigation = IrrigationApp(self.soybean, self.weather, name="Soybean_Irrigation")
        self.maize_irrigation = IrrigationApp(self.maize, self.weather, name="Maize_Irrigation")
        self.warehouse = WarehouseApp(stock=WarehouseStock(
            {SOYBEAN_CULTIVAR: 900000, MAIZE_CULTIVAR: 100000},
            pesticide_liters=20., fertilizer_kg=600., fuel_liters=800.),
            storage_capacity_kg=40000., drying_capacity_kg_per_day=20000., max_storage_moisture_pct=14.)
        self.farm_environment = FarmEnvironment([
            FarmContext("soybean_field", self.soybean, self.weather, self.soybean_sensor, self.soybean_irrigation),
            FarmContext("maize_field", self.maize, self.weather, self.maize_sensor, self.maize_irrigation),
        ], self.weather, warehouse=self.warehouse, start_time=self.start_time, timezone_name=self.timezone_name)

        # All six daily drivers are pinned. The generator's fallback climate is
        # never used during this season or its seven-day forecasts.
        generator = WeatherGenerator(default_harbin_soybean_config(), seed=0)
        for row in self.daily_weather:
            generator.set_day_override(date.fromisoformat(row["date"]),
                air_temp_min_c=row["tmin_c"], air_temp_max_c=row["tmax_c"],
                air_temp_mean_c=(row["tmin_c"] + row["tmax_c"]) / 2,
                rain_mm=row["rain_mm"], wind_ms=row["wind_2m_m_s"],
                solar_rad_mj_m2=row["shortwave_mj_m2_day"], relative_humidity_pct=row["relative_humidity_pct"],
                weather_tags=["pinned_nasa_power_thionville_2019"])
        location = manifest["location"]
        for farm, seed, variety, crop_name, water, fertilizer, n in (
            (self.soybean, SOYBEAN_CULTIVAR, "Soybean_901", "soybean", 120., 0., 50.),
            (self.maize, MAIZE_CULTIVAR, "Grain_maize_201", "maize", 150., 450., 30.),
        ):
            farm._sim_date = "2019-05-01"
            farm.set_season_phase("full_season")
            for ridge in farm._ridges:
                ridge.soil_vwc, ridge.soil_temp_c = .26, 12.
                ridge.pest_pressure = ridge.pest_pressure_base = 0.
                ridge.disease_pressure = ridge.disease_pressure_base = 0.
            physics = farm.physics
            physics.latitude_deg = location["latitude"]
            physics.soil.params = replace(physics.soil.params, root_depth_m=1.2,
                wilting_point_vwc=.10, field_capacity_vwc=.30, saturation_vwc=.45,
                max_infiltration_mm_day=50., rainfall_capture_efficiency=1.)
            physics.biotic.params = replace(physics.biotic.params, recruitment_fraction=0.)
            physics.biotic.set_pressure(list(range(NUM_RIDGES)), weed_pressure=0., insect_pressure=0., disease_pressure=0.)
            physics.weather_generator = generator
            physics.scenario_metadata = {
                "daily_settlement": "completed_calendar_day", "reference_id": "thionville",
                "weather_sha256": manifest["weather_sha256"], "parameter_overrides": {},
                "location": location, "field_trial_validation": False,
                "soil_source": "explicit shared-region loam and initial N assumptions, not measured trial soil",
                "biotic_events": [], "calendar": self.timezone_name,
            }
            farm.configure_management_regime(irrigation_quota_mm_total=water, fertilizer_quota_kg=fertilizer)
            farm.configure_crop_backend("wofost", crop_name=crop_name, variety_name=variety,
                cultivar_map={seed: variety}, require_explicit_cultivar_parameters=True,
                latitude_deg=location["latitude"], longitude_deg=location["longitude"], elevation_m=location["elevation_m"],
                reference_density_plants_m2=40. if crop_name == "soybean" else 1 / (.75 * .20),
                initial_available_n_kg_ha=n, base_soil_n_kg_ha=50.,
                soil_n_mineralization_fraction=.025 if crop_name == "soybean" else .002,
                fertilizer_n_fraction=.46, fertilizer_n_recovery=.7, external_biotic_coupling=crop_name == "soybean")
            if crop_name == "soybean":
                physics.yield_recovery.params.grain_moisture_mode = "soybean_equilibrium"
            farm.configure_postharvest_market(market_moisture_pct=13. if crop_name == "soybean" else 14.,
                max_storage_moisture_pct=13.5 if crop_name == "soybean" else 14., storage_capacity_kg=40000.)
            # Scenario-owned machinery requirements also appear in tool contracts.
            farm.crop_definition = replace(farm.crop_definition,
                planting_rules=replace(farm.crop_definition.planting_rules,
                    required_implement="soybean_planter" if crop_name == "soybean" else "maize_planter"),
                harvest_rules=replace(farm.crop_definition.harvest_rules,
                    required_implement="harvester" if crop_name == "soybean" else "maize_header"))
            physics.observation_model.rng.seed(int.from_bytes(hashlib.sha256(f"{self.seed}:{farm.farm_id}:observations".encode()).digest()[:8], "big"))

        self.tractor = SharedTractorApp(self.farm_environment, equipment=TractorEquipment(
            implements=(*DEFAULT_TRACTOR_IMPLEMENTS, "soybean_planter", "maize_planter", "maize_header"),
            ridging_implement="furrower"))
        self.drone = SharedDroneApp(self.farm_environment, name="Drone")
        self.robot = SharedRobotApp(self.farm_environment, name="Robot")
        self.system.attach_farm_environment(self.farm_environment)
        self.shared_equipment = [self.tractor, self.drone, self.robot]
        self.apps = [self.aui, self.soybean, self.maize, self.weather, self.warehouse,
            self.soybean_sensor, self.maize_sensor, self.soybean_irrigation, self.maize_irrigation,
            *self.shared_equipment, self.system]
        for app in self.apps:
            app.register_time_manager(self.farm_environment.time_manager)
            stream = int.from_bytes(hashlib.sha256(f"{self.seed}:{app.name}".encode()).digest()[:8], "big")
            app.seed = stream
            app.rng.seed(stream)
        self._initial_stock = deepcopy(self.warehouse.stock)
        from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs
        _build_weather_inputs(self.weather, date(2019, 5, 1), physics=self.soybean.physics, advance_weather=False)

    def build_events_flow(self):
        # This captures ordinary public tool calls; it runs no future model,
        # reads no future receipt and invokes no other scene's workflow.
        with EventRegisterer.capture_mode() as captured:
            previous = None

            def step(name, event, reason):
                nonlocal previous
                previous = event.oracle().with_id(name).depends_on(previous)
                previous.workflow_metadata = {"oracle_reason": reason}
                return previous

            def observe(phase, *, canopy=False):
                step(f"{phase}_weather", self.weather.get_current_weather(), "核对今天的共同作业天气。")
                step(f"{phase}_forecast", self.weather.get_forecast(days=4), "根据近期有效降雨与可作业窗口安排管理。")
                for farm_id, farm, sensor in (("soybean_field", self.soybean, self.soybean_sensor),
                                               ("maize_field", self.maize, self.maize_sensor)):
                    step(f"{phase}_{farm_id}_soil", sensor.read_soil_sensors(), "读取本场固定探头；不把另一场水分当作本场水分。")
                    if canopy:
                        step(f"{phase}_{farm_id}_canopy", sensor.read_canopy_sensors(), "将冠层变化与土水、阶段交叉判断。")
                    step(f"{phase}_{farm_id}_stage", farm.get_ridge_range_state(0, 63), "确认各垄实际阶段和公开管理状态。")

            def sow(farm, seed, spacing, depth, planter, base_kg):
                fid = farm.farm_id
                step(f"{fid}_grader", self.tractor.attach_implement("grader"), "挂载共享平地机。")
                step(f"{fid}_level", self.tractor.level(fid), "整平目标农场。")
                step(f"{fid}_detach_grader", self.tractor.detach_implement(), "整平后换机具。")
                if base_kg:
                    step(f"{fid}_base_load", self.tractor.load_fertilizer(base_kg), "玉米基肥200kg产品从唯一仓库转入撒肥器。")
                    step(f"{fid}_base", self.tractor.base_fertilize(fid, total_kg=base_kg), "玉米基肥按实际产品kg入土，非归一化肥力赋值。")
                step(f"{fid}_furrower", self.tractor.attach_implement("furrower"), "挂载共享起垄机。")
                step(f"{fid}_ridges", self.tractor.form_ridges(fid, farm.ridge_width_m), "按本场垄宽起垄。")
                step(f"{fid}_detach_furrower", self.tractor.detach_implement(), "起垄后换该作物播种机。")
                step(f"{fid}_planter", self.tractor.attach_implement(planter), "使用该作物的已配置播种机。")
                # Capacity splits are machinery passes, not extra agronomic rounds.
                per_ridge = farm.plants_per_ridge_from_spacing(spacing)
                load_ridges = min(NUM_RIDGES, (300000 // (per_ridge * 4)) * 4)
                for start in range(0, NUM_RIDGES, 4):
                    if start % load_ridges == 0:
                        step(f"{fid}_seed_{start:02d}", self.tractor.load_seeds(seed, per_ridge * min(load_ridges, NUM_RIDGES - start)), "按种箱容量批量装种，精确用完后再装下一批。")
                    step(f"{fid}_plant_{start:02d}", self.tractor.plant_seeds(fid, start, start + 3, depth, spacing), "每趟播4垄，登记本场播期、品种和实际密度。")
                step(f"{fid}_detach_planter", self.tractor.detach_implement(), "播完清空种箱并卸下播种机。")
                step(f"{fid}_return_supplies", self.tractor.return_supplies(), "余料回共同仓库后才换作物。")

            def harvest(farm, header, moisture):
                fid = farm.farm_id
                if farm is self.soybean:
                    step("harvest_refuel", self.tractor.refuel(100.), "开始两场收获前补足共享油箱，仓库只扣实际转入量。")
                step(f"{fid}_header", self.tractor.attach_implement(header), "使用目标作物割台。")
                batch_ridges = 12 if farm is self.soybean else 8
                for first in range(0, NUM_RIDGES, batch_ridges):
                    last = min(first + batch_ridges - 1, NUM_RIDGES - 1)
                    batch = f"{fid}_{first:02d}_{last:02d}"
                    for start in range(first, last + 1, 4):
                        step(f"harvest_{fid}_{start:02d}", self.tractor.harvest(fid, start, start + 3), "实际工具复核成熟、水分、无雨和通行性后收获4垄。")
                    step(f"unload_{batch}", self.tractor.unload_grain(batch), "本参考批次按2t粮箱安排多趟后卸粮，保留全部来源垄号。")
                    step(f"dry_{batch}", self.warehouse.dry_grain(batch, moisture), "按来源作物安全水分干燥；已安全的批次跳过。")
                    step(f"store_{batch}", self.warehouse.store_grain(batch), "安全批次逐一入库。")
                step(f"{fid}_detach_header", self.tractor.detach_implement(), "结束该场收获再换另一种作物割台。")

            step("briefing", self.aui.send_message_to_agent(self.scenario_input), "公开完整任务和资源边界。")
            step("initial_stock", self.warehouse.get_inventory(), "两场共用一份物料账。")
            step("soybean_capabilities", self.soybean.get_crop_capabilities(), "确认官方大豆与本场播收规则。")
            step("maize_capabilities", self.maize.get_crop_capabilities(), "确认原生玉米而非自定义EARLY模拟品种。")
            observe("preplant")
            sow(self.soybean, SOYBEAN_CULTIVAR, SOYBEAN_SPACING_CM, 4., "soybean_planter", 0.)
            sow(self.maize, MAIZE_CULTIVAR, MAIZE_SPACING_CM, 5., "maize_planter", 200.)

            step("wait_establishment", self.system.advance_time(seconds=ORACLE_WAIT_SECONDS["wait_establishment"]), "等待至6月1日07:00，前序实际作业耗时已经扣除。")
            observe("establishment", canopy=True)
            for fid in ("soybean_field", "maize_field"):
                step(f"{fid}_flight", self.drone.fly_survey(fid, 0, 63), "先航拍本场全田粗查，确定需要地面确认的范围。")
                step(f"{fid}_emergence", self.robot.inspect_emergence(fid, 0, 3), "再抽查0—3垄出苗，不宣称地面检查全田。")
                if fid == "soybean_field":
                    step("between_farms_drone_charge", self.drone.charge(), "同一电池不足以连续覆盖两场，跨场前充电。")
                    step("between_farms_charge_wait", self.system.advance_time(minutes=30), "共同等待无人机充电完成。")

            step("wait_maize_nutrition", self.system.advance_time(seconds=ORACLE_WAIT_SECONDS["wait_maize_nutrition"]), "等待至6月10日07:00玉米营养期需氮管理窗口。")
            observe("maize_nutrition")
            step("maize_nutrition_ground", self.robot.inspect_crop_health("maize_field", 28, 31), "复核玉米阶段与营养代理，不作未模拟的病虫诊断。")
            step("maize_topdress_refuel", self.tractor.refuel(100.), "两场播种已消耗同一油箱，追肥前从共同库存补足燃油。")
            step("maize_topdress_load", self.tractor.load_fertilizer(200.), "玉米追肥200kg产品，对应实际N输入；大豆不照搬。")
            for start in range(0, NUM_RIDGES, 10):
                step(f"maize_topdress_{start:02d}", self.tractor.apply_fertilizer("maize_field", start, min(start + 9, 63), 200. / 64), "分趟均匀完成一次全场玉米追肥。")

            # Fixed reference decisions on this pinned weather, not a hidden
            # optimizer. Whole-field 30mm rounds and next-day rechecks are explicit.
            for phase, irrigation in (
                ("maize_july_01", "maize_field"),
                ("soybean_july_05", "soybean_field"),
                ("maize_july_15", "maize_field"),
                ("soybean_july_20", "soybean_field"),
                ("maize_august_01", "maize_field"),
                ("soybean_august_05", "soybean_field"),
                ("maize_august_15", "maize_field"),
            ):
                step(f"wait_{phase}", self.system.advance_time(seconds=ORACLE_WAIT_SECONDS[f"wait_{phase}"]), "共同等待至步骤名称所列日期07:00的关键期检查。")
                observe(phase)
                installation = self.maize_irrigation if irrigation == "maize_field" else self.soybean_irrigation
                step(f"{phase}_irrigate", installation.irrigate(0, 63, 6.), "结合关键期根区下降与降雨预报补亏30mm；并非每轮都已发生水分胁迫。")
                step(f"{phase}_infiltration", self.system.advance_time(days=1), "经过原生日结算后复核，不把已入队水当成立即生长。")
                step(f"{phase}_soybean_recheck", self.soybean_sensor.read_soil_sensors(), "复核大豆独立土水。")
                step(f"{phase}_maize_recheck", self.maize_sensor.read_soil_sensors(), "复核玉米独立土水。")

            step("wait_late_fill", self.system.advance_time(seconds=ORACLE_WAIT_SECONDS["wait_late_fill"]), "8月20日07:00分别检查晚期灌浆。")
            observe("late_fill")
            step("wait_soybean_harvest", self.system.advance_time(seconds=ORACLE_WAIT_SECONDS["wait_soybean_harvest"]), "9月9日07:00复核大豆实际成熟与适收窗口。")
            observe("soybean_harvest")
            harvest(self.soybean, "harvester", 13.)
            step("wait_maize_harvest", self.system.advance_time(seconds=ORACLE_WAIT_SECONDS["wait_maize_harvest"]), "9月20日07:00复核玉米独立收获窗口。")
            observe("maize_harvest")
            harvest(self.maize, "maize_header", 14.)
            step("final_batches", self.warehouse.get_grain_batches(), "按来源核对两种作物全部安全批次。")
            step("final_stock", self.warehouse.get_inventory(), "核对共同库存及待入库粮食。")
            step("soybean_final", self.soybean.get_farm_overview(), "单独确认大豆64垄完成。")
            step("maize_final", self.maize.get_farm_overview(), "单独确认玉米64垄完成。")
            step("report", self.aui.send_message_to_user("两场原生WOFOST全季流程完成；分别核对来源粮批、商品水分、单位面积收成和共同资源账。"), "按作物分别报告，避免混合总粮重掩盖单场未完成。")
        self.events = captured
        return captured

    def validate(self, env=None):
        self.farm_environment.sync()
        failures, totals = [], {}
        workflow = env.workflow if env is not None else self.workflow
        steps = list(workflow.dag.values())
        log = self.tractor.get_state()["operation_log"]
        batches = list(self.warehouse.grain_batches.values())
        for farm, seed, spacing in ((self.soybean, SOYBEAN_CULTIVAR, SOYBEAN_SPACING_CM),
                                    (self.maize, MAIZE_CULTIVAR, MAIZE_SPACING_CM)):
            fid, backend = farm.farm_id, farm.physics.crop_backend
            own = [batch for batch in batches if batch.origin_farm_id == fid]
            planted = [op for op in log if op["operation"] == "plant_seeds" and op.get("farm_id") == fid]
            if (backend is None or backend.config.crop_name != farm.crop_type
                    or set(backend._runs) != set(range(NUM_RIDGES))):
                failures.append(f"{fid}: incomplete native WOFOST crop")
            elif any(float(run.pcse.get("DVS") or 0.) < 2. for run in backend._runs.values()):
                failures.append(f"{fid}: native crop did not reach maturity")
            if not all(r.harvested for r in farm._ridges):
                failures.append(f"{fid}: harvest incomplete")
            if not set(farm._required_field_preparation_ops) <= set(farm.completed_prep_ops):
                failures.append(f"{fid}: preparation incomplete")
            if Counter(rid for b in own for rid in b.ridge_ids) != Counter(range(NUM_RIDGES)):
                failures.append(f"{fid}: missing or duplicated grain origin ridges")
            if any(b.status != "stored" or b.quantity_kg <= 0 or b.crop_id != farm.crop_id
                   or b.cultivar_ids != [seed] or b.moisture_pct is None
                   or b.moisture_pct > farm._postharvest_market.max_storage_moisture_pct for b in own):
                failures.append(f"{fid}: unsafe, unaccounted or wrong-crop grain")
            expected_seeds = farm.plants_per_ridge_from_spacing(spacing) * NUM_RIDGES
            if (self._initial_stock.seed_stock[seed] - self.warehouse.stock.seed_stock[seed] != expected_seeds
                    or sum(op["seeds_used"] for op in planted) != expected_seeds):
                failures.append(f"{fid}: seed conservation failed")
            regime = farm._management_regime
            if regime.irrigation_used_mm_total > regime.irrigation_quota_mm_total + 1e-9 or regime.fertilizer_used_kg > regime.fertilizer_quota_kg + 1e-9:
                failures.append(f"{fid}: management budget exceeded")
            totals[fid] = {"crop": farm.crop_type, "seed": seed,
                "native_variety": backend.config.variety_name if backend else None,
                "area_ha": farm.field_area_m2 / 10000, "harvested_ridges": sum(r.harvested for r in farm._ridges),
                "stored_grain_kg": round(sum(b.quantity_kg for b in own), 2),
                "water_used_mm": regime.irrigation_used_mm_total, "fertilizer_product_kg": regime.fertilizer_used_kg,
                "market_moisture_pct": farm._postharvest_market.market_moisture_pct}
        state = self.tractor.get_state()
        if state["seed_hopper"] or state["grain_bin_kg"]:
            failures.append("Shared machine still contains seeds or grain")
        # Judge the achieved world state; an Agent may correct an earlier
        # refused call. Oracle/replay verification separately rejects errors.
        if not 0 <= state["fuel_tank_l"] <= 100 or min(self.warehouse.stock.fuel_liters,
                self.warehouse.stock.fertilizer_kg, self.warehouse.stock.pesticide_liters) < 0:
            failures.append("Negative or over-capacity shared resources")
        applied = sum(farm._management_regime.fertilizer_used_kg for farm in (self.soybean, self.maize))
        if abs(self._initial_stock.fertilizer_kg - self.warehouse.stock.fertilizer_kg - state["fertilizer_spreader_kg"] - applied) > 1e-7:
            failures.append("Shared fertilizer conservation failed")
        if self.farm_environment.time_manager.time() > self.start_time + self.duration:
            failures.append("Season deadline exceeded")
        return ScenarioValidationResult(success=not failures,
            message="; ".join(failures) or "Both native WOFOST farms harvested and safely stored by origin.",
            metadata={"farms": totals, "grain_batches": len(batches), "tool_calls": len(steps), "weather_sha256": self.weather_manifest["weather_sha256"],
                      "location": self.weather_manifest["location"], "model_scope": "official regional parameters; model scenario, not field calibration"})
