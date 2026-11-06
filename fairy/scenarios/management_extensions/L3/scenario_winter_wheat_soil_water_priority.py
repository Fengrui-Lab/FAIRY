"""Allocate a shared irrigation quota among winter wheat blocks with different soils."""
from fairy.scenarios.management_extensions.oracle_time import oracle_time_arguments

from copy import copy, deepcopy
import json
from pathlib import Path
from typing import ClassVar

from fairy.tool_utils import OperationType, app_tool
from fairy.types import EventRegisterer, event_registered

from ..apps.winter_wheat_accounts_app import SEED, WheatResources
from ..apps.winter_wheat_farm_app import WinterWheatFarm
from ..common import capture_step, finish_capture
from ..engines.winter_wheat_inputs import fingerprint
from ..winter_wheat_setup import initialize_wheat_farm
from ..winter_wheat_workflow import capture_wheat_oracle
from .scenario_winter_wheat_full_season import ScenarioWinterWheatFullSeason

REFERENCE_PATH = (
    Path(__file__).parents[1]
    / "data/winter_wheat_oracles"
    / "scenario_l3_winter_wheat_soil_water_priority.json"
)


class SoilWaterWheatFarm(WinterWheatFarm):
    """The first eight blocks have a shallower, coarser rootable profile."""

    shallow_block_count = 8
    profile_overrides = {
        "shallow": (
            {"SMW": 0.10, "SMFCF": 0.24, "SM0": 0.41, "RDMSOL": 60.0},
            {"WAV": 10.0, "SMLIM": 0.24},
            "benchmark shallow coarse soil, no local field calibration",
        )
    }

    def block_inputs(self, block_id):
        zone = "shallow" if block_id < self.shallow_block_count else "deep"
        if zone not in self.profile_overrides:
            return self.bundle
        soil, site, description = self.profile_overrides[zone]
        inputs = copy(self.bundle)
        inputs.manifest = deepcopy(self.bundle.manifest)
        inputs.manifest["native_soil_parameters"].update(soil)
        inputs.manifest["native_site_parameters"].update(site)
        inputs.manifest["soil_status"] = description
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


class SoilWaterPriorityFarm(SoilWaterWheatFarm):
    """Report native root-zone water on comparable, soil-specific scales."""

    profile_overrides = {
        **SoilWaterWheatFarm.profile_overrides,
        "deep": (
            {"SMW": 0.13, "SMFCF": 0.34, "SM0": 0.48, "RDMSOL": 120.0},
            {"WAV": 25.2, "SMLIM": 0.34},
            "benchmark deep fine-textured soil, no local field calibration",
        ),
    }

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def inspect_blocks(self, start_block: int, end_block: int) -> dict:
        """Read crop development and soil-specific root-zone water by block.

        Args:
            start_block: First block ID to inspect, inclusive.
            end_block: Last block ID, inclusive and at least start_block.

        Returns:
            Block status, native crop and soil estimates, root depth (cm), the
            plant-available water remaining (mm and fraction from 0 to 1), and net mm
            to refill the current root zone to field capacity. These water
            estimates use each block's soil limits and native root depth.
            Rooted water estimates are null before emergence and after maturity. Check them
            again on the calendar day after irrigation completion.
        """
        field = super().inspect_blocks(start_block, end_block)
        for block in field.get("blocks", []):
            backend = self.backends[block["block_id"]]
            soil = backend.bundle.manifest["native_soil_parameters"]
            root_depth = backend.values.get("RD")
            if (
                root_depth
                and backend.values.get("DOE") is not None
                and backend.maturity is None
            ):
                moisture = block["SM"]
                capacity, wilting = soil["SMFCF"], soil["SMW"]
                available = max(0.0, min(moisture, capacity) - wilting)
                block.update(
                    root_depth_cm=round(root_depth, 1),
                    available_water_fraction=round(available / (capacity - wilting), 3),
                    available_water_mm=round(available * root_depth * 10, 1),
                    net_mm_to_field_capacity=round(
                        max(0, capacity - moisture) * root_depth * 10, 1
                    ),
                )
            else:
                block.update(
                    root_depth_cm=None,
                    available_water_fraction=None,
                    available_water_mm=None,
                    net_mm_to_field_capacity=None,
                )
        return field


class ScenarioWinterWheatSoilWaterPriority(ScenarioWinterWheatFullSeason):
    scenario_id = "scenario_l3_winter_wheat_soil_water_priority"
    legacy_resources: ClassVar = WheatResources(water_stock_m3=1000.0)
    resources: ClassVar = WheatResources(water_stock_m3=950.0)
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

    def __init__(self, *, legacy=None, late_harvest=None, **kwargs):
        if legacy is not None and type(legacy) is not bool:
            raise ValueError("legacy must be a JSON boolean")
        self.legacy = late_harvest is False if legacy is None else legacy
        if self.legacy:
            self.resources = self.legacy_resources
        if late_harvest is None:
            late_harvest = not self.legacy
        super().__init__(late_harvest=late_harvest, **kwargs)

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("Configure inputs at construction")
        initialize_wheat_farm(
            self,
            farm_class=SoilWaterWheatFarm if self.legacy else SoilWaterPriorityFarm,
        )
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
        if self.legacy:
            return self._legacy_task_description(detailed)
        task = (
            "经营一座面积10000平方米的冬小麦农场。两区土壤保水能力不同，共用同一季灌溉水。"
            "按地块分配有限水量，完成秋播、越冬、成熟收获与安全入库，提高净经营收益。"
        )
        if not detailed:
            return task + (
                "通过WheatField.get_field_info查询土壤资料，"
                "通过OperatingAccounts.get_accounts查询物资价格和剩余配额。"
            )
        return task + (
            "\n\n秋播前查看各区田间持水量、萎蔫点和根系可达深度，再核对天气、库存和价格。"
            "十月中旬前后整地条播，播深约3 cm。底肥可参考约6 kg尿素/块，入冬前确认出苗。"
            "\n\n二月下旬到三月上旬返青，四月上旬冠层扩展时再查根区可用氮和长势。"
            "确需追肥时可分别参考约9和7–8 kg尿素/块。四月中下旬视读数和库存考虑少量追肥。"
            "分次装入当次用量，施后复查根区氮和长势。"
            "\n\n四月中下旬至五月开花前后，一起看各区的可用水比例、剩余水深和当前根深，"
            "结合未来几天降雨判断谁先补。浅土储水少，缺口初现可先补约20–30 mm，后续明显不足时可参考约40–50 mm。"
            "保留后续水量，根区还湿的区可以晚些再补。"
            "灌水完成后等到次日复查，按退湿速度决定是否再补。"
            "\n\n五月灌浆期继续比较两区读数。深土区的可用水降到约一半、后续少雨时，可参考补约25–35 mm。"
            "后续按两区退湿速度和余额调整分配。确认成熟后看短期预报，预留足够小时数完成分批收获、卸粮、干燥和安全入库。"
            "最后核对各块收获和粮批状态，报告用水、成本和净收益。"
        )

    def _legacy_task_description(self, detailed):
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

    def validate(self, env=None):
        result = super().validate(env)
        if self.legacy:
            return result
        farm = self.farm
        split = farm.shallow_block_count
        area_ha = farm.ridge_area_m2 / 10000
        zones = {}
        for name, start, end in (
            ("shallow", 0, split),
            ("deep", split, farm.num_ridges),
        ):
            blocks = farm.backends[start:end]
            zones[name] = {
                "block_ids": list(range(start, end)),
                "dry_grain_kg": area_ha
                * sum(b.values.get("TWSO") or 0 for b in blocks),
                "irrigation_m3": area_ha
                * 10
                * sum(
                    a["amount"]
                    for b in blocks
                    for a in b.receipts.values()
                    if a["kind"] == "irrigate"
                ),
            }
        result.metadata["soil_water_zones"] = zones
        return result

    def build_events_flow(self):
        if self.calibrating:
            return []
        if self.legacy:
            return self._build_legacy_events_flow()
        data = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
        self.ORACLE_REFERENCE = data["reference"]
        if self.input_fingerprint() != self.ORACLE_REFERENCE["input_fingerprint"]:
            raise ValueError("Soil-water priority requires its verified Oracle inputs")
        return capture_wheat_oracle(self, data["steps"])

    def _build_legacy_events_flow(self):
        previous = None
        with EventRegisterer.capture_mode() as events:

            def step(event, reason):
                nonlocal previous
                previous = capture_step(
                    previous, event, f"water_priority_{len(events):03d}", reason
                )

            def wait(seconds):
                step(
                    self.system.advance_time(**oracle_time_arguments(seconds)),
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
