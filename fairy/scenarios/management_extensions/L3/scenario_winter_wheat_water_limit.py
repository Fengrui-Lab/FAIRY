"""L3：有限供水下的冬小麦经营；初始化、题设、参考及显式 Oracle 均在本文件。"""

from typing import ClassVar
from fairy.scenarios.scenario import Scenario
from fairy.types import EventRegisterer
from ..apps.winter_wheat_accounts_app import WheatResources
from ..winter_wheat_setup import (
    configure_wheat_calendar,
    initialize_wheat_farm,
    wheat_fingerprint,
)
from ..evaluation.winter_wheat import evaluate
from ..common import capture_step, finish_capture


class ScenarioWinterWheatWaterLimit(Scenario):
    scenario_id = "scenario_l3_winter_wheat_water_limit"
    level = "L3"
    default_late_harvest = True
    objective_metric = "net_operating_margin"
    resources: ClassVar = WheatResources(water_stock_m3=1200.0)
    ORACLE_REFERENCE: ClassVar = {
        "scenario_id": "scenario_l3_winter_wheat_water_limit",
        "input_fingerprint": "408377411c4032a1bed8d5bd590ea8cdbba49088af937feabdd9c01ae18ecd0f",
        "legacy_input_fingerprint": "62efaab5f5a69e6119f810031ead55cf126f47c81dd243994bcd016a9dcd7eb8",
        "selected": {
            "currency": "USD",
            "price_book_id": "winter_wheat_china_2025_owned_machinery_usd_v2",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"winter_wheat": 7263.04},
            "stored_grain_kg": 7263.04,
            "dry_grain_kg": 6689.63808409018,
            "production_cost": 355.1316492360719,
            "stored_grain_value": 2408.9684908789386,
            "net_operating_margin": 2053.8368416428666,
        },
        "workflow_steps": 125,
        "candidate_count": 11,
        "feasible_count": 9,
        "scope": "Best feasible net operating margin among 11 actually executed block-management "
        "candidates. Native crop, weather and physical rules unchanged between trials. Finite "
        "comparison, not a global optimum.",
        "search_artifact": "validation_runs/winter_wheat_blocks_20261104/release_search/selection.json",
    }

    def __init__(
        self, *, input_dir=None, late_harvest=None, calibrating=False, **kwargs
    ):
        self.calibrating = calibrating
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
        configure_wheat_calendar(self, input_dir, late_harvest)

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
            "完成秋播、越冬管理、成熟收获与安全入库，在有限物资和预算内提高净经营收益。有限供水下的冬小麦经营。"
        )
        if not detailed:
            return (
                basic
                + "通过WheatField.get_field_info查地块、用种和作业条件，通过OperatingAccounts.get_accounts查价格与资源。"
            )
        return basic + (
            "\n\n先核对播期、农机、物资价格和全季剩余水量。每次用水按处理面积计入配额。"
            "\n\n十月中下旬根据地块条件安排秋播。整平土地后分块条播，播种时施一部分氮肥。十月底到十一月初出苗，入冬后检查苗情和根区水氮。"
            "\n\n三月前后进入返青期，检查苗情和根区水氮，安排主要追氮，配合较小的一轮补水。四月冠层加快扩展，预计五月上旬末到中旬初开花，把主要供水额度留给花前根区水分下降的阶段。花后灌浆延续到六月，期间复查墒情、长势和剩余水量。"
            "\n\n六月中旬前后陆续成熟。确认各块成熟及作业天气，按粮箱容量分批收获和卸粮，核对含水率后干燥入库。报告产量、实际成本和净经营收益。"
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
                self.system.advance_time(seconds=2068600.0),
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
                self.tractor.load_fertilizer(kg=71.73913043478261),
                "wheat_044",
                "Transfer urea product from the warehouse into the shared spreader.",
            )
            previous = capture_step(
                previous,
                self.tractor.fertilize(
                    start_block=0, end_block=9, kg_per_block=4.483695652173913
                ),
                "wheat_045",
                "Apply product kg per block; convert independently to pure N per hectare.",
            )
            previous = capture_step(
                previous,
                self.tractor.fertilize(
                    start_block=10, end_block=15, kg_per_block=4.483695652173913
                ),
                "wheat_046",
                "Apply product kg per block; convert independently to pure N per hectare.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=1807884.0),
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
                self.system.advance_time(seconds=3974400.0),
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
                self.system.advance_time(seconds=777600.0),
                "wheat_059",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_060",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_061",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_062",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.tractor.load_fertilizer(kg=286.95652173913044),
                "wheat_063",
                "Transfer urea product from the warehouse into the shared spreader.",
            )
            previous = capture_step(
                previous,
                self.tractor.fertilize(
                    start_block=0, end_block=9, kg_per_block=17.934782608695652
                ),
                "wheat_064",
                "Apply product kg per block; convert independently to pure N per hectare.",
            )
            previous = capture_step(
                previous,
                self.tractor.fertilize(
                    start_block=10, end_block=15, kg_per_block=17.934782608695652
                ),
                "wheat_065",
                "Apply product kg per block; convert independently to pure N per hectare.",
            )
            previous = capture_step(
                previous,
                self.irrigation.irrigate(start_block=0, end_block=15, depth_mm=30),
                "wheat_066",
                "Apply gross water depth only to the named blocks and debit their treated area.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=4382880.0),
                "wheat_067",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_068",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_069",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_070",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.irrigation.irrigate(start_block=0, end_block=15, depth_mm=90),
                "wheat_071",
                "Apply gross water depth only to the named blocks and debit their treated area.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=1230900.0),
                "wheat_072",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_073",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_074",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_075",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=1468800.0),
                "wheat_076",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_077",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_078",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_079",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=1641600.0),
                "wheat_080",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_081",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_082",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_083",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=86400.0),
                "wheat_084",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.system.advance_time(seconds=86400.0),
                "wheat_085",
                "Settle each intervening native day on the existing shared farm clock.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_root_zone_sensors(),
                "wheat_086",
                "Observe root-zone water and native nitrogen estimates before deciding inputs.",
            )
            previous = capture_step(
                previous,
                self.sensor.read_canopy_sensors(),
                "wheat_087",
                "Check current canopy response and coverage.",
            )
            previous = capture_step(
                previous,
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "wheat_088",
                "Inspect every block for development, native grain and water/N differences.",
            )
            previous = capture_step(
                previous,
                self.tractor.detach_implement(),
                "wheat_089",
                "Detach the current implement before changing equipment.",
            )
            previous = capture_step(
                previous,
                self.tractor.attach_implement(implement="harvester"),
                "wheat_090",
                "Mount the required available implement.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=0, end_block=1),
                "wheat_091",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_0"),
                "wheat_092",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_0", target_moisture_pct=12.5),
                "wheat_093",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_0"),
                "wheat_094",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=2, end_block=3),
                "wheat_095",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_2"),
                "wheat_096",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_2", target_moisture_pct=12.5),
                "wheat_097",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_2"),
                "wheat_098",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.tractor.refuel(liters=50.0),
                "wheat_099",
                "Transfer available fuel before further machine work.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=4, end_block=5),
                "wheat_100",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_4"),
                "wheat_101",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_4", target_moisture_pct=12.5),
                "wheat_102",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_4"),
                "wheat_103",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=6, end_block=7),
                "wheat_104",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_6"),
                "wheat_105",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_6", target_moisture_pct=12.5),
                "wheat_106",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_6"),
                "wheat_107",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=8, end_block=9),
                "wheat_108",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_8"),
                "wheat_109",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_8", target_moisture_pct=12.5),
                "wheat_110",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_8"),
                "wheat_111",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=10, end_block=11),
                "wheat_112",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_10"),
                "wheat_113",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_10", target_moisture_pct=12.5),
                "wheat_114",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_10"),
                "wheat_115",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=12, end_block=13),
                "wheat_116",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_12"),
                "wheat_117",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_12", target_moisture_pct=12.5),
                "wheat_118",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_12"),
                "wheat_119",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.tractor.harvest_blocks(start_block=14, end_block=15),
                "wheat_120",
                "Harvest native-mature blocks into the shared bin, preserving source IDs.",
            )
            previous = capture_step(
                previous,
                self.tractor.unload_grain(batch_id="wheat_14"),
                "wheat_121",
                "Transfer the bin to a unique warehouse batch before further harvest.",
            )
            previous = capture_step(
                previous,
                self.warehouse.dry_grain(batch_id="wheat_14", target_moisture_pct=12.5),
                "wheat_122",
                "Use the common dryer to reach the queried safe storage moisture.",
            )
            previous = capture_step(
                previous,
                self.warehouse.store_grain(batch_id="wheat_14"),
                "wheat_123",
                "Store the safe batch in the common warehouse.",
            )
            previous = capture_step(
                previous,
                self.accounts.get_accounts(),
                "wheat_124",
                "Query USD prices, actual costs, remaining resources and crop value.",
            )
        return finish_capture(self, events)
