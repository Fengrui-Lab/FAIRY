"""Physical tractor configuration, independent of its target crop or farm."""
from __future__ import annotations

from dataclasses import dataclass


DEFAULT_TRACTOR_IMPLEMENTS = ("grader", "furrower", "harvester", "sprayer", "cultivator")


@dataclass(frozen=True)
class TractorEquipment:
    implements: tuple[str, ...] = DEFAULT_TRACTOR_IMPLEMENTS
    planting_max_ridges_per_pass: int = 4
    harvest_max_ridges_per_pass: int = 4
    ridging_implement: str | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.implements, tuple)
                or any(not isinstance(name, str) or not name for name in self.implements)
                or len(set(self.implements)) != len(self.implements)):
            raise ValueError("Tractor implements must be distinct nonempty names")
        for value in (self.planting_max_ridges_per_pass, self.harvest_max_ridges_per_pass):
            if type(value) is not int or value <= 0:
                raise ValueError("Tractor pass limits must be positive integers")
        if self.ridging_implement is not None and (
            not isinstance(self.ridging_implement, str) or not self.ridging_implement
        ):
            raise ValueError("Ridging implement must have a nonempty name")
