"""L3：高水价下的冬小麦经营；初始化、题设、参考及显式 Oracle 均在本文件。"""

from datetime import datetime
from pathlib import Path
from typing import ClassVar
from zoneinfo import ZoneInfo
from fairy.scenarios.scenario import Scenario
from fairy.types import EventRegisterer
from ..apps.winter_wheat_accounts_app import WheatResources, wheat_price
from ..winter_wheat_setup import initialize_wheat_farm, wheat_fingerprint
from ..evaluation.winter_wheat import evaluate
from ..common import capture_step, finish_capture


class ScenarioWinterWheatHighWaterPrice(Scenario):
    scenario_id = "scenario_l3_winter_wheat_high_water_price"
    level = "L3"
    objective_metric = "net_operating_margin"
    resources: ClassVar = WheatResources(water_usd_m3=wheat_price("high_water_per_m3"))
    ORACLE_REFERENCE: ClassVar = {
        "scenario_id": "scenario_l3_winter_wheat_high_water_price",
        "input_fingerprint": "2806df79feb6838c678ed6febe9ae6388708f627dc29eb34d79cdec9dc6e2383",
        "selected": {
            "currency": "USD",
            "price_book_id": "winter_wheat_china_2025_owned_machinery_usd_v2",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"winter_wheat": 8133.120000000001},
            "stored_grain_kg": 8133.120000000001,
            "dry_grain_kg": 7491.008291936611,
            "production_cost": 614.7016585771192,
            "stored_grain_value": 2697.5522388059703,
            "net_operating_margin": 2082.850580228851,
        },
        "workflow_steps": 145,
        "candidate_count": 11,
        "feasible_count": 10,
        "scope": "Best feasible net operating margin among 11 actually executed block-management "
        "candidates. Native crop, weather and physical rules unchanged between trials. Finite "
        "comparison, not a global optimum.",
        "search_artifact": "validation_runs/winter_wheat_blocks_20261104/release_search/selection.json",
    }

    def __init__(self, *, input_dir=None, calibrating=False, **kwargs):
        self.calibrating = calibrating
        self.input_dir = (
            Path(input_dir)
            if input_dir is not None
            else Path(__file__).resolve().parents[1] / "data/winter_wheat_ncp_2019_2020"
        )
        self._input_override = kwargs.get("scenario_input")
        self._system_override = kwargs.get("additional_system_prompt")
        self._has_system_override = "additional_system_prompt" in kwargs
        if type(kwargs.get("detailed_briefing", True)) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean")
        if (
            kwargs.pop("crop_backend", "wofost") != "wofost"
            or kwargs.pop("crop_backend_options", {}) != {}
        ):
            raise ValueError("Winter wheat requires its declared native WOFOST inputs")
        kwargs.setdefault("scenario_id", self.scenario_id)
        super().__init__(crop_backend="wofost", **kwargs)
        self.timezone_name = "Asia/Shanghai"
        self.simulation_timezone = ZoneInfo(self.timezone_name)
        self.start_time = datetime(
            2019, 10, 1, 7, tzinfo=self.simulation_timezone
        ).timestamp()
        self.duration = (
            datetime(
                2020, 7, 15, 23, 59, 59, tzinfo=self.simulation_timezone
            ).timestamp()
            - self.start_time
        )

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("Configure inputs at construction")
        initialize_wheat_farm(self)
        self.scenario_input = (
            self._input_override
            if self._input_override is not None
            else self.task_description(self.detailed_briefing)
        )
        self.additional_system_prompt = (
            self._system_override if self._has_system_override else self.scenario_input
        )
        self.build_events_flow()

    def input_fingerprint(self):
        return wheat_fingerprint(self)

    def validate(self, env=None):
        return evaluate(self, env)

    def task_description(self, detailed=True):
        basic = (
            f"经营一座面积{self.resources.area_ha * 10000:g}平方米的冬小麦农场，田地按管理块划分，可分别播种、灌溉、施肥和收获。"
            "完成秋播、越冬管理、成熟收获与安全入库，在有限物资和预算内提高净经营收益。高水价下的冬小麦经营。"
            "通过WheatField.get_field_info查地块、用种和作业条件，通过OperatingAccounts.get_accounts查价格与资源。"
        )
        if not detailed:
            return basic
        return basic + (
            "先查询农场、仓库和农机状态，使用Sensor.read_root_zone_sensors、Sensor.read_canopy_sensors与WheatField.inspect_blocks检查水氮估计、冠层和各块生育进展，结合天气安排作业。"
            "播前整平土地并装种，分块条播，不需要起垄；投入前核对单位、库存和设备容量。按生育阶段及观测变化安排水肥，处理后推进时间并复查响应。"
            "越冬期间保留同一季作物与土壤，春季继续检查各块差异。原生成熟后分批收获、卸粮、干燥和入库，注意粮仓容量与安全水分。"
            "观测是模拟估计；具体日期、剂量和阈值通过工具查询并自主判断。最后报告产量、实际成本和净经营收益。"
        )

    def build_events_flow(self):
        previous = None
        with EventRegisterer.capture_mode() as events:
            previous = capture_step(
                previous,
                self.aui.send_message_to_agent(self.scenario_input),
                "task",
                "Read the block-managed farm task.",
            )
            previous = capture_step(
                previous,
                self.farm.get_field_info(),
                "wheat_001",
                "Read block geometry, sowing window, seed rate and native maturity rules.",
            )
            previous = capture_step(
                previous,
                self.accounts.get_accounts(),
                "wheat_002",
                "Query USD prices, actual costs, remaining resources and crop value.",
            )
            previous = capture_step(
                previous,
                self.tractor.get_status(),
                "wheat_003",
                "Check shared equipment and payload capacities.",
            )
            previous = capture_step(
                previous,
                self.tractor.attach_implement(implement="grader"),
                "wheat_004",
                "Mount the required available implement.",
            )
            previous = capture_step(
                previous,
                self.tractor.prepare_field(),
                "wheat_005",
                "Prepare flat land without a soybean ridge-forming step.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=1204600.0),
                "wheat_006",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_007",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_008",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_009",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.tractor.detach_implement(),
                "wheat_010",
                "Detach the current implement before changing equipment.",
            )
            previous = capture_step(
                previous,
                self.tractor.attach_implement(implement="seeder"),
                "wheat_011",
                "Mount the required available implement.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_012",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=0, end_block=0, depth_cm=3.0),
                "wheat_013",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_014",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=1, end_block=1, depth_cm=3.0),
                "wheat_015",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_016",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=2, end_block=2, depth_cm=3.0),
                "wheat_017",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_018",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=3, end_block=3, depth_cm=3.0),
                "wheat_019",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_020",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=4, end_block=4, depth_cm=3.0),
                "wheat_021",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_022",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=5, end_block=5, depth_cm=3.0),
                "wheat_023",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_024",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=6, end_block=6, depth_cm=3.0),
                "wheat_025",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_026",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=7, end_block=7, depth_cm=3.0),
                "wheat_027",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_028",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=8, end_block=8, depth_cm=3.0),
                "wheat_029",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_030",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=9, end_block=9, depth_cm=3.0),
                "wheat_031",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_032",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=10, end_block=10, depth_cm=3.0),
                "wheat_033",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_034",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=11, end_block=11, depth_cm=3.0),
                "wheat_035",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_036",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=12, end_block=12, depth_cm=3.0),
                "wheat_037",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_038",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=13, end_block=13, depth_cm=3.0),
                "wheat_039",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_040",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=14, end_block=14, depth_cm=3.0),
                "wheat_041",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_seeds(seed_type="WINTER_WHEAT_104", count=250000),
                "wheat_042",
                "Load only the seed quantity required for this block within hopper capacity.",
            )
            previous = capture_step(
                previous,
                self.tractor.sow(start_block=15, end_block=15, depth_cm=3.0),
                "wheat_043",
                "Sow this block at its fixed reference seed rate within the legal autumn window.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_fertilizer(kg=130.43478260869566),
                "wheat_044",
                "Transfer urea product from the warehouse into the shared spreader.",
            )
            previous = capture_step(
                previous,
                self.tractor.fertilize(
                    start_block=0, end_block=9, kg_per_block=8.152173913043478
                ),
                "wheat_045",
                "Apply product kg per block; convert independently to pure N per hectare.",
            )
            previous = capture_step(
                previous,
                self.tractor.fertilize(
                    start_block=10, end_block=15, kg_per_block=8.152173913043478
                ),
                "wheat_046",
                "Apply product kg per block; convert independently to pure N per hectare.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=2671884.0),
                "wheat_047",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_048",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_049",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_050",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=5270400.0),
                "wheat_051",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_052",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_053",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_054",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=3715200.0),
                "wheat_055",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_056",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_057",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_058",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_fertilizer(kg=152.17391304347825),
                "wheat_059",
                "Transfer urea product from the warehouse into the shared spreader.",
            )
            previous = capture_step(
                previous,
                self.tractor.fertilize(
                    start_block=0, end_block=9, kg_per_block=9.51086956521739
                ),
                "wheat_060",
                "Apply product kg per block; convert independently to pure N per hectare.",
            )
            previous = capture_step(
                previous,
                self.tractor.fertilize(
                    start_block=10, end_block=15, kg_per_block=9.51086956521739
                ),
                "wheat_061",
                "Apply product kg per block; convert independently to pure N per hectare.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=257580.0),
                "wheat_062",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_063",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_064",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_065",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=2764800.0),
                "wheat_066",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_067",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_068",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_069",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_fertilizer(kg=130.43478260869566),
                "wheat_070",
                "Transfer urea product from the warehouse into the shared spreader.",
            )
            previous = capture_step(
                previous,
                self.tractor.fertilize(
                    start_block=0, end_block=9, kg_per_block=8.152173913043478
                ),
                "wheat_071",
                "Apply product kg per block; convert independently to pure N per hectare.",
            )
            previous = capture_step(
                previous,
                self.tractor.refuel(liters=50.0),
                "wheat_072",
                "Transfer available fuel before further machine work.",
            )
            previous = capture_step(
                previous,
                self.tractor.fertilize(
                    start_block=10, end_block=15, kg_per_block=8.152173913043478
                ),
                "wheat_073",
                "Apply product kg per block; convert independently to pure N per hectare.",
            )
            previous = capture_step(
                previous,
                self.irrigation.irrigate(start_block=0, end_block=15, depth_mm=50),
                "wheat_074",
                "Apply gross water depth only to the named blocks and debit their treated area.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=1517280.0),
                "wheat_075",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_076",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_077",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_078",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_fertilizer(kg=86.95652173913044),
                "wheat_079",
                "Transfer urea product from the warehouse into the shared spreader.",
            )
            previous = capture_step(
                previous,
                self.tractor.fertilize(
                    start_block=0, end_block=9, kg_per_block=5.434782608695652
                ),
                "wheat_080",
                "Apply product kg per block; convert independently to pure N per hectare.",
            )
            previous = capture_step(
                previous,
                self.tractor.fertilize(
                    start_block=10, end_block=15, kg_per_block=5.434782608695652
                ),
                "wheat_081",
                "Apply product kg per block; convert independently to pure N per hectare.",
            )
            previous = capture_step(
                previous,
                self.irrigation.irrigate(start_block=0, end_block=15, depth_mm=50),
                "wheat_082",
                "Apply gross water depth only to the named blocks and debit their treated area.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=1258080.0),
                "wheat_083",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_084",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_085",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_086",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.irrigation.irrigate(start_block=0, end_block=15, depth_mm=50),
                "wheat_087",
                "Apply gross water depth only to the named blocks and debit their treated area.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=827700.0),
                "wheat_088",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_089",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_090",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_091",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=432000.0),
                "wheat_092",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_093",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_094",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_095",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.irrigation.irrigate(start_block=0, end_block=15, depth_mm=50),
                "wheat_096",
                "Apply gross water depth only to the named blocks and debit their treated area.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=1000500.0),
                "wheat_097",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_098",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_099",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_100",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=1641600.0),
                "wheat_101",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_102",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_103",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_104",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=86400.0),
                "wheat_105",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=86400.0),
                "wheat_106",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_107",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_108",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_109",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.tractor.detach_implement(),
                "wheat_110",
                "Detach the current implement before changing equipment.",
            )
            previous = capture_step(
                previous,
                self.tractor.attach_implement(implement="harvester"),
                "wheat_111",
                "Mount the required available implement.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=0, end_block=1),
                "wheat_112",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_0"),
                "wheat_113",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_0", target_moisture_pct=12.5),
                "wheat_114",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_0"),
                "wheat_115",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=2, end_block=3),
                "wheat_116",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_2"),
                "wheat_117",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_2", target_moisture_pct=12.5),
                "wheat_118",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_2"),
                "wheat_119",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=4, end_block=5),
                "wheat_120",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_4"),
                "wheat_121",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_4", target_moisture_pct=12.5),
                "wheat_122",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_4"),
                "wheat_123",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=6, end_block=7),
                "wheat_124",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_6"),
                "wheat_125",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_6", target_moisture_pct=12.5),
                "wheat_126",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_6"),
                "wheat_127",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=8, end_block=9),
                "wheat_128",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_8"),
                "wheat_129",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_8", target_moisture_pct=12.5),
                "wheat_130",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_8"),
                "wheat_131",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=10, end_block=11),
                "wheat_132",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_10"),
                "wheat_133",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_10", target_moisture_pct=12.5),
                "wheat_134",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_10"),
                "wheat_135",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=12, end_block=13),
                "wheat_136",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_12"),
                "wheat_137",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_12", target_moisture_pct=12.5),
                "wheat_138",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_12"),
                "wheat_139",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=14, end_block=15),
                "wheat_140",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_14"),
                "wheat_141",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_14", target_moisture_pct=12.5),
                "wheat_142",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_14"),
                "wheat_143",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.accounts.get_accounts(),
                "wheat_144",
                "Query USD prices, actual costs, remaining resources and crop value.",
            )
        return finish_capture(self, events)
