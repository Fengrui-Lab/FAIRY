"""Typed crop events and current-state projections, independent of Apps.

Equipment charges resources and schedules work. It sends a completed planting
event to crop dynamics; it never edits a crop's native state or public shadow.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping


@dataclass(frozen=True)
class PlantingEvent:
    ridge_ids: tuple[int, ...]
    planting_date: date
    seed_type: str
    depth_cm: float
    stand_fraction_by_ridge: Mapping[int, float]
    density_by_ridge: Mapping[int, float]
    latitude_deg: float = 45.7
    replace_existing: bool = False


@dataclass(frozen=True)
class CropStatus:
    """Current living crop; historical establishment remains in season records."""
    current_planted: bool
    emerged: bool
    current_stand: float
    harvested: bool
    stage: str
    days_since_planted: int
    grain_moisture_pct: float
    yield_potential: float


@dataclass(frozen=True)
class CropObservationTraits:
    """Diagnostic scope and a canopy thermal-response parameter."""
    unstressed_root_vwc: float
    diagnosed_pest_type: str | None = None
    diagnosed_disease_type: str | None = None


@dataclass(frozen=True)
class ReplantPlan:
    """Preflight result; applying it is the only crop mutation in a replant."""
    event: PlantingEvent
    fresh_ridge_ids: tuple[int, ...]
    stand_before: Mapping[int, float]
    stand_after: Mapping[int, float]
