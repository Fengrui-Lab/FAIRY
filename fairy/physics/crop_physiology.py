"""Crop adapters for the reduced (legacy) daily engines.

The seven engines share development anchors historically named SoybeanStage.
Those anchors are an internal compatibility vocabulary: maize R6 and rice
maturity both map to the full-maturity anchor. Public farm stages are derived
from the crop's own thresholds and continuous thermal progress, never by
renaming soybean R6 or its maturity duration. Soybean defaults remain intact.

Maize and direct-seeded, non-flooded rice are qualitative benchmark proxies.
They are not calibrated crop models. There is no paddy pond-water balance,
transplanting, explicit tiller/ear population, or species-specific pest model.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from fairy.physics.phenology_engine import SoybeanStage


_CROP_ANCHORS: dict[str, tuple[tuple[str, SoybeanStage], ...]] = {
    "maize": (("VE", SoybeanStage.VE), ("V3", SoybeanStage.V1),
              ("V6", SoybeanStage.V3), ("V9", SoybeanStage.V4_PLUS),
              ("VT", SoybeanStage.R1), ("R1", SoybeanStage.R3),
              ("R3", SoybeanStage.R5), ("R5", SoybeanStage.R6),
              ("R6", SoybeanStage.R8)),
    "rice": (("emergence", SoybeanStage.VE), ("tillering", SoybeanStage.V1),
             ("stem_elongation", SoybeanStage.V4_PLUS),
             ("booting", SoybeanStage.R1), ("heading", SoybeanStage.R3),
             ("grain_filling", SoybeanStage.R5), ("maturity", SoybeanStage.R8)),
}


def crop_stage_fraction(profile: Any, stage: str) -> float | None:
    """Return crop-native threshold as a fraction of its maturity duration."""
    maturity_day = float(profile.stage_thresholds[-1][0])
    for day, candidate in profile.stage_thresholds:
        if candidate == stage:
            return max(0.0, min(1.0, day / maturity_day))
    return None


def compatibility_stage(profile: Any, stage: str) -> SoybeanStage | None:
    return dict(_CROP_ANCHORS.get(profile.crop_type, ())).get(stage)


def public_crop_stage(profile: Any, state: Any, seed_params: Any) -> str:
    """Translate continuous thermal development to crop-native stage names."""
    if not state.planted or not state.emerged:
        return "bare"
    if state.stage == SoybeanStage.R8:
        return profile.mature_stage
    params = seed_params.get(state.seed_type)
    maturity_gdd = float(params.gdd_to_r8) if params is not None else 1.0
    progress = max(0.0, min(1.0, state.effective_development_gdd / maturity_gdd))
    equivalent_days = progress * profile.stage_thresholds[-1][0]
    # A tiny tolerance prevents binary rounding from regressing an exact
    # threshold (e.g. maize day 85 = R3) during initial-state synchronization.
    return profile.stage_for_days(equivalent_days + 1e-8)


def configure_crop_physics(physics: Any, profile: Any) -> None:
    """Install per-instance crop parameters without mutating global presets."""
    if profile.crop_type == "soybean":
        return
    anchors = _CROP_ANCHORS[profile.crop_type]
    fractions = {anchor: crop_stage_fraction(profile, stage)
                 for stage, anchor in anchors}
    # Intermediate compatibility anchors preserve monotone engine behavior
    # while retaining the crop's real public-stage vocabulary.
    fractions[SoybeanStage.VC] = fractions[SoybeanStage.V1] * 0.5
    fractions[SoybeanStage.V2] = (fractions[SoybeanStage.V1]
        + fractions.get(SoybeanStage.V3, fractions[SoybeanStage.V4_PLUS])) * 0.5
    if SoybeanStage.V3 not in fractions:
        fractions[SoybeanStage.V3] = (fractions[SoybeanStage.V2]
                                      + fractions[SoybeanStage.V4_PLUS]) * 0.5
    if SoybeanStage.R6 not in fractions:
        fractions[SoybeanStage.R6] = fractions[SoybeanStage.R5] + 0.5 * (1 - fractions[SoybeanStage.R5])
    fractions[SoybeanStage.R7] = fractions[SoybeanStage.R6] + 0.65 * (1 - fractions[SoybeanStage.R6])
    physics.phenology.params = replace(
        physics.phenology.params,
        stage_fraction_thresholds=dict(sorted(fractions.items(), key=lambda item: item[1])),
        nominal_seed_depth_cm=profile.planting_depth_cm,
        preferred_top_vwc_min=profile.planting_vwc_range[0],
        preferred_top_vwc_max=profile.planting_vwc_range[1],
        blocked_top_vwc_wet=min(0.48, profile.planting_vwc_range[1] + 0.08),
        max_photoperiod_delay_fraction=0.0 if profile.crop_type == "maize" else 0.15,
    )
    physics.management.params = replace(
        physics.management.params,
        nominal_seed_depth_cm=profile.planting_depth_cm,
    )
    physics.soil.params = replace(
        physics.soil.params,
        planting_temp_min_c=profile.planting_min_temp_c,
        planting_vwc_min=profile.planting_vwc_range[0],
        planting_vwc_max=profile.planting_vwc_range[1],
        planting_vwc_too_wet=min(0.48, profile.planting_vwc_range[1] + 0.05),
        water_stress_vwc=0.26 if profile.crop_type == "rice" else 0.20,
        irrigation_trigger_vwc=0.24 if profile.crop_type == "rice" else 0.18,
        max_crop_coefficient=1.15 if profile.crop_type == "rice" else 1.20,
    )
    fill = fractions[SoybeanStage.R5]
    physics.canopy.params = replace(
        physics.canopy.params,
        max_daily_biomass_g_m2=45.0 if profile.crop_type == "maize" else 38.0,
        seed_fill_points=((fill, 0.10), (fractions[SoybeanStage.R6], 0.65),
                          (fractions[SoybeanStage.R7], 0.90), (1.0, 1.0)),
    )
    p = physics.yield_recovery.params
    physics.yield_recovery.params = replace(
        p,
        market_moisture_frac=profile.storage_moisture_max_pct / 100.0,
        ideal_harvest_moisture_min=profile.harvest_moisture_min_pct / 100.0,
        ideal_harvest_moisture_max=profile.harvest_moisture_max_pct / 100.0,
        wet_harvest_threshold=profile.harvest_moisture_max_pct / 100.0,
        dry_shatter_threshold=max(0.08, (profile.harvest_moisture_min_pct - 3.0) / 100.0),
        initial_r8_grain_moisture=0.32 if profile.crop_type == "maize" else 0.28,
        max_field_grain_moisture=0.45,
        base_drydown_per_day=profile.grain_drydown_pct_per_day / 100.0 * 0.6,
        solar_drydown_coeff=0.00010,
        wind_drydown_coeff=0.0003,
        drying_required_moisture=profile.storage_moisture_max_pct / 100.0,
        shatter_loss_per_day_after_grace=0.0015 if profile.crop_type == "maize" else 0.003,
        # Historical field name; maize uses the 56 lb bushel, rice has no
        # standardized bushel output (the engine returns None for rice).
        kg_per_bushel_soybean=25.4012 if profile.crop_type == "maize" else p.kg_per_bushel_soybean,
        bushel_reporting_enabled=profile.crop_type != "rice",
    )
