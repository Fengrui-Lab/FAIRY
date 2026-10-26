"""Area and planting geometry for a ridge-managed field."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite


@dataclass(frozen=True)
class FieldGeometry:
    num_ridges: int = 64
    length_m: float = 268.0
    ridge_width_m: float = 1.1
    rows_per_ridge: int = 2
    boundary_width_m: float | None = None

    def __post_init__(self) -> None:
        if type(self.num_ridges) is not int or self.num_ridges <= 0:
            raise ValueError("num_ridges must be a positive integer")
        if type(self.rows_per_ridge) is not int or self.rows_per_ridge < 1:
            raise ValueError("rows_per_ridge must be a positive integer")
        for name in ("length_m", "ridge_width_m"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.boundary_width_m is not None and (
            type(self.boundary_width_m) not in (int, float)
            or not isfinite(self.boundary_width_m)
            or self.boundary_width_m < self.num_ridges * self.ridge_width_m
        ):
            raise ValueError("Field boundary must contain all configured ridges")

    @property
    def working_width_m(self) -> float:
        """Full field extent, including any explicitly configured unplanted margin."""
        return (self.boundary_width_m if self.boundary_width_m is not None
                else self.num_ridges * self.ridge_width_m)

    @property
    def ridge_area_m2(self) -> float:
        return self.length_m * self.ridge_width_m

    @property
    def planted_area_m2(self) -> float:
        return self.num_ridges * self.ridge_area_m2

    def plants_per_ridge(self, spacing_cm: float) -> int:
        if not isfinite(float(spacing_cm)) or spacing_cm <= 0:
            raise ValueError("seed_spacing_cm must be finite and positive")
        return int(round(self.length_m * self.rows_per_ridge * 100.0 / spacing_cm))

    def to_dict(self) -> dict:
        return {**asdict(self), "ridge_area_m2": self.ridge_area_m2,
                "planted_area_m2": self.planted_area_m2}
