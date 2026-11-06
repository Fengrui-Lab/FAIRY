"""Winter wheat with two lease handover dates and independent block sowing."""
from fairy.scenarios.management_extensions.oracle_time import oracle_time_arguments

from dataclasses import replace
from datetime import date

from fairy.tool_utils import OperationType, app_tool
from fairy.types import EventRegisterer, event_registered

from ..apps.winter_wheat_farm_app import DEFINITION, WinterWheatFarm
from ..apps.winter_wheat_accounts_app import SEED
from ..common import capture_step, finish_capture
from ..engines.winter_wheat_inputs import fingerprint
from ..winter_wheat_setup import initialize_wheat_farm
from .scenario_winter_wheat_full_season import ScenarioWinterWheatFullSeason


class StaggeredHandoverWheatFarm(WinterWheatFarm):
    """The lease permits pre-sowing preparation; sowing requires handover."""

    late_handover_blocks = tuple(range(8, 16))
    late_handover_date = date(2019, 10, 24)
    _crop_definition = replace(
        DEFINITION,
        planting_rules=replace(DEFINITION.planting_rules, respect_scenario_window=True),
    )

    @property
    def crop_definition(self):
        return self._crop_definition

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_field_info(self) -> dict:
        """Query block layout, sowing dates, and lease handover.

        Returns:
            Common wheat rules and each block's earliest authorized local
            sowing date. Planting still requires suitable soil.
        """
        result = super().get_field_info()
        for block in result["blocks"]:
            handover = (
                self.late_handover_date
                if block["block_id"] in self.late_handover_blocks
                else self.bundle.season.sowing_open
            )
            block["sowing_authorized_from"] = handover.isoformat()
        result["lease"] = (
            "Field preparation is authorized before handover; sowing is not."
        )
        return result

    def check_planting_window(self, ridge_ids, seed_type):
        error = super().check_planting_window(ridge_ids, seed_type)
        if error:
            return error
        blocked = [i for i in ridge_ids if i in self.late_handover_blocks]
        if blocked and self.simulation_date() < self.late_handover_date:
            return f"Blocks {blocked} are not authorized for sowing until {self.late_handover_date}"
        return None


class ScenarioWinterWheatStaggeredSowing(ScenarioWinterWheatFullSeason):
    scenario_id = "scenario_l3_winter_wheat_staggered_sowing"
    default_late_harvest = False
    ORACLE_REFERENCE = {
        "input_fingerprint": "229124d9805044fdcaf232c8ea1a95c0af9ad033376554d5b50ba250c95ad4ff",
        "selected": {
            "currency": "USD",
            "price_book_id": "winter_wheat_china_2025_owned_machinery_usd_v2",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"winter_wheat": 7957.919999999999},
            "stored_grain_kg": 7957.919999999999,
            "dry_grain_kg": 7329.6518737624165,
            "production_cost": 446.493957586275,
            "stored_grain_value": 2639.4427860696514,
            "net_operating_margin": 2192.9488284833765,
        },
        "workflow_steps": 139,
        "candidate_count": 9,
        "feasible_count": 9,
        "scope": "Best margin in a finite trial of early and late sow dates with identical spring inputs.",
    }

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("Configure inputs at construction")
        initialize_wheat_farm(self, farm_class=StaggeredHandoverWheatFarm)
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
                "late_handover_blocks": self.farm.late_handover_blocks,
                "late_handover_date": self.farm.late_handover_date.isoformat(),
            }
        )

    def task_description(self, detailed=True):
        task = (
            "经营一座面积10000平方米的冬小麦农场。租约允许先整地，但部分地块需等退租验收完成后才可播种。"
            "查看各块交接时间与秋播条件，完成收获和安全入库，提高全季净经营收益。"
        )
        if not detailed:
            return task + "通过OperatingAccounts.get_accounts查价格和物资库存。"
        return task + (
            "\n\n秋播与越冬。先核对价格、物资库存、地块交接日期和土壤墒情。先为已交接且条件合适的地块安排条播和基肥，"
            "其余地块交接后重新检查条件再作业。出苗后分别查看两批苗情。"
            "\n\n春季生长。返青时核对根区氮和苗情，分段追肥。开花前按生育进程和墒情安排追肥与补水，"
            "临近开花和花后灌浆时继续检查水分。"
            "\n\n成熟与入库。分别确认各批地块成熟，再按作业天气和粮箱容量分批收获、干燥入库。"
            "报告入库产量、实际成本和净经营收益。"
        )

    def build_events_flow(self):
        previous = None
        with EventRegisterer.capture_mode() as events:

            def step(event, reason):
                nonlocal previous
                previous = capture_step(
                    previous, event, f"sow_{len(events):03d}", reason
                )

            def wait(day, seconds):
                step(self.system.advance_time(**oracle_time_arguments(seconds)), f"Advance to {day}.")

            def observe():
                step(
                    self.sensor.read_root_zone_sensors(),
                    "Inspect root-zone water and nitrogen.",
                )
                step(
                    self.sensor.read_canopy_sensors(),
                    "Compare crop development and canopy.",
                )
                step(
                    self.farm.inspect_blocks(start_block=0, end_block=15),
                    "Inspect field conditions and crop development.",
                )

            def fertilize(start, end, pure_n_kg_ha):
                block_area_ha = self.farm.ridge_area_m2 / 10000
                kg_per_block = (
                    pure_n_kg_ha * block_area_ha / self.resources.fertilizer_n_fraction
                )
                step(
                    self.tractor.load_fertilizer(kg=kg_per_block * (end - start + 1)),
                    "Load the urea product for this application.",
                )
                for block in range(start, end + 1, 10):
                    step(
                        self.tractor.fertilize(
                            start_block=block,
                            end_block=min(block + 9, end),
                            kg_per_block=kg_per_block,
                        ),
                        "Apply the planned nitrogen to this group.",
                    )

            step(self.aui.send_message_to_agent(self.scenario_input), "Read the task.")
            step(
                self.farm.get_field_info(),
                "Read the sowing authorization for each block.",
            )
            step(
                self.accounts.get_accounts(),
                "Check inventory, prices, and operating limits.",
            )
            step(self.tractor.get_status(), "Check machine and payload capacities.")
            step(self.tractor.attach_implement(implement="grader"), "Mount the grader.")
            step(
                self.tractor.prepare_field(),
                "Prepare the whole field before autumn sowing.",
            )

            for day, seconds, start, end in (
                ("2019-10-11", 859000.0, 0, 7),
                ("2019-10-24", 1119942.0, 8, 15),
            ):
                wait(day, seconds)
                step(
                    self.weather.get_current_weather(),
                    "Check sowing weather after handover.",
                )
                step(
                    self.sensor.read_root_zone_sensors(),
                    "Check sowing moisture in the released blocks.",
                )
                step(
                    self.farm.inspect_blocks(start_block=start, end_block=end),
                    "Confirm the released blocks are unplanted and suitable.",
                )
                if start == 0:
                    step(
                        self.tractor.detach_implement(),
                        "Free the tractor for the seeder.",
                    )
                    step(
                        self.tractor.attach_implement(implement="seeder"),
                        "Mount the seeder.",
                    )
                for block in range(start, end + 1):
                    step(
                        self.tractor.load_seeds(
                            seed_type=SEED, count=self.resources.seeds_per_block
                        ),
                        "Load one block's seed within hopper capacity.",
                    )
                    step(
                        self.tractor.sow(
                            start_block=block, end_block=block, depth_cm=3.0
                        ),
                        "Sow this released block within the autumn window.",
                    )
                fertilize(start, end, 60)

            # Observed crop calendar, followed by kg pure N/ha and gross water depth in mm.
            for day, seconds, pure_n, water_mm in (
                ("2019-11-15", 1897542.0, 0, 0),
                ("2020-01-15", 5270400.0, 0, 0),
                ("2020-02-27", 3715200.0, 70, 0),
                ("2020-04-02", 3022380.0, 60, 50),
                ("2020-04-20", 1517280.0, 40, 50),
                ("2020-05-05", 1258080.0, 0, 50),
                ("2020-05-20", 1259700.0, 0, 50),
                ("2020-06-20", 2642100.0, 0, 0),
            ):
                wait(day, seconds)
                observe()
                if pure_n:
                    fertilize(0, 15, pure_n)
                if water_mm:
                    step(
                        self.irrigation.irrigate(
                            start_block=0, end_block=15, depth_mm=water_mm
                        ),
                        "Deliver the planned gross water depth to the crop.",
                    )

            step(self.weather.get_forecast(days=7), "Identify the dry harvest window.")
            wait("2020-06-22", 172800.0)
            step(
                self.weather.get_current_weather(),
                "Confirm that today's weather permits harvest.",
            )
            step(
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "Confirm all blocks have reached native maturity.",
            )
            step(
                self.warehouse.get_inventory(), "Check storage and drying constraints."
            )
            step(self.tractor.detach_implement(), "Free the tractor for the harvester.")
            step(
                self.tractor.attach_implement(implement="harvester"),
                "Mount the harvester.",
            )
            step(
                self.tractor.refuel(liters=50.0),
                "Refuel for the remaining harvest passes.",
            )
            for start in range(0, 16, 2):
                step(
                    self.tractor.harvest_blocks(start_block=start, end_block=start + 1),
                    "Harvest two adjacent blocks within the grain bin capacity.",
                )
                step(
                    self.tractor.unload_grain(batch_id=f"wheat_{start}"),
                    "Unload into a distinct warehouse batch.",
                )

            step(
                self.warehouse.get_grain_batches(),
                "Check pending batches and moisture.",
            )
            for start in range(0, 16, 2):
                batch = f"wheat_{start}"
                step(
                    self.warehouse.dry_grain(
                        batch_id=batch,
                        target_moisture_pct=self.resources.storage_moisture_pct,
                    ),
                    "Dry the pending grain to safe moisture.",
                )
                step(
                    self.warehouse.store_grain(batch_id=batch),
                    "Admit the safe grain to storage.",
                )

            step(
                self.accounts.get_accounts(),
                "Read final safe grain, costs, and net margin.",
            )
        return finish_capture(self, events)
