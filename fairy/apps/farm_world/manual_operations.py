"""Manual chemical application rules with an explicit target farm."""
from __future__ import annotations

from typing import Any

from fairy.apps.farm_world.farm_environment import FarmContext
from fairy.apps.farm_world.farm_world_app import FIELD_LENGTH_M

_MANUAL_SPRAY_SPEED_MS = 0.8
_MANUAL_SPRAY_SETUP_S = 15
_MANUAL_PESTICIDE_L_PER_RIDGE = 3.0


def _manual_spray_duration() -> int:
    return int(FIELD_LENGTH_M / _MANUAL_SPRAY_SPEED_MS) + _MANUAL_SPRAY_SETUP_S


class ManualOperations:
    """Behavior shared by the old bound facade and explicit farm tools."""

    def apply_pesticide_manual(
        self,
        farm: FarmContext,
        ridge_id: int,
        liters_per_ridge: float = _MANUAL_PESTICIDE_L_PER_RIDGE,
        advance_time: bool = True,
        ridge_count: int = 1,
    ) -> dict[str, Any]:
        """
        Apply pesticide to one or two contiguous ridges using the handheld backpack sprayer.
        Suitable for small, localised problems. For larger outbreaks use the
        tractor spray boom instead.

        Args:
            ridge_id: Ridge to spray (0-63).
            liters_per_ridge: Pesticide volume to apply on this ridge.
            advance_time: Whether to advance the simulation clock for one operator pass.
            ridge_count: Number of contiguous ridges to spray, max 2.
        """
        if not 0 <= ridge_id < farm.world.num_ridges:
            return {"error": f"Invalid ridge_id {ridge_id}"}
        count = int(ridge_count)
        if not 1 <= count <= 2:
            return {"error": "ridge_count must be 1 or 2"}
        end_ridge = ridge_id + count - 1
        if end_ridge >= farm.world.num_ridges:
            return {"error": f"Invalid ridge range [{ridge_id}, {end_ridge}]"}
        liters = float(liters_per_ridge)
        if liters <= 0:
            return {"error": "liters_per_ridge must be positive"}
        total_liters = liters * count
        if not farm.weather.is_sprayable:
            return {
                "error": "Weather conditions do not allow spraying (rain or wind above spray limit)"
            }
        regime_error = farm.world.check_chemical_application(
            "insecticide", total_liters
        )
        if regime_error:
            return {"error": regime_error}
        if not farm.world.consume_pesticide(total_liters):
            return {
                "error": (
                    f"Insufficient pesticide in warehouse: "
                    f"need {total_liters:.1f} L"
                )
            }

        if advance_time:
            farm.advance_time(_manual_spray_duration() * count)
        ridge_ids = list(range(ridge_id, end_ridge + 1))
        for sprayed_ridge_id in ridge_ids:
            farm.world.update_ridge_pesticide(sprayed_ridge_id)
        regime_status = farm.world.record_chemical_application(
            "insecticide", total_liters
        )

        for sprayed_ridge_id in ridge_ids:
            self._register_manual_spray_with_physics(farm, ridge_id=sprayed_ridge_id)

        self._manual_spray_log.append(
            {
                "ridge_id": ridge_id,
                "ridge_ids": ridge_ids,
                "date": farm.world.get_state()["sim_date"],
                "method": "manual_backpack",
                "farm_id": farm.farm_id,
                "pesticide_used_liters": total_liters,
                "duration_s": _manual_spray_duration() * count,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "ridge_id": ridge_id,
            "ridge_ids": ridge_ids,
            "pesticide_used_liters": total_liters,
            "management_regime": regime_status,
        }


    def _register_manual_spray_with_physics(self, farm: FarmContext, ridge_id: int) -> None:
        if not farm.world.physics_active:
            return

        import uuid

        from fairy.apps.farm_world.farm_action_record import FarmActionRecord
        from fairy.physics import (
            ManagementAction,
            ManagementActionType,
            TreatmentApplication,
            TreatmentType,
        )

        physics = farm.world.physics
        physics.queue_treatment(
            ridge_id,
            TreatmentApplication(
                treatment_type=TreatmentType.INSECTICIDE,
                efficacy_multiplier=1.0,
            ),
        )
        physics.queue_management_action(
            ridge_id,
            ManagementAction(
                action_type=ManagementActionType.INSECTICIDE,
                amount=1.0,
                quality=1.0,
                metadata={"method": "manual_backpack"},
            ),
        )
        farm.world.record_action(
            FarmActionRecord(
                action_id=str(uuid.uuid4())[:8],
                timestamp=float(self.time_manager.time()),
                actor_app=self.name,
                action_type="insecticide",
                ridge_ids=[ridge_id],
                parameters={"method": "manual_backpack"},
                direct_effect_summary={
                    "treatment_type": "INSECTICIDE",
                    "residual_window_opened": True,
                },
            )
        )
        farm.world.advance_physics_time()
