"""L3：受轮灌时段和泵站流量约束的冬小麦全季经营。"""

from functools import partial
from typing import ClassVar

from fairy.types import EventRegisterer

from ..apps.winter_wheat_accounts_app import SEED
from ..apps.winter_wheat_turn_irrigation_app import WinterWheatTurnIrrigation
from ..common import capture_step, finish_capture
from ..engines.winter_wheat_inputs import fingerprint
from ..winter_wheat_setup import initialize_wheat_farm
from .scenario_winter_wheat_water_limit import ScenarioWinterWheatWaterLimit


class ScenarioWinterWheatIrrigationTurn(ScenarioWinterWheatWaterLimit):
    scenario_id = "scenario_l3_winter_wheat_irrigation_turn"
    default_late_harvest = False
    max_blocks = 8
    supply_windows = (
        ("2020-03-10T07:00:00+08:00", "2020-03-11T07:00:00+08:00"),
        ("2020-04-29T07:00:00+08:00", "2020-05-01T07:00:00+08:00"),
    )
    ORACLE_REFERENCE: ClassVar = {
        "scenario_id": scenario_id,
        "input_fingerprint": "16fcb9b0b1d564a4d9b0a47103c8b216e176e8733f43229b39d7c48b48b18eba",
        "selected": {
            "currency": "USD",
            "price_book_id": "winter_wheat_china_2025_owned_machinery_usd_v2",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"winter_wheat": 7348.0},
            "stored_grain_kg": 7348.0,
            "dry_grain_kg": 6767.876817427793,
            "production_cost": 350.03087857955046,
            "stored_grain_value": 2437.1475953565505,
            "net_operating_margin": 2087.116716777,
        },
        "workflow_steps": 99,
        "candidate_count": 12,
        "feasible_count": 12,
        "scope": "Highest simulated margin among fixed plans varying depth, turn use "
        "and start time, including late starts that redistribute the remaining time.",
    }

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("Configure inputs at construction")
        initialize_wheat_farm(
            self,
            irrigation_factory=partial(
                WinterWheatTurnIrrigation,
                max_blocks=self.max_blocks,
                supply_windows=self.supply_windows,
            ),
        )
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
        return fingerprint(
            {
                "wheat": super().input_fingerprint(),
                "station_max_blocks": self.max_blocks,
                "supply_windows": self.supply_windows,
            }
        )

    def task_description(self, detailed=True):
        basic = (
            f"经营一座面积{self.resources.area_ha * 10000:g}平方米的冬小麦农场。"
            "泵站轮流给不同农户供水，只在本农场的轮次内供水，能同时灌溉的地块有限。"
            "完成秋播、越冬、成熟收获与安全入库，在供水和物资约束下提高净经营收益。"
        )
        if not detailed:
            return basic + (
                "通过OperatingAccounts.get_accounts查价格与物资，通过Irrigation.get_supply_schedule查轮次和泵站能力。"
            )
        return basic + (
            "\n\n核对播种条件、农机容量、物资价格和各次供水的起止时间。"
            "秋播前整平并分块条播，安排底肥，越冬后检查苗情和根区水氮，决定追肥及是否需要补水。"
            "\n\n开花前结合冠层生长与根区墒情安排主要补水。把装置准备时间和灌水用时一起计入轮次，"
            "提前给各批地块留足时间，并核对配额和土壤变化。灌浆期复查长势和墒情。"
            "\n\n成熟后确认作业天气，按粮箱容量分批收获和卸粮，核对水分后干燥入库。"
            "报告实际入库量、成本和净经营收益。"
        )

    def build_events_flow(self):
        previous = None
        with EventRegisterer.capture_mode() as events:

            def step(event, reason):
                nonlocal previous
                previous = capture_step(
                    previous, event, f"turn_{len(events):03d}", reason
                )

            step(self.aui.send_message_to_agent(self.scenario_input), "Read the task.")
            step(self.farm.get_field_info(), "Read geometry and sowing rules.")
            step(self.accounts.get_accounts(), "Check prices and water allocation.")
            step(
                self.irrigation.get_supply_schedule(), "Plan the shared station turns."
            )
            step(self.tractor.attach_implement(implement="grader"), "Mount the grader.")
            step(self.tractor.prepare_field(), "Prepare the field.")
            step(
                self.system.advance_time(seconds=2068600),
                "Wait for the autumn sowing date.",
            )
            step(self.sensor.read_root_zone_sensors(), "Check seedbed moisture.")
            step(self.tractor.detach_implement(), "Remove the grader.")
            step(self.tractor.attach_implement(implement="seeder"), "Mount the seeder.")
            for block in range(16):
                step(
                    self.tractor.load_seeds(
                        seed_type=SEED, count=self.resources.seeds_per_block
                    ),
                    "Load seed within hopper capacity.",
                )
                step(
                    self.tractor.sow(start_block=block, end_block=block, depth_cm=3.0),
                    "Sow the block.",
                )

            for n, reason in ((33, "basal"), (132, "spring")):
                if reason == "spring":
                    step(
                        self.system.advance_time(seconds=11830284),
                        "Advance through winter.",
                    )
                    step(
                        self.sensor.read_root_zone_sensors(),
                        "Check water and nitrogen after winter.",
                    )
                    step(
                        self.sensor.read_canopy_sensors(),
                        "Check spring canopy development.",
                    )
                product_kg = (
                    n
                    * (self.resources.area_ha / 16)
                    / self.resources.fertilizer_n_fraction
                )
                step(
                    self.tractor.load_fertilizer(kg=product_kg * 16),
                    f"Load {reason} urea.",
                )
                for start, end in ((0, 9), (10, 15)):
                    step(
                        self.tractor.fertilize(
                            start_block=start, end_block=end, kg_per_block=product_kg
                        ),
                        f"Apply {reason} urea within pass capacity.",
                    )

            step(
                self.system.advance_time(seconds=4318380),
                "Reach the start of the main station turn.",
            )
            step(
                self.sensor.read_root_zone_sensors(),
                "Check water deficit ahead of flowering.",
            )
            step(self.sensor.read_canopy_sensors(), "Confirm canopy development.")
            step(self.weather.get_current_weather(), "Check current weather.")
            step(
                self.irrigation.get_supply_schedule(),
                "Confirm both batches fit the remaining turn.",
            )
            for start in (0, 8):
                step(
                    self.irrigation.irrigate(
                        start_block=start, end_block=start + 7, depth_mm=100
                    ),
                    "Supply one batch within station capacity.",
                )

            step(self.system.advance_time(seconds=1237800), "Advance to grain fill.")
            step(
                self.sensor.read_root_zone_sensors(),
                "Recheck moisture after native settlement.",
            )
            step(self.sensor.read_canopy_sensors(), "Recheck the crop.")
            step(
                self.system.advance_time(seconds=3283200),
                "Wait for mature blocks and harvest weather.",
            )
            step(
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "Confirm maturity across both irrigation groups.",
            )
            step(self.weather.get_current_weather(), "Confirm harvest weather.")
            step(self.tractor.detach_implement(), "Remove the seeder.")
            step(
                self.tractor.attach_implement(implement="harvester"),
                "Mount the harvester.",
            )
            for start in range(0, 16, 2):
                batch = f"wheat_{start}"
                step(
                    self.tractor.harvest_blocks(start_block=start, end_block=start + 1),
                    "Harvest mature blocks within bin capacity.",
                )
                step(self.tractor.unload_grain(batch_id=batch), "Unload the batch.")
                step(
                    self.warehouse.dry_grain(batch_id=batch, target_moisture_pct=12.5),
                    "Dry to safe storage moisture.",
                )
                step(self.warehouse.store_grain(batch_id=batch), "Store the dry batch.")
            step(
                self.accounts.get_accounts(), "Read actual production costs and margin."
            )
        return finish_capture(self, events)
