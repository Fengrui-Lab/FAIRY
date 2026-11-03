"""上季大豆遗留高SCN，换种玉米。

一场景一文件：题设、初态和所有参考工具步骤均在本文件。
真实天气：Thionville 2019，49.4N/6.2E，Europe/Paris。
土地：64垄×268m×0.75m=12864.0m²；候选管理的模型结果不称田间最高产。
"""

import textwrap
from fairy.scenarios.registry import register_scenario
from fairy.types import EventRegisterer
from .china_market_prices import CONTRACTS, usd_cents
from .common import FullSeasonExtension, capture_step, finish_capture

SCENARIO_ID = "scenario_multiseason_scn_switch_to_maize"


@register_scenario(SCENARIO_ID)
class ScenarioScnSwitch(FullSeasonExtension):
    BASIC_BRIEFING = "经营面积12864m²、垄距0.75m的农田，依据上季种植记录、播前土壤报告和轮作规则，在玉米与大豆之间选择本季作物，完成全田种植、成熟收获及安全入库，并兼顾本场产量与成本目标。价格通过 SeasonPlanning.get_season_context 查询，作业与验收要求通过作物能力工具查询，费用以美元核算。"

    def task_description(self, detailed):
        task = self.BASIC_BRIEFING
        if not detailed:
            return task
        guidance = textwrap.dedent(
            """\
            管理指导：

            选择依据：先调用 SeasonPlanning.get_season_context 和 get_crop_options，核对报告编号、检测时点、种植历史及宿主轮作规则。按报告和规则比较续种与换作物，提交匹配的作物、种子和报告编号；不能仅凭上季作物下结论，也不把固定历史报告当成可用灌水施肥消除的病害过程。

            作物与目标：选择后读取 Field.get_crop_capabilities 中的播种、成熟、储粮要求及 management_objective，核对本场量化产量、成本和期限目标。检查公共库存、设备、土壤及天气后完成全田整地建植；若选择玉米，按其能力安排作业；若选择大豆，按大豆规则独立核对，不套用另一作物参数。

            水分依据与处理：用 Sensor.read_soil_sensors 对照覆盖区前次含水量、作物阶段和 WeatherApp.get_forecast。持续偏干且近期降水不足时，结合面积、设施和水量余额分次供水；湿润或有可利用降雨则暂缓。待供水响应生效后复读相同区域并核对用水账。

            营养判断与复查：结合 Sensor.read_canopy_sensors、地块状态、生育阶段和已施肥记录检查持续异常。先排除缺水、未出苗和衰老，不能仅凭低 NDVI 确诊缺肥；本场无独立土壤养分化验，营养指标只是模拟线索。按作物需求、产品单位、面积和余量考虑基施或分次追肥，施后核账并等待响应复查。

            收储与成本：依据实际成熟、水分、天气和设备限制分批收割卸粮，必要时干燥后安全入库。核对全田完成、粮批、实际消耗和资源余额，在满足本场产量与轮作要求的同时降低总成本；不把库存转移或未用余料重复计费。

            """
        ).strip()
        return task + "\n\n" + guidance

    def init_and_populate_apps(self):
        self.scenario_input = self.task_description(self.detailed_briefing)
        self.initialize_world(
            num_ridges=64,
            field_length_m=268.0,
            ridge_width_m=0.75,
            seed_budget_minor=usd_cents(CONTRACTS["legacy_total_budget_cny"]["maize"]),
            rain_free_october=True,
            crop="maize",
            history=[
                {
                    "season_id": "2018",
                    "crop_id": "soybean",
                    "harvest_completed": True,
                    "scn_detected": True,
                }
            ],
            report={
                "report_id": "preplant-2019",
                "sample_date": "2019-04-20",
                "scn_eggs_per_100cc": 18000,
                "source": "fixed synthetic laboratory fixture; SCN dynamics not simulated",
            },
            offers={},
            seed_stock={"SOYBEAN_901": 514560, "MAIZE_201": 85760},
            fertilizer_kg=800.0,
            fuel_liters=800.0,
        )
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input

    # 已测试候选最高安全入库量 17392.160000000kg；99%门槛 17218.238400000kg。
    best_tested_yield_kg = 17392.16
    oracle_cost_minor = 68200
    ORACLE_REFERENCE = {
        "scenario_id": "scenario_multiseason_scn_switch_to_maize",
        "price_book_id": "china_northeast_2025_usd_v1",
        "selected": {
            "currency": "USD",
            "price_book_id": "china_northeast_2025_usd_v1",
            "cny_per_usd": 7.1757,
            "prices": {
                "currency": "USD",
                "price_book_id": "china_northeast_2025_usd_v1",
                "cny_per_usd": 7.1757,
                "crop_per_kg": {
                    "maize": 0.3010159287595635,
                    "soybean": 0.602031857519127,
                },
                "seed_per_unit": {
                    "MAIZE_201": 0.002654461452906204,
                    "SOYBEAN_901": 0.00021182602394191507,
                    "SOYBEAN_902": 0.00021182602394191507,
                    "SOYBEAN_903": 0.00021182602394191507,
                },
                "fertilizer_per_kg": 0.2856864138690302,
                "fuel_per_liter": 0.923951670220327,
                "drying_per_kg": 0.005574369051103028,
                "water_per_m3": 0.027871845255515143,
            },
            "production_cost": 682.0,
            "production_cost_minor": 68200,
            "cost_components": {
                "seed": 227.64661420123608,
                "fertilizer": 208.25396825396825,
                "fuel": 87.1874394262454,
                "water": 62.745098039215684,
                "drying": 96.1654472734367,
            },
            "accounting_rounding": 0.0014328058978207991,
            "fuel_liters": 94.36363636363637,
            "water_m3": 2251.2,
            "drying_throughput_kg": 17251.359999999993,
            "fertilizer_product_kg": 728.9599999999999,
            "consumed_seeds": {"SOYBEAN_901": 0, "MAIZE_201": 85760},
            "stored_kg_by_crop": {"maize": 17251.359999999993},
            "stored_grain_kg": 17251.359999999993,
            "stored_grain_value": 5192.9341527655815,
            "net_operating_margin": 4510.9341527655815,
            "feasible": True,
            "crop": "maize",
            "area_m2": 12864.0,
            "fertilizer_kg": 728.96,
            "water_mm": 175.0,
        },
        "scope": "Minimum USD consumed-input cost among this finite search's feasible candidates retaining at least 99% of its highest tested yield; not a global optimum.",
    }

    def build_events_flow(self):
        # 每步字面写定；构图不执行、不读取未来状态、不运行优化器。
        with EventRegisterer.capture_mode() as events:
            previous = None
            previous = capture_step(
                previous,
                self.planning.get_season_context(farm_id="field"),
                "history",
                "读取前季作物、收获记录与播前SCN实测题设。",
            )
            previous = capture_step(
                previous,
                self.planning.get_crop_options(farm_id="field"),
                "options",
                "确认寄主/非寄主选项与各自种子和播种约束。",
            )
            previous = capture_step(
                previous,
                self.planning.select_crop(
                    farm_id="field",
                    crop_id="maize",
                    cultivar_id="MAIZE_201",
                    report_id="preplant-2019",
                ),
                "select",
                "18000枚卵/100cm³超过10000阈值，本季换种非寄主玉米。",
            )
            previous = capture_step(
                previous,
                self.farm.get_crop_capabilities(),
                "capabilities",
                "读取本场原生作物品种、播深、密度、机具和收获约束。",
            )
            previous = capture_step(
                previous,
                self.warehouse.get_inventory(),
                "inventory",
                "确认种子、肥料与燃油实际库存。",
            )
            previous = capture_step(
                previous,
                self.weather.get_current_weather(),
                "weather",
                "确认本日无雨且可作业。",
            )
            previous = capture_step(
                previous,
                self.weather.get_forecast(days=7),
                "forecast",
                "查看随后天气，安排播种与出苗检查。",
            )
            previous = capture_step(
                previous,
                self.sensor.read_soil_sensors(),
                "soil",
                "读取本场土温和水分，不用另一场观测替代。",
            )
            previous = capture_step(
                previous,
                self.tractor.get_status(),
                "tractor",
                "确认共享油箱、料斗和机具。",
            )
            previous = capture_step(
                previous,
                self.tractor.attach_implement(implement="grader"),
                "grader",
                "挂载共享平地机。",
            )
            previous = capture_step(
                previous,
                self.tractor.level(farm_id="field"),
                "level",
                "整平64垄实际面积，燃油和耗时按面积计。",
            )
            previous = capture_step(
                previous,
                self.tractor.detach_implement(),
                "detach_grader",
                "整平后卸机具。",
            )
            previous = capture_step(
                previous,
                self.tractor.load_fertilizer(kg=364.48),
                "base_load_00",
                "按500kg撒肥器容量装入基肥；实际扣仓。",
            )
            previous = capture_step(
                previous,
                self.tractor.base_fertilize(farm_id="field", total_kg=364.48),
                "base_fertilize_00",
                "全田均匀施入这一箱基肥；产品46%N、回收率0.7，非直接改肥力。",
            )
            previous = capture_step(
                previous,
                self.tractor.attach_implement(implement="furrower"),
                "ridger",
                "挂载起垄机。",
            )
            previous = capture_step(
                previous,
                self.tractor.form_ridges(farm_id="field", ridge_width_m=0.75),
                "ridges",
                "按本场真实垄宽完成64垄起垄。",
            )
            previous = capture_step(
                previous,
                self.tractor.detach_implement(),
                "detach_ridger",
                "起垄后卸机具。",
            )
            previous = capture_step(
                previous,
                self.tractor.attach_implement(implement="seeder"),
                "planter",
                "挂载已支持的播种机。",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="MAIZE_201", count=85760),
                "load_00",
                "按30万粒种箱容量装入85760粒；这一箱用完再补种。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=0,
                    end_ridge=3,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_00",
                "第1趟播种第0—3垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=4,
                    end_ridge=7,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_04",
                "第2趟播种第4—7垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=8,
                    end_ridge=11,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_08",
                "第3趟播种第8—11垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=12,
                    end_ridge=15,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_12",
                "第4趟播种第12—15垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=16,
                    end_ridge=19,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_16",
                "第5趟播种第16—19垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=20,
                    end_ridge=23,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_20",
                "第6趟播种第20—23垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=24,
                    end_ridge=27,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_24",
                "第7趟播种第24—27垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=28,
                    end_ridge=31,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_28",
                "第8趟播种第28—31垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=32,
                    end_ridge=35,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_32",
                "第9趟播种第32—35垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=36,
                    end_ridge=39,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_36",
                "第10趟播种第36—39垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=40,
                    end_ridge=43,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_40",
                "第11趟播种第40—43垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=44,
                    end_ridge=47,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_44",
                "第12趟播种第44—47垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=48,
                    end_ridge=51,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_48",
                "第13趟播种第48—51垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=52,
                    end_ridge=55,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_52",
                "第14趟播种第52—55垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=56,
                    end_ridge=59,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_56",
                "第15趟播种第56—59垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=60,
                    end_ridge=63,
                    depth_cm=5.0,
                    seed_spacing_cm=20.0,
                ),
                "plant_60",
                "第16趟播种第60—63垄；每垄1340粒、株距20cm、播深5cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.detach_implement(),
                "detach_planter",
                "64垄播完，种箱恰好用空后卸机具。",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=2663358.0),
                "wait_establishment",
                "等待至2019-06-01当地07:00；扣除先前工具真实耗时。",
            )
            previous = capture_step(
                previous,
                self.weather.get_current_weather(),
                "establishment_weather",
                "读取本日真实天气，核对作业窗口。",
            )
            previous = capture_step(
                previous,
                self.weather.get_forecast(days=7),
                "establishment_forecast",
                "读取近期降雨，交叉判断水分管理。",
            )
            previous = capture_step(
                previous,
                self.sensor.read_soil_sensors(),
                "establishment_soil",
                "读取本场根区水分与土温。",
            )
            previous = capture_step(
                previous,
                self.farm.get_ridge_range_state(start=0, end=63),
                "establishment_stage",
                "读取全部64垄实际阶段，不用日期代替生育状态。",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "canopy_establishment",
                "结合冠层与全部垄状态确认建植；不做未建模的病虫诊断。",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=777600.0),
                "wait_nutrition",
                "等待至2019-06-10当地07:00；扣除先前工具真实耗时。",
            )
            previous = capture_step(
                previous,
                self.weather.get_current_weather(),
                "nutrition_weather",
                "读取本日真实天气，核对作业窗口。",
            )
            previous = capture_step(
                previous,
                self.weather.get_forecast(days=7),
                "nutrition_forecast",
                "读取近期降雨，交叉判断水分管理。",
            )
            previous = capture_step(
                previous,
                self.sensor.read_soil_sensors(),
                "nutrition_soil",
                "读取本场根区水分与土温。",
            )
            previous = capture_step(
                previous,
                self.farm.get_ridge_range_state(start=0, end=63),
                "nutrition_stage",
                "读取全部64垄实际阶段，不用日期代替生育状态。",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "canopy_nutrition",
                "交叉复核营养与群体生长；大豆不例行施氮。",
            )
            previous = capture_step(
                previous,
                self.tractor.refuel(liters=100.0),
                "topdress_refuel",
                "追肥前从共同库存补足100L油箱；只转入剩余容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.load_fertilizer(kg=56.95),
                "topdress_load_00",
                "仅装本趟所需肥料，受500kg容量限制。",
            )
            previous = capture_step(
                previous,
                self.tractor.apply_fertilizer(
                    farm_id="field", start_ridge=0, end_ridge=9, kg_per_ridge=5.695
                ),
                "topdress_00",
                "追肥第0—9垄，每趟最多10垄；全季产品总量728.96kg。",
            )
            previous = capture_step(
                previous,
                self.tractor.load_fertilizer(kg=56.95),
                "topdress_load_10",
                "仅装本趟所需肥料，受500kg容量限制。",
            )
            previous = capture_step(
                previous,
                self.tractor.apply_fertilizer(
                    farm_id="field", start_ridge=10, end_ridge=19, kg_per_ridge=5.695
                ),
                "topdress_10",
                "追肥第10—19垄，每趟最多10垄；全季产品总量728.96kg。",
            )
            previous = capture_step(
                previous,
                self.tractor.load_fertilizer(kg=56.95),
                "topdress_load_20",
                "仅装本趟所需肥料，受500kg容量限制。",
            )
            previous = capture_step(
                previous,
                self.tractor.apply_fertilizer(
                    farm_id="field", start_ridge=20, end_ridge=29, kg_per_ridge=5.695
                ),
                "topdress_20",
                "追肥第20—29垄，每趟最多10垄；全季产品总量728.96kg。",
            )
            previous = capture_step(
                previous,
                self.tractor.load_fertilizer(kg=56.95),
                "topdress_load_30",
                "仅装本趟所需肥料，受500kg容量限制。",
            )
            previous = capture_step(
                previous,
                self.tractor.apply_fertilizer(
                    farm_id="field", start_ridge=30, end_ridge=39, kg_per_ridge=5.695
                ),
                "topdress_30",
                "追肥第30—39垄，每趟最多10垄；全季产品总量728.96kg。",
            )
            previous = capture_step(
                previous,
                self.tractor.load_fertilizer(kg=56.95),
                "topdress_load_40",
                "仅装本趟所需肥料，受500kg容量限制。",
            )
            previous = capture_step(
                previous,
                self.tractor.apply_fertilizer(
                    farm_id="field", start_ridge=40, end_ridge=49, kg_per_ridge=5.695
                ),
                "topdress_40",
                "追肥第40—49垄，每趟最多10垄；全季产品总量728.96kg。",
            )
            previous = capture_step(
                previous,
                self.tractor.load_fertilizer(kg=56.95),
                "topdress_load_50",
                "仅装本趟所需肥料，受500kg容量限制。",
            )
            previous = capture_step(
                previous,
                self.tractor.apply_fertilizer(
                    farm_id="field", start_ridge=50, end_ridge=59, kg_per_ridge=5.695
                ),
                "topdress_50",
                "追肥第50—59垄，每趟最多10垄；全季产品总量728.96kg。",
            )
            previous = capture_step(
                previous,
                self.tractor.load_fertilizer(kg=22.78),
                "topdress_load_60",
                "仅装本趟所需肥料，受500kg容量限制。",
            )
            previous = capture_step(
                previous,
                self.tractor.apply_fertilizer(
                    farm_id="field", start_ridge=60, end_ridge=63, kg_per_ridge=5.695
                ),
                "topdress_60",
                "追肥第60—63垄，每趟最多10垄；全季产品总量728.96kg。",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=1813070.0),
                "wait_management_1",
                "等待至2019-07-01当地07:00；扣除先前工具真实耗时。",
            )
            previous = capture_step(
                previous,
                self.weather.get_current_weather(),
                "management_1_weather",
                "读取本日真实天气，核对作业窗口。",
            )
            previous = capture_step(
                previous,
                self.weather.get_forecast(days=7),
                "management_1_forecast",
                "读取近期降雨，交叉判断水分管理。",
            )
            previous = capture_step(
                previous,
                self.sensor.read_soil_sensors(),
                "management_1_soil",
                "读取本场根区水分与土温。",
            )
            previous = capture_step(
                previous,
                self.farm.get_ridge_range_state(start=0, end=63),
                "management_1_stage",
                "读取全部64垄实际阶段，不用日期代替生育状态。",
            )
            previous = capture_step(
                previous,
                self.irrigation.irrigate(start=0, end=63, hours=8.75),
                "management_1_water",
                "全64垄补水43.75mm，实际用水562.8m³；受180mm全季额度约束。",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(days=1),
                "management_1_settle",
                "等待下一日原生结算，避免重复交付尚未生效的灌水。",
            )
            previous = capture_step(
                previous,
                self.sensor.read_soil_sensors(),
                "management_1_recheck",
                "次日复核供水后的实际水分。",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=1091400.0),
                "wait_management_2",
                "等待至2019-07-15当地07:00；扣除先前工具真实耗时。",
            )
            previous = capture_step(
                previous,
                self.weather.get_current_weather(),
                "management_2_weather",
                "读取本日真实天气，核对作业窗口。",
            )
            previous = capture_step(
                previous,
                self.weather.get_forecast(days=7),
                "management_2_forecast",
                "读取近期降雨，交叉判断水分管理。",
            )
            previous = capture_step(
                previous,
                self.sensor.read_soil_sensors(),
                "management_2_soil",
                "读取本场根区水分与土温。",
            )
            previous = capture_step(
                previous,
                self.farm.get_ridge_range_state(start=0, end=63),
                "management_2_stage",
                "读取全部64垄实际阶段，不用日期代替生育状态。",
            )
            previous = capture_step(
                previous,
                self.irrigation.irrigate(start=0, end=63, hours=8.75),
                "management_2_water",
                "全64垄补水43.75mm，实际用水562.8m³；受180mm全季额度约束。",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(days=1),
                "management_2_settle",
                "等待下一日原生结算，避免重复交付尚未生效的灌水。",
            )
            previous = capture_step(
                previous,
                self.sensor.read_soil_sensors(),
                "management_2_recheck",
                "次日复核供水后的实际水分。",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=1350600.0),
                "wait_management_3",
                "等待至2019-08-01当地07:00；扣除先前工具真实耗时。",
            )
            previous = capture_step(
                previous,
                self.weather.get_current_weather(),
                "management_3_weather",
                "读取本日真实天气，核对作业窗口。",
            )
            previous = capture_step(
                previous,
                self.weather.get_forecast(days=7),
                "management_3_forecast",
                "读取近期降雨，交叉判断水分管理。",
            )
            previous = capture_step(
                previous,
                self.sensor.read_soil_sensors(),
                "management_3_soil",
                "读取本场根区水分与土温。",
            )
            previous = capture_step(
                previous,
                self.farm.get_ridge_range_state(start=0, end=63),
                "management_3_stage",
                "读取全部64垄实际阶段，不用日期代替生育状态。",
            )
            previous = capture_step(
                previous,
                self.irrigation.irrigate(start=0, end=63, hours=8.75),
                "management_3_water",
                "全64垄补水43.75mm，实际用水562.8m³；受180mm全季额度约束。",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(days=1),
                "management_3_settle",
                "等待下一日原生结算，避免重复交付尚未生效的灌水。",
            )
            previous = capture_step(
                previous,
                self.sensor.read_soil_sensors(),
                "management_3_recheck",
                "次日复核供水后的实际水分。",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=1091400.0),
                "wait_management_4",
                "等待至2019-08-15当地07:00；扣除先前工具真实耗时。",
            )
            previous = capture_step(
                previous,
                self.weather.get_current_weather(),
                "management_4_weather",
                "读取本日真实天气，核对作业窗口。",
            )
            previous = capture_step(
                previous,
                self.weather.get_forecast(days=7),
                "management_4_forecast",
                "读取近期降雨，交叉判断水分管理。",
            )
            previous = capture_step(
                previous,
                self.sensor.read_soil_sensors(),
                "management_4_soil",
                "读取本场根区水分与土温。",
            )
            previous = capture_step(
                previous,
                self.farm.get_ridge_range_state(start=0, end=63),
                "management_4_stage",
                "读取全部64垄实际阶段，不用日期代替生育状态。",
            )
            previous = capture_step(
                previous,
                self.irrigation.irrigate(start=0, end=63, hours=8.75),
                "management_4_water",
                "全64垄补水43.75mm，实际用水562.8m³；受180mm全季额度约束。",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(days=1),
                "management_4_settle",
                "等待下一日原生结算，避免重复交付尚未生效的灌水。",
            )
            previous = capture_step(
                previous,
                self.sensor.read_soil_sensors(),
                "management_4_recheck",
                "次日复核供水后的实际水分。",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=313800.0),
                "wait_late_fill",
                "等待至2019-08-20当地07:00；扣除先前工具真实耗时。",
            )
            previous = capture_step(
                previous,
                self.weather.get_current_weather(),
                "late_fill_weather",
                "读取本日真实天气，核对作业窗口。",
            )
            previous = capture_step(
                previous,
                self.weather.get_forecast(days=7),
                "late_fill_forecast",
                "读取近期降雨，交叉判断水分管理。",
            )
            previous = capture_step(
                previous,
                self.sensor.read_soil_sensors(),
                "late_fill_soil",
                "读取本场根区水分与土温。",
            )
            previous = capture_step(
                previous,
                self.farm.get_ridge_range_state(start=0, end=63),
                "late_fill_stage",
                "读取全部64垄实际阶段，不用日期代替生育状态。",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=2678400.0),
                "wait_harvest",
                "等待至2019-09-20当地07:00；扣除先前工具真实耗时。",
            )
            previous = capture_step(
                previous,
                self.weather.get_current_weather(),
                "harvest_weather",
                "读取本日真实天气，核对作业窗口。",
            )
            previous = capture_step(
                previous,
                self.weather.get_forecast(days=7),
                "harvest_forecast",
                "读取近期降雨，交叉判断水分管理。",
            )
            previous = capture_step(
                previous,
                self.sensor.read_soil_sensors(),
                "harvest_soil",
                "读取本场根区水分与土温。",
            )
            previous = capture_step(
                previous,
                self.farm.get_ridge_range_state(start=0, end=63),
                "harvest_stage",
                "读取全部64垄实际阶段，不用日期代替生育状态。",
            )
            previous = capture_step(
                previous,
                self.tractor.get_status(),
                "harvest_status",
                "收获前复核油量、空粮箱与机具。",
            )
            previous = capture_step(
                previous,
                self.tractor.refuel(liters=100.0),
                "harvest_refuel",
                "收获前从共同仓库补足100L油箱；不重置油量。",
            )
            previous = capture_step(
                previous,
                self.tractor.attach_implement(implement="harvester"),
                "header",
                "挂载本场已支持的收割机。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=0, end_ridge=3),
                "harvest_00",
                "第1趟收获第0—3垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-00-03"),
                "unload_00",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-00-03", target_moisture_pct=14.0
                ),
                "dry_00",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-00-03"),
                "store_00",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=4, end_ridge=7),
                "harvest_04",
                "第2趟收获第4—7垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-04-07"),
                "unload_04",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-04-07", target_moisture_pct=14.0
                ),
                "dry_04",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-04-07"),
                "store_04",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=8, end_ridge=11),
                "harvest_08",
                "第3趟收获第8—11垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-08-11"),
                "unload_08",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-08-11", target_moisture_pct=14.0
                ),
                "dry_08",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-08-11"),
                "store_08",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=12, end_ridge=15),
                "harvest_12",
                "第4趟收获第12—15垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-12-15"),
                "unload_12",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-12-15", target_moisture_pct=14.0
                ),
                "dry_12",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-12-15"),
                "store_12",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=16, end_ridge=19),
                "harvest_16",
                "第5趟收获第16—19垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-16-19"),
                "unload_16",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-16-19", target_moisture_pct=14.0
                ),
                "dry_16",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-16-19"),
                "store_16",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=20, end_ridge=23),
                "harvest_20",
                "第6趟收获第20—23垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-20-23"),
                "unload_20",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-20-23", target_moisture_pct=14.0
                ),
                "dry_20",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-20-23"),
                "store_20",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=24, end_ridge=27),
                "harvest_24",
                "第7趟收获第24—27垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-24-27"),
                "unload_24",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-24-27", target_moisture_pct=14.0
                ),
                "dry_24",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-24-27"),
                "store_24",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=28, end_ridge=31),
                "harvest_28",
                "第8趟收获第28—31垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-28-31"),
                "unload_28",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-28-31", target_moisture_pct=14.0
                ),
                "dry_28",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-28-31"),
                "store_28",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=32, end_ridge=35),
                "harvest_32",
                "第9趟收获第32—35垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-32-35"),
                "unload_32",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-32-35", target_moisture_pct=14.0
                ),
                "dry_32",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-32-35"),
                "store_32",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=36, end_ridge=39),
                "harvest_36",
                "第10趟收获第36—39垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-36-39"),
                "unload_36",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-36-39", target_moisture_pct=14.0
                ),
                "dry_36",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-36-39"),
                "store_36",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=40, end_ridge=43),
                "harvest_40",
                "第11趟收获第40—43垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-40-43"),
                "unload_40",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-40-43", target_moisture_pct=14.0
                ),
                "dry_40",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-40-43"),
                "store_40",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=44, end_ridge=47),
                "harvest_44",
                "第12趟收获第44—47垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-44-47"),
                "unload_44",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-44-47", target_moisture_pct=14.0
                ),
                "dry_44",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-44-47"),
                "store_44",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=48, end_ridge=51),
                "harvest_48",
                "第13趟收获第48—51垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-48-51"),
                "unload_48",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-48-51", target_moisture_pct=14.0
                ),
                "dry_48",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-48-51"),
                "store_48",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=52, end_ridge=55),
                "harvest_52",
                "第14趟收获第52—55垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-52-55"),
                "unload_52",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-52-55", target_moisture_pct=14.0
                ),
                "dry_52",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-52-55"),
                "store_52",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=56, end_ridge=59),
                "harvest_56",
                "第15趟收获第56—59垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-56-59"),
                "unload_56",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-56-59", target_moisture_pct=14.0
                ),
                "dry_56",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-56-59"),
                "store_56",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest(farm_id="field", start_ridge=60, end_ridge=63),
                "harvest_60",
                "第16趟收获第60—63垄；工具检查真实成熟、天气、通行性和2t粮箱容量。",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="season-2019-60-63"),
                "unload_60",
                "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(
                    batch_id="season-2019-60-63", target_moisture_pct=14.0
                ),
                "dry_60",
                "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="season-2019-60-63"),
                "store_60",
                "这4垄安全粮批次入库；受20t总库容约束。",
            )
            previous = capture_step(
                previous,
                self.farm.get_farm_overview(),
                "final_field",
                "逐垄核对最终收获状态。",
            )
            previous = capture_step(
                previous,
                self.warehouse.get_inventory(),
                "final_inventory",
                "核对安全入库粮、种子、肥料和燃油账。",
            )
            previous = capture_step(
                previous,
                self.tractor.get_status(),
                "final_machine",
                "确认空料斗、空粮箱，设备状态未重置。",
            )
        return finish_capture(self, events)

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()
