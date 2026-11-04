"""Allocate a shared irrigation quota among winter wheat blocks with different soils."""

from copy import copy, deepcopy
from typing import ClassVar

from fairy.tool_utils import OperationType, app_tool
from fairy.types import EventRegisterer, event_registered

from ..apps.winter_wheat_accounts_app import SEED, WheatResources
from ..apps.winter_wheat_farm_app import WinterWheatFarm
from ..common import capture_step, finish_capture
from ..engines.winter_wheat_inputs import fingerprint
from ..winter_wheat_setup import initialize_wheat_farm
from .scenario_winter_wheat_full_season import ScenarioWinterWheatFullSeason


class SoilWaterWheatFarm(WinterWheatFarm):
    """The first eight blocks have a shallower, coarser rootable profile."""

    shallow_block_count = 8

    def block_inputs(self, block_id):
        if block_id >= self.shallow_block_count:
            return self.bundle
        inputs = copy(self.bundle)
        inputs.manifest = deepcopy(self.bundle.manifest)
        inputs.manifest["native_soil_parameters"].update(
            SMW=0.10, SMFCF=0.24, SM0=0.41, RDMSOL=60.0
        )
        inputs.manifest["native_site_parameters"].update(WAV=10.0, SMLIM=0.24)
        inputs.manifest["soil_status"] = (
            "benchmark shallow coarse soil, no local field calibration"
        )
        inputs.identity = fingerprint(inputs.manifest)
        return inputs

    def crop_backend_provenance(self):
        result = super().crop_backend_provenance()
        result["block_input_fingerprints"] = [
            block.bundle.identity for block in self.backends
        ]
        return result

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_field_info(self) -> dict:
        """Read block layout, soil profiles and wheat operation rules.

        Returns:
            dict: Block IDs and area (m²), field capacity and wilting point
            (m³/m³), rootable depth (cm), sowing and harvest rules. Soil
            properties are fixed; get current moisture from the probes.
        """
        field = super().get_field_info()
        field["soil_profiles"] = []
        for start, end in (
            (0, self.shallow_block_count - 1),
            (self.shallow_block_count, self.num_ridges - 1),
        ):
            soil = self.backends[start].bundle.manifest["native_soil_parameters"]
            field["soil_profiles"].append(
                {
                    "start_block": start,
                    "end_block": end,
                    "rootable_depth_cm": soil["RDMSOL"],
                    "field_capacity_vwc": soil["SMFCF"],
                    "wilting_point_vwc": soil["SMW"],
                }
            )
        return field


class ScenarioWinterWheatSoilWaterPriority(ScenarioWinterWheatFullSeason):
    scenario_id = "scenario_l3_winter_wheat_soil_water_priority"
    default_late_harvest = False
    resources: ClassVar = WheatResources(water_stock_m3=1000.0)
    ORACLE_REFERENCE: ClassVar = {
        "input_fingerprint": "fc9a451fdb95643fcef7b59b84cd2ee382d559cb41b394863e672e9b295f176a",
        "selected": {
            "currency": "USD",
            "price_book_id": "winter_wheat_china_2025_owned_machinery_usd_v2",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"winter_wheat": 6519.76},
            "stored_grain_kg": 6519.76,
            "dry_grain_kg": 6005.018250093803,
            "production_cost": 382.65769377077703,
            "stored_grain_value": 2162.441127694859,
            "net_operating_margin": 1779.783433924082,
        },
        "workflow_steps": 155,
        "candidate_count": 32,
        "feasible_count": 32,
        "scope": "Highest net operating margin among the executed irrigation and nitrogen treatments. "
        "Controls include equal water per date with uniform or reversed allocation, "
        "different timings, and reduced or zero inputs.",
    }

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("Configure inputs at construction")
        initialize_wheat_farm(self, farm_class=SoilWaterWheatFarm)
        self.scenario_input = (
            self.task_description(self.detailed_briefing)
            if self._input_override is None
            else self._input_override
        )
        self.additional_system_prompt = (
            self._system_override if self._has_system_override else self.scenario_input
        )
        self.build_events_flow()

    def task_description(self, detailed=True):
        task = (
            "经营一座面积10000平方米的冬小麦农场。地块的根系可达深度和保水能力不同，全场共用一季的灌溉水。"
            "完成秋播、越冬、分块收获和安全入库，在资源限制下提高净经营收益。"
        )
        if not detailed:
            return (
                task
                + "请查询土壤资料，并通过OperatingAccounts.get_accounts查询物资价格和剩余配额。"
            )
        return task + (
            "\n\n先查询土壤资料、物资价格和剩余配额。"
            "\n\n秋播与越冬。整平土地后分块条播，安排一部分氮肥。检查出苗和越冬长势，把灌溉水留给春季需水阶段。"
            "\n\n返青至孕穗。结合苗情和根区氮安排追肥。按各区的田间持水量、萎蔫点和根系可达深度解释探头读数，"
            "再核对逐块长势和天气，判断哪些地块需要先补水。"
            "\n\n临近开花和灌浆。根据前次补水后的墒情、降雨和长势，分次调整各区用水，给后续灌浆保留水量。"
            "\n\n成熟与入库。确认成熟及作业天气，按粮箱容量分批收获和卸粮，核对含水率后干燥入库。报告入库产量、用水、实际成本和净经营收益。"
        )

    def build_events_flow(self):
        previous = None
        with EventRegisterer.capture_mode() as events:

            def step(event, reason):
                nonlocal previous
                previous = capture_step(
                    previous, event, f"water_priority_{len(events):03d}", reason
                )

            def wait(seconds):
                step(
                    self.system.advance_time(seconds=seconds),
                    "Advance to the next field check.",
                )

            def observe():
                step(
                    self.sensor.read_root_zone_sensors(),
                    "Compare soil water and nitrogen across zones.",
                )
                step(
                    self.sensor.read_canopy_sensors(),
                    "Check canopy response in each soil zone.",
                )
                step(
                    self.farm.inspect_blocks(start_block=0, end_block=15),
                    "Confirm crop stage and block-level conditions.",
                )

            def apply_nitrogen(kg_n_ha, *, refuel_between_passes=False):
                product_kg = (
                    kg_n_ha
                    * self.resources.area_ha
                    / self.resources.fertilizer_n_fraction
                )
                step(
                    self.tractor.load_fertilizer(kg=product_kg),
                    "Load urea for the next application.",
                )
                for start, end in ((0, 9), (10, 15)):
                    if start and refuel_between_passes:
                        step(
                            self.tractor.refuel(liters=50.0),
                            "Refuel before the second pass.",
                        )
                    step(
                        self.tractor.fertilize(
                            start_block=start,
                            end_block=end,
                            kg_per_block=product_kg / self.resources.block_count,
                        ),
                        "Apply the planned nitrogen rate using the product's nitrogen fraction.",
                    )

            def irrigate(start, end, depth_mm, reason):
                step(
                    self.irrigation.irrigate(
                        start_block=start, end_block=end, depth_mm=depth_mm
                    ),
                    reason,
                )

            step(
                self.aui.send_message_to_agent(self.scenario_input),
                "Read the farm objective.",
            )
            step(
                self.farm.get_field_info(),
                "Read block layout and soil water capacity by zone.",
            )
            step(
                self.accounts.get_accounts(),
                "Read water quota, prices and input stocks.",
            )
            step(self.tractor.get_status(), "Check machine and hopper capacities.")
            step(
                self.tractor.attach_implement(implement="grader"),
                "Mount the levelling implement.",
            )
            step(self.tractor.prepare_field(), "Level the field before sowing.")

            # October 15: sow and apply the first nitrogen dose.
            wait(1_204_600.0)
            observe()
            step(self.tractor.detach_implement(), "Detach the levelling implement.")
            step(self.tractor.attach_implement(implement="seeder"), "Mount the seeder.")
            for block in range(self.resources.block_count):
                step(
                    self.tractor.load_seeds(
                        seed_type=SEED, count=self.resources.seeds_per_block
                    ),
                    "Load one block's seed within hopper capacity.",
                )
                step(
                    self.tractor.sow(start_block=block, end_block=block, depth_cm=3.0),
                    "Sow the prepared block in the autumn window.",
                )
            apply_nitrogen(45)

            # Emergence, winter and the first spring feeding.
            wait(2_671_884.0)
            observe()
            wait(5_270_400.0)
            observe()
            wait(3_715_200.0)
            observe()
            apply_nitrogen(65)
            wait(257_580.0)
            observe()

            # April 2: conserve water while both profiles are near field capacity.
            wait(2_764_800.0)
            observe()
            apply_nitrogen(55, refuel_between_passes=True)

            # April 20: the shallow profile has depleted faster during stem extension.
            wait(1_553_580.0)
            observe()
            apply_nitrogen(20)
            step(
                self.weather.get_current_weather(),
                "Check weather before the first irrigation.",
            )
            irrigate(
                0,
                7,
                35,
                "Prioritize the shallow blocks and reserve water for flowering and grain fill.",
            )

            # May 5: compare both profiles before flowering.
            wait(1_268_880.0)
            observe()
            step(
                self.weather.get_current_weather(),
                "Check weather before irrigating both profiles.",
            )
            irrigate(0, 7, 35, "Refill the depleted shallow profile before flowering.")
            irrigate(
                8,
                15,
                30,
                "Supply the deeper blocks after their initial reserve has declined.",
            )

            # May 15–16: check the flowering response and irrigate for early grain fill.
            wait(816_600.0)
            observe()
            wait(86_400.0)
            observe()
            step(
                self.weather.get_current_weather(),
                "Check weather during early grain fill.",
            )
            irrigate(
                0,
                7,
                30,
                "Maintain available water in the shallow profile during grain fill.",
            )
            irrigate(
                8, 15, 35, "Replenish the deeper profile through early grain fill."
            )

            # May 24: the shallow blocks need the final top-up.
            wait(643_800.0)
            observe()
            step(
                self.weather.get_current_weather(),
                "Check weather before using the remaining water.",
            )
            irrigate(
                0,
                7,
                35,
                "Use the remaining quota where relative root-zone water is lowest.",
            )

            # Recheck grain fill, maturity and the next legal harvest window.
            wait(665_700.0)
            observe()
            wait(1_641_600.0)
            observe()
            wait(172_800.0)
            observe()

            # Late June: both soil zones have matured and the weather is dry.
            step(self.weather.get_current_weather(), "Check weather before harvest.")
            step(
                self.tractor.detach_implement(), "Detach before mounting the harvester."
            )
            step(
                self.tractor.attach_implement(implement="harvester"),
                "Mount the harvester.",
            )
            for start in range(0, self.resources.block_count, 2):
                batch = f"wheat_{start}"
                step(
                    self.tractor.harvest_blocks(start_block=start, end_block=start + 1),
                    "Harvest two mature blocks within the grain bin capacity.",
                )
                step(
                    self.tractor.unload_grain(batch_id=batch),
                    "Unload to a distinct warehouse batch.",
                )
                step(
                    self.warehouse.dry_grain(
                        batch_id=batch,
                        target_moisture_pct=self.resources.storage_moisture_pct,
                    ),
                    "Dry to the permitted storage moisture.",
                )
                step(
                    self.warehouse.store_grain(batch_id=batch),
                    "Move the safe batch into storage.",
                )
            step(
                self.accounts.get_accounts(),
                "Read actual water use, costs, grain value and net margin.",
            )
        return finish_capture(self, events)
