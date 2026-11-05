"""Legacy single-farm facade for irrigation and manual spraying.

Two-farm scenes register fixed IrrigationApp instances and a shared ManualOpsApp.
The agricultural rules live in irrigation_app.py and manual_operations.py.
"""
from __future__ import annotations

from typing import Any

from fairy.apps.farm_world.farm_environment import FarmContext
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.farm_world.irrigation_app import (
    IrrigationApp, _IRRIGATION_SETUP_S, _IRRIGATION_S_PER_HOUR,
    _IRRIGATION_VWC_PER_HOUR, _IRRIGATION_EFFECT_DELAY_S,
)
from fairy.apps.farm_world.manual_operations import (
    ManualOperations, _MANUAL_PESTICIDE_L_PER_RIDGE, _MANUAL_SPRAY_SPEED_MS,
    _MANUAL_SPRAY_SETUP_S, _manual_spray_duration,
)
from fairy.apps.app import App
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check


class FieldOpsApp(IrrigationApp, ManualOperations):
    """Legacy single-farm irrigation and manual spraying tools."""

    require_explicit_tool_docs = False
    validate_tool_arguments = True

    def __init__(self, farm_world_app: FarmWorldApp, weather_app: WeatherApp, name: str | None = None) -> None:
        super().__init__(farm_world_app, weather_app, name=name or "FieldOpsApp")
        self._manual_spray_log: list[dict[str, Any]] = []

    def get_tools(self):
        return App.get_tools(self)

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["manual_spray_log"] = [dict(entry) for entry in self._manual_spray_log]
        return state

    def load_state(self, state_dict: dict[str, Any]) -> None:
        super().load_state(state_dict)
        self._manual_spray_log = [dict(entry) for entry in state_dict.get("manual_spray_log", [])]

    def reset(self) -> None:
        super().reset()
        self._manual_spray_log = []

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_pesticide_manual(
        self, ridge_id: int, liters_per_ridge: float = _MANUAL_PESTICIDE_L_PER_RIDGE,
        advance_time: bool = True, ridge_count: int = 1,
    ) -> dict[str, Any]:
        """Apply pesticide on one or two bound-farm ridges with a backpack sprayer.

        Fields without hand-spray support reject this operation before resource use.

        Args:
            ridge_id: First local ridge to spray.
            liters_per_ridge: Positive working-fluid litres per ridge; The standard working-fluid rate is 3 L/ridge and lower volumes reduce treatment strength.
            advance_time: Whether to count the operator working duration as elapsed time.
            ridge_count: Number of contiguous ridges, at most two.
        """
        farm = FarmContext(getattr(self._farm_world_app, "farm_id", "farm"),
                           self._farm_world_app, self._weather_app,
                           legacy_clock=self.time_manager)
        return ManualOperations.apply_pesticide_manual(
            self, farm, ridge_id, liters_per_ridge, advance_time, ridge_count)
