"""L3：冬小麦全季经营；题设、初始化、评估入口和完整Oracle均在本文件。"""

from datetime import date, datetime
from pathlib import Path
from typing import ClassVar
from zoneinfo import ZoneInfo

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.scenarios.scenario import Scenario
from fairy.types import EventRegisterer
from ..apps.winter_wheat_app import (
    WheatResources,
    WinterWheatApp,
    WinterWheatRuntime,
)
from ..engines.winter_wheat_wofost import InputBundle, WinterWheatBackend
from ..evaluation.winter_wheat import evaluate
from ..common import capture_step, finish_capture


class ScenarioWinterWheatFullSeason(Scenario):
    scenario_id = "scenario_l3_winter_wheat_full_season"
    level = "L3"
    objective_metric = "net_operating_margin"
    resources: ClassVar = WheatResources()
    ORACLE_REFERENCE: ClassVar = {
        "scenario_id": "scenario_l3_winter_wheat_full_season",
        "input_fingerprint": "e5a07272cfa8052238a68be37d75e4fc65b7ffa431666ebc3532395bb672648b",
        "selected": {
            "currency": "USD",
            "price_book_id": "winter_wheat_china_2025_usd_v1",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"winter_wheat": 8561.152333641845},
            "stored_grain_kg": 8561.152333641845,
            "dry_grain_kg": 7491.008291936614,
            "production_cost": 568.0818574642316,
            "stored_grain_value": 2839.519845320678,
            "net_operating_margin": 2271.4379878564464,
        },
        "workflow_steps": 45,
        "candidate_count": 401,
        "feasible_count": 329,
        "scope": "Best feasible net operating margin in the actually executed staged candidate search "
        "over water/N totals, splits, sowing dates, three/four-application schedules and spring "
        "timing, cross-scenario transfers and matched low-input controls. Official crop "
        "parameters and weather unchanged. Not a global optimum or a China field calibration.",
        "search_artifact": "validation_runs/winter_wheat_integration_20261104/search_four_phase/selection.json",
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
            raise ValueError(
                "Winter wheat requires its declared native WOFOST input bundle"
            )
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
        bundle = InputBundle(self.input_dir)
        if bundle.season.start != date(2019, 10, 1) or bundle.season.deadline != date(
            2020, 7, 15
        ):
            raise ValueError(
                "This frozen workflow requires the declared autumn-to-summer input season"
            )
        self.world = WinterWheatApp(
            WinterWheatRuntime(WinterWheatBackend(bundle), self.resources)
        )
        self.aui = AgentUserInterface()
        self.apps = [self.aui, self.world]
        self.scenario_input = (
            self._input_override
            if self._input_override is not None
            else self.task_description(self.detailed_briefing)
        )
        self.additional_system_prompt = (
            self._system_override if self._has_system_override else self.scenario_input
        )
        self.build_events_flow()

    @property
    def prices(self):
        return self.world.runtime.accounts()["prices"]

    def input_fingerprint(self):
        return self.world.crop_backend_provenance()["config_fingerprint"]

    def validate(self, env=None):
        return evaluate(self, env)

    def task_description(self, detailed=True):
        basic = (
            f"管理一块面积{self.resources.area_ha * 10000:g}平方米的冬小麦田，完成秋播、越冬管理、成熟收获与安全入库，在资源约束内提高净经营收益。"
            "供水与尿素库存有限，每次田间服务均计入成本。"
            "通过WinterWheat.get_field_info查询播期、用种和作业条件，通过WinterWheat.get_accounts查询价格、库存与预算。"
        )
        if not detailed:
            return basic
        return (
            basic
            + "先查询资料，再使用WinterWheat.observe检查原生生育状态、土壤水氮估计和上一完整日天气。"
            "播前核对窗口并整地，结合土壤情况安排秋播与投入；越冬期间保持同一作物和土壤连续推进，可合并等待并定期复查。"
            "春季结合生育进展与水氮变化比较分次投入的收益和费用，处理后等待模型结算，再检查响应。"
            "花后继续检查长势、库存和账本，确认原生成熟后收获、干燥并入库。土壤水氮是模型估计，不能当成独立化验。"
            "具体剂量、日期和限额均从工具查询，完成后报告产量、实际成本和净经营收益。"
        )

    def build_events_flow(self):
        previous = None
        with EventRegisterer.capture_mode() as events:
            previous = capture_step(
                previous,
                self.aui.send_message_to_agent(self.scenario_input),
                "task",
                "Read the field task and query conditions before management.",
            )
            previous = capture_step(
                previous,
                self.world.get_field_info(),
                "wheat_001",
                "Read area, sowing window, seed requirement and native harvest rules.",
            )
            previous = capture_step(
                previous,
                self.world.get_accounts(),
                "wheat_002",
                "Read current USD prices, remaining resources and actual accounts.",
            )
            previous = capture_step(
                previous,
                self.world.observe(),
                "wheat_003",
                "Check native crop stage, modeled root-zone water/N and completed-day weather.",
            )
            previous = capture_step(
                previous,
                self.world.prepare_field(operation_id="prepare"),
                "wheat_004",
                "Prepare the single field through its quoted service before sowing.",
            )
            previous = capture_step(
                previous,
                self.world.wait(days=14),
                "wheat_005",
                "Advance the shared clock; settle every intervening native calendar day without a year reset.",
            )
            previous = capture_step(
                previous,
                self.world.observe(),
                "wheat_006",
                "Check native crop stage, modeled root-zone water/N and completed-day weather.",
            )
            previous = capture_step(
                previous,
                self.world.sow(operation_id="sow"),
                "wheat_007",
                "Sow within the queried autumn window; keep official cultivar parameters unchanged.",
            )
            previous = capture_step(
                previous,
                self.world.apply_nitrogen(
                    operation_id="nitrogen_0", nitrogen_kg_ha=60.0
                ),
                "wheat_008",
                "Apply elemental N; consume the corresponding actual mass of urea product.",
            )
            previous = capture_step(
                previous,
                self.world.wait(days=31),
                "wheat_009",
                "Advance the shared clock; settle every intervening native calendar day without a year reset.",
            )
            previous = capture_step(
                previous,
                self.world.observe(),
                "wheat_010",
                "Check native crop stage, modeled root-zone water/N and completed-day weather.",
            )
            previous = capture_step(
                previous,
                self.world.wait(days=61),
                "wheat_011",
                "Advance the shared clock; settle every intervening native calendar day without a year reset.",
            )
            previous = capture_step(
                previous,
                self.world.observe(),
                "wheat_012",
                "Check native crop stage, modeled root-zone water/N and completed-day weather.",
            )
            previous = capture_step(
                previous,
                self.world.wait(days=43),
                "wheat_013",
                "Advance the shared clock; settle every intervening native calendar day without a year reset.",
            )
            previous = capture_step(
                previous,
                self.world.observe(),
                "wheat_014",
                "Check native crop stage, modeled root-zone water/N and completed-day weather.",
            )
            previous = capture_step(
                previous,
                self.world.apply_nitrogen(
                    operation_id="nitrogen_1", nitrogen_kg_ha=70.0
                ),
                "wheat_015",
                "Apply elemental N; consume the corresponding actual mass of urea product.",
            )
            previous = capture_step(
                previous,
                self.world.wait(days=3),
                "wheat_016",
                "Advance the shared clock; settle every intervening native calendar day without a year reset.",
            )
            previous = capture_step(
                previous,
                self.world.observe(),
                "wheat_017",
                "Check native crop stage, modeled root-zone water/N and completed-day weather.",
            )
            previous = capture_step(
                previous,
                self.world.wait(days=31),
                "wheat_018",
                "Advance the shared clock; settle every intervening native calendar day without a year reset.",
            )
            previous = capture_step(
                previous,
                self.world.observe(),
                "wheat_019",
                "Check native crop stage, modeled root-zone water/N and completed-day weather.",
            )
            previous = capture_step(
                previous,
                self.world.wait(days=1),
                "wheat_020",
                "Advance the shared clock; settle every intervening native calendar day without a year reset.",
            )
            previous = capture_step(
                previous,
                self.world.observe(),
                "wheat_021",
                "Check native crop stage, modeled root-zone water/N and completed-day weather.",
            )
            previous = capture_step(
                previous,
                self.world.apply_nitrogen(
                    operation_id="nitrogen_2", nitrogen_kg_ha=60.0
                ),
                "wheat_022",
                "Apply elemental N; consume the corresponding actual mass of urea product.",
            )
            previous = capture_step(
                previous,
                self.world.irrigate(operation_id="water_0", depth_mm=50.0),
                "wheat_023",
                "Purchase gross irrigation water and queue the declared effective native input.",
            )
            previous = capture_step(
                previous,
                self.world.wait(days=18),
                "wheat_024",
                "Advance the shared clock; settle every intervening native calendar day without a year reset.",
            )
            previous = capture_step(
                previous,
                self.world.observe(),
                "wheat_025",
                "Check native crop stage, modeled root-zone water/N and completed-day weather.",
            )
            previous = capture_step(
                previous,
                self.world.apply_nitrogen(
                    operation_id="nitrogen_3", nitrogen_kg_ha=40.0
                ),
                "wheat_026",
                "Apply elemental N; consume the corresponding actual mass of urea product.",
            )
            previous = capture_step(
                previous,
                self.world.irrigate(operation_id="water_1", depth_mm=50.0),
                "wheat_027",
                "Purchase gross irrigation water and queue the declared effective native input.",
            )
            previous = capture_step(
                previous,
                self.world.wait(days=15),
                "wheat_028",
                "Advance the shared clock; settle every intervening native calendar day without a year reset.",
            )
            previous = capture_step(
                previous,
                self.world.observe(),
                "wheat_029",
                "Check native crop stage, modeled root-zone water/N and completed-day weather.",
            )
            previous = capture_step(
                previous,
                self.world.irrigate(operation_id="water_2", depth_mm=50.0),
                "wheat_030",
                "Purchase gross irrigation water and queue the declared effective native input.",
            )
            previous = capture_step(
                previous,
                self.world.wait(days=10),
                "wheat_031",
                "Advance the shared clock; settle every intervening native calendar day without a year reset.",
            )
            previous = capture_step(
                previous,
                self.world.observe(),
                "wheat_032",
                "Check native crop stage, modeled root-zone water/N and completed-day weather.",
            )
            previous = capture_step(
                previous,
                self.world.wait(days=5),
                "wheat_033",
                "Advance the shared clock; settle every intervening native calendar day without a year reset.",
            )
            previous = capture_step(
                previous,
                self.world.observe(),
                "wheat_034",
                "Check native crop stage, modeled root-zone water/N and completed-day weather.",
            )
            previous = capture_step(
                previous,
                self.world.irrigate(operation_id="water_3", depth_mm=50.0),
                "wheat_035",
                "Purchase gross irrigation water and queue the declared effective native input.",
            )
            previous = capture_step(
                previous,
                self.world.wait(days=12),
                "wheat_036",
                "Advance the shared clock; settle every intervening native calendar day without a year reset.",
            )
            previous = capture_step(
                previous,
                self.world.observe(),
                "wheat_037",
                "Check native crop stage, modeled root-zone water/N and completed-day weather.",
            )
            previous = capture_step(
                previous,
                self.world.wait(days=19),
                "wheat_038",
                "Advance the shared clock; settle every intervening native calendar day without a year reset.",
            )
            previous = capture_step(
                previous,
                self.world.observe(),
                "wheat_039",
                "Check native crop stage, modeled root-zone water/N and completed-day weather.",
            )
            previous = capture_step(
                previous,
                self.world.harvest(operation_id="harvest"),
                "wheat_040",
                "Require native DOM maturity and recover the native TWSO dry matter once.",
            )
            previous = capture_step(
                previous,
                self.world.dry_grain(operation_id="dry"),
                "wheat_041",
                "Pay for actual drying throughput; remove water while preserving grain dry matter.",
            )
            previous = capture_step(
                previous,
                self.world.store_grain(operation_id="store"),
                "wheat_042",
                "Store the safe-moisture grain lot within physical capacity.",
            )
            previous = capture_step(
                previous,
                self.world.get_accounts(),
                "wheat_043",
                "Read current USD prices, remaining resources and actual accounts.",
            )
            capture_step(
                previous,
                self.aui.send_message_to_user(
                    "冬小麦管理流程结束；产量、资源消耗和经营收益以实际原生结果与账本为准。"
                ),
                "finish",
                "Report actual stored grain and accounts without inventing results.",
            )
        return finish_capture(self, events)
