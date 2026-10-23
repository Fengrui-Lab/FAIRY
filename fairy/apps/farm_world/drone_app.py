"""Single-farm drone App; shares algorithms with the explicitly routed App."""
from __future__ import annotations

from typing import Any

from fairy.apps.app import App
from fairy.apps.farm_world.farm_environment import FarmContext
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.farm_world.drone_operations import DroneOperations, _CHARGE_DURATION_S
from fairy.tool_utils import OperationType, app_tool, data_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check


class DroneApp(DroneOperations, App):
    """One physical drone permanently bound to a single legacy farm."""

    def __init__(
        self,
        farm_world_app: FarmWorldApp,
        weather_app: WeatherApp,
        *,
        name: str = "DroneApp",
        description: str = "",
        speed_ms: float = 5.0,
        effective_ridges_per_pass: int = 7,
        takeoff_overhead_s: int = 30,
        min_battery_pct: float = 20.0,
        battery_pct_per_ridge: float = 1.0,
    ) -> None:
        App.__init__(self, name=name)
        self._farm_world_app = farm_world_app
        self._weather_app = weather_app
        farm_world_app.attach_weather_app(weather_app)
        self._initialize_drone(
            description=description,
            speed_ms=speed_ms,
            effective_ridges_per_pass=effective_ridges_per_pass,
            takeoff_overhead_s=takeoff_overhead_s,
            min_battery_pct=min_battery_pct,
            battery_pct_per_ridge=battery_pct_per_ridge,
        )

    def _bound_farm(self) -> FarmContext:
        return FarmContext(
            farm_id=self._farm_world_app.name,
            world=self._farm_world_app,
            weather=self._weather_app,
            legacy_clock=self.time_manager,
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def fly_survey(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        """
        Fly an aerial survey over a contiguous ridge range, collecting
        multispectral (NDVI) and thermal (canopy temperature) observations
        for every surveyed ridge.

        The drone covers ridges in passes; each pass covers a number of
        ridges determined by the drone's effective_ridges_per_pass setting.
        If battery runs low mid-flight the drone returns automatically and
        reports the ridges it managed to cover.

        Args:
            start_ridge: First ridge of the survey range (0-based).
            end_ridge:   Last ridge of the survey range (inclusive, >= start_ridge).
        """

        return self._fly_survey(self._bound_farm(), start_ridge, end_ridge)

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def check_status(self) -> dict[str, Any]:
        """Return battery level, charging state, and drone configuration."""

        return self._check_status()

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def charge(self) -> dict[str, Any]:
        """
        Send this drone to its charging station.

        Charging completes asynchronously after about 30 minutes of
        environment time. The battery level increases gradually while charging.
        """

        return self._charge()
