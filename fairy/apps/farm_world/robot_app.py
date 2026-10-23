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
        """
        Send this robot dog to walk the full length of a ridge and back, reporting
        pest and disease presence at ground level.

        Use this to ground-truth anomalies flagged by drone surveys.
        Diagnostic species labels are returned only when the field's configured
        observation capability supports them; otherwise detections are noisy
        and do not identify pest species or disease identity.

        Args:
            ridge_id:  Local ridge ID, from 0 to this farm's num_ridges - 1.
        """

        return self._inspect_ridge(self._bound_farm(), ridge_id)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def inspect_pests(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        """
        Walk a contiguous ridge range, returning ground-level pest detections.

        Routes through the ObservationModel — results are noisy and may include
        false positives/negatives. A mission visits up to eight ridges, limited
        by battery. The observation model samples every visited ridge in batches
        (four ridges per batch by default). Unvisited ridges are explicitly
        returned as uncovered. Use after
        an aerial drone survey flagged an anomaly to confirm cause.

        Args:
            start_ridge: First local ridge, from 0 to this farm's num_ridges - 1.
            end_ridge:   Last ridge (inclusive, >= start_ridge).
        """

        return self._inspect_range(self._bound_farm(), start_ridge, end_ridge, modality="pest")

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def inspect_crop_health(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        """
        Walk a contiguous ridge range, returning ground-level pest + disease detections
        plus visible canopy health diagnostics.

        Use this when you need to discriminate among nutrient stress, drought
        stress, and biotic causes of low NDVI. The robot can return both pest
        and disease confidence scores per ridge in one pass.
        A mission visits up to eight ridges, limited by battery. Each visited
        ridge receives an actual observation-model product in sensor-sized
        batches (four ridges by default); unvisited ridges are uncovered.

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
        """
        Walk a contiguous ridge range, returning per-ridge emergence stand
        estimates (fraction of expected plants visible).

        Used in the early-season emergence-check loop. Stand fraction below
        0.7 typically indicates a replant decision.
        A mission visits up to eight ridges, limited by battery, using actual
        sensor-sized observation batches (four ridges per batch by default).
        Unemerged crops and harvested ground have zero visible stand.

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
