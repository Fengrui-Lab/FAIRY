"""Single-farm robot App; shares algorithms with the explicitly routed App."""
from __future__ import annotations

from typing import Any

from fairy.apps.app import App
from fairy.apps.farm_world.farm_environment import FarmContext
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.farm_world.robot_operations import RobotOperations
from fairy.tool_utils import OperationType, app_tool, data_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check


class RobotApp(RobotOperations, App):
    """One physical robot permanently bound to a single legacy farm."""

    validate_tool_arguments = True

    def __init__(
        self,
        farm_world_app: FarmWorldApp,
        weather_app: WeatherApp,
        *,
        name: str = "RobotApp",
        description: str = "",
    ) -> None:
        App.__init__(self, name=name)
        self._farm_world_app = farm_world_app
        self._weather_app = weather_app
        farm_world_app.attach_weather_app(weather_app)
        self._initialize_robot(description=description)

    def _bound_farm(self) -> FarmContext:
        environment = self._farm_world_app.farm_environment
        if environment is not None:
            return environment.get_farm(self._farm_world_app.farm_id)
        return FarmContext(
            farm_id=self._farm_world_app.name,
            world=self._farm_world_app,
            weather=self._weather_app,
            legacy_clock=self.time_manager,
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def inspect_ridge(self, ridge_id: int) -> dict[str, Any]:
        """Walk the full length of one ridge and back to inspect ground-level crop condition.

        Use this to investigate anomalies. Read the returned diagnoses and their
        confidence; species identification depends on the field's diagnostic
        capabilities. An unavailable diagnosis is not confirmed absence of a problem.

        Args:
            ridge_id:  Local ridge ID, from 0 to this farm's num_ridges - 1.
        """

        return self._inspect_ridge(self._bound_farm(), ridge_id)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def inspect_pests(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        """Inspect a ridge range for ground-level pest, disease and weed evidence.

        A mission visits up to eight ridges, limited by battery. Check covered
        and uncovered ridges before planning follow-up work. Detections have
        uncertainty and may miss or misidentify a problem. Unavailable diagnoses
        are unknown, not evidence that a problem is absent.

        Args:
            start_ridge: First local ridge, from 0 to this farm's num_ridges - 1.
            end_ridge:   Last ridge (inclusive, >= start_ridge).
        """

        return self._inspect_range(self._bound_farm(), start_ridge, end_ridge, modality="pest")

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def inspect_crop_health(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        """Inspect visible crop condition and available pest, disease and weed evidence.

        A mission visits up to eight ridges, limited by battery. Read coverage,
        symptoms and confidence together with soil and weather observations when
        assessing the cause of poor growth. This inspection alone does not establish
        a nutrient-deficiency diagnosis. Unavailable diagnoses remain unknown.

        Args:
            start_ridge: First local ridge, from 0 to this farm's num_ridges - 1.
            end_ridge:   Last ridge (inclusive, >= start_ridge).
        """

        return self._inspect_range(
            self._bound_farm(), start_ridge, end_ridge, modality="crop_health"
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def inspect_emergence(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        """Estimate the fraction of expected plants currently visible in a ridge range.

        A mission visits up to eight ridges, limited by battery. Read coverage
        before interpreting stand estimates. Assess gap distribution, crop stage
        and the remaining planting window before deciding whether to replant.

        Args:
            start_ridge: First local ridge, from 0 to this farm's num_ridges - 1.
            end_ridge:   Last ridge (inclusive, >= start_ridge).
        """

        return self._inspect_range(self._bound_farm(), start_ridge, end_ridge, modality="emergence")

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def check_status(self) -> dict[str, Any]:
        """Return battery level, charging state, and robot configuration."""

        return self._check_status()

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def charge(self) -> dict[str, Any]:
        """
        Send this robot dog back to its charging station.

        Charging completes asynchronously after about 60 minutes of
        environment time. The battery level increases gradually while charging.
        """

        return self._charge()
