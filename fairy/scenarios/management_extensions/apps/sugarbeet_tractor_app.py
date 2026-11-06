"""Shared wheat machinery is reused; beet lifting is a separate nongrain operation."""

from copy import deepcopy
from datetime import datetime
import math
from fairy.apps.app import App
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.apps.farm_world.equipment import TractorEquipment
from fairy.apps.farm_world.tractor_operations import _fuel_per_pass
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered
from .winter_wheat_tractor_app import WinterWheatTractor


class SugarBeetTractor(WinterWheatTractor):
    def __init__(self, environment):
        SharedTractorApp.__init__(
            self,
            environment,
            name="Tractor",
            equipment=TractorEquipment(
                implements=("grader", "seeder", "harvester", "beet_harvester"),
                planting_max_ridges_per_pass=4,
                harvest_max_ridges_per_pass=4,
            ),
        )
        self._active_blocks = (0, 0)
        self._active_operation = "_operate_plant_seeds"
        self.root_operations = {}
        self.delivery = None
        self.accounts = None

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
            "harvest_roots",
            "unload_grain",
            "return_supplies",
        }
        return [t for t in App.get_tools(self) if t.name in names]

    def _context(self):
        return self._prepare("arable")

    def _range_error(self, start, end):
        n = self.farm_environment.get_farm("arable").world.num_ridges
        if type(start) is not int or type(end) is not int or not 0 <= start <= end < n:
            return "Invalid block range"
        return None

    def _budget_error(self, extra):
        if self.accounts is None:
            return None
        if (
            self.accounts.compute_accounts()["production_cost"] + extra
            > self.accounts.resources.budget_usd + 1e-7
        ):
            return "Operating cost budget would be exceeded"
        return None

    def _work(self, start, end, operation, **args):
        farm = self._context()
        err = self._range_error(start, end) or self._target_error("arable")
        if err:
            return err if isinstance(err, dict) else {"error": err}
        f = farm.world
        self._active_blocks, self._active_operation = (start, end), operation
        paths = self._path_count(farm)
        fuel = _fuel_per_pass(f) * paths
        if self._fuel_tank_l < fuel:
            return {"error": "Insufficient fuel for all working-width passes"}
        extra = fuel * (self.accounts.prices.fuel_per_liter if self.accounts else 0)
        try:
            for i in range(start, end + 1):
                if operation == "_operate_plant_seeds":
                    f.backends[i].preflight("sow")
                    finish = datetime.fromtimestamp(
                        self.time_manager.time()
                        + self._tractor_pass_duration(farm, 4000 / 3600),
                        f.simulation_timezone,
                    ).date()
                    f.current_cycle.check_sowing(finish)
                elif operation == "_operate_apply_fertilizer":
                    dose = (
                        args["kg_per_ridge"]
                        * f.resources.fertilizer_n_fraction
                        / (f.ridge_area_m2 / 10000)
                    )
                    f.backends[i].preflight("fertilize", dose)
                    finish = datetime.fromtimestamp(
                        self.time_manager.time()
                        + self._tractor_pass_duration(farm, 6000 / 3600),
                        f.simulation_timezone,
                    ).date()
                    f.current_cycle.check_nitrogen(
                        finish, f.backends[i].n_by_cycle[f.current_cycle.cycle_id], dose
                    )
            if self.accounts:
                if operation == "_operate_plant_seeds":
                    extra += (
                        (end - start + 1)
                        * f.plants_per_ridge_from_spacing(1)
                        * self.accounts.prices.seed_per_unit[f.current_cycle.seed]
                    )
                elif operation == "_operate_apply_fertilizer":
                    extra += (
                        (end - start + 1)
                        * args["kg_per_ridge"]
                        * self.accounts.prices.fertilizer_per_kg
                    )
            if error := self._budget_error(extra):
                return {"error": error}
        except ValueError as exc:
            return {"error": str(exc)}
        before = self._fuel_tank_l
        result = getattr(self, operation)(
            farm, start_ridge=start, end_ridge=end, **args
        )
        spent = before - self._fuel_tank_l
        if spent > 0:
            self._fuel_tank_l -= spent * (paths - 1)
        return (
            self._finish_harvest(farm, result)
            if operation == "_operate_harvest"
            else self._finish(farm, result)
        )

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def sow(self, start_block: int, end_block: int, depth_cm: float = 3.0) -> dict:
        """Sow current crop with shared seed hopper and seeder.
        Args:
            start_block: First block inclusive.
            end_block: Last block inclusive, maximum four blocks per pass.
            depth_cm: Beet 2--3 cm; wheat 2--5 cm.
        Returns:
            dict: Status, consumed seeds and elapsed work; density is fixed reference.
        """
        f = self._context().world
        return self._work(
            start_block,
            end_block,
            "_operate_plant_seeds",
            depth_cm=depth_cm,
            seed_spacing_cm=20.0 if f.current_cycle.crop == "sugarbeet" else 1.25,
        )

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def harvest_blocks(self, start_block: int, end_block: int) -> dict:
        """Harvest mature WHEAT only using the reused grain machinery.
        Args:
            start_block: First wheat block inclusive.
            end_block: Last wheat block inclusive, max four; respect grain-bin capacity.
        Returns:
            dict: Harvested grain kg or error; beet requires harvest_roots instead.
        """
        f = self._context().world
        if f.current_cycle.crop != "winter_wheat":
            return {"error": "Use beet_harvester and harvest_roots for roots"}
        err = self._range_error(start_block, end_block)
        if err:
            return {"error": err}
        try:
            for i in range(start_block, end_block + 1):
                f.backends[i].harvest_preflight()
        except ValueError as exc:
            return {"error": str(exc)}
        result = self._work(start_block, end_block, "_operate_harvest")
        if "error" not in result and result.get("grain_kg_added", 0) > 0:
            self._grain_cultivar_ids = sorted(
                set(self._grain_cultivar_ids) | {f.current_cycle.seed}
            )
        return result

    def _tractor_register_harvest_with_physics(self, farm, ridge_ids):
        f = farm.world
        total = 0.0
        for i in ridge_ids:
            b = f.backends[i]
            dry = float(b.values.get("TWSO") or 0) * f.ridge_area_m2 / 10000
            total += dry * 0.95 / (1 - f.resources.storage_moisture_pct / 100)
            f.set_ridge_harvested(i)
            b.harvest_now(f"wheat_harvest:{b.cycle.cycle_id}:{i}")
        f._sync_blocks()
        return round(total, 2)

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def harvest_roots(
        self, start_block: int, end_block: int, operation_id: str
    ) -> dict:
        """Lift beet into traceable field batches; never use a grain bin or dryer.
        Args:
            start_block: First beet block inclusive.
            end_block: Last beet block inclusive, at most four per operation.
            operation_id: Unique retry-safe identifier; changing a payload is rejected.
        Returns:
            dict: Root batch IDs, native dry kg and recovered clean fresh kg. Requires
            beet_harvester, dry trafficable field, legal harvest window and withholding.
            Assumed machine performance: 1 ha/hour and 12 L fuel/ha.
        """
        request = dict(start_block=start_block, end_block=end_block)
        if not operation_id or not isinstance(operation_id, str):
            return {"error": "Operation ID required"}
        if operation_id in self.root_operations:
            old = self.root_operations[operation_id]
            return (
                deepcopy(old["result"])
                if old["request"] == request
                else {"error": "Conflicting operation ID"}
            )
        farm = self._context()
        f = farm.world
        err = self._range_error(start_block, end_block)
        if err:
            return {"error": err}
        if end_block - start_block + 1 > 4:
            return {"error": "Maximum four blocks per root lifting operation"}
        if (
            f.current_cycle.crop != "sugarbeet"
            or self._attached_implement != "beet_harvester"
        ):
            return {
                "error": "Current crop must be beet and beet_harvester must be mounted"
            }
        if farm.weather.rainfall_mm > 0:
            return {"error": "Cannot lift roots in rainy conditions"}
        if err := self._tractor_trafficability_error(farm, "harvest"):
            return {"error": err}
        if self.delivery is None:
            raise RuntimeError("RootDelivery must be wired")
        ids = list(range(start_block, end_block + 1))
        area = len(ids) * f.ridge_area_m2 / 10000
        duration = math.ceil(area * 3600) + 30
        end_day = datetime.fromtimestamp(
            self.time_manager.time() + duration, f.simulation_timezone
        ).date()
        if end_day != f.simulation_date():
            return {
                "error": "Root lifting must fit within one native day; resume next morning"
            }
        fuel = 12 * area
        if self._fuel_tank_l < fuel:
            return {"error": "Insufficient fuel"}
        if err := self._budget_error(fuel * self.accounts.prices.fuel_per_liter):
            return {"error": err}
        try:
            for i in ids:
                f.backends[i].harvest_preflight()
                if (
                    f"{f.current_cycle.cycle_id}:block:{i}"
                    in self.delivery.ledger.batches
                ):
                    raise ValueError("Block already has a root batch")
        except ValueError as exc:
            return {"error": str(exc)}
        self._fuel_tank_l -= fuel
        farm.advance_time(duration)
        batches = []
        for i in ids:
            b = f.backends[i]
            snap = b.harvest_now(f"root:{f.current_cycle.cycle_id}:{i}")
            batch_id = f"{f.current_cycle.cycle_id}:block:{i}"
            dry = snap["native"]["TWSO"] * f.ridge_area_m2 / 10000
            self.delivery.ledger.add(
                batch_id, b.cycle.cycle_id, i, f.simulation_date(), dry
            )
            f._ridges[i].harvested = True
            f._ridges[i].planted = False
            batches.append(batch_id)
        f._sync_blocks()
        result = dict(
            status="ok", batch_ids=batches, fuel_liters=fuel, duration_s=duration
        )
        self._operation_log.append(
            dict(operation="harvest_roots", farm_id="arable", ridge_ids=ids, **result)
        )
        self.root_operations[operation_id] = dict(request=request, result=result)
        return deepcopy(result)

    def get_state(self):
        return {
            **super().get_state(),
            "root_operations": deepcopy(self.root_operations),
        }

    def load_state(self, state):
        super().load_state(state)
        self.root_operations = deepcopy(state.get("root_operations", {}))
