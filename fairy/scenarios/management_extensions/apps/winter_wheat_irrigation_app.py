"""Reuse irrigation delivery, time, quota and logs with explicit block/depth units."""

import math
from fairy.apps.farm_world.irrigation_app import IrrigationApp
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered


class WinterWheatIrrigation(IrrigationApp):
    def __init__(self, farm, weather):
        super().__init__(farm, weather, name="Irrigation")

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def irrigate(self, start_block: int, end_block: int, depth_mm: float) -> dict:
        """Deliver gross irrigation depth to selected blocks at 5 mm/hour.

        Args:
            start_block: First block ID, inclusive; see WheatField.get_field_info.
            end_block: Last block ID, inclusive, at least start_block.
            depth_mm: Positive finite gross mm per block. m3 = mm * treated m2 / 1000.

        Returns:
            dict: Consumed water, duration and next daily effect time or error.
            Requires active crop, soil below saturation and remaining farm water.
            Delivery advances the shared clock; recheck after native daily settlement.
        """
        f = self._farm_world_app
        f.advance_physics_time()
        if (
            type(start_block) is not int
            or type(end_block) is not int
            or not 0 <= start_block <= end_block < f.num_ridges
        ):
            return {"error": "Invalid block range"}
        if (
            type(depth_mm) not in (int, float)
            or not math.isfinite(depth_mm)
            or depth_mm <= 0
        ):
            return {"error": "depth_mm must be finite and positive"}
        ids = list(range(start_block, end_block + 1))
        if any(not f._ridges[i].planted or f.backends[i].maturity for i in ids):
            return {
                "error": "Irrigation requires a living crop in every selected block"
            }
        if any(f._ridges[i].soil_vwc >= 0.45 for i in ids):
            return {"error": "Selected soil is saturated"}
        return self._start_irrigation(ids, depth_mm / 5)

    def _register_irrigation_with_physics(
        self, ridge_ids, duration_hours, duration_s, effect_ready_at
    ):
        f = self._farm_world_app
        for i in ridge_ids:
            b = f.backends[i]
            b.queue(f"water_{len(b.receipts)}", "irrigate", duration_hours * 5)
            self._irrigation_log.append(
                dict(
                    ridge_id=i,
                    block_id=i,
                    duration_hours=duration_hours,
                    duration_s=duration_s,
                    date=f._sim_date,
                    effect_ready_at=effect_ready_at,
                    estimated_water_mm=duration_hours * 5,
                )
            )
