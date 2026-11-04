"""同品种大豆种子折扣采购与高产全季管理。

一场景一文件：题设、初态和所有参考工具步骤均在本文件。
真实天气：Thionville 2019，49.4N/6.2E，Europe/Paris。
土地：64垄×268m×1.1m=18867.2m²；候选管理的模型结果不称田间最高产。
"""

import textwrap
from fairy.scenarios.registry import register_scenario
from fairy.types import EventRegisterer
from .china_market_prices import CNY_PRICES, CONTRACTS, usd_cents
from .common import FullSeasonExtension, capture_step, finish_capture

SCENARIO_ID = "scenario_multiobjective_seed_discount"


@register_scenario(SCENARIO_ID)
class ScenarioSeedDiscount(FullSeasonExtension):
    BASIC_BRIEFING = "经营面积18867.2m²、垄距1.1m的大豆田，比较种子采购方案，完成全季管理、成熟收获和安全入库，在满足本场产量要求的同时降低总成本。价格通过 SeedMarket.get_budget 查询，播种与验收要求通过作物能力工具查询，费用以美元核算。"

    def task_description(self, detailed):
        task = self.BASIC_BRIEFING
        if not detailed:
            return task
        guidance = textwrap.dedent(
            """\
            管理指导：

            采购与验收：先读 SeedMarket.get_budget，再按作物能力查询所需种子并 list_offers。比较同品种、数量、质量及交付条件下的种价、折扣、运费和到货总价，结合采购现金与库存选择可执行方案；保留订单并核对实际到货。通过 Field.get_crop_capabilities 的 management_objective 查询量化产量、总成本及期限目标，采购付款和实际消耗口径分别核对。

            建植与排程：读取作物能力、土壤、天气预报、库存和机器状态，按实际种子、播种与整地要求完成全田建植。播后核对覆盖和长势，异常区域先查原因；作业批次及装载量由设备限制和真实余量决定。

            水分依据与处理：用 Sensor.read_soil_sensors 查看各覆盖区含水量的变化，结合生育阶段和近期预报判断需水。持续偏干且降雨不足时按面积、设施能力及水源余额分次供水；土壤湿润或有可利用降雨时暂缓。待响应生效后复读同区探头并核对费用，不把灌溉上限当作目标量。

            营养依据与复查：结合 Sensor.read_canopy_sensors、地块阶段、可见营养指标和投入记录检查持续异常，先排除缺水、未出苗或自然衰老。本场无独立养分化验，低 NDVI 不能直接确诊缺肥；按作物需求、产品单位、面积和余量决定是否基施或分次追肥，施后核账、等待响应并复查。

            成熟与成本复核：以实际成熟阶段、粮食水分、天气和设备容量安排收获卸粮，必要时干燥后安全入库。核对全田、粮批及种肥水油和干燥消耗，在满足本场产量与总成本要求的同时控制费用；未用库存不重复计费，不能把采购现金余额等同于经营收益。

            """
        ).strip()
        return task + "\n\n" + guidance

    def init_and_populate_apps(self):
        self.scenario_input = self.task_description(self.detailed_briefing)
        self.initialize_world(
            num_ridges=64,
            field_length_m=268.0,
            ridge_width_m=1.1,
            seed_budget_minor=usd_cents(CONTRACTS["legacy_seed_cash_cny"]["soybean"]),
            crop="soybean",
            history=[],
            report={},
            offers={
                "regular": {
                    "offer_id": "regular",
                    "seed_type": "SOYBEAN_901",
                    "quantity": 754688,
                    "seed_minor": usd_cents(
                        754688 * CNY_PRICES["seed_per_unit"]["SOYBEAN_901"]
                    ),
                    "discount_minor": 0,
                    "delivery_minor": 0,
                    "available_lots": 1,
                    "quality": "identical",
                    "delivery": "immediate",
                },
                "discount": {
                    "offer_id": "discount",
                    "seed_type": "SOYBEAN_901",
                    "quantity": 754688,
                    "seed_minor": usd_cents(
                        754688 * CNY_PRICES["seed_per_unit"]["SOYBEAN_901"]
                    ),
                    "discount_minor": usd_cents(
                        754688
                        * CNY_PRICES["seed_per_unit"]["SOYBEAN_901"]
                        * CONTRACTS["seed_discount_fraction"]
                    ),
                    "delivery_minor": 0,
                    "available_lots": 1,
                    "quality": "identical",
                    "delivery": "immediate",
                },
            },
            seed_stock={"SOYBEAN_901": 0, "MAIZE_201": 0},
            fertilizer_kg=1200.0,
            fuel_liters=800.0,
        )
        original_briefing = self.scenario_input
        if self._briefing_input_override:
            self.scenario_input = self._briefing_input_override
        elif not self.detailed_briefing:
            self.scenario_input = self.BASIC_BRIEFING
        if self.additional_system_prompt == original_briefing:
            self.additional_system_prompt = self.scenario_input

    # 已测试候选最高安全入库量 8126.080000000kg；99%门槛 8044.819200000kg。
    best_tested_yield_kg = 8126.080000000001
    oracle_cost_minor = 31020
    ORACLE_REFERENCE = {
        "scenario_id": "scenario_multiobjective_seed_discount",
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
            "production_cost": 310.2,
            "production_cost_minor": 31020,
            "cost_components": {
                "seed": 143.87,
                "fertilizer": 0.0,
                "fuel": 73.91613361762616,
                "water": 47.32773109243698,
                "drying": 45.0846049862731,
            },
            "accounting_rounding": 0.001530303663741961,
            "fuel_liters": 80.0,
            "water_m3": 1698.048,
            "drying_throughput_kg": 8087.839999999997,
            "fertilizer_product_kg": 0.0,
            "consumed_seeds": {"SOYBEAN_901": 754688, "MAIZE_201": 0},
            "biological_kg_by_crop": {"soybean": 7387.013918632073},
            "recovered_kg_by_crop": {"soybean": 8087.846250636559},
            "stored_kg_by_crop": {"soybean": 8087.839999999997},
            "stored_grain_kg": 8087.839999999997,
            "stored_grain_value": 4869.137338517495,
            "net_operating_margin": 4558.937338517495,
            "feasible": True,
            "crop": "soybean",
            "area_m2": 18867.2,
            "fertilizer_kg": 0.0,
            "water_mm": 90.0,
        },
        "scope": "Minimum USD consumed-input cost among this finite search's feasible candidates retaining at least 99% of its highest tested yield; not a global optimum.",
    }

    def build_events_flow(self):
        # 每步字面写定；构图不执行、不读取未来状态、不运行优化器。
        with EventRegisterer.capture_mode() as events:
            previous = None
            previous = capture_step(
                previous,
                self.market.get_budget(),
                "budget",
                "核对本场美元采购与全季核算预算。",
            )
            previous = capture_step(
                previous,
                self.market.list_offers(seed_type="SOYBEAN_901"),
                "quotes",
                "比较相同品种、质量、数量与即时交货条件下的含折扣、运费总价。",
            )
            previous = capture_step(
                previous,
                self.market.purchase_seed(
                    offer_id="discount", quantity=754688, order_id="seed-order"
                ),
                "purchase",
                "购买最低到货总价批次，实际扣预算并增加共同仓库种子。",
            )
            previous = capture_step(
                previous,
                self.market.get_purchase_records(),
                "receipt",
                "核对采购收据与来源，避免只报价格不入库。",
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
                self.tractor.attach_implement(implement="furrower"),
                "ridger",
                "挂载起垄机。",
            )
            previous = capture_step(
                previous,
                self.tractor.form_ridges(farm_id="field", ridge_width_m=1.1),
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
                self.tractor.load_seeds(seed_type="SOYBEAN_901", count=283008),
                "load_00",
                "按30万粒种箱容量装入283008粒；这一箱用完再补种。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=0,
                    end_ridge=3,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_00",
                "第1趟播种第0—3垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=4,
                    end_ridge=7,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_04",
                "第2趟播种第4—7垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=8,
                    end_ridge=11,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_08",
                "第3趟播种第8—11垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=12,
                    end_ridge=15,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_12",
                "第4趟播种第12—15垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=16,
                    end_ridge=19,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_16",
                "第5趟播种第16—19垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=20,
                    end_ridge=23,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_20",
                "第6趟播种第20—23垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="SOYBEAN_901", count=283008),
                "load_24",
                "按30万粒种箱容量装入283008粒；这一箱用完再补种。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=24,
                    end_ridge=27,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_24",
                "第7趟播种第24—27垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=28,
                    end_ridge=31,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_28",
                "第8趟播种第28—31垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=32,
                    end_ridge=35,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_32",
                "第9趟播种第32—35垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=36,
                    end_ridge=39,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_36",
                "第10趟播种第36—39垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=40,
                    end_ridge=43,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_40",
                "第11趟播种第40—43垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=44,
                    end_ridge=47,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_44",
                "第12趟播种第44—47垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="SOYBEAN_901", count=188672),
                "load_48",
                "按30万粒种箱容量装入188672粒；这一箱用完再补种。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=48,
                    end_ridge=51,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_48",
                "第13趟播种第48—51垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=52,
                    end_ridge=55,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_52",
                "第14趟播种第52—55垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=56,
                    end_ridge=59,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_56",
                "第15趟播种第56—59垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.plant_seeds(
                    farm_id="field",
                    start_ridge=60,
                    end_ridge=63,
                    depth_cm=4.0,
                    seed_spacing_cm=4.545454545454546,
                ),
                "plant_60",
                "第16趟播种第60—63垄；每垄11792粒、株距4.54545cm、播深4cm。",
            )
            previous = capture_step(
                previous,
                self.tractor.detach_implement(),
                "detach_planter",
                "64垄播完，种箱恰好用空后卸机具。",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=2662151.0),
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
                self.system.advance_time(seconds=2160000.0),
                "wait_management_1",
                "等待至2019-07-05当地07:00；扣除先前工具真实耗时。",
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
                self.irrigation.irrigate(start=0, end=63, hours=6.0),
                "management_1_water",
                "全64垄补水30mm，实际用水566.016m³；受180mm全季额度约束。",
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
                self.system.advance_time(seconds=1187700.0),
                "wait_management_2",
                "等待至2019-07-20当地07:00；扣除先前工具真实耗时。",
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
                self.irrigation.irrigate(start=0, end=63, hours=6.0),
                "management_2_water",
                "全64垄补水30mm，实际用水566.016m³；受180mm全季额度约束。",
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
                self.system.advance_time(seconds=1274100.0),
                "wait_management_3",
                "等待至2019-08-05当地07:00；扣除先前工具真实耗时。",
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
                self.irrigation.irrigate(start=0, end=63, hours=6.0),
                "management_3_water",
                "全64垄补水30mm，实际用水566.016m³；受180mm全季额度约束。",
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
                self.system.advance_time(seconds=1187700.0),
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
                self.system.advance_time(seconds=1728000.0),
                "wait_harvest",
                "等待至2019-09-09当地07:00；扣除先前工具真实耗时。",
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
                    batch_id="season-2019-00-03", target_moisture_pct=13.0
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
                    batch_id="season-2019-04-07", target_moisture_pct=13.0
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
                    batch_id="season-2019-08-11", target_moisture_pct=13.0
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
                    batch_id="season-2019-12-15", target_moisture_pct=13.0
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
                    batch_id="season-2019-16-19", target_moisture_pct=13.0
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
                    batch_id="season-2019-20-23", target_moisture_pct=13.0
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
                    batch_id="season-2019-24-27", target_moisture_pct=13.0
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
                    batch_id="season-2019-28-31", target_moisture_pct=13.0
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
                    batch_id="season-2019-32-35", target_moisture_pct=13.0
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
                    batch_id="season-2019-36-39", target_moisture_pct=13.0
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
                    batch_id="season-2019-40-43", target_moisture_pct=13.0
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
                    batch_id="season-2019-44-47", target_moisture_pct=13.0
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
                    batch_id="season-2019-48-51", target_moisture_pct=13.0
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
                    batch_id="season-2019-52-55", target_moisture_pct=13.0
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
                    batch_id="season-2019-56-59", target_moisture_pct=13.0
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
                    batch_id="season-2019-60-63", target_moisture_pct=13.0
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
            previous = capture_step(
                previous,
                self.market.get_budget(),
                "final_budget",
                "核对种子预算余额及实付价格。",
            )
        return finish_capture(self, events)

    def __post_init__(self):
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean: false or true")
        self._briefing_input_override = self.scenario_input
        super().__post_init__()
