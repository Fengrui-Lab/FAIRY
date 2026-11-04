"""Block names over shared machinery operations; wheat-specific native hooks only."""

import math
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.tractor_operations import _fuel_per_pass
from fairy.apps.farm_world.equipment import TractorEquipment
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered


# Existing spreader/header widths; wheat uses an explicitly configured 3-m drill.
WORKING_WIDTH_M = {
    "_operate_plant_seeds": 3.0,
    "_operate_apply_fertilizer": 6.0,
    "_operate_harvest": 4.4,
}


class WinterWheatTractor(SharedTractorApp):
    def __init__(self, environment):
        super().__init__(
            environment,
            name="Tractor",
            equipment=TractorEquipment(
                implements=("grader", "seeder", "harvester"),
                planting_max_ridges_per_pass=4,
                harvest_max_ridges_per_pass=4,
            ),
        )
        self._active_blocks = (0, 0)
        self._active_operation = "_operate_plant_seeds"

    def get_tools(self):
        names = {
            "attach_implement",
            "detach_implement",
            "refuel",
            "load_fertilizer",
            "load_seeds",
            "get_status",
            "prepare_field",
            "sow",
            "fertilize",
            "harvest_blocks",
            "unload_grain",
            "return_supplies",
        }
        return [t for t in super().get_tools() if t.name in names]

    def _context(self):
        return self._prepare("wheat")

    def _range_error(self, start, end):
        n = self.farm_environment.get_farm("wheat").world.num_ridges
        if type(start) is not int or type(end) is not int or not 0 <= start <= end < n:
            return "Invalid block range; query WheatField.get_field_info"
        return None

    def _work(self, start, end, operation, **args):
        farm = self._context()
        error = self._range_error(start, end) or self._target_error("wheat")
        if error:
            return error if isinstance(error, dict) else {"error": error}
        if operation == "_operate_apply_fertilizer" and any(
            farm.world.backends[i].maturity is not None for i in range(start, end + 1)
        ):
            return {"error": "Fertilizer requires blocks before native maturity"}
        self._active_blocks = (start, end)
        self._active_operation = operation
        # Work may span adjacent blocks. Count paths over their combined width,
        # so batching can avoid duplicated edge passes without changing dose/area.
        paths = self._path_count(farm)
        needed = _fuel_per_pass(farm.world) * paths
        if self._fuel_tank_l < needed:
            return {"error": f"Insufficient fuel: need {needed:g} L"}
        before = self._fuel_tank_l
        result = getattr(self, operation)(
            farm, start_ridge=start, end_ridge=end, **args
        )
        spent = before - self._fuel_tank_l
        if spent > 0:
            self._fuel_tank_l -= spent * (paths - 1)
        if operation == "_operate_harvest":
            return self._finish_harvest(farm, result)
        return self._finish(farm, result)

    def _path_count(self, farm):
        start, end = self._active_blocks
        width = farm.world.ridge_width_m * (end - start + 1)
        return math.ceil(width / WORKING_WIDTH_M[self._active_operation])

    def _tractor_pass_duration(self, farm, speed_ms):
        return self._path_count(farm) * (int(farm.world.field_length_m / speed_ms) + 30)

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def prepare_field(self) -> dict:
        """Level/till the flat wheat field with the attached grader.

        Returns:
            dict: Operation status, fuel L and duration; requires grader, fuel
            and trafficable soil. Completes the only required preparation step.
        """
        farm = self._context()
        if "level" in farm.world.completed_prep_ops:
            return {"status": "already_prepared"}
        return self._finish(farm, self._operate_level(farm))

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def sow(self, start_block: int, end_block: int, depth_cm: float = 3.0) -> dict:
        """Sow flat blocks using the shared seeder, hopper, fuel and clock.

        Args:
            start_block: First block ID, inclusive; see WheatField.get_field_info.
            end_block: Last block ID, inclusive, at least start_block; hopper must
                contain all required seeds. Split work and reload when necessary.
            depth_cm: Seed placement depth, 2–5 cm.

        Returns:
            dict: Status, planted blocks and seeds used, or a preflight error.
            Requires prepared soil, seeder, legal sowing date and queried conditions.
            Reference kg/ha is fixed because this native model has no density response.
        """
        return self._work(
            start_block,
            end_block,
            "_operate_plant_seeds",
            depth_cm=depth_cm,
            seed_spacing_cm=1.25,
        )

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def fertilize(self, start_block: int, end_block: int, kg_per_block: float) -> dict:
        """Spread urea PRODUCT on selected blocks from the loaded spreader.

        Args:
            start_block: First block ID, inclusive.
            end_block: Last block ID, inclusive, at least start_block; max 10 blocks.
            kg_per_block: Positive kg urea product per block, not kg pure N/ha.
                Pure N/ha = kg_per_block * 0.46 / block_area_ha.

        Returns:
            dict: Status and consumed product kg or error. Requires stock loaded,
            fuel, trafficable soil and remaining quota. Native N settles daily.
        """
        return self._work(
            start_block,
            end_block,
            "_operate_apply_fertilizer",
            kg_per_ridge=kg_per_block,
        )

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def harvest_blocks(self, start_block: int, end_block: int) -> dict:
        """Harvest mature flat blocks into the existing 2000-kg grain bin.

        Args:
            start_block: First block ID, inclusive.
            end_block: Last block ID, inclusive; max 4 blocks, subject to bin room.

        Returns:
            dict: Recovered market-moisture kg and block IDs, or error. Requires
            harvester, native maturity, dry weather, trafficable soil and fuel.
            Unload full bins into unique Warehouse batches before continuing.
        """
        farm = self.farm_environment.get_farm("wheat")
        error = self._range_error(start_block, end_block)
        if error:
            return {"error": error}
        cultivars = {
            r.seed_type
            for r in farm.world._ridges[start_block : end_block + 1]
            if r.seed_type
        }
        result = self._work(start_block, end_block, "_operate_harvest")
        if "error" not in result and result.get("grain_kg_added", 0) > 0:
            self._grain_cultivar_ids = sorted(set(self._grain_cultivar_ids) | cultivars)
        return result

    def _tractor_register_planting_with_physics(
        self, farm, ridges, seed_depth_cm, seed_spacing_cm, *, event=None, **kwargs
    ):
        for ridge in ridges:
            b = farm.world.backends[ridge.ridge_id]
            b.queue(f"sow_{len(b.receipts)}", "sow")
            ridge.seed_type = self.seed_type
        farm.world._sync_blocks()

    def _tractor_register_fertilizer_with_physics(
        self, farm, ridge_ids, kg_per_ridge, method
    ):
        # The shared spreader advances one path before this hook. Complete the
        # remaining paths BEFORE queueing native inputs, including midnight.
        one = int(farm.world.field_length_m / (6000 / 3600)) + 30
        farm.advance_time(one * (self._path_count(farm) - 1))
        for i in ridge_ids:
            b = farm.world.backends[i]
            dose = (
                kg_per_ridge
                * farm.world.resources.fertilizer_n_fraction
                / (farm.world.ridge_area_m2 / 10000)
            )
            b.queue(f"fertilize_{len(b.receipts)}", "fertilize", dose)

    def _tractor_register_harvest_with_physics(self, farm, ridge_ids):
        total = 0.0
        for i in ridge_ids:
            b = farm.world.backends[i]
            dry = (b.values.get("TWSO") or 0) * farm.world.ridge_area_m2 / 10000
            total += dry * 0.95 / (1 - farm.world.resources.storage_moisture_pct / 100)
            farm.world.set_ridge_harvested(i)
        farm.world._sync_blocks()
        return round(total, 2)
