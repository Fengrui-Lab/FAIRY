"""Farm-local irrigation and handheld application tools."""
from __future__ import annotations

from typing import Any

from fairy.tool_utils import OperationType
from .base import FarmId, Hours, LitersPerRidge, RidgeId, SharedFarmService, service_tool


class FieldOpsService(SharedFarmService):
    service_name = "FieldOps"
    service_kind = "field_ops"

    @service_tool(OperationType.WRITE, routing=("farm_id",))
    def irrigate(self, farm_id: FarmId, start: RidgeId, end: RidgeId, hours: Hours) -> dict[str, Any]:
        """Run irrigation for an inclusive ridge range in one farm.

        Requires soil below the crop's stop-VWC threshold and available water
        quota. Uses 5 mm per ridge per requested hour, charges field-equivalent
        water quota, and advances the shared clock by setup/run duration.
        Water delivery remains pending for a further two environment hours.
        If part of the range already has pending irrigation, returns that
        pending state without scheduling another run. Recheck after delivery.

        Args:
            farm_id: Farm receiving water and charged for irrigation usage.
            start: First local ridge ID, inclusive.
            end: Last local ridge ID, inclusive and at least start.
            hours: Positive irrigation run time per ridge, in hours.

        Returns:
            Receipt with irrigation_started or irrigation_pending status,
            irrigated_ridges, effect_ready_at and available dose/usage details in data.
        """
        return self._execute("irrigate", farm_id=farm_id, start=start, end=end, hours=hours)

    @service_tool(OperationType.WRITE, routing=("farm_id",))
    def apply_pesticide_manual(
        self, farm_id: FarmId, start_ridge: RidgeId, end_ridge: RidgeId,
        liters_per_ridge: LitersPerRidge = 3.0,
    ) -> dict[str, Any]:
        """Hand-spray insecticide on one or two contiguous local ridges.

        Requires sprayable weather, farm warehouse chemical and management
        permission. Consumes pesticide directly from this farm, records
        treatment and quota usage, and advances the shared clock for the
        operator passes. No tractor or shared onboard tank is used.

        Args:
            farm_id: Farm supplying chemical and receiving the treatment.
            start_ridge: First local ridge ID, inclusive.
            end_ridge: Last local ridge ID; inclusive range contains at most two ridges.
            liters_per_ridge: Positive insecticide volume per ridge in L/ridge.

        Returns:
            Receipt with treated ridge_ids, pesticide_used_liters and
            management_regime usage in data.
        """
        return self._execute("apply_pesticide_manual", farm_id=farm_id, start_ridge=start_ridge,
                             end_ridge=end_ridge, liters_per_ridge=liters_per_ridge)

    @service_tool(OperationType.READ, routing=("farm_id",))
    def get_irrigation_log(self, farm_id: FarmId) -> dict[str, Any]:
        """Read this farm's recorded irrigation history without advancing time.

        History does not itself prove water has arrived; inspect delivery
        timestamps and re-read soil moisture after the pending period.

        Args:
            farm_id: Farm whose irrigation history should be read.

        Returns:
            Receipt with irrigation_log entries in data.
        """
        return self._execute("get_irrigation_log", farm_id=farm_id)
