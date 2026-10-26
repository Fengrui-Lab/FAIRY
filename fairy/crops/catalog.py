"""Registered crop identities and rules shared by tools and operations.

Definitions express crop requirements, never machinery ownership or warehouse
stock. Biological model factories are registered by the integration layer.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from fairy.crops.rules import HarvestRules, PlantingRules, ScalarRange


@dataclass(frozen=True)
class CropDefinition:
    crop_id: str
    cultivar_id: str | None
    seed_types: tuple[str, ...]
    planting_rules: PlantingRules
    harvest_rules: HarvestRules
    market_moisture_pct: float
    storage_moisture_pct: float
    default_ridge_width_m: float
    default_rows_per_ridge: int
    replanting_rules: PlantingRules | None = None

    def __post_init__(self) -> None:
        if not self.crop_id or not self.seed_types or len(set(self.seed_types)) != len(self.seed_types):
            raise ValueError("A crop needs an identity and distinct seed types")
        if self.cultivar_id is not None and self.cultivar_id not in self.seed_types:
            raise ValueError("The default cultivar must belong to the crop")
        for moisture in (self.market_moisture_pct, self.storage_moisture_pct):
            if ScalarRange(0, 100, maximum_inclusive=False).validate(moisture, "moisture"):
                raise ValueError("Crop moisture values must be within [0, 100)")
        if ScalarRange(0, minimum_inclusive=False).validate(self.default_ridge_width_m, "ridge width"):
            raise ValueError("Default ridge width must be positive")
        if type(self.default_rows_per_ridge) is not int or self.default_rows_per_ridge <= 0:
            raise ValueError("Default planted rows must be a positive integer")


SOYBEAN = CropDefinition(
    crop_id="soybean", cultivar_id=None,
    seed_types=("EARLY_COLD", "STANDARD", "HIGH_DENSITY", "STRESS_TOLERANT",
                "HEIHE43", "HEIHE50", "HEINONG58", "HEINONG60", "HEINONG84", "HEIKE71",
                "SUINONG42", "KENDOU40", "HEINONG44", "HEINONG65",
                "SOYBEAN_901", "SOYBEAN_902", "SOYBEAN_903", "SOYBEAN_905"),
    planting_rules=PlantingRules(
        depth_cm=ScalarRange(3.0, 5.0), soil_vwc=ScalarRange(0.20, 0.35),
        soil_temperature_c=ScalarRange(10.0, minimum_inclusive=False),
        soil_temperature_by_seed=(("EARLY_COLD", ScalarRange(8.0)),),
        # Existing soybean tools did not require an attached planter.
        required_implement=None,
    ),
    harvest_rules=HarvestRules(("R8", "R8_FULL_MATURITY"), 18.0, required_implement=None),
    market_moisture_pct=13.0, storage_moisture_pct=13.5,
    default_ridge_width_m=1.1, default_rows_per_ridge=2,
    # Historical gap filling only checked depth/spacing and device resources.
    # Keep that operation distinct from fresh sowing, including in its docs.
    replanting_rules=PlantingRules(
        depth_cm=ScalarRange(3.0, 5.0), soil_vwc=ScalarRange(0.0, 1.0),
        soil_temperature_c=ScalarRange(), required_implement=None,
        required_preparation=(), respect_scenario_window=False,
    ),
)

MAIZE = CropDefinition(
    crop_id="maize", cultivar_id="MAIZE_EARLY_2026", seed_types=("MAIZE_EARLY_2026",),
    planting_rules=PlantingRules(
        depth_cm=ScalarRange(3.0, 6.0), soil_vwc=ScalarRange(0.18, 0.35),
        soil_temperature_c=ScalarRange(10.0), required_implement="maize_planter",
        density_plants_m2=ScalarRange(0.01, 30.0),
        supported_replant_modes=("pre_emergence", "full"),
    ),
    harvest_rules=HarvestRules(("R6_MATURITY",), 30.0, required_implement="maize_header"),
    market_moisture_pct=14.0, storage_moisture_pct=14.0,
    default_ridge_width_m=0.65, default_rows_per_ridge=1,
)

# These three identities select different biological implementations. Their
# operation rules must not silently migrate an existing field to the new
# MAIZE_EARLY_2026 model or require equipment its scenario never configured.
MAIZE_STANDARD = CropDefinition(
    crop_id="maize", cultivar_id="MAIZE_STANDARD", seed_types=("MAIZE_STANDARD",),
    planting_rules=PlantingRules(
        depth_cm=ScalarRange(4.0, 6.0), soil_vwc=ScalarRange(0.20, 0.35),
        soil_temperature_c=ScalarRange(10.0, minimum_inclusive=False),
        required_implement=None,
    ),
    harvest_rules=HarvestRules(("R6",), 25.0, required_implement=None),
    market_moisture_pct=14.0, storage_moisture_pct=14.0,
    default_ridge_width_m=1.1, default_rows_per_ridge=1,
)

MAIZE_201 = CropDefinition(
    crop_id="maize", cultivar_id="MAIZE_201", seed_types=("MAIZE_201",),
    planting_rules=PlantingRules(
        depth_cm=ScalarRange(4.0, 6.0), soil_vwc=ScalarRange(0.20, 0.35),
        soil_temperature_c=ScalarRange(10.0, minimum_inclusive=False),
        required_implement=None,
    ),
    harvest_rules=HarvestRules(("MATURE",), 25.0, required_implement=None),
    market_moisture_pct=14.0, storage_moisture_pct=14.0,
    default_ridge_width_m=0.75, default_rows_per_ridge=1,
)

RICE_STANDARD = CropDefinition(
    crop_id="rice", cultivar_id="RICE_STANDARD", seed_types=("RICE_STANDARD",),
    planting_rules=PlantingRules(
        depth_cm=ScalarRange(1.0, 3.0), soil_vwc=ScalarRange(0.24, 0.40),
        soil_temperature_c=ScalarRange(12.0, minimum_inclusive=False),
        required_implement=None,
    ),
    harvest_rules=HarvestRules(("maturity",), 24.0, required_implement=None),
    market_moisture_pct=14.0, storage_moisture_pct=14.0,
    default_ridge_width_m=1.1, default_rows_per_ridge=4,
)

_DEFINITIONS: dict[str, CropDefinition] = {
    crop.crop_id: crop for crop in (SOYBEAN, MAIZE, RICE_STANDARD)
}
_MAIZE_VARIANTS = {
    crop.cultivar_id: crop for crop in (MAIZE, MAIZE_STANDARD, MAIZE_201)
}


def register_crop_definition(definition: CropDefinition) -> None:
    """Register requirements once; register the biological model separately."""
    if definition.crop_id in _DEFINITIONS:
        raise ValueError(f"Crop {definition.crop_id!r} is already registered")
    _DEFINITIONS[definition.crop_id] = definition


def get_crop_definition(crop_id: str, cultivar_id: str | None = None) -> CropDefinition:
    """Resolve an explicit crop and cultivar, without a fallback species."""
    try:
        definition = _DEFINITIONS[crop_id]
    except KeyError:
        raise ValueError(f"Unknown crop_id {crop_id!r}; choose one of {list(_DEFINITIONS)}") from None
    if crop_id == "maize" and cultivar_id in _MAIZE_VARIANTS:
        return _MAIZE_VARIANTS[cultivar_id]
    if cultivar_id is not None:
        if cultivar_id not in definition.seed_types:
            raise ValueError(f"Cultivar {cultivar_id!r} does not belong to {crop_id}")
        definition = replace(definition, cultivar_id=cultivar_id)
    return definition
