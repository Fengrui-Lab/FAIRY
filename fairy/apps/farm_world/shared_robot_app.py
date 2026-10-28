"""One ground inspection robot shared by a FarmEnvironment."""
from __future__ import annotations

from typing import Any

from fairy.apps.app import App
from fairy.apps.farm_world.farm_environment import FarmEnvironment
from fairy.apps.farm_world.robot_operations import RobotOperations
from fairy.tool_utils import OperationType, app_tool, data_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check


class SharedRobotApp(RobotOperations, App):
    """One battery, charge session and inspection log across all target farms."""

    require_explicit_tool_docs = True
    validate_tool_arguments = True

    def __init__(
        self,
        environment: FarmEnvironment,
        *,
        name: str = "RobotApp",
        description: str = "",
    ) -> None:
        App.__init__(self, name=name)
        self.farm_environment = environment
        self.time_manager = environment.time_manager
        self.tool_parameter_choices = {"farm_id": list(environment.farms)}
        self._initialize_robot(description=description)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def inspect_ridge(self, farm_id: str, ridge_id: int) -> dict[str, Any]:
        """Walk one ridge of the selected farm and report pest/disease presence.

        Consumes 20 percentage points of this robot's shared battery and advances
        every farm by the round-trip walking time. Refused during charging or
        with less than 20 percent battery available for the full trip. Wet weather
        produces a ground-wet warning. Species identification depends on the target field's diagnostic
        capabilities. Detections may be uncertain; read confidence where provided.
        An unavailable diagnosis is not confirmed absence of a problem.

        Args:
            farm_id: Exact target farm ID from the available farm directory.
            ridge_id: Local ridge ID, from 0 to that farm's num_ridges - 1.

        Returns:
            Farm-qualified inspection, pest/disease diagnostic, shared remaining
            battery and optional wet-ground warning, or error if refused.
        """
        farm = self.farm_environment.get_farm(farm_id)
        self.farm_environment.before_tool()
        return self._inspect_ridge(farm, ridge_id)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def inspect_pests(
        self, farm_id: str, start_ridge: int, end_ridge: int
    ) -> dict[str, Any]:
        """Inspect a local ridge range for pests using this shared ground robot.

        Detections have uncertainty. A mission visits at most eight ridges,
        limited by remaining battery. Unvisited ridges remain uncovered. Each ridge consumes
        5 battery percentage points, leaving at least 10 percent for return.
        Advances all farms by round-trip walking time per covered ridge.
        Charging or starting battery below 15 percent refuses the inspection.
        Unavailable diagnoses remain unknown.

        Args:
            farm_id: Exact target farm ID from the available farm directory.
            start_ridge: First local ridge ID in that farm, starting at 0.
            end_ridge: Last local ridge ID, inclusive; at least start_ridge and
                less than that farm's num_ridges.

        Returns:
            Farm-qualified observations, covered and uncovered ridge IDs,
            shared remaining battery and wet-ground warning when applicable.
            Status partial means some requested ridges were not inspected.
            Unavailable weed evidence is reported as unknown; error reports
            a refused inspection.
        """
        farm = self.farm_environment.get_farm(farm_id)
        self.farm_environment.before_tool()
        return self._inspect_range(farm, start_ridge, end_ridge, modality="pest")

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def inspect_crop_health(
        self, farm_id: str, start_ridge: int, end_ridge: int
    ) -> dict[str, Any]:
        """Inspect pest/disease/weed presence and stand fraction in one target farm.

        Detections have uncertainty. A mission visits at most eight ridges,
        reduced by remaining battery. Each covered ridge consumes 5 battery percentage points, leaving at least
        10 percent for return. Advances time for every registered farm.
        Charging or starting battery below 15 percent refuses the inspection.
        Unavailable diagnoses remain unknown. Combine symptoms with soil and
        weather evidence before deciding on treatment.

        Args:
            farm_id: Exact target farm ID from the available farm directory.
            start_ridge: First local ridge ID in that farm, starting at 0.
            end_ridge: Last local ridge ID, inclusive; at least start_ridge and
                less than that farm's num_ridges.

        Returns:
            Farm-qualified observations, covered/uncovered local ridge IDs,
            shared battery and optional ground-wet warning. Status partial means
            incomplete coverage; error means refused. Missing evidence is unknown.
        """
        farm = self.farm_environment.get_farm(farm_id)
        self.farm_environment.before_tool()
        return self._inspect_range(farm, start_ridge, end_ridge, modality="crop_health")

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def inspect_emergence(
        self, farm_id: str, start_ridge: int, end_ridge: int
    ) -> dict[str, Any]:
        """Inspect emergence stand fraction in the specified farm's ridge range.

        Read current visible-stand estimates and the observation's source and
        coverage. A mission visits up to eight ridges, limited by battery.
        Unavailable stand evidence must not be treated as confirmed crop failure.
        Each covered ridge consumes 5 battery percentage points, leaving at least
        10 percent for return. Advances time for every registered farm.
        Charging or starting battery below 15 percent refuses the inspection.

        Args:
            farm_id: Exact target farm ID from the available farm directory.
            start_ridge: First local ridge ID in that farm, starting at 0.
            end_ridge: Last local ridge ID, inclusive; at least start_ridge and
                less than that farm's num_ridges.

        Returns:
            Farm-qualified stand fractions and detections, covered/uncovered
            local ridge IDs and shared battery. Status partial means incomplete
            coverage; error means refused. Ground-wet warning may be present.
        """
        farm = self.farm_environment.get_farm(farm_id)
        self.farm_environment.before_tool()
        return self._inspect_range(farm, start_ridge, end_ridge, modality="emergence")

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def check_status(self) -> dict[str, Any]:
        """Read this robot's shared battery and charging session without a farm.

        Returns:
            Device name, description, battery percentage, charging flag and
            minutes until full according to the shared elapsed time.
        """
        self.farm_environment.before_tool()
        return self._check_status()

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def charge(self) -> dict[str, Any]:
        """Start charging this shared robot without selecting a farm.

        Battery rises over 60 minutes of elapsed time. This call does
        not wait or advance time. During charging the robot cannot inspect any
        registered farm. Repeated calls do not restart an active charge session.

        Returns:
            Charging status, shared battery, completion timestamp and ETA in
            minutes; already charging/full states are reported without restart.
        """
        self.farm_environment.before_tool()
        return self._charge()
