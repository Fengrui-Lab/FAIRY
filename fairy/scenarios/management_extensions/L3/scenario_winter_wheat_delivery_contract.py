"""Fulfill a fixed winter wheat delivery at the lowest actual operating cost."""

from typing import ClassVar

from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.tool_utils import OperationType, app_tool
from fairy.types import EventRegisterer, event_registered

from ..apps.winter_wheat_accounts_app import SEED
from ..apps.winter_wheat_farm_app import WinterWheatFarm
from ..common import capture_step, finish_capture
from ..engines.winter_wheat_inputs import fingerprint
from ..winter_wheat_setup import initialize_wheat_farm
from .scenario_winter_wheat_full_season import ScenarioWinterWheatFullSeason


MINIMUM_DELIVERY_KG = 7600.0


class DeliveryContractWheatFarm(WinterWheatFarm):
    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_field_info(self) -> dict:
        """Read block geometry, operation rules and the wheat delivery contract.

        Returns:
            dict: Block areas (m²), sowing and harvest rules, contract delivery
            weight (kg of safely stored grain) and the USD cost objective.
        """
        result = super().get_field_info()
        result["delivery_contract"] = {
            "minimum_stored_grain_kg": MINIMUM_DELIVERY_KG,
            "storage_moisture_pct": self.resources.storage_moisture_pct,
            "complete_all_blocks": True,
            "objective": "minimize actual production cost in USD",
        }
        return result


class ScenarioWinterWheatDeliveryContract(ScenarioWinterWheatFullSeason):
    scenario_id = "scenario_l3_winter_wheat_delivery_contract"
    objective_metric = "production_cost"
    ORACLE_REFERENCE: ClassVar = {
        "scenario_id": "scenario_l3_winter_wheat_delivery_contract",
        "input_fingerprint": "79bea3174ff111097a2608644c7ffbcd2808c018c06ab868c81054b9c6526330",
        "selected": {
            "currency": "USD",
            "price_book_id": "winter_wheat_china_2025_owned_machinery_usd_v2",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"winter_wheat": 7628.0},
            "stored_grain_kg": 7628.0,
            "dry_grain_kg": 7025.794554332149,
            "production_cost": 355.1362735387455,
            "stored_grain_value": 2530.016583747927,
            "net_operating_margin": 2174.8803102091815,
        },
        "minimum_stored_grain_kg": MINIMUM_DELIVERY_KG,
        "workflow_steps": 142,
        "candidate_count": 32,
        "feasible_count": 17,
        "scope": "Lowest production cost among the contract-feasible trials. The tested "
        "grid varies seasonal nitrogen splits and two to four spring irrigation events "
        "at a fixed sowing date. Two policies tied; equal depths were selected.",
        "search_artifact": "validation_runs/wheat_next_delivery_contract/selection.json",
    }

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("Configure inputs at construction")
        initialize_wheat_farm(self, farm_class=DeliveryContractWheatFarm)
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
                "farm_inputs": super().input_fingerprint(),
                "minimum_stored_grain_kg": MINIMUM_DELIVERY_KG,
            }
        )

    def validate(self, env=None):
        result = super().validate(env)
        shortfall = max(0.0, MINIMUM_DELIVERY_KG - result.metadata["stored_grain_kg"])
        result.metadata.update(
            objective="minimize_production_cost",
            minimum_stored_grain_kg=MINIMUM_DELIVERY_KG,
            delivery_shortfall_kg=shortfall,
            delivery_requirement_met=shortfall <= 1e-7,
        )
        if shortfall <= 1e-7:
            return result
        unmet = f"Stored grain is {shortfall:.2f} kg below the minimum delivery"
        message = unmet if result.success else f"{result.message}. {unmet}"
        return ScenarioValidationResult(
            success=False, message=message, metadata=result.metadata
        )

    def task_description(self, detailed=True):
        task = (
            f"经营一座面积{self.resources.area_ha * 10000:g}平方米的冬小麦农场。"
            "完成全田秋播、越冬、成熟收获与安全入库，达到交付合同的最低入库重量，"
            "并把实际生产成本控制在尽可能低的水平。"
        )
        if not detailed:
            return (
                task
                + "通过WheatField.get_field_info查交付门槛和作业条件，通过OperatingAccounts.get_accounts查价格和资源。"
            )
        return task + (
            "\n\n播前核对交付门槛、地块条件、设备容量、物资库存和价格。"
            "\n\n秋播与越冬。整平后分块条播，结合底墒和根区供氮判断是否可把追肥留到春季。"
            "出苗后查看苗情，越冬期间与返青前复查根区和冠层读数。"
            "\n\n春季管理。返青至拔节前，依据根区氮和冠层长势分次安排追肥。"
            "从拔节到开花前，再到灌浆初期，结合天气和根区墒情安排补水。"
            "\n\n成熟与入库。检查成熟度和作业天气，分批收获、卸粮并核对含水率，"
            "按仓储要求处理后入库。报告实收重量、交付是否达标、实际成本和净经营收益。"
        )

    def build_events_flow(self):
        previous = None
        block_count = self.farm.num_ridges
        last_block = block_count - 1
        with EventRegisterer.capture_mode() as events:

            def step(event, reason):
                nonlocal previous
                previous = capture_step(
                    previous, event, f"delivery_{len(events):03d}", reason
                )

            def observe():
                step(
                    self.sensor.read_root_zone_sensors(),
                    "Check root-zone water and nitrogen before making input decisions.",
                )
                step(
                    self.sensor.read_canopy_sensors(),
                    "Check canopy development after the previous treatment.",
                )
                step(
                    self.farm.inspect_blocks(start_block=0, end_block=last_block),
                    "Confirm the phenological stage and block maturity.",
                )

            def advance(seconds, stage):
                step(self.system.advance_time(seconds=seconds), stage)
                observe()

            def apply_nitrogen(pure_n_kg_ha):
                total_kg = (
                    pure_n_kg_ha
                    * self.resources.area_ha
                    / self.resources.fertilizer_n_fraction
                )
                step(
                    self.tractor.load_fertilizer(kg=total_kg),
                    "Load the urea product mass corresponding to this nitrogen dose.",
                )
                for start in range(0, block_count, 10):
                    step(
                        self.tractor.fertilize(
                            start_block=start,
                            end_block=min(start + 9, last_block),
                            kg_per_block=total_kg / block_count,
                        ),
                        "Apply this dressing within the machine's block limit.",
                    )

            def irrigate(depth_mm):
                step(
                    self.weather.get_forecast(),
                    "Check upcoming rain before committing irrigation water.",
                )
                step(
                    self.irrigation.irrigate(
                        start_block=0, end_block=last_block, depth_mm=depth_mm
                    ),
                    "Supplement water during a yield-sensitive growth period.",
                )

            step(self.aui.send_message_to_agent(self.scenario_input), "Read the task.")
            step(
                self.farm.get_field_info(),
                "Read the fixed delivery minimum, block layout and operating rules.",
            )
            step(
                self.accounts.get_accounts(),
                "Check USD prices, budget and available stock.",
            )
            step(self.tractor.get_status(), "Check shared equipment and capacity.")
            step(self.tractor.attach_implement(implement="grader"), "Mount the grader.")
            step(self.tractor.prepare_field(), "Prepare a flat seedbed.")

            advance(1204600.0, "Reach the autumn sowing window.")
            step(self.tractor.detach_implement(), "Remove the grader after leveling.")
            step(self.tractor.attach_implement(implement="seeder"), "Mount the seeder.")
            for block in range(block_count):
                step(
                    self.tractor.load_seeds(
                        seed_type=SEED, count=self.resources.seeds_per_block
                    ),
                    "Load seed for the next block within hopper capacity.",
                )
                step(
                    self.tractor.sow(start_block=block, end_block=block, depth_cm=3.0),
                    "Sow the block at the recommended depth.",
                )

            # Waits account for the simulated time consumed by previous operations.
            advance(2673504.0, "Review post-emergence establishment.")
            advance(5270400.0, "Check the crop and soil through overwintering.")
            advance(3715200.0, "Check soil nitrogen as spring growth resumes.")
            apply_nitrogen(95.0)
            advance(257580.0, "Follow up on green-up and canopy growth.")
            advance(
                2764800.0,
                "Recheck soil nitrogen and canopy demand before stem elongation.",
            )
            apply_nitrogen(60.0)
            advance(1553580.0, "Assess water during stem elongation.")
            irrigate(45.0)
            advance(1263300.0, "Review root-zone water just before flowering.")
            irrigate(45.0)
            advance(831300.0, "Monitor early grain set after flowering.")
            advance(432000.0, "Reassess water supply during early grain filling.")
            irrigate(45.0)
            advance(
                1004100.0, "Check grain fill and monitor the approach to maturity."
            )
            advance(1641600.0, "Verify native maturity and inspect the harvest window.")
            step(self.weather.get_current_weather(), "Check for a dry harvest window.")
            advance(172800.0, "Wait for the next dry harvest window.")

            step(
                self.weather.get_current_weather(),
                "Verify harvest weather after all blocks reach native maturity.",
            )
            step(self.tractor.detach_implement(), "Remove the seeder before harvest.")
            step(
                self.tractor.attach_implement(implement="harvester"),
                "Mount the harvester.",
            )
            for start in range(0, block_count, 2):
                if start == 4:
                    step(
                        self.tractor.refuel(liters=50.0),
                        "Refill fuel to complete harvest.",
                    )
                batch_id = f"wheat_{start}"
                step(
                    self.tractor.harvest_blocks(
                        start_block=start, end_block=min(start + 1, last_block)
                    ),
                    "Recover the mature wheat within grain-bin capacity.",
                )
                step(
                    self.tractor.unload_grain(batch_id=batch_id),
                    "Unload recovered wheat into its warehouse batch.",
                )
                step(
                    self.warehouse.dry_grain(
                        batch_id=batch_id,
                        target_moisture_pct=self.resources.storage_moisture_pct,
                    ),
                    "Bring grain to the storage moisture standard.",
                )
                step(
                    self.warehouse.store_grain(batch_id=batch_id),
                    "Store the batch toward the delivery minimum.",
                )
            step(
                self.accounts.get_accounts(),
                "Read the delivered quantity and final actual costs.",
            )
        return finish_capture(self, events)
