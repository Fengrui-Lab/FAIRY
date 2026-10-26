"""One drone shared by the farms of a FarmEnvironment."""
from __future__ import annotations

from typing import Any

from fairy.apps.app import App
from fairy.apps.farm_world.drone_operations import DroneOperations
from fairy.apps.farm_world.farm_environment import FarmEnvironment
from fairy.tool_utils import OperationType, app_tool, data_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check


class SharedDroneApp(DroneOperations, App):
    """A single battery and mission log; each survey names its target farm."""

    require_explicit_tool_docs = True
    validate_tool_arguments = True

    def __init__(
        self,
        environment: FarmEnvironment,
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
        self.farm_environment = environment
        self.time_manager = environment.time_manager
        self.tool_parameter_choices = {"farm_id": list(environment.farms)}
        self._initialize_drone(
            description=description,
            speed_ms=speed_ms,
            effective_ridges_per_pass=effective_ridges_per_pass,
            takeoff_overhead_s=takeoff_overhead_s,
            min_battery_pct=min_battery_pct,
            battery_pct_per_ridge=battery_pct_per_ridge,
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def fly_survey(
        self, farm_id: str, start_ridge: int, end_ridge: int
    ) -> dict[str, Any]:
        """Survey the specified farm using this shared drone.

        Reads only the target farm's crop and weather conditions, and updates
        only its observed NDVI and canopy temperature. Consumes this drone's
        shared battery and advances time for every farm. Flight is refused while
        charging, below its minimum battery, or in unflyable weather. A low
        battery can stop the mission between passes, leaving partial coverage.

        Args:
            farm_id: Exact target farm ID from the available farm directory.
            start_ridge: First local ridge ID in that farm, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be at least start_ridge
                and less than that farm's num_ridges.

        Returns:
            Farm-qualified mission ID, surveyed ridges, NDVI/temperature readings,
            elapsed minutes and remaining battery. Status partial and a warning
            identify incomplete coverage; error reports a refused mission.
        """
        farm = self.farm_environment.get_farm(farm_id)
        self.farm_environment.before_tool()
        return self._fly_survey(farm, start_ridge, end_ridge)

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def check_status(self) -> dict[str, Any]:
        """Read this drone's shared battery, charging ETA and flight configuration.

        Returns:
            Device name, battery percentage, charging flag, minutes until full,
            speed in metres per second and ridges covered per pass. No farm
            parameter is required because the state belongs to this drone.
        """
        self.farm_environment.before_tool()
        return self._check_status()

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def charge(self) -> dict[str, Any]:
        """Start charging this shared drone; no farm is selected.

        Charging is asynchronous: battery rises over 30 minutes of the common
        simulation clock. This call does not wait or advance the clock, and a
        charging drone cannot survey any registered farm until charging completes.

        Returns:
            Charging status, shared battery percentage, completion timestamp and
            ETA in minutes; already charging/full are reported without restart.
        """
        self.farm_environment.before_tool()
        return self._charge()
