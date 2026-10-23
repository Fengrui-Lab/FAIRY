"""Typed agronomic operation rules shared by execution and tool discovery.

These values describe a crop's requirements. Equipment ownership, current
weather and operation effects belong to their respective device/world layers.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ScalarRange:
    minimum: float | None = None
    maximum: float | None = None
    minimum_inclusive: bool = True
    maximum_inclusive: bool = True

    def __post_init__(self) -> None:
        for value in (self.minimum, self.maximum):
            if value is not None and (type(value) not in (int, float) or not isfinite(value)):
                raise ValueError("Rule bounds must be finite numbers")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum or (
                self.minimum == self.maximum
                and not (self.minimum_inclusive and self.maximum_inclusive)
            ):
                raise ValueError("Rule range cannot be empty")

    def validate(self, value: float, label: str) -> str | None:
        try:
            finite = type(value) in (int, float) and isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            return f"{label} must be finite"
        if self.minimum is not None and (
            value < self.minimum or (value == self.minimum and not self.minimum_inclusive)
        ):
            return f"{label} must be {'>=' if self.minimum_inclusive else '>'} {self.minimum:g}"
        if self.maximum is not None and (
            value > self.maximum or (value == self.maximum and not self.maximum_inclusive)
        ):
            return f"{label} must be {'<=' if self.maximum_inclusive else '<'} {self.maximum:g}"
        return None

    def describe(self, unit: str = "") -> str:
        suffix = f" {unit}" if unit else ""
        if self.minimum is not None and self.maximum is not None:
            if self.minimum_inclusive and self.maximum_inclusive:
                return f"{self.minimum:g}–{self.maximum:g}{suffix}"
        parts = []
        if self.minimum is not None:
            parts.append(f"{'>=' if self.minimum_inclusive else '>'} {self.minimum:g}{suffix}")
        if self.maximum is not None:
            parts.append(f"{'<=' if self.maximum_inclusive else '<'} {self.maximum:g}{suffix}")
        return " and ".join(parts) or f"finite{suffix}"

    def json_schema(self) -> dict[str, float]:
        result = {}
        if self.minimum is not None:
            result["minimum" if self.minimum_inclusive else "exclusiveMinimum"] = self.minimum
        if self.maximum is not None:
            result["maximum" if self.maximum_inclusive else "exclusiveMaximum"] = self.maximum
        return result


@dataclass(frozen=True)
class PlantingRules:
    depth_cm: ScalarRange
    soil_vwc: ScalarRange
    soil_temperature_c: ScalarRange
    required_implement: str | None
    required_preparation: tuple[str, ...] = ("level", "base_fertilize", "form_ridges")
    density_plants_m2: ScalarRange | None = None
    soil_temperature_by_seed: tuple[tuple[str, ScalarRange], ...] = ()
    supported_replant_modes: tuple[str, ...] = ("pre_emergence", "full", "gap_fill")
    respect_scenario_window: bool = True

    def __post_init__(self) -> None:
        names = [name for name, _ in self.soil_temperature_by_seed]
        if len(set(names)) != len(names):
            raise ValueError("A seed can have only one planting temperature rule")
        if not set(self.supported_replant_modes) <= {"pre_emergence", "full", "gap_fill"}:
            raise ValueError("Unknown replant mode")

    def temperature_rule(self, seed_type: str | None) -> ScalarRange:
        return dict(self.soil_temperature_by_seed).get(seed_type, self.soil_temperature_c)

    def validate_parameters(self, depth_cm: float, spacing_cm: float) -> str | None:
        return self.depth_cm.validate(depth_cm, "depth_cm") or ScalarRange(
            minimum=0, minimum_inclusive=False,
        ).validate(spacing_cm, "seed spacing (cm)")

    def validate_conditions(
        self, seed_type: str | None, soil_temp_c: float, soil_vwc: float,
        density: float | None = None,
    ) -> str | None:
        error = (self.temperature_rule(seed_type).validate(soil_temp_c, "Soil temperature (°C)")
                 or self.soil_vwc.validate(soil_vwc, "Soil VWC"))
        if error is None and self.density_plants_m2 is not None:
            error = self.density_plants_m2.validate(density, "Planting density (plants/m²)")
        return error

    def validate_implement(self, implement: str | None) -> str | None:
        if self.required_implement is not None and implement != self.required_implement:
            return f"Planting requires attached implement '{self.required_implement}'"
        return None


@dataclass(frozen=True)
class HarvestRules:
    stage_codes: tuple[str, ...]
    max_moisture_pct: float
    required_implement: str | None

    def __post_init__(self) -> None:
        if not self.stage_codes or any(not value for value in self.stage_codes):
            raise ValueError("Harvest rules require explicit mature stage codes")
        if ScalarRange(0, 100, maximum_inclusive=False).validate(self.max_moisture_pct, "harvest moisture"):
            raise ValueError("Harvest moisture limit must be within [0, 100)")

    def validate_conditions(self, stage_code: str, moisture_pct: float) -> str | None:
        if str(stage_code).upper() not in {value.upper() for value in self.stage_codes}:
            return f"Crop is not mature; required stage: {', '.join(self.stage_codes)}"
        return ScalarRange(0, self.max_moisture_pct).validate(moisture_pct, "Grain moisture (%)")

    def validate_implement(self, implement: str | None) -> str | None:
        if self.required_implement is not None and implement != self.required_implement:
            return f"Harvest requires attached implement '{self.required_implement}'"
        return None
