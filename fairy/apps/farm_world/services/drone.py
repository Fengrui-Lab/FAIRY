"""Explicit drone tools selecting a field and one persistent device."""
from __future__ import annotations

from typing import Any

from fairy.tool_utils import OperationType
from .base import AssetId, FarmId, RidgeId, SharedFarmService, service_tool


class DroneService(SharedFarmService):
    service_name = "Drone"
    service_kind = "drone"
    asset_kind = "drone"

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def fly_survey(
        self, farm_id: FarmId, asset_id: AssetId, start_ridge: RidgeId, end_ridge: RidgeId,
    ) -> dict[str, Any]:
        """Survey an inclusive ridge range in the explicitly selected field.

        Requires a drone assigned to this farm, flyable weather, sufficient
        battery and no active charging. The mission spends this asset's battery
        and advances the shared clock. It records noisy NDVI and canopy
        temperature observations. Battery reserve may force an early return;
        a successful receipt can therefore contain only partial coverage.
        Always inspect data.status and data.surveyed_ridges before planning
        follow-up inspections. Split uncovered ridges into later missions.

        Args:
            farm_id: Exact farm ID identifying the field to survey.
            asset_id: Physical drone ID; battery persists when it changes farms.
            start_ridge: First local ridge ID, zero based and inclusive.
            end_ridge: Last local ridge ID, inclusive and at least start_ridge.

        Returns:
            Receipt whose data includes status (ok or partial), mission_id,
            surveyed_ridges, per-ridge observations, duration_minutes,
            battery_remaining_pct and an early-return warning when partial.
        """
        return self._execute("fly_survey", farm_id=farm_id, asset_id=asset_id,
                             start_ridge=start_ridge, end_ridge=end_ridge)

    @service_tool(OperationType.READ, routing=("asset_id",))
    def check_status(self, asset_id: AssetId) -> dict[str, Any]:
        """Read one drone's battery, charging progress and flight configuration.

        Charging progress is synchronized to the current shared clock. This
        does not select a farm or schedule a flight.

        Args:
            asset_id: Physical drone ID from the environment directory.

        Returns:
            Receipt with battery_pct, charging, eta_minutes_to_full, speed,
            effective_ridges_per_pass and asset provenance in data.
        """
        return self._execute("check_status", asset_id=asset_id)

    @service_tool(OperationType.WRITE, routing=("asset_id",))
    def charge(self, asset_id: AssetId) -> dict[str, Any]:
        """Start asynchronous charging of one drone without advancing time.

        Charging takes about 30 environment minutes; wait using System before
        flying again. Repeating this call reports current charging/full state.

        Args:
            asset_id: Physical drone ID to charge; no farm target is required.

        Returns:
            Receipt with charging_started, charging or already_full status,
            current battery and estimated minutes to full in data.
        """
        return self._execute("charge", asset_id=asset_id)
