"""Scout uneven wheat growth and manage the affected blocks through harvest."""

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


class ScoutingWheatFarm(WinterWheatFarm):
    """Two blocks have depleted nitrogen reserves at the start of the season."""

    low_n_blocks = (6, 7)

    def block_inputs(self, block_id):
        if block_id not in self.low_n_blocks:
            return self.bundle
        inputs = copy(self.bundle)
        inputs.manifest = deepcopy(self.bundle.manifest)
        inputs.manifest["native_site_parameters"].update(NAVAILI=2.0, NSOILBASE=4.0)
        inputs.identity = fingerprint(inputs.manifest)
        return inputs

    def crop_backend_provenance(self):
        result = super().crop_backend_provenance()
        result["block_input_fingerprints"] = [b.bundle.identity for b in self.backends]
        return result

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def inspect_blocks(self, start_block: int, end_block: int) -> dict:
        """Read planting and harvest status. Use scout tools to diagnose growth.

        Args:
            start_block: First block ID, inclusive.
            end_block: Last block ID, inclusive, at least start_block.

        Returns:
            dict: Date and selected blocks' planted, harvested, stage, and
            grain moisture percentage for harvest planning. Invalid range returns error.
        """
        self.advance_physics_time()
        if (
            type(start_block) is not int
            or type(end_block) is not int
            or not 0 <= start_block <= end_block < self.num_ridges
        ):
            return {"error": "Invalid block range"}
        return {
            "date": self._sim_date,
            "blocks": [
                {
                    "block_id": rid,
                    "planted": block.planted,
                    "harvested": block.harvested,
                    "stage": block.growth_stage,
                    "grain_moisture_pct": block.grain_moisture_pct,
                }
                for rid, block in enumerate(
                    self._ridges[start_block : end_block + 1], start_block
                )
            ],
        }


class ScenarioWinterWheatBlockScouting(ScenarioWinterWheatFullSeason):
    scenario_id = "scenario_l3_winter_wheat_block_scouting"
    resources: ClassVar = WheatResources(fertilizer_stock_kg=360.0)
    ORACLE_REFERENCE: ClassVar = {
        "input_fingerprint": "cdc892212abd0ac7a2f006f60282d62d78c281c1666f7fd525b6e53ef3f60194",
        "selected": {
            "currency": "USD",
            "price_book_id": "winter_wheat_china_2025_owned_machinery_usd_v2",
            "cny_per_usd": 7.1757,
            "stored_kg_by_crop": {"winter_wheat": 7675.55},
            "stored_grain_kg": 7675.55,
            "dry_grain_kg": 7069.5689702121235,
            "production_cost": 377.3128374822886,
            "stored_grain_value": 2545.787728026534,
            "net_operating_margin": 2168.474890544245,
        },
        "workflow_steps": 108,
        "candidate_count": 7,
        "feasible_count": 7,
        "scope": "Best net operating margin among seven executed treatments including no rescue, same-N "
        "blanket and wrong-block controls. The early and late targeted treatments tied; the "
        "reference acts on the first inspection.",
    }

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("Configure inputs at construction")
        from ..apps.winter_wheat_scouting_apps import WheatScoutDrone, WheatScoutRobot

        initialize_wheat_farm(self, farm_class=ScoutingWheatFarm)
        self.drone = WheatScoutDrone(self.farm_environment)
        self.robot = WheatScoutRobot(self.farm_environment)
        for device in (self.drone, self.robot):
            device.rng.seed(self.seed)
            self.apps.append(device)
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
            "经营一座面积10000平方米的冬小麦农场。地块过去的耕作和投入有差异，春季关注局部长势并按需处理。"
            "完成秋播、越冬、收获和安全入库，在资源限制下提高净经营收益。"
            "通过WheatField.get_field_info查地块与作业条件，通过OperatingAccounts.get_accounts查价格和资源。"
        )
        if not detailed:
            return task
        return task + (
            "先整地并按地块播种。春季用Sensor.read_root_zone_sensors与Sensor.read_canopy_sensors比较分区读数，结合天气判断巡查窗口。"
            "可用Drone.survey_blocks定位冠层异常，再用Robot.inspect_blocks比较异常块和正常块的近地长势。"
            "结合根区、冠层和近地观测选择处理，注意设备覆盖与电量，等地块结算后复查，再确认成熟并分批收获入库。"
        )

    def build_events_flow(self):
        previous = None
        with EventRegisterer.capture_mode() as events:

            def step(event, reason):
                nonlocal previous
                previous = capture_step(
                    previous, event, f"scout_{len(events):03d}", reason
                )

            step(
                self.aui.send_message_to_agent(self.scenario_input),
                "Read the management task.",
            )
            step(
                self.farm.get_field_info(), "Read geometry, season and operating rules."
            )
            step(
                self.accounts.get_accounts(),
                "Check prices, inventory and operating results.",
            )
            step(
                self.tractor.attach_implement(implement="grader"),
                "Mount the required implement.",
            )
            step(self.tractor.prepare_field(), "Prepare the flat field for sowing.")

            # 2019-10-15
            step(
                self.system.advance_time(seconds=1204600.0),
                "Advance the farm calendar to 2019-10-15.",
            )
            step(self.tractor.detach_implement(), "Detach before changing implements.")
            step(
                self.tractor.attach_implement(implement="seeder"),
                "Mount the required implement.",
            )
            for block in range(16):
                step(
                    self.tractor.load_seeds(
                        seed_type=SEED, count=self.resources.seeds_per_block
                    ),
                    "Reload the shared seed hopper for this block.",
                )
                step(
                    self.tractor.sow(start_block=block, end_block=block, depth_cm=3.0),
                    "Sow this block with the shared seeder.",
                )

            # 2020-04-02
            step(
                self.system.advance_time(seconds=14683104.0),
                "Advance the farm calendar to 2020-04-02.",
            )
            step(
                self.irrigation.irrigate(start_block=0, end_block=15, depth_mm=50.0),
                "Deliver gross water depth to the selected blocks.",
            )

            # 2020-04-06
            step(
                self.system.advance_time(seconds=309300.0),
                "Advance the farm calendar to 2020-04-06.",
            )
            step(
                self.sensor.read_root_zone_sensors(),
                "Compare root-zone water and nitrogen across sensor zones.",
            )
            step(
                self.sensor.read_canopy_sensors(),
                "Compare zone canopy readings for localized weak growth.",
            )
            step(
                self.weather.get_current_weather(),
                "Check current weather before scouting or harvest.",
            )
            step(
                self.drone.survey_blocks(start_block=0, end_block=15),
                "Locate weak canopy by block using aerial NDVI and thermal evidence.",
            )
            step(
                self.robot.inspect_blocks(start_block=5, end_block=7),
                "Compare weak blocks with a nearby reference using ground crop and leaf readings.",
            )
            step(
                self.tractor.load_fertilizer(kg=239.1304347826087),
                "Load the urea product needed for the next treatment.",
            )
            step(
                self.tractor.fertilize(
                    start_block=0, end_block=5, kg_per_block=13.586956521739129
                ),
                "Apply the specified product mass to the selected blocks.",
            )
            step(
                self.tractor.fertilize(
                    start_block=6, end_block=7, kg_per_block=24.456521739130434
                ),
                "Apply supplemental urea to the two blocks identified by the converging observations.",
            )
            step(
                self.tractor.fertilize(
                    start_block=8, end_block=15, kg_per_block=13.586956521739129
                ),
                "Apply the specified product mass to the selected blocks.",
            )

            # 2020-04-20
            step(
                self.system.advance_time(seconds=1206700.0),
                "Advance the farm calendar to 2020-04-20.",
            )
            step(
                self.sensor.read_root_zone_sensors(),
                "Compare root-zone water and nitrogen across sensor zones.",
            )
            step(
                self.sensor.read_canopy_sensors(),
                "Compare zone canopy readings for localized weak growth.",
            )
            step(
                self.weather.get_current_weather(),
                "Check current weather before scouting or harvest.",
            )
            step(
                self.drone.survey_blocks(start_block=0, end_block=15),
                "Compare aerial canopy evidence after the targeted treatment.",
            )
            step(
                self.robot.inspect_blocks(start_block=6, end_block=7),
                "Recheck the treated blocks with the ground robot.",
            )
            step(
                self.tractor.load_fertilizer(kg=108.69565217391303),
                "Load the urea product needed for the next treatment.",
            )
            step(
                self.tractor.fertilize(
                    start_block=0, end_block=9, kg_per_block=6.7934782608695645
                ),
                "Apply the specified product mass to the selected blocks.",
            )
            step(
                self.tractor.fertilize(
                    start_block=10, end_block=15, kg_per_block=6.7934782608695645
                ),
                "Apply the specified product mass to the selected blocks.",
            )
            step(
                self.irrigation.irrigate(start_block=0, end_block=15, depth_mm=50.0),
                "Deliver gross water depth to the selected blocks.",
            )

            # 2020-05-05
            step(
                self.system.advance_time(seconds=1257170.0),
                "Advance the farm calendar to 2020-05-05.",
            )
            step(
                self.sensor.read_root_zone_sensors(),
                "Compare root-zone water and nitrogen across sensor zones.",
            )
            step(
                self.irrigation.irrigate(start_block=0, end_block=15, depth_mm=50.0),
                "Deliver gross water depth to the selected blocks.",
            )

            # 2020-05-20
            step(
                self.system.advance_time(seconds=1259700.0),
                "Advance the farm calendar to 2020-05-20.",
            )
            step(
                self.sensor.read_root_zone_sensors(),
                "Compare root-zone water and nitrogen across sensor zones.",
            )
            step(
                self.irrigation.irrigate(start_block=0, end_block=15, depth_mm=50.0),
                "Deliver gross water depth to the selected blocks.",
            )

            # 2020-06-20
            step(
                self.system.advance_time(seconds=2642100.0),
                "Advance the farm calendar to 2020-06-20.",
            )

            # 2020-06-21
            step(
                self.system.advance_time(seconds=86400.0),
                "Advance the farm calendar to 2020-06-21.",
            )

            # 2020-06-22
            step(
                self.system.advance_time(seconds=86400.0),
                "Advance the farm calendar to 2020-06-22.",
            )
            step(
                self.farm.inspect_blocks(start_block=0, end_block=15),
                "Check block status.",
            )
            step(
                self.weather.get_current_weather(),
                "Check current weather before scouting or harvest.",
            )
            step(self.tractor.detach_implement(), "Detach before changing implements.")
            step(
                self.tractor.attach_implement(implement="harvester"),
                "Mount the required implement.",
            )
            for start in range(0, 16, 2):
                batch_id = f"wheat_{start}"
                step(
                    self.tractor.harvest_blocks(start_block=start, end_block=start + 1),
                    "Harvest mature blocks within bin capacity.",
                )
                step(
                    self.tractor.unload_grain(batch_id=batch_id),
                    "Unload with block provenance.",
                )
                step(
                    self.warehouse.dry_grain(
                        batch_id=batch_id, target_moisture_pct=12.5
                    ),
                    "Dry the batch to safe storage moisture.",
                )
                step(self.warehouse.store_grain(batch_id=batch_id), "Store the batch.")
            step(
                self.accounts.get_accounts(),
                "Check prices, inventory and operating results.",
            )
        return finish_capture(self, events)
