"""Shared-water admission check layered on the existing irrigation operation."""

from math import isfinite
from textwrap import dedent

from fairy.apps.farm_world.irrigation_app import IrrigationApp


def water_used_m3(farms):
    return sum(
        farm._management_regime.irrigation_used_mm_total * farm.field_area_m2 / 1000
        for farm in farms
    )


class PooledIrrigation(IrrigationApp):
    """Each stationary controller checks the same remaining physical supply."""

    def __init__(self, farm, weather, farms, capacity_m3, name):
        super().__init__(farm, weather, name=name)
        self._pool_farms = farms
        self._pool_capacity_m3 = capacity_m3

    def get_tools(self):
        """Add this controller's shared-supply documentation to fresh tool metadata."""
        details = {
            "irrigate": """
                This field shares supply with the other fields. Check
                OperatingAccounts.get_accounts.shared_water_remaining_m3.
                Delivery is 5 mm per ridge-hour; requested m3 = hours * 5 *
                treated area_m2 / 1000. Field and shared limits both apply.

                Returns:
                    dict: Started/pending status, water mm and effect_ready_at
                    (Unix seconds). WOFOST settles queued water daily; recheck
                    soil after delivery. Shared-limit errors include requested_m3
                    and remaining_m3, without consuming water.
            """,
            "get_irrigation_log": """
                Returns:
                    dict: This field's irrigation_log with ridge IDs, duration
                    (hours/seconds), effect_ready_at (Unix seconds) and, for
                    physics entries, estimated_water_mm. For the shared m3
                    balance use OperatingAccounts.get_accounts.
            """,
        }
        tools = super().get_tools()
        for tool in tools:
            detail = details.get(tool.name)
            if detail is not None:
                tool.function_description = (
                    f"{tool.function_description or ''}\n\n{dedent(detail).strip()}"
                )
        return tools

    def _start_irrigation(self, ridge_ids, duration_hours):
        requested = (
            duration_hours
            * 5
            * len(ridge_ids)
            * self._farm_world_app.ridge_area_m2
            / 1000
        )
        if not isfinite(requested) or requested < 0:
            return {"error": "Water request must be finite and nonnegative"}
        remaining = self._pool_capacity_m3 - water_used_m3(self._pool_farms)
        if requested > remaining + 1e-8:
            return {
                "error": "Shared seasonal water supply exceeded",
                "requested_m3": requested,
                "remaining_m3": remaining,
            }
        # Base operation owns the sole quota update; refusal never debits a second ledger.
        return super()._start_irrigation(ridge_ids, duration_hours)
