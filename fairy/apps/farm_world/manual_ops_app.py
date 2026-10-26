"""Shared operator tools: each call explicitly selects a farm."""
from __future__ import annotations

from typing import Any

from fairy.apps.app import App
from fairy.apps.farm_world.farm_environment import FarmEnvironment
from fairy.apps.farm_world.manual_operations import ManualOperations
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check


class ManualOpsApp(App, ManualOperations):
    require_explicit_tool_docs = True
    validate_tool_arguments = True

    def __init__(self, environment: FarmEnvironment, name: str = "ManualOps") -> None:
        super().__init__(name)
        self.farm_environment = environment
        self.time_manager = environment.time_manager
        self.tool_parameter_choices = {"farm_id": sorted(environment.farms)}
        self._manual_spray_log: list[dict[str, Any]] = []

    def get_state(self) -> dict[str, Any]:
        return {"app_name": self.name,
                "manual_spray_log": [dict(entry) for entry in self._manual_spray_log]}

    def load_state(self, state_dict: dict[str, Any]) -> None:
        self._manual_spray_log = [dict(entry) for entry in state_dict.get("manual_spray_log", [])]

    def reset(self) -> None:
        super().reset()
        self._manual_spray_log = []

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_pesticide_manual(
        self, farm_id: str, start_ridge: int, end_ridge: int,
        liters_per_ridge: float = 3.0,
    ) -> dict[str, Any]:
        """Hand-spray one or two contiguous ridges in the selected farm.

        Draws chemicals from the shared warehouse and records application quota
        on the selected farm. Requires sprayable weather and advances the common
        clock for the operator passes.
        Native WOFOST maize has no crop-protection model and refuses this action.

        Args:
            farm_id: Exact target farm ID; chemical stock comes from the shared warehouse.
            start_ridge: First local ridge ID, inclusive and zero based.
            end_ridge: Last local ridge ID; at most two ridges per call.
            liters_per_ridge: Positive working-fluid litres per ridge. The simulation
                backpack reference is 3 L/ridge; lower volumes reduce treatment strength.

        Returns:
            Farm ID, treated ridge IDs, actual pesticide use and quota status,
            or an error explaining the rejected operation.
        """
        farm = self.farm_environment.get_farm(farm_id)
        if type(start_ridge) is not int or type(end_ridge) is not int:
            return {"error": "ridge IDs must be integers", "farm_id": farm_id}
        if not 0 <= start_ridge <= end_ridge < farm.world.num_ridges:
            return {"error": "Invalid inclusive ridge range", "farm_id": farm_id}
        self.farm_environment.before_tool()
        result = ManualOperations.apply_pesticide_manual(
            self, farm, start_ridge, liters_per_ridge, True, end_ridge - start_ridge + 1)
        return {**result, "farm_id": farm_id}
