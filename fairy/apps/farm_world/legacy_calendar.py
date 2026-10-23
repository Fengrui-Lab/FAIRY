"""The calendar and pressure proxy retained for historical soybean scenarios.

Explicit crop selection never installs this adapter. Physical crop state and
current observations are provided by the common crop integration instead.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fairy.apps.farm_world.farm_world_app import FarmWorldApp
    from fairy.apps.farm_world.models import RidgeState


class LegacySoybeanCalendar:
    def planting_establishment(self, ridge: RidgeState) -> float:
        """Old scenes used the bare ridge's stand field as initial seed quality."""
        return max(0.0, min(1.0, float(ridge.stand_fraction)))

    def refresh(self, world: FarmWorldApp, ridge: RidgeState, now_t: float) -> None:
        from fairy.apps.farm_world.farm_world_app import (
            _effective_pressure, _stage_for_days, _grain_moisture_for_stage,
            _STAGE_THRESHOLDS, _SECONDS_PER_DAY,
        )
        from fairy.apps.farm_world.models import GrowthStage
        # Pest / disease (three-phase curve after spray)
        ridge.pest_pressure = _effective_pressure(
            ridge.pest_pressure_base, ridge.last_spray_sim_time, now_t
        )
        ridge.disease_pressure = _effective_pressure(
            ridge.disease_pressure_base, ridge.last_spray_sim_time, now_t
        )
        if ridge.last_spray_sim_time is None:
            ridge.pesticide_applied_days_ago = -1
        else:
            elapsed = max(0.0, now_t - ridge.last_spray_sim_time)
            ridge.pesticide_applied_days_ago = int(elapsed // _SECONDS_PER_DAY)

        # Growth progression (only when a real `set_ridge_planted` happened).
        # Once physics engines are active, the orchestrator owns stage and
        # moisture; legacy timestamp refresh must not overwrite its shadow.
        if (
            not world.physics_active
            and ridge.planted
            and ridge.planted_at_sim_time is not None
        ):
            elapsed_s = max(0.0, now_t - ridge.planted_at_sim_time)
            days = int(elapsed_s // _SECONDS_PER_DAY)
            ridge.days_since_planted = days
            ridge.growth_stage = _stage_for_days(days)
            r6_threshold = next(
                (t for t, s in _STAGE_THRESHOLDS if s == GrowthStage.R6.value), 110
            )
            days_in_r6_plus = max(0, days - r6_threshold)
            ridge.grain_moisture_pct = _grain_moisture_for_stage(
                ridge.growth_stage, days_in_r6_plus
            )
