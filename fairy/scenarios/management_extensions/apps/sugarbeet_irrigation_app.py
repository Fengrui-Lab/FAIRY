"""Reuse wheat flow, pump time, quota and water-consumption logging."""

from datetime import datetime, timedelta
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered
from .winter_wheat_irrigation_app import WinterWheatIrrigation
from ..sugarbeet.contracts import finite


class SugarBeetIrrigation(WinterWheatIrrigation):
    accounts = None

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def irrigate(self, start_block: int, end_block: int, depth_mm: float) -> dict:
        """Apply gross mm with the shared pump and per-cycle agronomic checks.
        Args:
            start_block: First block inclusive.
            end_block: Last block inclusive.
            depth_mm: Positive gross irrigation depth in mm; pump rate is 5 mm/hour.
        Returns:
            dict: Water, duration and daily effect time, or a preflight error.
        """
        f = self._farm_world_app
        f.advance_physics_time()
        try:
            dose = finite(depth_mm, "irrigation depth", 0.000001, 100)
            if (
                type(start_block) is not int
                or type(end_block) is not int
                or not 0 <= start_block <= end_block < f.num_ridges
            ):
                raise ValueError("Invalid block range")
            end_day = datetime.fromtimestamp(
                self.time_manager.time() + dose / 5 * 3600, f.simulation_timezone
            ).date()
            if end_day > f.current_cycle.harvest_close - timedelta(
                days=f.current_cycle.irrigation_withholding_days
            ):
                raise ValueError(
                    "Cannot finish irrigation early enough for a legal harvest"
                )
            for i in range(start_block, end_block + 1):
                f.backends[i].preflight("irrigate", dose)
            if self.accounts:
                cost = (
                    dose
                    * (end_block - start_block + 1)
                    * f.ridge_area_m2
                    / 1000
                    * self.accounts.prices.water_per_m3
                )
                if (
                    self.accounts.compute_accounts()["production_cost"] + cost
                    > f.resources.budget_usd + 1e-7
                ):
                    raise ValueError("Water would exceed operating budget")
        except ValueError as e:
            return {"error": str(e)}
        return super().irrigate(start_block, end_block, depth_mm)
