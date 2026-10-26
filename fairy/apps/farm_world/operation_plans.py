"""Validated device work, before spending resources or advancing the clock."""
from __future__ import annotations

from dataclasses import dataclass

from fairy.crops.runtime import PlantingEvent


@dataclass(frozen=True)
class PlantingPlan:
    event: PlantingEvent
    spacing_cm: float
    seeds_per_ridge: int
    duration_s: int
    fuel_liters: float

    @property
    def total_seeds(self) -> int:
        return len(self.event.ridge_ids) * self.seeds_per_ridge
