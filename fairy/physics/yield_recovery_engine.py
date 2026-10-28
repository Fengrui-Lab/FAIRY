from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from math import exp, isfinite
from typing import Mapping


# Wet-basis soybean EMC (%), published by NDSU Extension agricultural engineer
# Ken Hellevang, reproduced by University of Minnesota Extension (Table 1):
# https://blog-crop-news.extension.umn.edu/2022/10/ndsu-addresses-conditioning-too-dry.html
# These are equilibrium observations, not a field drying-rate calibration.
_SOYBEAN_EMC_TEMPERATURE_F = (32.0, 40.0, 50.0, 60.0, 70.0, 80.0)
_SOYBEAN_EMC_RH_PCT = (50.0, 60.0, 70.0, 80.0, 90.0)
_SOYBEAN_EMC_WET_BASIS_PCT = (
    (10.0, 11.8, 13.7, 16.2, 19.8),
    (9.8, 11.5, 13.5, 16.0, 19.6),
    (9.5, 11.2, 13.2, 15.7, 19.4),
    (9.2, 11.0, 13.0, 15.4, 19.1),
    (8.9, 10.7, 12.7, 15.2, 18.9),
    (8.6, 10.4, 12.5, 15.0, 18.7),
)


def soybean_equilibrium_moisture_frac(
    air_temp_mean_c: float, relative_humidity_pct: float,
) -> float:
    """Bilinearly interpolate the published soybean wet-basis EMC table.

    The table covers 0--26.67 C and 50--90% RH. Outside that domain the nearest
    boundary is used, rather than claiming an unsupported extrapolation. The
    daily engine adds a diagnostic tag when it has to use a boundary value.
    """
    if not isfinite(air_temp_mean_c):
        raise ValueError("Soybean EMC requires finite air temperature")
    if not isfinite(relative_humidity_pct) or not 0 <= relative_humidity_pct <= 100:
        raise ValueError("Soybean EMC requires relative humidity in [0, 100]")

    def bracket(knots: tuple[float, ...], value: float) -> tuple[int, float]:
        value = max(knots[0], min(knots[-1], value))
        for index in range(len(knots) - 1):
            if value <= knots[index + 1]:
                return index, (value - knots[index]) / (knots[index + 1] - knots[index])
        raise AssertionError("Clamped interpolation input has no bracket")

    ti, tw = bracket(_SOYBEAN_EMC_TEMPERATURE_F, air_temp_mean_c * 1.8 + 32.0)
    hi, hw = bracket(_SOYBEAN_EMC_RH_PCT, relative_humidity_pct)
    lower = _SOYBEAN_EMC_WET_BASIS_PCT[ti]
    upper = _SOYBEAN_EMC_WET_BASIS_PCT[ti + 1]
    lower_rh = lower[hi] + hw * (lower[hi + 1] - lower[hi])
    upper_rh = upper[hi] + hw * (upper[hi + 1] - upper[hi])
    return (lower_rh + tw * (upper_rh - lower_rh)) / 100.0


class GrowthStage(str, Enum):
    """
    Crop stages consumed from the phenology engine.

    R8 is physiological full maturity. Harvest readiness also depends on grain
    moisture and weather/trafficability, which are handled in this module.
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
    # Native non-soybean crops use coarse stages, not soybean reproductive labels.
    VEGETATIVE = "VEGETATIVE"
    REPRODUCTIVE = "REPRODUCTIVE"
    MATURE = "MATURE"


@dataclass
class YieldRecoveryParameters:
    """
    Parameters for the Farm-ARE yield and recovered-yield model.

    Scientific / agronomic basis:
        The model separates:
          1. biological yield potential from the canopy/biomass engine,
          2. harvestable yield after field losses,
          3. recovered yield after machine/header losses and grain moisture effects.

        Agronomic anchors:
          - Soybean grain is commonly marketed near 13% moisture.
          - Harvesting around 13-15% moisture is operationally desirable.
          - Very dry soybean seed (< ~11%) increases shattering and mechanical
            damage risk.
          - Delayed harvest after maturity increases pod shattering risk,
            especially under repeated wetting/drying cycles.
          - Typical combine/field harvest loss targets are low single-digit
            percentages under good conditions; losses rise with lodging,
            low moisture, poor settings, and rough conditions.

    Engineering simplification:
        This is not a mechanistic seed-moisture model, combine mechanics model,
        or grain-quality model. It is a compact accounting model for scenario
        evaluation.
    """

    # Moisture basis.
    market_moisture_frac: float = 0.13
    ideal_harvest_moisture_min: float = 0.12
    ideal_harvest_moisture_max: float = 0.15
    wet_harvest_threshold: float = 0.18
    dry_shatter_threshold: float = 0.11

    # Grain moisture dynamics after R8.
    # R8 grain starts wetter and dries down depending on weather.
    initial_r8_grain_moisture: float = 0.30
    min_field_grain_moisture: float = 0.08
    max_field_grain_moisture: float = 0.35
    # Calibrated to typical soybean field drydown of ~1.5-2.5%/day under
    # average sunny Harbin September conditions. Earlier defaults pushed
    # drydown to 4-5%/day which made even one-day waits push moisture
    # below the 13% safe-storage minimum, making harvest scenarios
    # unrunnable.
    base_drydown_per_day: float = 0.010
    solar_drydown_coeff: float = 0.0003
    wind_drydown_coeff: float = 0.0008
    humidity_proxy_rain_penalty: float = 0.012
    rain_rewetting_per_mm: float = 0.0015
    max_daily_rewetting: float = 0.035

    # Explicit opt-in: historic scenarios retain their exact drydown equation.
    grain_moisture_mode: str = "legacy"
    # First-order water/dry-matter-ratio relaxation toward the EMC table above.
    # Five days is an engineering time constant, NOT a calibrated local field
    # coefficient. ISU field observations support rapid initial drying and
    # slowing near equilibrium (about 3.2 percentage points/day in the first
    # 12 days after maturity), not this particular constant:
    # https://crops.extension.iastate.edu/cropnews/2017/09/how-fast-do-soybeans-dry-down-field
    soybean_equilibrium_time_constant_days: float = 5.0

    # Delayed harvest and shattering.
    shatter_delay_grace_days: int = 7
    shatter_loss_per_day_after_grace: float = 0.003
    shatter_loss_dry_bonus: float = 0.005
    wet_dry_cycle_loss: float = 0.006
    max_field_loss_fraction: float = 0.35

    # Lodging / biotic / disease field-loss effects.
    lodging_loss_weight: float = 0.12
    disease_quality_loss_weight: float = 0.08
    insect_pod_damage_loss_weight: float = 0.06

    # Machine recovery / combine loss.
    base_machine_loss_fraction: float = 0.025
    low_moisture_machine_loss_bonus: float = 0.020
    high_moisture_machine_loss_bonus: float = 0.015
    lodging_machine_loss_weight: float = 0.08
    max_machine_loss_fraction: float = 0.25

    # Moisture price/weight adjustment.
    # The recovered dry-matter equivalent is converted to market-moisture yield.
    # Wet soybeans may require drying/discount; overdry soybeans lose saleable
    # mass relative to 13% moisture.
    drying_required_moisture: float = 0.15
    quality_discount_wet: float = 0.03
    quality_discount_damaged: float = 0.05

    # Unit conversion.
    # 1 bushel soybean = 60 lb at 13% moisture.
    kg_per_bushel_soybean: float | None = 27.2155
    bushel_reporting_enabled: bool = True

    # WOFOST TWSO is dry matter, unlike the old empirical wet-yield proxy.
    biological_yield_is_dry_matter: bool = False

    def __post_init__(self) -> None:
        if self.grain_moisture_mode not in {"legacy", "soybean_equilibrium"}:
            raise ValueError("Unknown grain_moisture_mode")
        if (
            not isfinite(self.soybean_equilibrium_time_constant_days)
            or self.soybean_equilibrium_time_constant_days <= 0
        ):
            raise ValueError("soybean_equilibrium_time_constant_days must be positive and finite")


@dataclass
class YieldWeatherInput:
    day: date
    air_temp_mean_c: float
    rain_mm: float
    solar_rad_mj_m2: float
    wind_ms: float
    # None preserves callers that predate humidity-aware grain moisture. It is
    # accepted by the legacy mode, but never fabricated in the opt-in mode.
    relative_humidity_pct: float | None = None


@dataclass
class YieldPhenologyInput:
    stage: GrowthStage
    maturity_date: date | None


@dataclass
class YieldGrowthInput:
    """
    Output consumed from canopy/biomass model.

    yield_potential_g_m2:
        Biological grain-yield potential proxy before harvest losses.
        The canopy/biomass module updates this mainly after R5.

    aboveground_biomass_g_m2:
        Optional diagnostic used for reporting.
    """

    yield_potential_g_m2: float
    aboveground_biomass_g_m2: float = 0.0


@dataclass
class YieldStressInput:
    """
    Optional field condition modifiers.

    lodging_severity:
        0-1 state where high values increase field and machine losses.

    disease_severity / insect_pod_damage:
        0-1 states representing late-season quality or pod-loss risks.
    """

    lodging_severity: float = 0.0
    disease_severity: float = 0.0
    insect_pod_damage: float = 0.0


@dataclass
class HarvestAction:
    """
    Harvest operation applied to a ridge on a given day.

    machine_quality:
        0-1 factor reflecting combine/header setup and operator execution.
        Lower values increase machine loss.

    pass_completed:
        False can represent partial/incomplete operation; no recovered yield is
        recorded unless the pass is completed.
    """

    machine_quality: float = 1.0
    pass_completed: bool = True


@dataclass
class YieldRecoveryState:
    ridge_id: int
    r8_reached: bool = False
    maturity_date: date | None = None

    grain_moisture_frac: float | None = None
    wet_dry_cycles_after_r8: int = 0
    last_rain_or_rewetting: bool = False

    biological_yield_g_m2: float = 0.0
    field_loss_fraction: float = 0.0
    machine_loss_fraction: float = 0.0
    recovered_yield_g_m2_at_market_moisture: float = 0.0

    harvested: bool = False
    harvest_date: date | None = None
    drying_required: bool = False
    quality_discount_fraction: float = 0.0
    # A harvest settlement does not consume or replace a daily weather tick.
    last_daily_update_day: date | None = None

    tags: list[str] = field(default_factory=list)


@dataclass
class YieldRecoveryDayResult:
    day: date
    ridge_id: int
    stage: GrowthStage
    grain_moisture_frac: float | None
    biological_yield_g_m2: float
    field_loss_fraction: float
    machine_loss_fraction: float
    harvestable_yield_g_m2: float
    recovered_yield_g_m2_at_market_moisture: float
    recovered_yield_kg_ha_at_market_moisture: float
    recovered_yield_bu_ac_at_market_moisture: float | None
    harvested: bool
    drying_required: bool
    quality_discount_fraction: float
    harvest_ready: bool
    tags: list[str]


class YieldRecoveryEngine:
    """
    Reduced yield and recovered-yield engine for Farm-ARE.

    Purpose:
        Convert biological yield potential into recovered yield under realistic
        harvest timing, grain moisture, shattering, lodging, and machine-loss
        effects.

    Scope:
        Ridge-level yield accounting from R8 maturity through harvest.

    Non-scope:
        Detailed seed composition, grain elevator pricing rules, drying energy
        cost, combine mechanics, storage spoilage, and market price modeling.
    """

    def __init__(
        self,
        num_ridges: int = 64,
        params: YieldRecoveryParameters | None = None,
    ) -> None:
        self.params = params or YieldRecoveryParameters()
        self.states: dict[int, YieldRecoveryState] = {
            ridge_id: YieldRecoveryState(ridge_id=ridge_id)
            for ridge_id in range(num_ridges)
        }

    def update_day(
        self,
        weather: YieldWeatherInput,
        phenology_by_ridge: Mapping[int, YieldPhenologyInput],
        growth_by_ridge: Mapping[int, YieldGrowthInput],
        stress_by_ridge: Mapping[int, YieldStressInput] | None = None,
        harvest_actions_by_ridge: Mapping[int, HarvestAction] | None = None,
    ) -> list[YieldRecoveryDayResult]:
        """
        Advance yield/recovery once per date, plus the legacy harvest update.

        Harvest actions are optional. If no harvest action is provided, the
        model only updates biological potential, grain moisture, and losses.
        """
        stress_by_ridge = stress_by_ridge or {}
        harvest_actions_by_ridge = harvest_actions_by_ridge or {}

        results: list[YieldRecoveryDayResult] = []
        for ridge_id, state in self.states.items():
            phen = phenology_by_ridge.get(
                ridge_id,
                YieldPhenologyInput(stage=GrowthStage.NOT_PLANTED, maturity_date=None),
            )
            growth = growth_by_ridge.get(
                ridge_id,
                YieldGrowthInput(
                    yield_potential_g_m2=0.0, aboveground_biomass_g_m2=0.0
                ),
            )
            stress = stress_by_ridge.get(ridge_id, YieldStressInput())
            harvest_action = harvest_actions_by_ridge.get(ridge_id)
            results.append(
                self._update_ridge_day(
                    state, weather, phen, growth, stress, harvest_action
                )
            )

        return results

    def get_state(self) -> dict[int, YieldRecoveryState]:
        return {
            ridge_id: YieldRecoveryState(**vars(state))
            for ridge_id, state in self.states.items()
        }

    def settle_harvest(
        self,
        weather: YieldWeatherInput,
        phenology_by_ridge: Mapping[int, YieldPhenologyInput],
        growth_by_ridge: Mapping[int, YieldGrowthInput],
        harvest_actions_by_ridge: Mapping[int, HarvestAction],
        stress_by_ridge: Mapping[int, YieldStressInput] | None = None,
    ) -> list[YieldRecoveryDayResult]:
        """Apply the historical drying/loss update before settling each harvest.

        A harvest performs another recovery-day update at the current date,
        including when a regular daily update already ran. Only selected
        ridges change, matching the historical non-target state restoration.
        """
        stress_by_ridge = stress_by_ridge or {}
        return [
            self._update_ridge_day(
                self.states[ridge_id], weather, phenology_by_ridge[ridge_id],
                growth_by_ridge[ridge_id],
                stress_by_ridge.get(ridge_id, YieldStressInput()), action,
            )
            for ridge_id, action in harvest_actions_by_ridge.items()
        ]

    def _update_ridge_day(
        self,
        state: YieldRecoveryState,
        weather: YieldWeatherInput,
        phen: YieldPhenologyInput,
        growth: YieldGrowthInput,
        stress: YieldStressInput,
        harvest_action: HarvestAction | None,
    ) -> YieldRecoveryDayResult:
        p = self.params
        tags: list[str] = []
        if (
            state.last_daily_update_day is not None
            and weather.day < state.last_daily_update_day
        ):
            raise ValueError("Yield recovery cannot move backwards in date")
        evolve_daily = (
            state.last_daily_update_day != weather.day or harvest_action is not None
        )

        # Biological yield potential is updated from the growth engine until
        # first R8 maturity. After R8, only moisture/loss/recovery terms move.
        if not state.harvested and not state.r8_reached:
            state.biological_yield_g_m2 = max(
                state.biological_yield_g_m2, growth.yield_potential_g_m2
            )

        # Initialize R8/maturity state.
        if phen.stage in {GrowthStage.R8, GrowthStage.MATURE} and not state.r8_reached:
            state.r8_reached = True
            state.maturity_date = phen.maturity_date or weather.day
            state.grain_moisture_frac = p.initial_r8_grain_moisture
            state.wet_dry_cycles_after_r8 = 0
            state.last_rain_or_rewetting = weather.rain_mm > 0.0
            tags.append("maturity_reached" if phen.stage == GrowthStage.MATURE else "r8_maturity_reached")

        # Update grain moisture and field loss only after R8 and before harvest.
        if state.r8_reached and not state.harvested and evolve_daily:
            self._update_grain_moisture(state, weather, tags)
            state.field_loss_fraction = self._field_loss_fraction(
                state, weather, stress, tags
            )
        if evolve_daily:
            state.last_daily_update_day = weather.day

        # Harvest if action is provided and pass is completed.
        if harvest_action is not None:
            if not state.r8_reached:
                tags.append("harvest_attempt_before_maturity" if p.kg_per_bushel_soybean is None
                            else "harvest_attempt_before_r8")
            elif state.harvested:
                tags.append("harvest_attempt_already_harvested")
            elif not harvest_action.pass_completed:
                tags.append("harvest_pass_incomplete")
            else:
                self._apply_harvest(state, weather, stress, harvest_action, tags)

        harvestable = state.biological_yield_g_m2 * (1.0 - state.field_loss_fraction)
        recovered_kg_ha = state.recovered_yield_g_m2_at_market_moisture * 10.0
        recovered_bu_ac = self._kg_ha_to_bu_ac(recovered_kg_ha)

        harvest_ready = (
            state.r8_reached
            and not state.harvested
            and state.grain_moisture_frac is not None
            and p.ideal_harvest_moisture_min
            <= state.grain_moisture_frac
            <= p.ideal_harvest_moisture_max
        )

        if harvest_ready:
            tags.append("harvest_ready")
        if state.grain_moisture_frac is not None:
            if state.grain_moisture_frac < p.dry_shatter_threshold:
                tags.append("overdry_shatter_risk")
            if state.grain_moisture_frac > p.wet_harvest_threshold:
                tags.append("too_wet_for_harvest")

        state.tags = tags

        return YieldRecoveryDayResult(
            day=weather.day,
            ridge_id=state.ridge_id,
            stage=phen.stage,
            grain_moisture_frac=(
                round(state.grain_moisture_frac, 4)
                if state.grain_moisture_frac is not None
                else None
            ),
            biological_yield_g_m2=round(state.biological_yield_g_m2, 3),
            field_loss_fraction=round(state.field_loss_fraction, 4),
            machine_loss_fraction=round(state.machine_loss_fraction, 4),
            harvestable_yield_g_m2=round(harvestable, 3),
            recovered_yield_g_m2_at_market_moisture=round(
                state.recovered_yield_g_m2_at_market_moisture, 3
            ),
            recovered_yield_kg_ha_at_market_moisture=round(recovered_kg_ha, 1),
            recovered_yield_bu_ac_at_market_moisture=(
                round(recovered_bu_ac, 1) if recovered_bu_ac is not None else None
            ),
            harvested=state.harvested,
            drying_required=state.drying_required,
            quality_discount_fraction=round(state.quality_discount_fraction, 4),
            harvest_ready=harvest_ready,
            tags=tags,
        )

    def _update_grain_moisture(
        self,
        state: YieldRecoveryState,
        weather: YieldWeatherInput,
        tags: list[str],
    ) -> None:
        p = self.params
        assert state.grain_moisture_frac is not None
        if p.grain_moisture_mode == "soybean_equilibrium":
            self._update_equilibrium_grain_moisture(state, weather, tags)
            return
        if p.grain_moisture_mode != "legacy":
            raise ValueError("Unknown grain_moisture_mode")

        # Daily dry-down increases with solar radiation and wind, and slows with
        # rain/cloudy wet conditions. Rain can rewet mature grain/pods.
        drydown = (
            p.base_drydown_per_day
            + p.solar_drydown_coeff * max(0.0, weather.solar_rad_mj_m2)
            + p.wind_drydown_coeff * max(0.0, weather.wind_ms)
        )

        if weather.rain_mm > 0:
            drydown = max(0.0, drydown - p.humidity_proxy_rain_penalty)
            rewetting = min(
                p.max_daily_rewetting, p.rain_rewetting_per_mm * weather.rain_mm
            )
        else:
            rewetting = 0.0

        previous_moisture = state.grain_moisture_frac
        state.grain_moisture_frac = previous_moisture - drydown + rewetting
        state.grain_moisture_frac = self._clip(
            state.grain_moisture_frac,
            p.min_field_grain_moisture,
            p.max_field_grain_moisture,
        )

        rewet = rewetting > 0.002
        if state.r8_reached:
            if rewet and not state.last_rain_or_rewetting:
                state.wet_dry_cycles_after_r8 += 1
                tags.append("wet_dry_cycle_after_maturity" if p.kg_per_bushel_soybean is None
                            else "wet_dry_cycle_after_r8")
            state.last_rain_or_rewetting = rewet

    def _update_equilibrium_grain_moisture(
        self,
        state: YieldRecoveryState,
        weather: YieldWeatherInput,
        tags: list[str],
    ) -> None:
        """Relax toward soybean EMC, with bounded liquid-rain water uptake.

        Air exchange is first order in water per unit dry matter. It never
        jumps immediately to EMC and cannot overshoot the day's EMC. Rain
        uptake retains the legacy *engineering* uptake/cap parameters, but is
        also bounded by actual incoming rainwater (1 mm = 1000 g/m2). Neither
        the EMC lookup nor water exchange changes seed dry matter or native
        WOFOST growth. This is a daily approximation; it has no hourly pod,
        dew, radiation-heating, or canopy-aerodynamics calibration.
        """
        p = self.params
        rh = weather.relative_humidity_pct
        if rh is None:
            raise ValueError("soybean_equilibrium grain moisture requires observed relative_humidity_pct")
        tau = p.soybean_equilibrium_time_constant_days
        if not isfinite(tau) or tau <= 0:
            raise ValueError("soybean_equilibrium_time_constant_days must be positive and finite")
        emc = soybean_equilibrium_moisture_frac(weather.air_temp_mean_c, rh)
        temp_f = weather.air_temp_mean_c * 1.8 + 32.0
        if not 32.0 <= temp_f <= 80.0 or not 50.0 <= rh <= 90.0:
            tags.append("soybean_emc_input_clamped_to_published_table")
        tags.append("soybean_equilibrium_moisture")

        previous = state.grain_moisture_frac
        assert previous is not None
        previous_water_ratio = previous / (1.0 - previous)
        equilibrium_water_ratio = emc / (1.0 - emc)
        air_water_ratio = equilibrium_water_ratio + (
            previous_water_ratio - equilibrium_water_ratio
        ) * exp(-1.0 / tau)
        air_moisture = air_water_ratio / (1.0 + air_water_ratio)

        # Rain is an external water input, not a reset to an arbitrary wet
        # moisture. Limit both the requested wet-basis rise and water mass.
        rain_mm = max(0.0, weather.rain_mm)
        requested_rise = min(p.max_daily_rewetting, p.rain_rewetting_per_mm * rain_mm)
        requested_moisture = min(p.max_field_grain_moisture, air_moisture + requested_rise)
        dry_mass = max(0.0, state.biological_yield_g_m2)
        if not p.biological_yield_is_dry_matter:
            dry_mass *= 1.0 - p.market_moisture_frac
        if dry_mass > 0 and requested_moisture > air_moisture:
            requested_water = dry_mass * (
                requested_moisture / (1.0 - requested_moisture) - air_water_ratio
            )
            rain_water = min(requested_water, rain_mm * 1000.0)
            if rain_water < requested_water:
                tags.append("rain_rewetting_limited_by_incoming_water")
            air_water_ratio += rain_water / dry_mass
        state.grain_moisture_frac = self._clip(
            air_water_ratio / (1.0 + air_water_ratio),
            p.min_field_grain_moisture,
            p.max_field_grain_moisture,
        )

        # Humid air can also rewet grain. Count the observed net wetting, not
        # every rainy day regardless of whether the grain actually got wetter.
        rewet = state.grain_moisture_frac - previous > 0.002
        if state.r8_reached:
            if rewet and not state.last_rain_or_rewetting:
                state.wet_dry_cycles_after_r8 += 1
                tags.append("wet_dry_cycle_after_r8")
            state.last_rain_or_rewetting = rewet

    def _field_loss_fraction(
        self,
        state: YieldRecoveryState,
        weather: YieldWeatherInput,
        stress: YieldStressInput,
        tags: list[str],
    ) -> float:
        p = self.params

        if state.maturity_date is None:
            return 0.0

        days_after_maturity = max(0, (weather.day - state.maturity_date).days)
        loss = 0.0

        # Delayed harvest shattering loss.
        if (days_after_maturity > p.shatter_delay_grace_days
                and (p.kg_per_bushel_soybean is not None or p.shatter_loss_per_day_after_grace > 0)):
            delay_days = days_after_maturity - p.shatter_delay_grace_days
            loss += delay_days * p.shatter_loss_per_day_after_grace
            tags.append("delayed_harvest_loss")

        # Low moisture increases shattering risk.
        if (
            state.grain_moisture_frac is not None
            and state.grain_moisture_frac < p.dry_shatter_threshold
        ):
            loss += p.shatter_loss_dry_bonus
            tags.append("low_moisture_field_loss")

        # Repeated wet/dry cycles increase pod splitting/shattering risk.
        loss += state.wet_dry_cycles_after_r8 * p.wet_dry_cycle_loss

        # Lodging and late biotic damage reduce harvestable field yield.
        loss += p.lodging_loss_weight * self._clip(stress.lodging_severity, 0.0, 1.0)
        loss += p.disease_quality_loss_weight * self._clip(
            stress.disease_severity, 0.0, 1.0
        )
        loss += p.insect_pod_damage_loss_weight * self._clip(
            stress.insect_pod_damage, 0.0, 1.0
        )

        return self._clip(loss, 0.0, p.max_field_loss_fraction)

    def _apply_harvest(
        self,
        state: YieldRecoveryState,
        weather: YieldWeatherInput,
        stress: YieldStressInput,
        harvest_action: HarvestAction,
        tags: list[str],
    ) -> None:
        p = self.params
        assert state.grain_moisture_frac is not None

        harvestable_g_m2 = state.biological_yield_g_m2 * (
            1.0 - state.field_loss_fraction
        )

        machine_loss = p.base_machine_loss_fraction
        if state.grain_moisture_frac < p.dry_shatter_threshold:
            machine_loss += p.low_moisture_machine_loss_bonus
            tags.append("low_moisture_machine_loss")
        if state.grain_moisture_frac > p.wet_harvest_threshold:
            machine_loss += p.high_moisture_machine_loss_bonus
            tags.append("wet_harvest_machine_loss")

        machine_loss += p.lodging_machine_loss_weight * self._clip(
            stress.lodging_severity, 0.0, 1.0
        )

        # Poor machine quality increases loss.
        machine_quality = self._clip(harvest_action.machine_quality, 0.0, 1.0)
        machine_loss += (1.0 - machine_quality) * 0.10
        machine_loss = self._clip(machine_loss, 0.0, p.max_machine_loss_fraction)

        recovered_as_harvested = harvestable_g_m2 * (1.0 - machine_loss)

        # Convert recovered mass to the scenario's effective market yield basis.
        # Wet grain is discounted to market moisture. Grain already drier than
        # market moisture is not "rewetted" for a bonus; the model keeps the
        # in-field dry-down as effective weight loss.
        field_moisture = state.grain_moisture_frac
        if p.biological_yield_is_dry_matter:
            market_mass = recovered_as_harvested / (1.0 - p.market_moisture_frac)
            tags.append("dry_matter_to_standard_market_moisture")
        elif field_moisture > p.market_moisture_frac:
            market_mass = recovered_as_harvested * (
                    (1.0 - field_moisture) / (1.0 - p.market_moisture_frac)
            )
        else:
            market_mass = recovered_as_harvested * (
                    1.0 - (p.market_moisture_frac - field_moisture)
            )

        state.machine_loss_fraction = machine_loss
        state.recovered_yield_g_m2_at_market_moisture = max(0.0, market_mass)
        state.harvested = True
        state.harvest_date = weather.day

        state.drying_required = field_moisture > p.drying_required_moisture
        if state.drying_required:
            state.quality_discount_fraction += p.quality_discount_wet
            tags.append("drying_required")

        # Quality discount proxy for high damage risk.
        if field_moisture < p.dry_shatter_threshold or stress.disease_severity > 0.5:
            state.quality_discount_fraction += p.quality_discount_damaged
            tags.append("quality_discount_damage_risk")

        tags.append("harvest_completed")

    def _kg_ha_to_bu_ac(self, kg_ha: float) -> float | None:
        if not self.params.bushel_reporting_enabled:
            return None
        # 1 ha = 2.47105 acres.
        # bu/ac = kg/ha / kg_per_bushel / 2.47105
        if self.params.kg_per_bushel_soybean is None:
            return None
        return kg_ha / self.params.kg_per_bushel_soybean / 2.47105

    @staticmethod
    def _clip(x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, x))


if __name__ == "__main__":
    from datetime import timedelta

    engine = YieldRecoveryEngine(num_ridges=1)

    maturity = date(2026, 9, 15)
    for i in range(20):
        day = maturity + timedelta(days=i)
        weather = YieldWeatherInput(
            day=day,
            air_temp_mean_c=16.0,
            rain_mm=8.0 if i in {5, 12} else 0.0,
            solar_rad_mj_m2=14.0,
            wind_ms=4.0,
        )
        phen = {0: YieldPhenologyInput(stage=GrowthStage.R8, maturity_date=maturity)}
        growth = {
            0: YieldGrowthInput(
                yield_potential_g_m2=320.0, aboveground_biomass_g_m2=710.0
            )
        }
        stress = {
            0: YieldStressInput(
                lodging_severity=0.10, disease_severity=0.05, insect_pod_damage=0.0
            )
        }

        harvest = {}
        if i == 12:
            harvest = {0: HarvestAction(machine_quality=0.92)}

        result = engine.update_day(weather, phen, growth, stress, harvest)[0]
        print(result)
        if result.harvested:
            break
