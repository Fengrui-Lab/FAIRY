"""Station queries routed through an explicit farm's station binding."""
from __future__ import annotations

from typing import Annotated, Any

from fairy.tool_utils import OperationType, ToolParameter
from .base import FarmId, SharedFarmService, service_tool


class WeatherService(SharedFarmService):
    service_name = "Weather"
    service_kind = "weather"

    @service_tool(OperationType.READ, routing=("farm_id",))
    def get_current_weather(self, farm_id: FarmId) -> dict[str, Any]:
        """Read current weather from the station bound to this farm.

        Farms sharing a station receive the same meteorology. This query
        does not determine field trafficability; soil conditions are local.
        It does not advance the shared clock.

        Args:
            farm_id: Farm whose configured station should be queried.

        Returns:
            Receipt with station_id and current weather readings in data.
        """
        return self._execute("get_current_weather", farm_id=farm_id)

    @service_tool(OperationType.READ, routing=("farm_id",))
    def get_forecast(
        self, farm_id: FarmId,
        days: Annotated[int, ToolParameter(unit="days", minimum=1, maximum=7)] = 7,
    ) -> dict[str, Any]:
        """Read up to seven forecast entries from this farm's weather station.

        Does not advance time. Available forecast entries can be fewer than
        requested; inspect the returned forecast list.

        Args:
            farm_id: Farm whose configured station supplies the forecast.
            days: Number of forecast days requested, between 1 and 7 days.

        Returns:
            Receipt with station_id and forecast list in data.
        """
        return self._execute("get_forecast", farm_id=farm_id, days=days)
