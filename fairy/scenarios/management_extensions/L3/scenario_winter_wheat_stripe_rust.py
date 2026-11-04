"""L3 local wheat stripe rust: detect infection, target the focus, and verify."""

from pathlib import Path
import json

from .scenario_winter_wheat_full_season import ScenarioWinterWheatFullSeason
from ..apps.winter_wheat_rust_app import (
    PRODUCT_ID,
    StripeRustAccounts,
    StripeRustRobot,
    StripeRustWheatFarm,
    StripeRustWheatTractor,
    WheatRustProtection,
)
from ..apps.winter_wheat_scouting_apps import WheatScoutDrone
from ..engines.winter_wheat_inputs import fingerprint
from ..winter_wheat_setup import initialize_wheat_farm, wheat_fingerprint
from ..winter_wheat_workflow import capture_wheat_oracle

REFERENCE_PATH = (
    Path(__file__).parents[1]
    / "data"
    / "winter_wheat_oracles"
    / "scenario_l3_winter_wheat_stripe_rust.json"
)


class ScenarioWinterWheatStripeRust(ScenarioWinterWheatFullSeason):
    scenario_id = "scenario_l3_winter_wheat_stripe_rust"
    ORACLE_REFERENCE = None

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("Configure inputs at construction")
        initialize_wheat_farm(
            self,
            farm_class=StripeRustWheatFarm,
            tractor_factory=StripeRustWheatTractor,
            accounts_factory=StripeRustAccounts,
        )
        self.drone = WheatScoutDrone(self.farm_environment)
        self.robot = StripeRustRobot(self.farm_environment)
        self.protection = WheatRustProtection(self.farm, self.weather)
        self.accounts.protection = self.tractor.protection = self.protection
        new_apps = (self.drone, self.robot, self.protection)
        self.apps.extend(new_apps)
        for app in new_apps:
            app.register_time_manager(self.farm_environment.time_manager)
            app.rng.seed(self.seed)
        self.scenario_input = (
            self.task_description(self.detailed_briefing)
            if self._input_override is None
            else self._input_override
        )
        self.additional_system_prompt = (
            self._system_override if self._has_system_override else self.scenario_input
        )
        self.build_events_flow()

    def input_fingerprint(self):
        return fingerprint(
            {
                "wheat": wheat_fingerprint(self),
                "crop_protection": self.protection.catalog_fingerprint,
            }
        )

    def task_description(self, detailed=True):
        basic = (
            "经营一座面积10000平方米的冬小麦农场。完成全季管理和安全入库。"
            "春季有条锈病传播风险，结合田间证据控制病害，在水肥、药剂和服务开销下提高净经营收益。"
        )
        if not detailed:
            return (
                basic
                + "通过OperatingAccounts.get_accounts查资源和价格，通过药剂目录查可用产品与作业限制。"
            )
        return basic + (
            "\n\n先通过农场账本核对资源和价格，通过药剂目录了解防治成本与作业限制。"
            "\n\n十月中旬前后查看墒情和天气，合适时整平并分块播种。播种、返青和四月冠层扩展时结合根区水氮、苗情和库存分次管理。"
            "首轮尿素产品每块约8公斤，返青约9–10公斤，四月初和中下旬结合生长分别参考约8和5–6公斤。"
            "四月上中旬至五月灌浆，按墒情趋势和近期降雨分次补水，单轮可参考50毫米。"
            "\n\n四月中下旬的冷湿天气过后，先比较各区墒情、冠层和叶片。天气合适时用无人机圈定弱区，再用地面巡查比较异常块和邻块。"
            "叶脉方向成行的黄色孢子堆可以作为条锈病线索。证据不足时扩查，确认早期病灶时连同紧邻高风险块安排点片防治。"
            "先核对药剂标签、库存和用药天气，再按允许范围施药。约一周后回查原区和边缘，按标签完成疗程，留意新增病叶和病区是否扩张。"
            "\n\n开花和灌浆结合实际生育进度和墒情检查。六月中下旬确认成熟、天气和用药安全间隔均允许，再分批收获、干燥和安全入库。"
            "最后核对每个块的收获、粮批、投入及净经营收益。"
        )

    def build_events_flow(self):
        if self.calibrating:
            return []
        data = json.loads(REFERENCE_PATH.read_text())
        self.ORACLE_REFERENCE = data["reference"]
        return capture_wheat_oracle(self, data["steps"])


def run_rust_trial(trial, treatment):
    """Run one candidate through the public tools and record its replayable trace."""
    trial.sow("2019-10-15")
    trial.fertilize(60)
    for day, nitrogen, water in (
        ("2020-02-27", 70, 0),
        ("2020-04-02", 60, 50),
        ("2020-04-20", 40, 50),
    ):
        trial.goto(day)
        trial.observe()
        trial.fertilize(nitrogen)
        trial.irrigate(water)

    trial.call("protection", "get_products")
    trial.call(
        "drone",
        "survey_blocks",
        start_block=0,
        end_block=15,
        reason="Locate candidate weak canopy near the middle of the field.",
    )
    first = trial.call(
        "robot",
        "inspect_blocks",
        start_block=5,
        end_block=8,
        reason="Compare neighboring blocks and check leaf symptoms.",
    )
    trial.call("robot", "charge")
    blocks = {
        "focus_only": [(6, 7)],
        "spot": [(5, 8)],
        "wide_spot": [(4, 7), (8, 9)],
        "late": [(5, 8)],
        "blanket": [(i, i + 3) for i in range(0, 16, 4)],
        "no_treatment": [],
    }[treatment]
    if blocks:
        trial.call(
            "protection",
            "purchase",
            product_id=PRODUCT_ID,
            quantity=2 * 180.0 * sum(end - start + 1 for start, end in blocks) / 16,
            order_id="wheat_rust_product",
        )
    dates = (
        ("2020-04-24", "2020-05-01")
        if treatment == "late"
        else ("2020-04-20", "2020-04-27")
    )
    for pass_index, day in enumerate(dates):
        trial.goto(day)
        if pass_index == 1:
            trial.call(
                "drone",
                "survey_blocks",
                start_block=0,
                end_block=15,
                reason="Repeat the aerial survey to check the focus and its margins.",
            )
            trial.call(
                "robot",
                "inspect_blocks",
                start_block=5,
                end_block=8,
                reason="Check signs in the original blocks and adjacent margin.",
            )
        trial.call("weather", "get_current_weather")
        for start, end in blocks:
            trial.call(
                "protection",
                "spray_blocks",
                product_id=PRODUCT_ID,
                start_block=start,
                end_block=end,
                rate_per_ha=180.0,
                application_id=f"rust_{pass_index}_{start}",
                reason="Apply the selected rust-control policy within label and weather constraints.",
            )
    for day in ("2020-05-05", "2020-05-20"):
        trial.goto(day)
        trial.observe()
        trial.irrigate(50)
    trial.goto("2020-06-15")
    trial.harvest()
    return first
