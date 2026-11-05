"""Environment discovery tools; no farm or device mutation."""
from __future__ import annotations

from typing import Annotated, Any

from fairy.tool_utils import OperationType, ToolParameter
from .base import AssetId, FarmId, SharedFarmService, service_tool


class WorldService(SharedFarmService):
    service_name = "World"
    service_kind = "world"

    @service_tool(OperationType.READ)
    def describe_environment(self) -> dict[str, Any]:
        """List the available farms, equipment, weather stations and tools.

        Read this before selecting IDs. Each farm currently represents one
        rectangular field; ridge IDs are local to that farm. This directory
        describes configuration, not current battery, inventory or weather.

        Returns:
            Receipt with data containing farms and local ridge bounds, crops,
            asset eligibility and bindings, global sensor IDs, station links,
            catalog version and the shared tool response contract.
        """
        return self._execute("describe_environment")

    @service_tool(OperationType.READ, routing=("farm_id", "asset_id"))
    def get_capabilities(
        self,
        farm_id: FarmId,
        asset_id: Annotated[str | None, ToolParameter(entity_kind="asset")] = None,
    ) -> dict[str, Any]:
        """Read this farm's crop limits and an optional asset's capabilities.

        An asset, when selected, must be eligible for this farm. These are
        configuration limits; use status and observation tools for readiness.

        Args:
            farm_id: Exact target farm ID from describe_environment.
            asset_id: Optional eligible physical asset ID; None requests crop limits only.

        Returns:
            Receipt with data containing required field preparation operations,
            crop planting ranges, seed types,
            maturity and moisture limits, plus selected asset capacities and
            coverage limits when asset_id is supplied.
        """
        return self._execute("get_capabilities", farm_id=farm_id, asset_id=asset_id)
