"""Validated crop presets for the deterministic farm simulator.

The maize/rice presets are transparent simulation assumptions, not calibrated
cultivars or agronomic advice. Rice represents direct-seeded, non-flooded rice;
ponded-water and transplanting dynamics are deliberately outside this model.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass


# These IDs preserve the upstream parameter-set identity. They are not named
# Chinese cultivars or independently established cold/drought tolerance classes.
OFFICIAL_WOFOST_SEED_VARIETIES = {
    "MAIZE_201": "Grain_maize_201",
    "SOYBEAN_901": "Soybean_901",
    "SOYBEAN_902": "Soybean_902",
    "SOYBEAN_903": "Soybean_903",
    "SOYBEAN_905": "Soybean_905",
}


def official_seed_backend_error(seed_type: str | None, physics) -> str | None:
    """Reject native-only identities before a tractor consumes seed or fuel.

    Read the already configured backend only; rejecting an unconfigured legacy
    farm must not initialize its physical state as a side effect.
    """
    variety = OFFICIAL_WOFOST_SEED_VARIETIES.get(seed_type)
    if variety is None:
        return None
    backend = getattr(physics, "crop_backend", None)
    if getattr(physics, "crop_backend_name", "legacy") != "wofost" or backend is None:
        return f"Seed {seed_type} requires the native WOFOST backend; legacy growth is not supported"
    if seed_type == "MAIZE_201":
        if backend.config.crop_name != "maize" or backend.config.variety_name != variety:
            return f"Seed {seed_type} requires native maize cultivar {variety}"
        return None
    if backend.config.cultivar_map.get(seed_type) != variety:
        return f"Seed {seed_type} requires explicit native cultivar_map identity {variety}"
    return None


@dataclass(frozen=True)
class CropProfile:
    crop_type: str
    seed_type: str
    planting_depth_cm: float
    planting_depth_range_cm: tuple[float, float]
    seed_spacing_cm: float
    seed_spacing_range_cm: tuple[float, float]
    rows_per_ridge: int
    stage_thresholds: tuple[tuple[int, str], ...]
    emergence_stage: str
    mature_stage: str
    harvest_moisture_min_pct: float
    harvest_moisture_max_pct: float
    yield_kg_m2: float
    grain_fill_day: int
    grain_moisture_start_pct: float
    grain_drydown_pct_per_day: float
    storage_moisture_max_pct: float
    planting_min_temp_c: float
    planting_vwc_range: tuple[float, float]
    irrigation_stop_vwc: float

    def stage_for_days(self, days: int) -> str:
        stage = self.emergence_stage
        for threshold, candidate in self.stage_thresholds:
            if days >= threshold:
                stage = candidate
        return stage

    def grain_moisture_for_days(self, days: int) -> float:
        if days < self.grain_fill_day:
            return 0.0
        return round(max(self.harvest_moisture_min_pct,
                         self.grain_moisture_start_pct
                         - (days - self.grain_fill_day) * self.grain_drydown_pct_per_day), 2)

    @property
    def model_assumptions(self) -> tuple[str, ...]:
        if self.crop_type == "soybean":
            return ()
        return (
            "crop-specific reduced thermal-time and biomass proxy; uncalibrated cultivar",
            "internal soybean-named development anchors are a compatibility vocabulary",
            "generic latent biotic pressure; no species-specific pest population model",
            *(("direct-seeded non-flooded rice; no paddy ponding or transplanting",)
              if self.crop_type == "rice" else ()),
        )

    def to_dict(self) -> dict:
        result = asdict(self)
        result["model_assumptions"] = list(self.model_assumptions)
        result["seed_spacing_range_cm"] = [value if math.isfinite(value) else None
                                            for value in self.seed_spacing_range_cm]
        return result


_SOYBEAN_THRESHOLDS = tuple([(0, "VE")] + [(10 * i, f"V{i}") for i in range(1, 7)]
    + [(70, "R1"), (80, "R2"), (90, "R3"), (100, "R4"),
       (105, "R5"), (110, "R6"), (115, "R7"), (120, "R8")])

CROP_PROFILES = {
    "soybean": CropProfile(
        "soybean", "STANDARD", 4.0, (3.0, 5.0), 8.0, (0.0, math.inf), 2,
        _SOYBEAN_THRESHOLDS, "VE", "R8", 13.0, 18.0,
        245.0 / (268.0 * 1.1), 110, 35.0, 1.5, 13.5, 10.0, (0.20, 0.35), 0.30),
    "maize": CropProfile(
        "maize", "MAIZE_STANDARD", 5.0, (4.0, 6.0), 20.0, (15.0, 35.0), 1,
        ((0, "VE"), (15, "V3"), (30, "V6"), (45, "V9"), (60, "VT"),
         (65, "R1"), (85, "R3"), (105, "R5"), (125, "R6")),
        "VE", "R6", 15.0, 25.0, 1.0, 105, 38.0, 0.65, 14.0, 10.0, (0.20, 0.35), 0.30),
    "rice": CropProfile(
        "rice", "RICE_STANDARD", 2.0, (1.0, 3.0), 10.0, (5.0, 20.0), 4,
        ((0, "emergence"), (15, "tillering"), (40, "stem_elongation"),
         (60, "booting"), (75, "heading"), (85, "grain_filling"), (115, "maturity")),
        "emergence", "maturity", 18.0, 24.0, 0.75, 85, 40.0, 0.70, 14.0, 12.0,
        (0.24, 0.40), 0.38),
}


def get_crop_profile(crop_type: str) -> CropProfile:
    if not isinstance(crop_type, str) or crop_type not in CROP_PROFILES:
        raise ValueError(f"Unsupported crop_type {crop_type!r}; choose soybean, maize, or rice")
    return CROP_PROFILES[crop_type]


def seed_crop_type(seed_type: str) -> str:
    if seed_type in {"MAIZE_STANDARD", "MAIZE_201"}:
        return "maize"
    if seed_type == "RICE_STANDARD":
        return "rice"
    from fairy.apps.farm_world.models import SeedType
    if seed_type in {seed.value for seed in SeedType}:
        return "soybean"
    raise ValueError(f"Unknown seed_type {seed_type!r}")


def get_seed_trait_reference(seed_type: str) -> dict | None:
    """Return evidence and actual native response settings for a reference seed.

    Quantities in the common warehouse are independent of this catalogue.
    This lookup neither changes a farm's selected backend nor substitutes a
    WOFOST profile; scenarios must configure the explicit profile ID.
    """
    seed_crop_type(seed_type)
    from fairy.physics.wofost_profiles import REFERENCE_CULTIVAR_PROFILES, load_cultivar_profile

    profile_id = REFERENCE_CULTIVAR_PROFILES.get(seed_type)
    if profile_id is None:
        return None
    profile = load_cultivar_profile(profile_id)
    return {"seed_type": seed_type, "crop_type": "soybean", "profile_id": profile_id,
            "profile_sha256": profile.sha256, "validation_status": "unvalidated",
            "trait_reference": profile.trait_reference}
