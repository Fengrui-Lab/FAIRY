"""Fixed irrigation controller bound to exactly one farm.

Each farm owns its controller, history and pending deliveries. Water effects
and operation durations retain the original FieldOps irrigation rules.
"""
from __future__ import annotations

from typing import Any
from datetime import datetime, time, timedelta

from fairy.apps.app import App
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.tool_utils import OperationType, app_tool, data_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check

_IRRIGATION_SETUP_S = 300
_IRRIGATION_S_PER_HOUR = 3600
_IRRIGATION_VWC_PER_HOUR = 0.05
_IRRIGATION_EFFECT_DELAY_S = 2 * 60 * 60


class IrrigationApp(App):
    """One farm's stationary irrigation; no manual chemical operations."""

    require_explicit_tool_docs = True
    validate_tool_arguments = True

    def __init__(self, farm_world_app: FarmWorldApp, weather_app: WeatherApp,
                 name: str | None = None) -> None:
        super().__init__(name or "IrrigationApp")
        self._farm_world_app = farm_world_app
        self._weather_app = weather_app
        self._irrigation_log: list[dict[str, Any]] = []
        self.bound_farm_id = getattr(farm_world_app, "farm_id", None)
        farm_world_app.attach_weather_app(weather_app)

    def get_tools(self):
        """Expose the canonical irrigation methods; legacy aliases stay local."""
        return [tool for tool in super().get_tools()
                if tool.name in {"irrigate", "get_irrigation_log"}]

    @property
    def irrigation_stop_vwc(self) -> float:
        return self._farm_world_app.crop_profile.irrigation_stop_vwc

    def get_state(self) -> dict[str, Any]:
        return {"app_name": self.name, "farm_id": self.bound_farm_id,
                "irrigation_log": [dict(entry) for entry in self._irrigation_log]}

    def load_state(self, state_dict: dict[str, Any]) -> None:
        """Restore history without changing this controller's farm binding.

        Old snapshots without an identified farm, and unbound legacy instances,
        retain their original loading behavior.
        """
        saved_farm_id = state_dict.get("farm_id")
        if (self.bound_farm_id is not None and saved_farm_id is not None
                and saved_farm_id != self.bound_farm_id):
            raise ValueError(
                f"Cannot load farm {saved_farm_id!r} state into irrigation bound to {self.bound_farm_id!r}"
            )
        self._irrigation_log = [dict(entry) for entry in state_dict.get("irrigation_log", [])]

    def reset(self) -> None:
        super().reset()
        self._irrigation_log = []

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def irrigate_ridge(self, ridge_id: int, duration_hours: float) -> dict[str, Any]:
        """Irrigate a single ridge.

        Args:
            ridge_id:       Ridge to irrigate (within this farm).
            duration_hours: Irrigation run time in hours.
        """
        if not 0 <= ridge_id < self._farm_world_app.num_ridges:
            return {"error": f"Invalid ridge_id {ridge_id}"}
        if float(duration_hours) <= 0:
            return {"error": "duration_hours must be positive"}
        current_vwc = self._irrigation_check_vwc(ridge_id)
        if current_vwc >= self.irrigation_stop_vwc:
            return {
                "error": f"Ridge {ridge_id} soil VWC {current_vwc:.3f} already >= {self.irrigation_stop_vwc:.2f}"
            }
        return self._start_irrigation([ridge_id], float(duration_hours))


    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def irrigate(self, start: int, end: int, hours: float) -> dict[str, Any]:
        """Irrigate a contiguous range using this field's water allowance.

        Requires the irrigation moisture check to be below the crop's stop
        threshold throughout the requested range. Consumes setup and running
        time. Water delivery or its soil response may complete later; use
        effect_ready_at to schedule a recheck. Inspect already-pending irrigation
        before starting another run.

        Args:
            start: First local ridge ID, zero based and inclusive.
            end: Last local ridge ID, inclusive and at least start.
            hours: Positive irrigation run time per ridge in hours.
        """
        if not 0 <= start <= end < self._farm_world_app.num_ridges:
            return {"error": f"Invalid ridge range [{start}, {end}]"}
        if float(hours) <= 0:
            return {"error": "hours must be positive"}
        for ridge_id in range(start, end + 1):
            current_vwc = self._irrigation_check_vwc(ridge_id)
            if current_vwc >= self.irrigation_stop_vwc:
                return {
                    "error": f"Ridge {ridge_id} soil VWC {current_vwc:.3f} already >= {self.irrigation_stop_vwc:.2f}"
                }
        return self._start_irrigation(list(range(start, end + 1)), float(hours))


    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def irrigate_range(
        self, start: int, end: int, duration_hours: float
    ) -> dict[str, Any]:
        """Irrigate a contiguous range of ridges.

        Args:
            start:          First ridge to irrigate (within this farm).
            end:            Last ridge to irrigate (within this farm, >= start).
            duration_hours: Irrigation run time per ridge in hours.
        """
        if not 0 <= start <= end < self._farm_world_app.num_ridges:
            return {"error": f"Invalid ridge range [{start}, {end}]"}
        if float(duration_hours) <= 0:
            return {"error": "duration_hours must be positive"}
        for ridge_id in range(start, end + 1):
            current_vwc = self._irrigation_check_vwc(ridge_id)
            if current_vwc >= self.irrigation_stop_vwc:
                return {
                    "error": f"Ridge {ridge_id} soil VWC {current_vwc:.3f} already >= {self.irrigation_stop_vwc:.2f}"
                }
        return self._start_irrigation(
            list(range(start, end + 1)), float(duration_hours)
        )


    def _irrigation_check_vwc(self, ridge_id: int) -> float:
        """Use root-zone VWC for physics irrigation decisions when available."""
        environment = getattr(self._farm_world_app, "farm_environment", None)
        if environment is not None:
            environment.before_tool()
        if self._farm_world_app.physics_active:
            self._farm_world_app.advance_physics_time()
            soil_state = self._farm_world_app.physics.soil.states.get(ridge_id)
            if soil_state is not None:
                return float(soil_state.root_vwc)
        return float(self._farm_world_app.get_ridge(ridge_id).soil_vwc)


    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_irrigation_log(self) -> dict[str, Any]:
        """
        Return the irrigation history for all ridges.
        """
        return {"irrigation_log": list(self._irrigation_log)}


    def _start_irrigation(
        self, ridge_ids: list[int], duration_hours: float
    ) -> dict[str, Any]:
        pending = self._farm_world_app.get_pending_irrigation_for_ridges(ridge_ids)
        if pending:
            earliest = pending[0]
            return {
                "status": "irrigation_pending",
                "farm_id": self.bound_farm_id,
                "irrigated_ridges": [item["ridge_id"] for item in pending],
                "effect_ready_at": earliest["effect_ready_at"],
                "message": (
                    "Irrigation effect is still pending for part of this range. "
                    "Wait until effect_ready_at before rechecking soil moisture."
                ),
            }

        duration_s = _IRRIGATION_SETUP_S + int(duration_hours * _IRRIGATION_S_PER_HOUR)
        add_vwc = duration_hours * _IRRIGATION_VWC_PER_HOUR
        mm_per_hour = 5.0
        mm_per_ridge = float(duration_hours) * mm_per_hour
        field_equivalent_mm = (
            mm_per_ridge * len(ridge_ids) / max(1, self._farm_world_app.num_ridges)
        )
        quota_error = self._farm_world_app.check_irrigation_quota(field_equivalent_mm)
        if quota_error:
            return {"error": quota_error}
        self._advance_linked_time(duration_s)
        finished_at = float(self.time_manager.time())
        effect_ready_at = finished_at + _IRRIGATION_EFFECT_DELAY_S

        if self._farm_world_app.physics_active:
            effect_ready_at = finished_at
            if self._farm_world_app.physics.crop_backend is not None:
                zone = self._farm_world_app.simulation_timezone
                next_day = datetime.fromtimestamp(finished_at, zone).date() + timedelta(days=1)
                effect_ready_at = datetime.combine(next_day, time.min, zone).timestamp()
            # Physics path: queue ManagementAction(IRRIGATION) so the soil
            # engine receives water on the next advance_physics_time call,
            # and record a FarmActionRecord. The legacy add_vwc bump is
            # bypassed (set_irrigation_pending not called).
            self._register_irrigation_with_physics(
                ridge_ids=ridge_ids,
                duration_hours=duration_hours,
                duration_s=duration_s,
                effect_ready_at=effect_ready_at,
            )
        else:
            for ridge_id in ridge_ids:
                self._farm_world_app.set_irrigation_pending(
                    ridge_id, add_vwc, effect_ready_at=effect_ready_at
                )
                self._irrigation_log.append(
                    {
                        "ridge_id": ridge_id,
                        "duration_hours": duration_hours,
                        "duration_s": duration_s,
                        "date": self._farm_world_app.get_state()["sim_date"],
                        "effect_ready_at": effect_ready_at,
                    }
                )

        regime_status = self._farm_world_app.record_irrigation_use(field_equivalent_mm)
        self.is_state_modified = True
        response = {
            "status": "irrigation_started",
            "farm_id": self.bound_farm_id,
            "irrigated_ridges": list(ridge_ids),
            "duration_hours_per_ridge": duration_hours,
            "estimated_water_mm_per_ridge": round(mm_per_ridge, 3),
            "field_equivalent_irrigation_mm": round(field_equivalent_mm, 4),
            "management_regime": regime_status,
            "total_duration_minutes": round(duration_s / 60, 1),
            "effect_ready_at": effect_ready_at,
            "eta_minutes_to_confirmation": round((effect_ready_at - finished_at) / 60.0, 1),
            "message": (
                "Irrigation run finished. Water is queued for the next native daily settlement; recheck at effect_ready_at."
                if self._farm_world_app.physics_active and self._farm_world_app.physics.crop_backend is not None else
                "Irrigation run finished. Water input has been applied by the soil engine."
                if self._farm_world_app.physics_active else
                "Irrigation run finished. Recheck soil moisture after the 2-hour delivery delay."
            ),
        }
        if len(ridge_ids) == 1:
            response["ridge_id"] = ridge_ids[0]
            response["duration_hours"] = duration_hours
            response["duration_minutes"] = round(duration_s / 60, 1)
        return response


    def _advance_linked_time(self, offset_seconds: float) -> None:
        """
        Advance time for this app and directly linked farm/weather apps.

        In tests these apps often share references without being registered into
        an Environment, so they do not automatically share the same TimeManager.
        """
        environment = getattr(self._farm_world_app, "farm_environment", None)
        if environment is not None:
            environment.advance_time(offset_seconds)
            return
        self.time_manager.add_offset(offset_seconds)
        for app in (self._farm_world_app, self._weather_app):
            if app.time_manager is self.time_manager:
                continue
            app.time_manager.add_offset(offset_seconds)


    def _register_irrigation_with_physics(
        self,
        ridge_ids: list[int],
        duration_hours: float,
        duration_s: int,
        effect_ready_at: float,
    ) -> None:
        import uuid

        from fairy.apps.farm_world.farm_action_record import FarmActionRecord
        from fairy.physics import ManagementAction, ManagementActionType

        # Approximate water delivered: legacy +0.05 VWC per hour matched a
        # ~5 mm/hour delivery in our top-zone soil engine. Keep that mapping
        # so scenarios calibrated to the legacy behaviour still produce a
        # comparable VWC bump after the soil engine processes the action.
        mm_per_hour = 5.0
        mm_per_ridge = float(duration_hours) * mm_per_hour

        physics = self._farm_world_app.physics
        for ridge_id in ridge_ids:
            physics.queue_management_action(
                ridge_id,
                ManagementAction(
                    action_type=ManagementActionType.IRRIGATION,
                    amount=mm_per_ridge,
                    quality=1.0,
                    metadata={"duration_hours": float(duration_hours)},
                ),
            )
            self._irrigation_log.append(
                {
                    "ridge_id": ridge_id,
                    "duration_hours": float(duration_hours),
                    "duration_s": duration_s,
                    "date": self._farm_world_app.get_state()["sim_date"],
                    "effect_ready_at": effect_ready_at,
                    "estimated_water_mm": mm_per_ridge,
                }
            )

        self._farm_world_app.record_action(
            FarmActionRecord(
                action_id=str(uuid.uuid4())[:8],
                timestamp=float(self.time_manager.time()),
                actor_app=self.name,
                action_type="irrigation",
                ridge_ids=list(ridge_ids),
                parameters={
                    "duration_hours": float(duration_hours),
                    "estimated_water_mm": mm_per_ridge,
                },
                direct_effect_summary={
                    "soil_water_input_registered": True,
                    "effect_ready_at": effect_ready_at,
                },
            )
        )

        # Apply the action immediately to soil via the orchestrator's
        # sub-daily path. The next time advance crosses a date boundary,
        # the daily cycle will pick up cumulative effects.
        self._farm_world_app.advance_physics_time()
