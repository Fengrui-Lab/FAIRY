"""Winter wheat harvest scheduling with a daily dryer limit and delivery cutoff."""

from datetime import datetime
from functools import partial

from fairy.apps.farm_world.warehouse_app import WarehouseApp
from fairy.tool_utils import OperationType, app_tool
from fairy.types import EventRegisterer, event_registered
from fairy.utils.type_utils import type_check

from ..apps.winter_wheat_accounts_app import SEED
from ..common import capture_step, finish_capture
from ..engines.winter_wheat_inputs import fingerprint
from ..winter_wheat_setup import initialize_wheat_farm
from .scenario_winter_wheat_full_season import ScenarioWinterWheatFullSeason


class DeliveryWarehouse(WarehouseApp):
    """Admit safe wheat into the contracted store only through the cutoff."""

    def __init__(self, *args, cutoff, **kwargs):
        self.cutoff = cutoff
        super().__init__(*args, **kwargs)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def store_grain(self, batch_id: str) -> dict:
        """Store a pending batch at safe moisture before the delivery cutoff.

        Args:
            batch_id: Exact ID of the batch to admit into long-term storage.

        Returns:
            Batch and total stored kg at market moisture, or an error.
        """
        if self.time_manager.time() > self.cutoff:
            return {"error": "Safe-storage delivery cutoff exceeded"}
        return super().store_grain(batch_id)


class ScenarioWinterWheatDryingWindow(ScenarioWinterWheatFullSeason):
    scenario_id = "scenario_l3_winter_wheat_drying_window"
    default_late_harvest = False
    drying_capacity_kg_per_day = 3100.0
    ORACLE_REFERENCE = {
        "input_fingerprint": "447a6cb0fcf748b90c670094800617a099628c5543f46281c4014a7f183b4cbc",
        "selected": {
            "currency": "USD",
            "price_book_id": "winter_wheat_china_2025_owned_machinery_usd_v2",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"winter_wheat": 8133.120000000001},
            "stored_grain_kg": 8133.120000000001,
            "dry_grain_kg": 7491.008291936611,
            "production_cost": 447.4705870440282,
            "stored_grain_value": 2697.5522388059703,
            "net_operating_margin": 2250.0816517619423,
        },
        "workflow_steps": 138,
        "candidate_count": 4,
        "feasible_count": 3,
        "scope": "Best feasible margin among tested growth input and dryer schedules under the harvest window and delivery cutoff.",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        cutoff = datetime(2020, 6, 24, 23, 59, 59, tzinfo=self.simulation_timezone)
        self.duration = cutoff.timestamp() - self.start_time

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("Configure inputs at construction")
        initialize_wheat_farm(
            self,
            warehouse_factory=partial(
                DeliveryWarehouse, cutoff=self.start_time + self.duration
            ),
        )
        self.warehouse.drying_capacity_kg_per_day = self.drying_capacity_kg_per_day
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
                "cutoff": self.accounts.operation_deadline,
                "drying_capacity_kg_per_day": self.warehouse.drying_capacity_kg_per_day,
            }
        )

    def validate(self, env=None):
        result = super().validate(env)
        result.metadata.update(
            delivery_cutoff=self.accounts.operation_deadline,
            drying_capacity_kg_per_day=self.warehouse.drying_capacity_kg_per_day,
            drying_usage_by_date=self.warehouse.get_state()["drying_usage_by_date"],
            pending_grain_kg=self.warehouse.get_inventory()["harvest_grain_kg"],
        )
        return result

    def task_description(self, detailed=True):
        task = (
            "经营一座面积10000平方米的冬小麦农场。收购合同要求在约定期限前完成整田收获和安全入库，"
            "合作仓库每天为本农场预留的烘干量有限。根据天气和设施能力调度作业，提高净经营收益。"
        )
        if not detailed:
            return task + "通过OperatingAccounts.get_accounts查价格、库存和交付期限。"
        return task + (
            "\n\n秋播与越冬。检查播期、墒情、物资库存和价格，整平后分块条播，安排适量基肥并观察苗情。"
            "\n\n春季生长。返青后检查苗情和土壤氮，分阶段追肥。开花前观察冠层和墒情，安排灌水和追氮；"
            "临近开花和花后灌浆时关注根区水分。"
            "\n\n成熟与交付。提前核对合同截止时间、预计成熟进度、天气预报和烘干能力。"
            "在成熟且田间可作业的窗口收获，按粮箱和烘干设备容量拆分批次，当天用足可用烘干能力，"
            "其余湿粮暂存在库，留到后续日期烘干。下雨时仍可处理已经卸入仓库的湿粮。"
            "报告安全入库产量、实际成本和净经营收益。"
        )

    def build_events_flow(self):
        previous = None
        with EventRegisterer.capture_mode() as events:

            def step(event, reason):
                nonlocal previous
                previous = capture_step(
                    previous, event, f"delivery_{len(events):03d}", reason
                )

            def wait(day, seconds):
                step(self.system.advance_time(seconds=seconds), f"Advance to {day}.")

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
                "Check geometry, maturity and weather rules.",
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

            wait("2019-10-15", 1204600.0)
            step(self.weather.get_current_weather(), "Check autumn sowing weather.")
            step(self.sensor.read_root_zone_sensors(), "Check sowing moisture.")
            step(
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "Check that the prepared blocks are ready to sow.",
            )
            step(self.tractor.detach_implement(), "Free the tractor for the seeder.")
            step(self.tractor.attach_implement(implement="seeder"), "Mount the seeder.")
            for block in range(16):
                step(
                    self.tractor.load_seeds(
                        seed_type=SEED, count=self.resources.seeds_per_block
                    ),
                    "Load one block's seed within hopper capacity.",
                )
                step(
                    self.tractor.sow(start_block=block, end_block=block, depth_cm=3.0),
                    "Sow this block within the autumn window.",
                )
            fertilize(0, 15, 60)

            # Observed crop calendar, followed by kg pure N/ha and gross water depth in mm.
            for day, seconds, pure_n, water_mm in (
                ("2019-11-15", 2671884.0, 0, 0),
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

            # The dry window precedes two wet days. Process those days from the wet-grain buffer.
            for day, seconds, starts in (
                ("2020-06-22", 0, (0, 2, 4)),
                ("2020-06-23", 79680.0, (6, 8, 10)),
                ("2020-06-24", 86400.0, (12, 14)),
            ):
                if seconds:
                    wait(day, seconds)
                step(
                    self.warehouse.get_grain_batches(),
                    "Check pending grain for today’s dryer slots.",
                )
                for start in starts:
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
