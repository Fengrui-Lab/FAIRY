"""Small operational crop profiles for the shared upland farm tools.

These are scenario assumptions, not local agronomic recommendations. Native
growth parameters remain in the versioned WOFOST crop data.
"""
from dataclasses import dataclass

from .yield_recovery_engine import YieldRecoveryParameters


@dataclass(frozen=True)
class CropProfile:
    crop_name: str
    seed_type: str
    rows_per_ridge: int
    row_spacing_m: float
    ridge_width_m: float
    default_plant_spacing_cm: float
    market_moisture_frac: float
    max_storage_moisture_frac: float
    max_harvest_moisture_frac: float
    maturity_stage: str

    @property
    def reference_density_plants_m2(self) -> float:
        return self.rows_per_ridge / (self.ridge_width_m * self.default_plant_spacing_cm / 100.0)


_PROFILES = {
    "soybean": CropProfile("soybean", "STANDARD", 2, 0.4, 1.1, 10.0,
                           0.13, 0.135, 0.18, "R8_FULL_MATURITY"),
    "maize": CropProfile("maize", "MAIZE_201", 1, 0.75, 0.75, 20.0,
                         0.14, 0.14, 0.25, "MATURE"),
}


def get_crop_profile(crop_name: str = "soybean") -> CropProfile:
    try:
        return _PROFILES[crop_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported upland crop {crop_name!r}; expected soybean or maize") from exc


def maize_yield_parameters() -> YieldRecoveryParameters:
    """Dry-matter accounting and explicit maize v1 post-maturity assumptions.

    The shared moisture model is an operational proxy. Soybean pod-shattering,
    disease and insect losses are disabled, rather than transferred to maize.
    """
    return YieldRecoveryParameters(
        market_moisture_frac=0.14,
        # Drier maize remains harvestable; 14% is the storage/market basis,
        # not a minimum moisture prerequisite for harvesting.
        ideal_harvest_moisture_min=0.10,
        ideal_harvest_moisture_max=0.25,
        wet_harvest_threshold=0.25,
        dry_shatter_threshold=0.0,
        initial_r8_grain_moisture=0.30,
        min_field_grain_moisture=0.10,
        max_field_grain_moisture=0.40,
        shatter_loss_per_day_after_grace=0.0,
        shatter_loss_dry_bonus=0.0,
        wet_dry_cycle_loss=0.0,
        disease_quality_loss_weight=0.0,
        insect_pod_damage_loss_weight=0.0,
        low_moisture_machine_loss_bonus=0.0,
        drying_required_moisture=0.14,
        quality_discount_damaged=0.0,
        kg_per_bushel_soybean=None,
        biological_yield_is_dry_matter=True,
    )
