from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from fairy.apps.app import App
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check


@dataclass
class WaitForNotificationTimeout:
    time_created: float
    timeout: int = 0
    timeout_timestamp: float = field(init=False)

    def __post_init__(self) -> None:
        self.timeout_timestamp = self.time_created + self.timeout


class SystemApp(App):
    def __init__(self, name: str | None = None):
        super().__init__(name)
        self.wait_for_notification_timeout: WaitForNotificationTimeout | None = None
        self.wait_for_next_notification: Callable[[], None] = lambda: None
        self._farm_world_app = None

    def wait(self, time: int = 0) -> None:
        assert time >= 0, "Time must be non-negative"
        self.time_manager.add_offset(time)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_current_time(self) -> dict:
        """
        Get the current time, date, and weekday.

        Returns a dictionary with the keys "current_timestamp" (epoch
        timestamp), "current_datetime" (YYYY-MM-DD HH:MM:SS), and
        "current_weekday" (Monday, Tuesday, etc.).
        """
        timestamp = self.time_manager.time()
        date = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return {
            "current_timestamp": timestamp,
            "current_datetime": date.strftime("%Y-%m-%d %H:%M:%S"),
            "current_weekday": date.strftime("%A"),
        }

    def reset_wait_for_notification_timeout(self) -> None:
        self.wait_for_notification_timeout = None

    def attach_farm_world_app(self, farm_world_app) -> None:
        self._farm_world_app = farm_world_app

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def advance_time(
        self,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        days: int = 0,
    ) -> dict:
        """
        Advance the simulation clock by a specified amount of time.

        Use this fast-forward tool when waiting for biological or physical
        processes to play out, such as crop growth, soil drying, treatment
        residual decay, irrigation effects, or post-harvest drying. After time
        advances, subsequent state reads reflect the evolved world.

        Args:
            seconds: Seconds to advance.
            minutes: Minutes to advance.
            hours: Hours to advance.
            days: Days to advance.

        Returns:
            A dictionary containing the new current time.
        """
        total_seconds = (
            int(seconds) + int(minutes) * 60 + int(hours) * 3600 + int(days) * 86400
        )
        if total_seconds <= 0:
            return {"error": "advance_time amount must be > 0"}
        farm_world_app = self._farm_world_app
        if farm_world_app is not None:
            prepare = getattr(farm_world_app, "prepare_for_time_advance", None)
            if callable(prepare):
                prepare(float(self.time_manager.time()))
        self.time_manager.add_offset(total_seconds)
        if farm_world_app is not None:
            fw_tm = getattr(farm_world_app, "time_manager", None)
            if fw_tm is not None and fw_tm is not self.time_manager:
                fw_tm.add_offset(total_seconds)
            weather_app = getattr(farm_world_app, "_weather_app", None)
            if weather_app is not None:
                w_tm = getattr(weather_app, "time_manager", None)
                if w_tm is not None and w_tm is not self.time_manager and w_tm is not fw_tm:
                    w_tm.add_offset(total_seconds)
            advance = getattr(farm_world_app, "advance_physics_time", None)
            if callable(advance):
                advance()
        timestamp = self.time_manager.time()
        return {
            "status": "ok",
            "advanced_seconds": total_seconds,
            "current_timestamp": timestamp,
            "current_datetime": datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        }

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def wait_for_notification(self, timeout: int = 0) -> None:
        """
        Wait until the next notification or user message is received.

        Use this only when there are no other useful tasks to perform. If
        timeout is greater than zero, waiting ends after at most that many
        seconds even if no notification arrives.

        Args:
            timeout: Maximum number of seconds to wait.
        """
        timeout = int(timeout)
        assert timeout >= 0, "Timeout must be non-negative"
        self.wait_for_notification_timeout = WaitForNotificationTimeout(
            timeout=timeout, time_created=self.time_manager.time()
        )
        self.wait_for_next_notification()
