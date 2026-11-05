"""Ground scouting tools with explicit farm and persistent robot selection."""
from __future__ import annotations

from typing import Any

from fairy.tool_utils import OperationType
from .base import AssetId, FarmId, RidgeId, SharedFarmService, service_tool


class RobotService(SharedFarmService):
    service_name = "Robot"
    service_kind = "robot"
    asset_kind = "robot"

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def inspect_ridge(self, farm_id: FarmId, asset_id: AssetId, ridge_id: RidgeId) -> dict[str, Any]:
        """Walk one whole ridge to inspect pest and disease evidence.

        Requires an eligible robot with at least 20% battery and no charging.
        Consumes battery and working time. Rain adds a wet-ground warning.
        Read the field's available diagnoses and confidence where provided.

        Args:
            farm_id: Farm containing the ridge to inspect.
            asset_id: Physical robot ID whose battery will be consumed.
            ridge_id: Zero-based ridge ID within this farm.

        Returns:
            Receipt with inspection_id, pest/disease result and remaining
            battery, plus a wet-ground warning when applicable, in data.
        """
        return self._execute("inspect_ridge", farm_id=farm_id, asset_id=asset_id, ridge_id=ridge_id)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def inspect_pests(
        self, farm_id: FarmId, asset_id: AssetId, start_ridge: RidgeId, end_ridge: RidgeId,
    ) -> dict[str, Any]:
        """Scout an inclusive ridge range for ground-level biotic evidence.

        Requires an eligible, noncharging robot with at least 15% battery.
        Spends battery and shared time. At most the first eight requested
        ridges are covered; battery may reduce coverage further. Inspect
        covered_ridges and uncovered_ridges even when the receipt succeeds.
        Detections have observation uncertainty; this does not
        replace surveying ridges that were not visited. Unavailable weed evidence is reported as unknown, not confirmed absence.

        Args:
            farm_id: Farm containing every requested local ridge.
            asset_id: Physical robot ID whose state persists across farms.
            start_ridge: First local ridge ID, zero based and inclusive.
            end_ridge: Last local ridge ID, inclusive and at least start_ridge.

        Returns:
            Receipt with modality, covered_ridges, uncovered_ridges,
            per-ridge pest/disease/weed observations and remaining battery in data.
        """
        return self._execute("inspect_pests", farm_id=farm_id, asset_id=asset_id,
                             start_ridge=start_ridge, end_ridge=end_ridge)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def inspect_crop_health(
        self, farm_id: FarmId, asset_id: AssetId, start_ridge: RidgeId, end_ridge: RidgeId,
    ) -> dict[str, Any]:
        """Scout crop health and biotic evidence in an inclusive ridge range.

        Requires an eligible, noncharging robot with at least 15% battery.
        Spends battery and shared time. Visits at most eight ridges per call
        and may visit fewer when battery is limiting. Read the available diagnoses, uncertainty and coverage before treating
        or scheduling the next pass. Missing weed or nutrition evidence is unknown,
        not confirmed absence or adequacy.

        Args:
            farm_id: Farm containing every requested local ridge.
            asset_id: Physical robot ID to send; battery is shared across its missions.
            start_ridge: First local ridge ID, zero based and inclusive.
            end_ridge: Last local ridge ID, inclusive and at least start_ridge.

        Returns:
            Receipt with covered_ridges, uncovered_ridges, per-ridge health
            observations, inspection_id and battery_remaining_pct in data.
        """
        return self._execute("inspect_crop_health", farm_id=farm_id, asset_id=asset_id,
                             start_ridge=start_ridge, end_ridge=end_ridge)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def inspect_emergence(
        self, farm_id: FarmId, asset_id: AssetId, start_ridge: RidgeId, end_ridge: RidgeId,
    ) -> dict[str, Any]:
        """Inspect stand establishment in an inclusive local ridge range.

        Requires an eligible robot with at least 15% battery and no charging.
        Uses battery and working time, visiting at most eight ridges. Check
        covered and uncovered ridges and the available stand evidence before
        planning replanting. An unavailable estimate is not confirmed crop failure.

        Args:
            farm_id: Farm whose emergence should be inspected.
            asset_id: Physical robot ID to send to this farm.
            start_ridge: First local ridge ID, zero based and inclusive.
            end_ridge: Last local ridge ID, inclusive and at least start_ridge.

        Returns:
            Receipt with covered_ridges, uncovered_ridges, per-ridge
            observations including stand_fraction and remaining battery in data.
        """
        return self._execute("inspect_emergence", farm_id=farm_id, asset_id=asset_id,
                             start_ridge=start_ridge, end_ridge=end_ridge)

    @service_tool(OperationType.READ, routing=("asset_id",))
    def check_status(self, asset_id: AssetId) -> dict[str, Any]:
        """Read one robot's battery and synchronize charging progress.

        Uses the current shared clock; does not advance time or select a farm.

        Args:
            asset_id: Physical robot ID from the environment directory.

        Returns:
            Receipt with battery_pct, charging, eta_minutes_to_full and
            asset provenance in data.
        """
        return self._execute("check_status", asset_id=asset_id)

    @service_tool(OperationType.WRITE, routing=("asset_id",))
    def charge(self, asset_id: AssetId) -> dict[str, Any]:
        """Start asynchronous charging of one robot without advancing time.

        Charging takes about 60 environment minutes. Wait using System, then
        query status before the next inspection. Repeating this call reports
        charging or already-full state.

        Args:
            asset_id: Physical robot ID to charge; no farm target is required.

        Returns:
            Receipt with charging_started, charging or already_full status,
            battery_pct and estimated minutes to full in data.
        """
        return self._execute("charge", asset_id=asset_id)
