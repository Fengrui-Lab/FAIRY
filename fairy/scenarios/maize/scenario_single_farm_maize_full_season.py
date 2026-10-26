"""单农场籽粒玉米全季；配置、初态、完整 workflow、Oracle 与验收均在本文件。

这是未做田间标定的早熟玉米模拟品种 MAIZE_EARLY_2026，不对应真实审定品种。
64 个管理垄 × 268m × 0.65m，单行，25cm 株距；有效种植面积 1.11488ha，
每垄 1,072 粒，全田 68,608 粒（约 6.15 株/m²）。64 垄来自现有六区探头布局，
不是用面积随意反推的数量。玉米物理阶段和作业门槛由 crop_id="maize" 选择。

场景使用一套绑定本场的旧式工具签名，不需要 farm_id 参数；单场环境只负责
共享模拟时钟与北京时间日界。已有大豆场景继续保留各自的默认配置和工具。
参考流程是经实际工具验证的固定管理路径；观察窗口不是强行改写生育期的事件。
不在季中写入成熟、含水率、营养、病虫或产量真值，Oracle 也只调用公开工具。

运行：
    python -m fairy.cli -s scenario_single_farm_maize_full_season \
        --build-oracle --run-oracle-tools --replay --evaluate --output-dir /tmp/maize-full-season
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world import (
    DroneApp, FarmWorldApp, FieldOpsApp, RobotApp, SensorApp, TractorApp, WeatherApp,
)
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.equipment import DEFAULT_TRACTOR_IMPLEMENTS, TractorEquipment
from fairy.apps.system import SystemApp
from fairy.physics.soil_engine import SoilHydraulicModifier
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.types import EventRegisterer


SCENARIO_ID = "scenario_single_farm_maize_full_season"
WEATHER_PROFILE = "harbin_baseline_2026_seed_101"
CROP_ID = "maize"
CULTIVAR_ID = "MAIZE_EARLY_2026"
NUM_RIDGES = 64
FIELD_LENGTH_M = 268.0
RIDGE_WIDTH_M = 0.65
ROWS_PER_RIDGE = 1
SEED_SPACING_CM = 25.0
PLANTING_DEPTH_CM = 5.0
BASE_FERTILIZER_KG = 200.0
TOPDRESS_KG_PER_RIDGE = 6.0

BASIC_BRIEFING = """
管理哈尔滨 maize_field 籽粒玉米田的完整季节，从裸地播前准备到收获、安全入库。
作物 maize，品种 MAIZE_EARLY_2026；这是未经过田间标定的模拟早熟品种，产量不是现实预测。
本场64垄，本地编号0–63；每垄268m，垄距0.65m，每垄单行，有效面积1.11488ha。

FarmWorldApp 公开本场作物规则与状态，SensorApp 和 FieldOpsApp 是本场固定探头和灌溉设施。
TractorApp、Mavic3M、Robot0 均绑定此唯一农场，工具无需 farm_id。
先查询作物能力、天气、土壤、冠层、机器状态与库存，再决定播种和季内管理。
根据实际生育阶段与观测证据开展出苗、水肥、健康和成熟检查；处理后复查效果。
从工具查询播收、安全水分、作业条件和资源限制，不根据日期或单一指标猜测是否可作业。

完成边界：全田64垄播种并收获，粮食按本场玉米安全条件入库，粮箱与挂车清空，
核对库存、作业覆盖与入库账，报告实际管理和收获结果；抽查不能代替全田覆盖。
所有日期与作业时间均使用北京时间；工具、物理日推和回放共用一只模拟时钟。
""".strip()

DETAILED_BRIEFING = """
管理哈尔滨一块籽粒玉米田的完整季节，从播前整地到收获、安全入库。
作物 maize；模拟早熟品种 MAIZE_EARLY_2026。该品种用于测试软件中的玉米规则，
尚未经过田间标定，产量不是现实预测。64垄，本地编号0–63；每垄268m，垄距0.65m，
每垄单行，播深5cm、株距25cm。有效面积11148.8m²（1.11488ha），共需68608粒种子。

本场有固定土壤/冠层探头和 FieldOpsApp 灌溉设施；TractorApp、Mavic3M、Robot0
均绑定此唯一农场，工具无需 farm_id。先读取 FarmWorldApp.get_crop_capabilities，
确认种子、几何、玉米专用播种机/收获割台、成熟与含水率门槛，再执行作业。

1. 5月中旬播前检查天气、墒情、库存、拖拉机。完成平地、200kg底肥、0.65m起垄。
   安装 maize_planter，使用本场玉米种子，逐趟最多4垄，装足该趟所需4288粒。
   全田精确装种不留余种。播种要满足实际温度、墒情和通行条件。
2. 约6月初检查出苗：全田状态、六区探头、多光谱全田巡查和0–3垄地面抽查。
   地面抽查只有4垄，不能声称全田均完成地面检查；异常应复查并按实际缺苗决策。
3. 约6月下旬营养生长期，读全田阶段、营养和天气；参考全田追施6kg/垄的模拟肥料，
   使用真实拖拉机分区作业并扣除库存、燃油和作业时间。该重量是肥料产品重量，
   不是纯氮量，也不是现实配方推荐。施后复查，不把正常的低早期NDVI当病害。
4. 约7月中下旬抽雄吐丝窗口、8月上旬灌浆窗口，分别读取墒情、阶段、预报与冠层。
   参考各补水20mm（固定设施4小时），全季水预算50个全田等效毫米。
   实际土壤已湿、即将有效降雨或作物阶段不同，应依据观测调整，不按日历盲目补水。
   次日复核入渗。机器人健康检查用于区分病虫和非生物胁迫；无确诊不施药。
5. 8月下旬复核灌浆与成熟进度，秋季再次读全田成熟及籽粒含水率。
   只有全部目标垄达到玉米 R6_MATURITY、籽粒水分≤30%、无雨、土壤可通行，
   才安装 maize_header 收获；不能把大豆R8当成玉米成熟条件。
   每趟最多4垄并立即卸粮，避免粮箱溢出；逐批核对作物身份、重量和水分。
6. 玉米安全储存上限14%。必要时干燥至14%后入库；核对64垄均已收获，粮箱与挂车
   清空、仓库有正的玉米入库量，汇报播种量、水肥、阶段观察与入库结果。

所有日期与作业时间均使用北京时间。工具调用、物理日推和回放共用一只模拟时钟。
参考 Oracle 为固定天气种子下的可重复基线，不宣称产量最优。每个阶段都应先读实际状态。
""".strip()


@register_scenario(SCENARIO_ID)
class ScenarioSingleFarmMaizeFullSeason(Scenario):
    """One complete maize season, using the same public single-farm App APIs."""

    start_time = datetime(2026, 5, 15, 7, tzinfo=timezone(timedelta(hours=8))).timestamp()
    duration = 190 * 86400
    queue_based_loop = True
    time_increment_in_seconds = 60
    expects_agent_harvest = True
    additional_system_prompt = (
        "Manage this single farm from maize planting through safe grain storage. "
        "Read crop capabilities and use maize stages, maize_planter, and maize_header. "
        "Tools are permanently bound to this field and take no farm_id. "
        "Check observations at emergence, vegetative growth, silking, grain filling, "
        "and maturity. Calendar windows guide checks; actual conditions determine operations. "
        "Keep resource, coverage, moisture, and one-clock constraints visible. "
        "This simulated maize cultivar is not field-calibrated."
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        if not self.scenario_input:
            self.scenario_input = DETAILED_BRIEFING if self.detailed_briefing else BASIC_BRIEFING

    def init_and_populate_apps(self) -> None:
        self.aui = AgentUserInterface()
        self.weather = WeatherApp()
        self.weather.set_weather(
            date="2026-05-15", temp_c=17.0, humidity_pct=55.0,
            wind_speed_ms=2.0, rainfall_mm=0.0, solar_radiation=20.0 / 0.0864,
            forecast=[
                {"date": "2026-05-16", "temp_c": 17.5, "humidity_pct": 55.0,
                 "wind_speed_ms": 2.0, "rainfall_mm": 0.0,
                 "solar_radiation": 20.5 / 0.0864},
            ],
        )
        self.farm_world = FarmWorldApp(
            farm_id="maize_field", crop_id=CROP_ID, cultivar_id=CULTIVAR_ID,
            field_length_m=FIELD_LENGTH_M, ridge_width_m=RIDGE_WIDTH_M,
            rows_per_ridge=ROWS_PER_RIDGE,
        )
        self.sensor = SensorApp(self.farm_world)
        self.field_ops = FieldOpsApp(self.farm_world, self.weather)
        self.farm_environment = FarmEnvironment([
            FarmContext("maize_field", self.farm_world, self.weather,
                        self.sensor, self.field_ops),
        ], self.weather, start_time=self.start_time, timezone_name="Asia/Shanghai")
        self.tractor = TractorApp(self.farm_world, self.weather, equipment=TractorEquipment(
            implements=(*DEFAULT_TRACTOR_IMPLEMENTS, "maize_planter", "maize_header"),
            ridging_implement="furrower",
        ))
        self.mavic = DroneApp(
            self.farm_world, self.weather, name="Mavic3M",
            description="本场玉米多光谱巡查无人机", speed_ms=5.0,
            effective_ridges_per_pass=7, battery_pct_per_ridge=1.0,
        )
        self.robot = RobotApp(self.farm_world, self.weather, name="Robot0")
        self.system = SystemApp()
        self.system.attach_farm_environment(self.farm_environment)
        self.apps = [self.aui, self.farm_world, self.weather, self.sensor,
                     self.field_ops, self.tractor, self.mavic, self.robot, self.system]
        for app in self.apps:
            app.register_time_manager(self.farm_environment.time_manager)
            app.set_seed(self.seed)

        # Only initial conditions are set here; no calendar event rewrites crop truth.
        farm = self.farm_world
        farm._sim_date = "2026-05-15"
        farm.set_season_phase("full_season")
        farm._inventory.seed_stock = {CULTIVAR_ID: 150000}
        farm._inventory.fertilizer_kg = 1200.0
        farm._inventory.fuel_liters = 800.0
        farm._inventory.pesticide_liters = 0.0
        for ridge in farm._ridges:
            ridge.planted = ridge.harvested = False
            ridge.soil_vwc = 0.26 + ((ridge.ridge_id % 5) - 2) * 0.002
            ridge.soil_temp_c = 13.0 + (ridge.ridge_id % 4) * 0.2
            ridge.nutrient_index = 0.78
            ridge.stand_fraction = 1.0
            ridge.pest_pressure_base = ridge.pest_pressure = 0.01
            ridge.disease_pressure_base = ridge.disease_pressure = 0.01
        farm.configure_physics_profile(
            WEATHER_PROFILE, location="Harbin/Heilongjiang", seed_type=CULTIVAR_ID,
            cultivar="模拟早熟籽粒玉米/未田间标定", start_date="2026-05-15",
        )
        # Copy the registry profile, preserving independent scene ownership.
        farm.physics.profile = deepcopy(farm.physics.profile)
        farm.physics.soil.set_hydraulic_modifiers({
            rid: SoilHydraulicModifier(
                root_depth_m=1.20, field_capacity_vwc=0.36,
                top_drainage_rate=0.22, root_drainage_rate=0.04,
                rainfall_capture_efficiency=0.95, irrigation_efficiency=0.90,
                max_infiltration_mm_day=80.0,
            ) for rid in range(NUM_RIDGES)
        })
        farm.configure_management_regime(
            regime="conventional", irrigation_quota_mm_total=50.0,
        )
        self._initial_inventory = deepcopy(farm._inventory.to_dict())

    def _reference_actions(self):
        """The entire fixed-seed reference, with no imported scene workflow."""
        actions: list[tuple[str, Any, str, dict[str, Any], str]] = []

        def add(step, app, method, reason, **arguments):
            actions.append((step, app, method, arguments, reason))

        add("capabilities", self.farm_world, "get_crop_capabilities", "确认本场的玉米规则。")
        add("prep_weather", self.weather, "get_current_weather", "检查播前实时天气。")
        add("prep_forecast", self.weather, "get_forecast", "检查播种窗口。", days=3)
        add("prep_soil", self.sensor, "read_soil_sensors", "检查六区土温与墒情。")
        add("prep_inventory", self.farm_world, "get_inventory", "核对真实种子、水肥和燃油库存。")
        add("prep_status", self.tractor, "get_status", "核对油箱、种箱和可用机具。")
        add("prep_refuel", self.tractor, "refuel", "从本场库存补足拖拉机燃油。", liters=100.0)
        add("prep_grader", self.tractor, "attach_implement", "安装平地机。", implement="grader")
        add("prep_level", self.tractor, "level", "完成全田平地。")
        add("prep_detach_grader", self.tractor, "detach_implement", "卸下平地机。")
        add("prep_load_base", self.tractor, "load_fertilizer", "精确装入200kg底肥。", kg=BASE_FERTILIZER_KG)
        add("prep_base", self.tractor, "base_fertilize", "全田施用题设的200kg底肥，按实际作业耗时结算。", total_kg=BASE_FERTILIZER_KG)
        add("prep_furrower", self.tractor, "attach_implement", "安装起垄机。", implement="furrower")
        add("prep_ridges", self.tractor, "form_ridges", "形成64条单行0.65m管理垄。", ridge_width_m=RIDGE_WIDTH_M)
        add("prep_detach_furrower", self.tractor, "detach_implement", "起垄机不能充当玉米播种机。")
        add("plant_attach", self.tractor, "attach_implement", "安装玉米专用播种机。", implement="maize_planter")
        for start in range(0, NUM_RIDGES, 4):
            end = start + 3
            add(f"plant_load_{start}_{end}", self.tractor, "load_seeds", "按单行实际长度精确装该趟种子。",
                seed_type=CULTIVAR_ID, count=self.farm_world.plants_per_ridge_from_spacing(SEED_SPACING_CM) * 4)
            add(f"plant_{start}_{end}", self.tractor, "plant_seeds", "按玉米播深和株距播种这四垄。",
                start_ridge=start, end_ridge=end, depth_cm=PLANTING_DEPTH_CM, seed_spacing_cm=SEED_SPACING_CM)
        add("plant_detach", self.tractor, "detach_implement", "播种结束卸下机具。")
        add("wait_emergence", self.system, "advance_time", "约6月初进入出苗复查窗口。", days=17)
        add("emergence_state", self.farm_world, "get_ridge_range_state", "读取全田实际玉米阶段与出苗状态。", start=0, end=63)
        add("emergence_soil", self.sensor, "read_soil_sensors", "查看播后水热条件。")
        add("emergence_ground", self.robot, "inspect_emergence", "只抽查0–3垄出苗，记录实际覆盖。", start_ridge=0, end_ridge=3)
        add("emergence_weather", self.weather, "get_current_weather", "飞行前检查天气。")
        add("emergence_survey", self.mavic, "fly_survey", "获取全田多光谱覆盖。", start_ridge=0, end_ridge=63)
        add("emergence_charge_drone", self.mavic, "charge", "异步补充无人机电量。")
        add("emergence_charge_robot", self.robot, "charge", "异步补充机器人电量。")
        add("wait_vegetative", self.system, "advance_time", "约6月下旬营养生长复查。", days=24)
        add("vegetative_state", self.farm_world, "get_ridge_range_state", "读取V期进度和公开营养指数。", start=0, end=63)
        add("vegetative_soil", self.sensor, "read_soil_sensors", "追肥前检查土壤通行条件。")
        add("vegetative_forecast", self.weather, "get_forecast", "追肥前检查天气窗口。", days=3)
        add("topdress_load", self.tractor, "load_fertilizer", "装全田384kg肥料产品。", kg=NUM_RIDGES * TOPDRESS_KG_PER_RIDGE)
        for start in range(0, NUM_RIDGES, 10):
            end = min(start + 9, NUM_RIDGES - 1)
            add(f"topdress_{start}_{end}", self.tractor, "apply_fertilizer", "分区追肥，逐趟扣肥、油和作业时间。",
                start_ridge=start, end_ridge=end, kg_per_ridge=TOPDRESS_KG_PER_RIDGE)
        add("wait_silking", self.system, "advance_time", "约7月中下旬检查抽雄吐丝和水分。", days=23)
        for phase, wait_days in (("silking", 0), ("grain_fill", 20)):
            if wait_days:
                add(f"wait_{phase}", self.system, "advance_time", "进入下一个关键期观察窗口。", days=wait_days)
            add(f"{phase}_state", self.farm_world, "get_ridge_range_state", "按玉米实际阶段判断管理窗口。", start=0, end=63)
            add(f"{phase}_soil", self.sensor, "read_soil_sensors", "核对表层墒情和持续趋势。")
            add(f"{phase}_canopy", self.sensor, "read_canopy_sensors", "冠层观测与土壤、阶段相互印证。")
            add(f"{phase}_forecast", self.weather, "get_forecast", "检查未来有效降雨。", days=4)
            add(f"{phase}_health", self.robot, "inspect_crop_health", "地面抽查4垄，辅助排除明显病虫。", start_ridge=28, end_ridge=31)
            add(f"{phase}_water", self.field_ops, "irrigate", "关键期补水20mm；固定设施计4小时+5分钟。", start=0, end=63, hours=4.0)
            add(f"{phase}_infiltration_wait", self.system, "advance_time", "等一天后核对入渗。", days=1)
            add(f"{phase}_next_day_soil", self.sensor, "read_soil_sensors", "补水后次日复查，避免宣称立即解除根区缺水。")
            add(f"{phase}_charge_robot", self.robot, "charge", "为下一次抽查异步充电。")
        add("wait_dent", self.system, "advance_time", "约8月下旬复核灌浆/蜡熟进度。", days=19)
        add("dent_state", self.farm_world, "get_ridge_range_state", "读取实际R期，不能套用大豆R5–R8。", start=0, end=63)
        add("dent_canopy", self.sensor, "read_canopy_sensors", "观察后期冠层衰老。")
        add("wait_maturity", self.system, "advance_time", "秋季成熟和田间降水分后复核。", days=43)
        add("harvest_weather", self.weather, "get_current_weather", "收获必须无雨。")
        add("harvest_soil", self.sensor, "read_soil_sensors", "核对全田土壤可通行。")
        add("harvest_maturity", self.farm_world, "get_ridge_range_state", "收前逐垄确认R6_MATURITY及≤30%水分。", start=0, end=63)
        add("harvest_refuel", self.tractor, "refuel", "为全部收获趟次补足燃油。", liters=100.0)
        add("harvest_attach", self.tractor, "attach_implement", "安装玉米收获割台。", implement="maize_header")
        for start in range(0, NUM_RIDGES, 4):
            end = start + 3
            add(f"harvest_{start}_{end}", self.tractor, "harvest", "仅收获这四垄，实际成熟门槛由工具检查。", start_ridge=start, end_ridge=end)
            add(f"unload_{start}_{end}", self.tractor, "unload_grain", "每趟即卸，防止高产玉米撑满粮箱。")
        add("harvest_detach", self.tractor, "detach_implement", "收获结束卸下割台。")
        add("storage_dry", self.farm_world, "dry_grain", "必要时干燥到本场玉米安全上限14%。", target_moisture_pct=14.0)
        add("storage_store", self.farm_world, "store_grain", "将安全玉米批次入库。")
        add("final_overview", self.farm_world, "get_farm_overview", "逐垄核对64垄收获完成。")
        add("final_inventory", self.farm_world, "get_inventory", "核对玉米仓储及全季资源用量。")
        add("report", self.aui, "send_message_to_user", "汇报此单场完整玉米季。",
            content="单场玉米全季参考结束：核对阶段、68608粒播种、底肥与追肥、关键期补水、64垄收获及≤14%水分入库；该模拟品种尚未田间标定。")
        return actions

    def build_events_flow(self):
        """Capture exactly the same public actions used by the Oracle."""
        with EventRegisterer.capture_mode() as events:
            previous = self.aui.send_message_to_agent(content=self.scenario_input).with_id("briefing")
            for step, app, method, arguments, _ in self._reference_actions():
                previous = (getattr(app, method)(**arguments).oracle()
                            .with_id(step).depends_on(previous))
        self.events = events
        return events

    def oracle_solution(self, run_oracle: bool = False) -> None:
        """Export or execute public actions; failed/partial tools stop this baseline."""
        if not self.apps:
            self.setup()
        self.workflow = Workflow()
        previous = None
        for step, app, method, arguments, reason in self._reference_actions():
            before = self.farm_environment.time_manager.time() if run_oracle else None
            result = getattr(app, method)(**arguments) if run_oracle else {}
            if isinstance(result, dict) and ("error" in result or result.get("status") == "partial"):
                raise RuntimeError(f"{step}: {app.name}__{method}: {result}")
            content = dict(result) if isinstance(result, dict) else {"result": result}
            content["oracle_reason"] = reason
            operation = getattr(getattr(app, method), "_event_operation_type", None)
            self.workflow.add_node(WorkflowStep(
                name=step, tool_name=f"{app.name}__{method}", tool_args=arguments,
                content=content, depends_on=[previous] if previous else [],
                op_type=operation.value if operation is not None else None,
                time_before=before,
                time_after=self.farm_environment.time_manager.time() if run_oracle else None,
            ))
            previous = step

    def validate(self, env=None) -> ScenarioValidationResult:
        """Judge final crop, complete coverage, accounting, and safe stored grain."""
        self.farm_environment.sync()
        farm = self.farm_world
        failures = []
        ridges = set(range(NUM_RIDGES))
        operations = self.tractor.get_state()["operation_log"]
        planting = [op for op in operations if op["operation"] == "plant_seeds"]
        harvest = [op for op in operations if op["operation"] == "harvest"]
        if farm.crop_id != CROP_ID or farm.cultivar_id != CULTIVAR_ID:
            failures.append("wrong crop or cultivar")
        if not {"level", "base_fertilize", "form_ridges"} <= set(farm.completed_prep_ops):
            failures.append("incomplete field preparation")
        if {rid for op in planting for rid in op["ridge_ids"]} != ridges:
            failures.append("planting coverage incomplete")
        if any(op["depth_cm"] != PLANTING_DEPTH_CM or op["seed_spacing_cm"] != SEED_SPACING_CM for op in planting):
            failures.append("incorrect maize planting geometry")
        if {rid for op in harvest for rid in op["ridge_ids"]} != ridges or not all(r.harvested for r in farm._ridges):
            failures.append("harvest coverage incomplete")
        expected_seeds = farm.plants_per_ridge_from_spacing(SEED_SPACING_CM) * NUM_RIDGES
        seed_use = self._initial_inventory["seed_stock"][CULTIVAR_ID] - farm._inventory.seed_stock[CULTIVAR_ID]
        if seed_use != expected_seeds or sum(op["seeds_used"] for op in planting) != expected_seeds:
            failures.append("seed accounting does not match the actual single-row area")
        # The public ridge is reset to BARE after harvest. Native crop states
        # and planting operation records retain the season's identity/counts.
        if any(state.seed_type != CULTIVAR_ID for state in farm.physics.phenology.states.values()):
            failures.append("soybean or wrong cultivar in maize field")
        if any(state.stage.value != "R6_MATURITY" or state.maturity_date is None
               for state in farm.physics.phenology.states.values()):
            failures.append("maize maturity was not reached")
        if farm._inventory.warehouse_grain_kg <= 0 or farm._inventory.harvest_grain_kg != 0 or self.tractor._grain_bin_kg != 0:
            failures.append("grain missing from warehouse or left in bin/trailer")
        if any(state.grain_moisture_frac is None or state.grain_moisture_frac > 0.14 + 1e-9
               for state in farm.physics.yield_recovery.states.values()):
            failures.append("stored maize exceeds 14% moisture")
        regime = farm._management_regime
        if regime.irrigation_used_mm_total > regime.irrigation_quota_mm_total + 1e-9:
            failures.append("water quota exceeded")
        if farm._inventory.fertilizer_kg < 0 or farm._inventory.fuel_liters < 0:
            failures.append("negative farm inventory")
        steps = list((env.workflow if env is not None else self.workflow).dag.values())
        observed_stages = {
            ridge["growth_stage"] for step in steps if isinstance(step.content, dict)
            for ridge in step.content.get("ridges", []) if "growth_stage" in ridge
        }
        for phase, allowed in (
            ("emergence", {"VE", "V3"}), ("vegetative", {"V6", "V12"}),
            ("silking", {"VT", "R1_SILKING", "R2_BLISTER"}),
            ("grain filling", {"R3_MILK", "R4_DOUGH", "R5_DENT"}),
            ("maturity", {"R6_MATURITY"}),
        ):
            if not observed_stages & allowed:
                failures.append(f"missing actual {phase} observation")
        if any(step.error_stage or (isinstance(step.content, dict) and
                                   ("error" in step.content or step.content.get("status") == "partial")) for step in steps):
            failures.append("workflow has failed or partial tools")
        return ScenarioValidationResult(
            success=not failures, message="; ".join(failures) or "Single-farm maize season harvested and stored safely.",
            metadata={"crop_id": farm.crop_id, "cultivar_id": farm.cultivar_id,
                      "area_m2": farm.field_geometry.planted_area_m2,
                      "seed_use": seed_use, "warehouse_grain_kg": farm._inventory.warehouse_grain_kg,
                      "harvested_ridges": sum(r.harvested for r in farm._ridges),
                      "water_used_mm": regime.irrigation_used_mm_total,
                      "observed_stages": sorted(observed_stages),
                      "model_scope": "simulated cultivar; not field-calibrated"},
        )
