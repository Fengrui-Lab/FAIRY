from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from math import isfinite
from typing import Mapping


class ManagementActionType(str, Enum):
    """
    Management actions that create delayed or persistent effects.

    The action types are intentionally coarse. Tool-level APIs can be more
    detailed, but the physics engine only needs the agronomic effect state.
    """

    PLANTING = "PLANTING"
    IRRIGATION = "IRRIGATION"
    FERTIGATION = "FERTIGATION"
    BASE_FERTILIZER = "BASE_FERTILIZER"
    HERBICIDE = "HERBICIDE"
    MECHANICAL_WEED_CONTROL = "MECHANICAL_WEED_CONTROL"
    INSECTICIDE = "INSECTICIDE"
    FUNGICIDE = "FUNGICIDE"
    # Post-harvest residue management (logged action; no physics state mutation
    # — used by the Decision component of FOS to verify the agent followed
    # the residue-incorporation step rather than burning).
    INCORPORATE_RESIDUE = "INCORPORATE_RESIDUE"


class GrowthStage(str, Enum):
    """
    Growth stages consumed from phenology.

    This duplicate enum keeps the module standalone. In the full Farm-ARE
    codebase, import this from the phenology module.
    """

    NOT_PLANTED = "NOT_PLANTED"
    PLANTED_PRE_EMERGENCE = "PLANTED_PRE_EMERGENCE"
    VE = "VE"
    VC = "VC"
    V1 = "V1"
    V2 = "V2"
    V3 = "V3"
    V4_PLUS = "V4_PLUS"
    R1 = "R1_BEGINNING_BLOOM"
    R3 = "R3_BEGINNING_POD"
    R5 = "R5_BEGINNING_SEED"
    R6 = "R6_FULL_SEED"
    R7 = "R7_BEGINNING_MATURITY"
    R8 = "R8_FULL_MATURITY"


@dataclass
class ManagementEffectParameters:
    """
    Parameters for the Farm-ARE management-effect model.

    Purpose:
        Translate agent operations into delayed and persistent effect states
        consumed by the soil, canopy/biomass, and biotic-pressure engines.

    Scientific / agronomic basis:
        Farm actions do not directly overwrite crop state. Irrigation first
        modifies soil water; fertilization modifies nutrient availability;
        pesticide/herbicide/fungicide applications reduce biotic pressure with
        residual effects; planting quality affects stand establishment and
        later canopy closure.

    Engineering simplification:
        This module does not model chemical fate, nutrient chemistry, pesticide
        degradation kinetics, or full crop nutrient uptake. It provides compact
        ridge-level effect states for closed-loop scenarios.
    """

    # Planting / stand establishment.
    nominal_seed_depth_cm: float = 4.0
    seed_depth_tolerance_cm: float = 1.0
    bad_depth_stand_penalty: float = 0.20
    poor_soil_stand_penalty: float = 0.20
    poor_alignment_stand_penalty: float = 0.15
    min_stand_fraction: float = 0.35

    # Nutrient state.
    # A composite availability index, not kg of nitrogen or an N/P/K balance.
    # Full-growth and low-availability thresholds are configured below.
    initial_nutrient_index: float = 0.75
    max_nutrient_index: float = 1.10
    base_fertilizer_gain: float = 1.0
    fertigation_gain: float = 0.32
    daily_nutrient_decay: float = 0.0008
    # Index units per g/m² of new biomass; inherited proxy coefficient, not
    # field-calibrated plant N concentration or total nitrogen requirement.
    nutrient_uptake_coeff: float = 0.00018
    nutrient_stress_min: float = 0.72

    # Over-application penalty.
    nutrient_excess_threshold: float = 1.05
    nutrient_excess_penalty: float = 0.08

    # Irrigation accounting.
    # The soil engine performs actual water-balance physics. This module records
    # recent irrigation and provides irrigation delay/effect tags.
    irrigation_effect_window_days: int = 2
    irrigation_overapply_mm_day: float = 18.0

    # Treatment residuals. These should match or be coordinated with the
    # biotic-pressure engine parameters.
    herbicide_residual_days: int = 18
    insecticide_residual_days: int = 10
    fungicide_residual_days: int = 14

    # Weather/application quality modifiers.
    rain_washoff_mm: float = 8.0
    high_wind_ms: float = 6.0
    rain_washoff_efficacy_factor: float = 0.50
    high_wind_efficacy_factor: float = 0.70

    # Effect-to-stress mapping.
    nutrient_index_full_growth: float = 0.85
    nutrient_index_zero_growth: float = 0.35


@dataclass
class ManagementWeatherInput:
    day: date
    rain_mm: float = 0.0
    wind_ms: float = 0.0


@dataclass
class ManagementSoilInput:
    top_vwc: float = 0.25
    root_vwc: float = 0.25
    planting_ready: bool = True
    trafficability: str = "good"


@dataclass
class ManagementCropInput:
    stage: GrowthStage | str = GrowthStage.NOT_PLANTED
    # None defers uptake until the crop reports actual growth for this date.
    # Zero is a known no-growth result, not an unavailable measurement.
    daily_biomass_g_m2: float | None = None


@dataclass
class ManagementAction:
    """
    Action applied on a ridge for a given day.

    amount:
        Generic action amount:
          - irrigation/fertigation: mm water equivalent for water component
          - fertilizer: relative unit or kg/ha-equivalent normalized externally
          - pesticide/herbicide/fungicide: normalized application amount

    quality:
        Execution quality in [0, 1]. This can reflect equipment calibration,
        bad alignment, rain/wind, poor depth, or manual operation quality.

    metadata:
        Optional details such as seed_depth_cm, row_alignment_quality, etc.
    """

    action_type: ManagementActionType
    amount: float = 1.0
    quality: float = 1.0
    metadata: dict[str, float | str | bool] = field(default_factory=dict)


@dataclass
class ManagementEffectState:
    ridge_id: int

    # Planting / stand effects.
    planted: bool = False
    planting_date: date | None = None
    seed_depth_cm: float | None = None
    planting_quality: float = 1.0
    stand_fraction: float = 0.0

    # Nutrient effects.
    nutrient_index: float = 0.75
    nutrient_stress: float = 0.85
    # Shared date cursor for nutrient, irrigation-memory and residual aging.
    last_nutrient_decay_day: date | None = None
    # Growth may be settled after daily aging. These fields describe the last
    # settled growth date; uptake is composite index depletion, not kg N.
    last_growth_uptake_day: date | None = None
    daily_growth_biomass_g_m2: float = 0.0
    daily_growth_uptake_index: float = 0.0
    cumulative_growth_uptake_index: float = 0.0

    # Recent action memory.
    days_since_irrigation: int | None = None
    recent_irrigation_mm: float = 0.0

    # Treatment residuals.
    herbicide_residual_days_left: int = 0
    insecticide_residual_days_left: int = 0
    fungicide_residual_days_left: int = 0

    # Cumulative accounting.
    cumulative_irrigation_mm: float = 0.0
    cumulative_fertigation_amount: float = 0.0
    cumulative_base_fertilizer_amount: float = 0.0
    cumulative_pesticide_applications: int = 0

    tags: list[str] = field(default_factory=list)


@dataclass
class ManagementEffectDayResult:
    day: date
    ridge_id: int
    planted: bool
    stand_fraction: float
    planting_quality: float
    nutrient_index: float
    nutrient_stress: float
    recent_irrigation_mm: float
    days_since_irrigation: int | None
    herbicide_residual_days_left: int
    insecticide_residual_days_left: int
    fungicide_residual_days_left: int
    treatment_efficacy_modifier: float
    tags: list[str]


class ManagementEffectEngine:
    """
    Reduced management-effect engine for Farm-ARE.

    Purpose:
        Convert farm actions into persistent ridge-level effect states that are
        consumed by other physics modules.

    Examples:
        - Planting creates stand_fraction and planting_quality.
        - Fertilizer/fertigation modifies nutrient_index and nutrient_stress.
        - Irrigation is recorded and passed to the soil engine as water input.
        - Herbicide/insecticide/fungicide create residual effect windows.
        - Rain/wind on application day reduce treatment efficacy.

    Non-scope:
        This module does not perform water balance, crop growth, chemical fate,
        or pest/disease reduction directly. It produces effect signals that the
        soil, growth, and biotic engines consume.
    """

    def __init__(
        self,
        num_ridges: int = 64,
        params: ManagementEffectParameters | None = None,
    ) -> None:
        self.params = params or ManagementEffectParameters()
        self.states: dict[int, ManagementEffectState] = {
            ridge_id: ManagementEffectState(
                ridge_id=ridge_id,
                nutrient_index=(
                    params.initial_nutrient_index
                    if params
                    else ManagementEffectParameters().initial_nutrient_index
                ),
                nutrient_stress=0.85,
            )
            for ridge_id in range(num_ridges)
        }

    def update_day(
        self,
        weather: ManagementWeatherInput,
        actions_by_ridge: Mapping[int, list[ManagementAction]] | None = None,
        soil_by_ridge: Mapping[int, ManagementSoilInput] | None = None,
        crop_by_ridge: Mapping[int, ManagementCropInput] | None = None,
        *,
        advance_daily: bool = True,
    ) -> list[ManagementEffectDayResult]:
        """
        Apply new actions and, at most once per date, age persistent effects.

        Sub-daily callers use ``advance_daily=False``: actions take effect now,
        without spending a day or marking the next daily tick as completed.
        """
        actions_by_ridge = actions_by_ridge or {}
        soil_by_ridge = soil_by_ridge or {}
        crop_by_ridge = crop_by_ridge or {}

        # Validate all available growth inputs before any ridge is aged. A
        # later invalid ridge must not leave earlier ridges partly advanced.
        if advance_daily:
            self._validate_growth_inputs(weather.day, {
                rid: crop.daily_biomass_g_m2
                for rid, crop in crop_by_ridge.items()
                if crop.daily_biomass_g_m2 is not None
            })
        for state in self.states.values():
            for previous in (state.last_nutrient_decay_day, state.last_growth_uptake_day):
                if previous is not None and weather.day < previous:
                    raise ValueError("Management effects cannot move backwards in date")

        results: list[ManagementEffectDayResult] = []
        for ridge_id, state in self.states.items():
            actions = actions_by_ridge.get(ridge_id, [])
            soil = soil_by_ridge.get(ridge_id, ManagementSoilInput())
            crop = crop_by_ridge.get(ridge_id, ManagementCropInput())
            results.append(self._update_ridge_day(
                state, weather, actions, soil, crop, advance_daily=advance_daily
            ))

        return results

    def settle_crop_growth(
        self, day: date, biomass_by_ridge: Mapping[int, float],
    ) -> None:
        """Debit actual new biomass once per ridge and calendar date.

        This second phase changes only nutrient availability and its stress
        signal. It neither advances the clock nor repeats action application,
        crop growth, pesticide aging or irrigation-memory aging. Validate the
        complete batch before mutating any ridge. Repeated settlement for an
        already settled date is a no-op; None inputs belong to update_day and
        must not be submitted here as if they were observed zero growth.

        Biomass is in g/m². The inherited uptake coefficient converts that
        increment to composite nutrient-index units, not a measured N mass.
        """
        self._validate_growth_inputs(day, biomass_by_ridge)
        for ridge_id, biomass in biomass_by_ridge.items():
            state = self.states[ridge_id]
            if state.last_growth_uptake_day == day:
                continue
            self._settle_ridge_growth(state, day, float(biomass))
            tags = [tag for tag in state.tags
                    if tag not in {"nutrient_stress", "nutrient_excess_penalty"}]
            self._refresh_nutrient_stress(state, tags)
            state.tags = tags

    def _validate_growth_inputs(self, day: date, biomass_by_ridge: Mapping[int, float]) -> None:
        if type(day) is not date:
            raise ValueError("Growth settlement requires a calendar date")
        coefficient = self.params.nutrient_uptake_coeff
        if not isfinite(coefficient) or coefficient < 0:
            raise ValueError("Nutrient uptake coefficient must be finite and nonnegative")
        for ridge_id, biomass in biomass_by_ridge.items():
            if type(ridge_id) is not int or ridge_id not in self.states:
                raise ValueError(f"Unknown growth settlement ridge {ridge_id!r}")
            if (type(biomass) not in (int, float) or not isfinite(biomass)
                    or biomass < 0 or not isfinite(coefficient * biomass)):
                raise ValueError("Daily biomass must be finite and nonnegative")
            state = self.states[ridge_id]
            for previous in (state.last_growth_uptake_day, state.last_nutrient_decay_day):
                if previous is not None and day < previous:
                    raise ValueError("Growth settlement cannot move backwards in date")

    def _settle_ridge_growth(
        self, state: ManagementEffectState, day: date, biomass: float,
        *, background_depletion: float = 0.0,
    ) -> None:
        """Shared debit for existing pre-growth and new post-growth callers."""
        if state.last_growth_uptake_day == day:
            # A post-growth caller can settle before the day's ordinary aging.
            # A later daily update still owes background depletion, but no
            # second biomass-driven debit.
            state.nutrient_index = self._clip(
                state.nutrient_index - background_depletion,
                0.0, self.params.max_nutrient_index,
            )
            return
        before = state.nutrient_index
        requested_uptake = self.params.nutrient_uptake_coeff * biomass
        state.nutrient_index = self._clip(
            before - (background_depletion + requested_uptake),
            0.0, self.params.max_nutrient_index,
        )
        # Report the part actually debited, separately from background aging;
        # availability cannot fall below zero even when demand exceeds it.
        available_after_background = self._clip(
            before - background_depletion, 0.0, self.params.max_nutrient_index,
        )
        state.daily_growth_biomass_g_m2 = biomass
        state.daily_growth_uptake_index = max(0.0, available_after_background - state.nutrient_index)
        state.cumulative_growth_uptake_index += state.daily_growth_uptake_index
        state.last_growth_uptake_day = day

    def irrigation_mm_by_ridge(
        self,
        actions_by_ridge: Mapping[int, list[ManagementAction]],
    ) -> dict[int, float]:
        """
        Extract irrigation water inputs for the soil engine.

        The management engine records the effect history, but the soil engine
        performs the actual water-balance update.
        """
        out: dict[int, float] = {}
        for ridge_id, actions in actions_by_ridge.items():
            total = 0.0
            for action in actions:
                if action.action_type == ManagementActionType.IRRIGATION:
                    water_mm = action.amount
                elif action.action_type == ManagementActionType.FERTIGATION:
                    water_mm = float(action.metadata.get("water_mm", action.amount))
                else:
                    continue
                total += max(0.0, water_mm) * self._clip(action.quality, 0.0, 1.0)
            if total > 0:
                out[ridge_id] = total
        return out

    def nutrient_stress_by_ridge(self) -> dict[int, float]:
        return {
            ridge_id: state.nutrient_stress for ridge_id, state in self.states.items()
        }

    def stand_fraction_by_ridge(self) -> dict[int, float]:
        return {
            ridge_id: state.stand_fraction for ridge_id, state in self.states.items()
        }

    def get_state(self) -> dict[int, ManagementEffectState]:
        return {
            ridge_id: ManagementEffectState(**vars(state))
            for ridge_id, state in self.states.items()
        }

    def _update_ridge_day(
        self,
        state: ManagementEffectState,
        weather: ManagementWeatherInput,
        actions: list[ManagementAction],
        soil: ManagementSoilInput,
        crop: ManagementCropInput,
        *,
        advance_daily: bool = True,
    ) -> ManagementEffectDayResult:
        p = self.params
        tags: list[str] = []

        treatment_efficacy_modifier = self._application_efficacy_modifier(weather)
        if treatment_efficacy_modifier < 1.0:
            tags.append("application_conditions_reduce_efficacy")

        if (
            state.last_nutrient_decay_day is not None
            and weather.day < state.last_nutrient_decay_day
        ):
            raise ValueError("Management effects cannot move backwards in date")
        # The existing nutrient-decay date guards all once-per-day aging.
        age_effects = advance_daily and state.last_nutrient_decay_day != weather.day

        # Age recent irrigation memory only on a real daily tick.
        if age_effects and state.days_since_irrigation is not None:
            state.days_since_irrigation += 1
            if state.days_since_irrigation > p.irrigation_effect_window_days:
                state.days_since_irrigation = None
                state.recent_irrigation_mm = 0.0

        # Background availability ages once per day. Crops whose daily growth
        # is not known yet settle their actual increment after canopy growth.
        # Existing callers with an explicit biomass retain the original debit
        # order: subtract background plus uptake before applying new actions.
        if age_effects:
            if crop.daily_biomass_g_m2 is None:
                state.nutrient_index = self._clip(
                    state.nutrient_index - p.daily_nutrient_decay, 0.0, p.max_nutrient_index,
                )
            else:
                self._settle_ridge_growth(
                    state, weather.day, float(crop.daily_biomass_g_m2),
                    background_depletion=p.daily_nutrient_decay,
                )
            state.last_nutrient_decay_day = weather.day

        # Age residual treatment windows.
        if state.herbicide_residual_days_left > 0:
            if age_effects:
                state.herbicide_residual_days_left -= 1
            tags.append("herbicide_residual_active")
        if state.insecticide_residual_days_left > 0:
            if age_effects:
                state.insecticide_residual_days_left -= 1
            tags.append("insecticide_residual_active")
        if state.fungicide_residual_days_left > 0:
            if age_effects:
                state.fungicide_residual_days_left -= 1
            tags.append("fungicide_residual_active")

        for action in actions:
            quality = self._clip(action.quality, 0.0, 1.0)

            if action.action_type == ManagementActionType.PLANTING:
                self._apply_planting(state, weather, action, soil, quality, tags)

            elif action.action_type == ManagementActionType.IRRIGATION:
                self._apply_irrigation(state, action, quality, tags)

            elif action.action_type == ManagementActionType.FERTIGATION:
                self._apply_fertigation(state, action, quality, tags)

            elif action.action_type == ManagementActionType.BASE_FERTILIZER:
                self._apply_base_fertilizer(state, action, quality, tags)

            elif action.action_type == ManagementActionType.HERBICIDE:
                state.herbicide_residual_days_left = p.herbicide_residual_days
                state.cumulative_pesticide_applications += 1
                tags.append("herbicide_effect_registered")

            elif action.action_type == ManagementActionType.MECHANICAL_WEED_CONTROL:
                tags.append("mechanical_weed_effect_registered")

            elif action.action_type == ManagementActionType.INSECTICIDE:
                state.insecticide_residual_days_left = p.insecticide_residual_days
                state.cumulative_pesticide_applications += 1
                tags.append("insecticide_effect_registered")

            elif action.action_type == ManagementActionType.FUNGICIDE:
                state.fungicide_residual_days_left = p.fungicide_residual_days
                state.cumulative_pesticide_applications += 1
                tags.append("fungicide_effect_registered")

            elif action.action_type == ManagementActionType.INCORPORATE_RESIDUE:
                # Logged-only action: residue incorporation has aggronomic
                # value (organic matter, soil structure) but the reduced
                # physics doesn't model soil organic carbon dynamics. The
                # tag is what FOS gate matchers look for.
                tags.append("residue_incorporated")

            else:
                raise ValueError(f"Unsupported action type: {action.action_type}")

        self._refresh_nutrient_stress(state, tags)
        state.tags = tags

        return ManagementEffectDayResult(
            day=weather.day,
            ridge_id=state.ridge_id,
            planted=state.planted,
            stand_fraction=round(state.stand_fraction, 3),
            planting_quality=round(state.planting_quality, 3),
            nutrient_index=round(state.nutrient_index, 3),
            nutrient_stress=round(state.nutrient_stress, 3),
            recent_irrigation_mm=round(state.recent_irrigation_mm, 2),
            days_since_irrigation=state.days_since_irrigation,
            herbicide_residual_days_left=state.herbicide_residual_days_left,
            insecticide_residual_days_left=state.insecticide_residual_days_left,
            fungicide_residual_days_left=state.fungicide_residual_days_left,
            treatment_efficacy_modifier=round(treatment_efficacy_modifier, 3),
            tags=tags,
        )

    def _apply_planting(
        self,
        state: ManagementEffectState,
        weather: ManagementWeatherInput,
        action: ManagementAction,
        soil: ManagementSoilInput,
        quality: float,
        tags: list[str],
    ) -> None:
        p = self.params

        seed_depth = float(
            action.metadata.get("seed_depth_cm", p.nominal_seed_depth_cm)
        )
        row_alignment_quality = float(action.metadata.get("row_alignment_quality", 1.0))

        state.planted = True
        state.planting_date = weather.day
        state.seed_depth_cm = seed_depth

        initial_stand_fraction = float(
            action.metadata.get("initial_stand_fraction", 1.0)
        )
        stand_fraction = (
            self._clip(initial_stand_fraction, p.min_stand_fraction, 1.0) * quality
        )
        if initial_stand_fraction < 0.999:
            tags.append("initial_stand_fraction_limit")

        # Seed depth penalty.
        depth_error = abs(seed_depth - p.nominal_seed_depth_cm)
        if depth_error > p.seed_depth_tolerance_cm:
            stand_fraction -= p.bad_depth_stand_penalty
            tags.append("planting_depth_penalty")

        # Soil condition penalty.
        if not soil.planting_ready:
            stand_fraction -= p.poor_soil_stand_penalty
            tags.append("planting_under_marginal_soil")

        # Alignment penalty.
        if row_alignment_quality < 0.85:
            stand_fraction -= p.poor_alignment_stand_penalty
            tags.append("ridge_alignment_penalty")

        state.planting_quality = self._clip(stand_fraction, p.min_stand_fraction, 1.0)
        state.stand_fraction = state.planting_quality
        tags.append("planting_effect_registered")

    def _apply_irrigation(
        self,
        state: ManagementEffectState,
        action: ManagementAction,
        quality: float,
        tags: list[str],
    ) -> None:
        p = self.params
        applied_mm = max(0.0, action.amount) * quality
        state.recent_irrigation_mm = applied_mm
        state.days_since_irrigation = 0
        state.cumulative_irrigation_mm += applied_mm
        tags.append("irrigation_effect_registered")

        if applied_mm >= p.irrigation_overapply_mm_day:
            tags.append("possible_over_irrigation")

    def _apply_fertigation(
        self,
        state: ManagementEffectState,
        action: ManagementAction,
        quality: float,
        tags: list[str],
    ) -> None:
        p = self.params
        # Default fertigation amount is normalized; metadata can override nutrient units.
        nutrient_amount = float(action.metadata.get("nutrient_amount", action.amount))
        gain = p.fertigation_gain * max(0.0, nutrient_amount) * quality
        state.nutrient_index = self._clip(
            state.nutrient_index + gain, 0.0, p.max_nutrient_index
        )
        state.cumulative_fertigation_amount += max(0.0, nutrient_amount)
        tags.append("fertigation_effect_registered")

        water_mm = float(action.metadata.get("water_mm", action.amount))
        applied_mm = max(0.0, water_mm) * quality
        if applied_mm > 0.0:
            state.recent_irrigation_mm = applied_mm
            state.days_since_irrigation = 0
            state.cumulative_irrigation_mm += applied_mm
            tags.append("fertigation_water_effect_registered")
            if applied_mm >= p.irrigation_overapply_mm_day:
                tags.append("possible_over_irrigation")

    def _apply_base_fertilizer(
        self,
        state: ManagementEffectState,
        action: ManagementAction,
        quality: float,
        tags: list[str],
    ) -> None:
        p = self.params
        nutrient_amount = float(action.metadata.get("nutrient_amount", action.amount))
        gain = p.base_fertilizer_gain * max(0.0, nutrient_amount) * quality
        state.nutrient_index = self._clip(
            state.nutrient_index + gain, 0.0, p.max_nutrient_index
        )
        state.cumulative_base_fertilizer_amount += max(0.0, nutrient_amount)
        tags.append("base_fertilizer_effect_registered")

    def _application_efficacy_modifier(self, weather: ManagementWeatherInput) -> float:
        p = self.params
        modifier = 1.0
        if weather.rain_mm >= p.rain_washoff_mm:
            modifier *= p.rain_washoff_efficacy_factor
        if weather.wind_ms >= p.high_wind_ms:
            modifier *= p.high_wind_efficacy_factor
        return self._clip(modifier, 0.0, 1.0)

    def _refresh_nutrient_stress(self, state: ManagementEffectState, tags: list[str]) -> None:
        state.nutrient_stress = self._nutrient_stress_from_index(state.nutrient_index)
        if state.nutrient_index > self.params.nutrient_excess_threshold:
            state.nutrient_stress = max(0.0, state.nutrient_stress - self.params.nutrient_excess_penalty)
            tags.append("nutrient_excess_penalty")
        if state.nutrient_stress < 0.80:
            tags.append("nutrient_stress")

    def _nutrient_stress_from_index(self, nutrient_index: float) -> float:
        p = self.params
        if nutrient_index >= p.nutrient_index_full_growth:
            return 1.0
        if nutrient_index <= p.nutrient_index_zero_growth:
            return p.nutrient_stress_min

        frac = (nutrient_index - p.nutrient_index_zero_growth) / (
            p.nutrient_index_full_growth - p.nutrient_index_zero_growth
        )
        return p.nutrient_stress_min + frac * (1.0 - p.nutrient_stress_min)

    @staticmethod
    def _clip(x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, x))


if __name__ == "__main__":
    from datetime import timedelta

    engine = ManagementEffectEngine(num_ridges=2)

    start = date(2026, 5, 10)
    for i in range(10):
        day = start + timedelta(days=i)
        weather = ManagementWeatherInput(day=day, rain_mm=0.0, wind_ms=3.0)
        soil = {
            0: ManagementSoilInput(top_vwc=0.25, root_vwc=0.25, planting_ready=True),
            1: ManagementSoilInput(top_vwc=0.34, root_vwc=0.30, planting_ready=False),
        }
        crop = {
            0: ManagementCropInput(stage=GrowthStage.VE, daily_biomass_g_m2=2.0),
            1: ManagementCropInput(stage=GrowthStage.VE, daily_biomass_g_m2=2.0),
        }

        actions = {}
        if i == 0:
            actions = {
                0: [
                    ManagementAction(
                        ManagementActionType.PLANTING,
                        quality=1.0,
                        metadata={"seed_depth_cm": 4.0, "row_alignment_quality": 1.0},
                    )
                ],
                1: [
                    ManagementAction(
                        ManagementActionType.PLANTING,
                        quality=0.9,
                        metadata={"seed_depth_cm": 6.0, "row_alignment_quality": 0.8},
                    )
                ],
            }
        if i == 4:
            actions = {
                0: [
                    ManagementAction(
                        ManagementActionType.FERTIGATION,
                        amount=8.0,
                        quality=0.95,
                        metadata={"nutrient_amount": 0.8},
                    )
                ],
                1: [
                    ManagementAction(
                        ManagementActionType.IRRIGATION, amount=10.0, quality=0.9
                    )
                ],
            }

        results = engine.update_day(weather, actions, soil, crop)
        for r in results:
            if r.tags:
                print(r)
