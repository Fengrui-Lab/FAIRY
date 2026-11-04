"""A fixed supply roster and station throughput for block irrigation."""

import math
from datetime import datetime

from fairy.apps.app import App
from fairy.apps.farm_world.irrigation_app import (
    _IRRIGATION_SETUP_S,
    _IRRIGATION_S_PER_HOUR,
)
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered

from .winter_wheat_irrigation_app import WinterWheatIrrigation


class WinterWheatTurnIrrigation(WinterWheatIrrigation):
    def __init__(self, farm, weather, *, max_blocks, supply_windows):
        super().__init__(farm, weather)
        self.max_blocks = max_blocks
        self.supply_windows = supply_windows
        self._supply_times = tuple(
            (
                datetime.fromisoformat(start).timestamp(),
                datetime.fromisoformat(end).timestamp(),
            )
            for start, end in supply_windows
        )

    def get_tools(self):
        return [
            tool
            for tool in App.get_tools(self)
            if tool.name in {"irrigate", "get_irrigation_log", "get_supply_schedule"}
        ]

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_supply_schedule(self) -> dict:
        """Check station capacity and the remaining supply turns.

        Returns:
            dict: Maximum simultaneous blocks, depth rate (mm/hour), setup
            time (seconds), local turn times and seconds left in the active turn.
            A delivery including setup must finish within one turn.
        """
        now = self.time_manager.time()
        return {
            "max_simultaneous_blocks": self.max_blocks,
            "depth_rate_mm_per_hour": 5.0,
            "setup_seconds": _IRRIGATION_SETUP_S,
            "remaining_turns": [
                {"opens_at": start, "closes_at": end}
                for (start, end), (_, close) in zip(
                    self.supply_windows, self._supply_times
                )
                if now < close
            ],
            "active_turn_seconds_left": next(
                (
                    close - now
                    for start, close in self._supply_times
                    if start <= now < close
                ),
                0,
            ),
        }

    def _start_irrigation(self, ridge_ids, duration_hours):
        schedule = self.get_supply_schedule()
        if len(ridge_ids) > self.max_blocks:
            return {
                "error": "The station cannot serve that many blocks at once",
                **schedule,
            }
        run_seconds = duration_hours * _IRRIGATION_S_PER_HOUR
        if not math.isfinite(run_seconds):
            return {"error": "Requested delivery duration is too large"}
        needed_s = _IRRIGATION_SETUP_S + int(run_seconds)
        if needed_s > schedule["active_turn_seconds_left"]:
            return {
                "error": "Delivery and setup do not fit in the active supply turn",
                "required_seconds": needed_s,
                **schedule,
            }
        return super()._start_irrigation(ridge_ids, duration_hours)
