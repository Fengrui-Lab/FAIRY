"""Farm-local state queries, fertigation and postharvest tools."""
from __future__ import annotations

from typing import Annotated, Any

from fairy.tool_utils import OperationType, ToolParameter
from .base import FarmId, RidgeId, SharedFarmService, service_tool


class FarmService(SharedFarmService):
    service_name = "Farm"
    service_kind = "farm"

    @service_tool(OperationType.READ, routing=("farm_id",))
    def get_farm_overview(self, farm_id: FarmId) -> dict[str, Any]:
        """Read one farm's geometry, crop, season phase and ridge summary.

        Reports that farm's state at the current time without advancing time. Use ridge-state and sensor tools for detail.

        Args:
            farm_id: Exact farm ID whose state should be queried.

        Returns:
            Receipt with configuration, area, crop_profile, sim_date,
            season_phase, inventory and ridges_overview in data.
        """
        return self._execute("get_farm_overview", farm_id=farm_id)

    @service_tool(OperationType.READ, routing=("farm_id",))
    def get_ridge_state(self, farm_id: FarmId, ridge_id: RidgeId) -> dict[str, Any]:
        """Read operational state for one local ridge without advancing time.

        Returns public planting, maturity and latest observation fields.
        This query does not acquire new field measurements; use Sensor, Drone
        or Robot tools for fresh observations.

        Args:
            farm_id: Farm containing the ridge.
            ridge_id: Zero-based ridge ID within this farm's declared bounds.

        Returns:
            Receipt with the selected ridge's public operational state in data.
        """
        return self._execute("get_ridge_state", farm_id=farm_id, ridge_id=ridge_id)

    @service_tool(OperationType.READ, routing=("farm_id",))
    def get_ridge_range_state(self, farm_id: FarmId, start: RidgeId, end: RidgeId) -> dict[str, Any]:
        """Read public operational states for an inclusive local ridge range.

        Does not advance time or acquire a new remote/ground inspection.
        Use observation tools for fresh field measurements.

        Args:
            farm_id: Farm containing all requested ridges.
            start: First local ridge ID, inclusive.
            end: Last local ridge ID, inclusive and at least start.

        Returns:
            Receipt with a ridges list of public operational states in data.
        """
        return self._execute("get_ridge_range_state", farm_id=farm_id, start=start, end=end)

    @service_tool(OperationType.READ, routing=("farm_id",))
    def get_inventory(self, farm_id: FarmId) -> dict[str, Any]:
        """Read this farm's warehouse, trailer, resource budgets and market.

        Device payloads are separate; query Tractor status for material still
        aboard a machine. This query does not advance the shared clock.

        Args:
            farm_id: Farm whose own inventory and management limits should be read.

        Returns:
            Receipt with seed, fertilizer, pesticide, fuel and grain stocks,
            management_regime limits/usage and postharvest_market in data.
        """
        return self._execute("get_inventory", farm_id=farm_id)

    @service_tool(OperationType.WRITE, routing=("farm_id",))
    def apply_fertigation(
        self, farm_id: FarmId, start_ridge: RidgeId, end_ridge: RidgeId,
        nutrient_amount: Annotated[float, ToolParameter(unit="model nutrient units", exclusive_minimum=0)],
        water_mm: Annotated[float, ToolParameter(unit="mm", minimum=0)],
    ) -> dict[str, Any]:
        """Apply normalized nutrients and carrier water to local ridges.

        Requires this farm's fertilizer inventory, fertilizer allowance and
        any applicable water quota. One nutrient unit uses 30 kg per ridge.
        Field response is not instantaneous; reassess conditions after treatment.
        This call does not add operation time.

        Args:
            farm_id: Farm supplying fertilizer and receiving the treatment.
            start_ridge: First local ridge ID, inclusive.
            end_ridge: Last local ridge ID, inclusive and at least start_ridge.
            nutrient_amount: Positive normalized dose; 1.0 equals 30 kg per ridge.
            water_mm: Carrier water depth per ridge in mm, zero or greater.

        Returns:
            Receipt with fertigated_ridges, nutrient and water input,
            fertilizer_kg_used, field-equivalent water and management usage in data.
        """
        return self._execute("apply_fertigation", farm_id=farm_id, start_ridge=start_ridge,
                             end_ridge=end_ridge, nutrient_amount=nutrient_amount, water_mm=water_mm)

    @service_tool(OperationType.WRITE, routing=("farm_id",))
    def dry_grain(
        self, farm_id: FarmId,
        target_moisture_pct: Annotated[float, ToolParameter(unit="%", minimum=11, maximum=16)] = 13.0,
    ) -> dict[str, Any]:
        """Dry this farm's unloaded trailer batch before long-term storage.

        Target must also satisfy the farm's storage limit and drying capacity.
        If the current batch is already safe, drying is skipped. Updates
        grain moisture and batch flags; does not advance time.

        Args:
            farm_id: Farm owning the pending unloaded grain batch.
            target_moisture_pct: Target moisture percentage, 11–16%, within this farm's storage limit.

        Returns:
            Receipt with drying_skipped or target moisture, affected batch
            ridges, trailer grain mass and postharvest_market in data.
        """
        return self._execute("dry_grain", farm_id=farm_id, target_moisture_pct=target_moisture_pct)

    @service_tool(OperationType.WRITE, routing=("farm_id",))
    def store_grain(self, farm_id: FarmId) -> dict[str, Any]:
        """Move this farm's trailer batch into its long-term warehouse.

        Requires warehouse capacity. Wet undried grain is currently stored
        with a spoilage-risk warning rather than rejected; inspect the result
        and moisture limits. Successful transfer alone does not establish safe storage.
        Clears the trailer batch without adding operation time.

        Args:
            farm_id: Farm owning both the trailer batch and destination warehouse.

        Returns:
            Receipt with moved_kg, batch_ridge_ids, warehouse/trailer mass,
            storage moisture and any spoilage-risk warning in data.
        """
        return self._execute("store_grain", farm_id=farm_id)
