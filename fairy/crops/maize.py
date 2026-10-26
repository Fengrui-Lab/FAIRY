"""Independent, reduced grain-maize model for simulation scenarios.

``MAIZE_EARLY_2026`` is a fictional simulation cultivar. Its Celsius thermal
thresholds, growth coefficients and stress penalties are engineering choices,
not coefficients fitted to a real hybrid or a validated yield forecast.

The model uses native maize stages, intercepted-light biomass growth, a lasting
kernel-set penalty near silking, and post-maturity drydown. Biological grain is
dry matter; recovered grain is reported at the configured standard moisture.
Harvest settlement never performs an additional day of growth or drydown.

Qualitative basis (not a claim of implementing these complete models):
* UMN Extension, corn growth/development: maize V/R stages and thermal time.
  https://extension.umn.edu/agriculture/crop-production/corn/growth-and-development
* Purdue Extension, grain filling: silking stress, R6 physiological maturity,
  and weather-dependent drydown after maturity.
  https://www.agry.purdue.edu/ext/corn/news/timeless/GrainFill.html
* APSIM maize documentation: thermal development, intercepted radiation and
  stress effects on biomass and grain production.
  https://github.com/APSIMInitiative/APSIM710/blob/master/Documentation/Model%2CCropandSoil/CropModuleDocumentation/Maize.html
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from copy import deepcopy
from datetime import date
from enum import Enum
from math import exp, isfinite, sqrt
from typing import Any, Mapping, Protocol, Sequence

from fairy.crops.catalog import MAIZE
from fairy.crops.rules import PlantingRules
from fairy.crops.runtime import PlantingEvent


class MaizeStage(str, Enum):
    NOT_PLANTED = "NOT_PLANTED"
    PLANTED_PRE_EMERGENCE = "PLANTED_PRE_EMERGENCE"
    VE = "VE"
    V3 = "V3"
    V6 = "V6"
    V12 = "V12"
    VT = "VT"
    R1_SILKING = "R1_SILKING"
    R2_BLISTER = "R2_BLISTER"
    R3_MILK = "R3_MILK"
    R4_DOUGH = "R4_DOUGH"
    R5_DENT = "R5_DENT"
    R6_MATURITY = "R6_MATURITY"


@dataclass(frozen=True)
class MaizeParameters:
    cultivar_id: str = MAIZE.cultivar_id
    base_temp_c: float = 10.0
    upper_temp_c: float = 30.0
    emergence_gdd: float = 80.0
    gdd_to_v3: float = 160.0
    gdd_to_v6: float = 280.0
    gdd_to_v12: float = 450.0
    gdd_to_vt: float = 590.0
    gdd_to_r1: float = 620.0
    gdd_to_r2: float = 730.0
    gdd_to_r3: float = 840.0
    gdd_to_r4: float = 940.0
    gdd_to_r5: float = 1050.0
    gdd_to_r6: float = 1280.0
    max_lai: float = 5.5
    rue_g_mj_apar: float = 3.2
    harvest_index: float = 0.48
    max_biological_yield_g_m2: float = 1500.0
    density_opt_plants_m2: float = 6.5
    max_canopy_height_m: float = 2.4
    wilting_root_vwc: float = 0.12
    unstressed_root_vwc: float = 0.22
    initial_mature_grain_moisture: float = 0.35
    market_moisture_frac: float = MAIZE.market_moisture_pct / 100
    max_harvest_moisture_frac: float = MAIZE.harvest_rules.max_moisture_pct / 100
    drying_required_moisture: float = MAIZE.storage_moisture_pct / 100
    min_field_grain_moisture: float = 0.12
    base_drydown_per_day: float = 0.005

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, (int, float)) and not isfinite(value):
                raise ValueError(f"Maize parameter {item.name} must be finite")
        if self.cultivar_id != "MAIZE_EARLY_2026":
            raise ValueError("Only the simulated cultivar MAIZE_EARLY_2026 is supported")
        thresholds = [threshold for _, threshold in self.stage_thresholds]
        if not 0 < self.emergence_gdd < thresholds[0] or any(
            right <= left for left, right in zip(thresholds, thresholds[1:])
        ):
            raise ValueError("Maize thermal thresholds must be strictly increasing")
        if not self.upper_temp_c > self.base_temp_c:
            raise ValueError("Maize upper temperature must exceed its base")
        if not 0 <= self.wilting_root_vwc < self.unstressed_root_vwc <= 1:
            raise ValueError("Maize root-water thresholds are invalid")
        if not (
            0 <= self.min_field_grain_moisture <= self.market_moisture_frac
            <= self.max_harvest_moisture_frac
            < self.initial_mature_grain_moisture < 1
        ):
            raise ValueError("Maize moisture thresholds are invalid")
        if not 0 < self.harvest_index <= 1 or not 0 <= self.drying_required_moisture < 1:
            raise ValueError("Maize harvest index or drying threshold is invalid")
        if min(self.max_lai, self.rue_g_mj_apar, self.max_biological_yield_g_m2,
               self.density_opt_plants_m2,
               self.max_canopy_height_m, self.base_drydown_per_day) <= 0:
            raise ValueError("Maize growth and drydown coefficients must be positive")

    @property
    def stage_thresholds(self) -> tuple[tuple[MaizeStage, float], ...]:
        return (
            (MaizeStage.V3, self.gdd_to_v3), (MaizeStage.V6, self.gdd_to_v6),
            (MaizeStage.V12, self.gdd_to_v12), (MaizeStage.VT, self.gdd_to_vt),
            (MaizeStage.R1_SILKING, self.gdd_to_r1),
            (MaizeStage.R2_BLISTER, self.gdd_to_r2),
            (MaizeStage.R3_MILK, self.gdd_to_r3), (MaizeStage.R4_DOUGH, self.gdd_to_r4),
            (MaizeStage.R5_DENT, self.gdd_to_r5),
            (MaizeStage.R6_MATURITY, self.gdd_to_r6),
        )

    @property
    def market_moisture_pct(self) -> float:
        return self.market_moisture_frac * 100


@dataclass
class MaizePhenologyState:
    ridge_id: int
    planted: bool = False
    planting_date: date | None = None
    seed_type: str | None = None
    seed_depth_cm: float = 4.5
    stage: MaizeStage = MaizeStage.NOT_PLANTED
    days_after_planting: int = 0
    accumulated_gdd: float = 0.0
    effective_development_gdd: float = 0.0
    emergence_thermal_time: float = 0.0
    emerged: bool = False
    emergence_date: date | None = None
    maturity_date: date | None = None
    last_daily_gdd: float = 0.0


@dataclass
class MaizeCanopyState:
    ridge_id: int
    initialized: bool = False
    seed_type: str | None = None
    stand_fraction: float = 1.0
    planting_density_plants_m2: float = 6.5
    lai: float = 0.0
    canopy_cover: float = 0.0
    ndvi_proxy: float = 0.18
    aboveground_biomass_g_m2: float = 0.0
    daily_biomass_g_m2: float = 0.0
    yield_potential_g_m2: float = 0.0
    cumulative_apar_mj_m2: float = 0.0
    cumulative_stress_days: float = 0.0
    kernel_set_fraction: float = 1.0


@dataclass
class MaizeYieldState:
    ridge_id: int
    r6_reached: bool = False
    maturity_date: date | None = None
    grain_moisture_frac: float | None = None
    biological_yield_g_m2: float = 0.0
    field_loss_fraction: float = 0.0
    machine_loss_fraction: float = 0.0
    recovered_yield_g_m2_at_market_moisture: float = 0.0
    harvested: bool = False
    harvest_date: date | None = None
    drying_required: bool = False
    quality_discount_fraction: float = 0.0
    last_daily_update_day: date | None = None
    tags: list[str] = field(default_factory=list)


class MaizePhenology:
    def __init__(self, num_ridges: int, params: MaizeParameters) -> None:
        self.params = params
        self.states = {rid: MaizePhenologyState(rid) for rid in range(num_ridges)}


class MaizeCanopy:
    def __init__(self, num_ridges: int, params: MaizeParameters) -> None:
        self.params = params
        self.states = {rid: MaizeCanopyState(rid) for rid in range(num_ridges)}


class MaizeYieldRecovery:
    def __init__(self, num_ridges: int, params: MaizeParameters) -> None:
        self.params = params
        self.states = {rid: MaizeYieldState(rid) for rid in range(num_ridges)}


class SoilStateInput(Protocol):
    top_temp_c: float
    top_vwc: float
    root_vwc: float


class ManagementStateInput(Protocol):
    nutrient_stress: float
    stand_fraction: float


class BioticStateInput(Protocol):
    weed_pressure: float
    insect_pressure: float
    disease_pressure: float


class HarvestActionInput(Protocol):
    machine_quality: float
    pass_completed: bool


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _finite(value: Any, name: str, low: float | None = None,
            high: float | None = None) -> float:
    number = float(value)
    if not isfinite(number) or (low is not None and number < low) or (
        high is not None and number > high
    ):
        raise ValueError(f"Invalid maize input {name}: {value!r}")
    return number


class MaizeCropModel:
    """Own maize state and its daily cursor; shared soil/equipment stay outside.

    ``weather`` uses the orchestrator's ``phenology``, ``canopy`` and ``yield``
    weather inputs. The three input-state mappings remain owned by their shared
    engines. Calling a date twice is a no-op; dates cannot move backwards.
    """

    def __init__(self, num_ridges: int = 64,
                 params: MaizeParameters | None = None, *,
                 planting_rules: PlantingRules | None = None) -> None:
        if isinstance(num_ridges, bool) or not isinstance(num_ridges, int) or num_ridges <= 0:
            raise ValueError("num_ridges must be a positive integer")
        self.params = params or MaizeParameters()
        self.planting_rules = planting_rules or MAIZE.planting_rules
        self.phenology = MaizePhenology(num_ridges, self.params)
        self.canopy = MaizeCanopy(num_ridges, self.params)
        self.yield_recovery = MaizeYieldRecovery(num_ridges, self.params)
        self.last_daily_update_day: date | None = None

    @property
    def max_recoverable_yield_g_m2(self) -> float:
        """Conservative grain-bin bound, including moisture conversion.

        The dry-grain ceiling is an explicit simulation guard, not a claim that
        this fictional cultivar can attain that yield in a real field.
        """
        return self.params.max_biological_yield_g_m2 / (1 - self.params.market_moisture_frac)

    def plant(self, ridge_ids: Sequence[int], planting_date: date,
              seed_type: str, depth_cm: float,
              stand_fraction_by_ridge: Mapping[int, float],
              density_by_ridge: Mapping[int, float], *,
              replace_existing: bool = False) -> None:
        """Plant selected ridges, or explicitly replace their existing crop.

        Replant eligibility and resource charging belong to the operation App.
        ``replace_existing`` only resets these target crop states; it preserves
        other ridges and the world's daily clock.
        """
        event = PlantingEvent(tuple(ridge_ids), planting_date, seed_type, depth_cm,
                              stand_fraction_by_ridge, density_by_ridge,
                              replace_existing=replace_existing)
        self.validate_planting(event)
        ridges = list(event.ridge_ids)
        for rid in ridges:
            self.phenology.states[rid] = MaizePhenologyState(
                rid, planted=True, planting_date=planting_date, seed_type=seed_type,
                seed_depth_cm=depth_cm, stage=MaizeStage.PLANTED_PRE_EMERGENCE,
            )
            self.canopy.states[rid] = MaizeCanopyState(
                rid, seed_type=seed_type, stand_fraction=stand_fraction_by_ridge[rid],
                planting_density_plants_m2=density_by_ridge[rid],
            )
            self.yield_recovery.states[rid] = MaizeYieldState(rid)

    def validate_planting(self, event: PlantingEvent) -> None:
        """Validate the complete event without mutating crop state or clocks."""
        ridges = self._validate_ridges(event.ridge_ids)
        if event.seed_type != self.params.cultivar_id:
            raise ValueError(f"Unsupported maize seed {event.seed_type!r}")
        error = self.planting_rules.depth_cm.validate(event.depth_cm, "planting depth")
        if error:
            raise ValueError(error)
        planting_date = event.planting_date
        if self.last_daily_update_day is not None and planting_date < self.last_daily_update_day:
            raise ValueError("Maize planting cannot precede the current simulation date")
        for rid in ridges:
            if self.phenology.states[rid].planted and not event.replace_existing:
                raise ValueError(f"Maize ridge {rid} already has a planted crop")
            _finite(event.stand_fraction_by_ridge[rid], "stand fraction", 0, 1)
            density = _finite(event.density_by_ridge[rid], "planting density", 0)
            if self.planting_rules.density_plants_m2 is not None:
                error = self.planting_rules.density_plants_m2.validate(density, "planting density")
                if error:
                    raise ValueError(error)

    def plant_event(self, event: PlantingEvent) -> None:
        self.plant(event.ridge_ids, event.planting_date, event.seed_type,
                   event.depth_cm, event.stand_fraction_by_ridge,
                   event.density_by_ridge, replace_existing=event.replace_existing)

    def update_day(self, day: date, weather: Mapping[str, Any],
                   soil_states: Mapping[int, SoilStateInput],
                   management_states: Mapping[int, ManagementStateInput],
                   biotic_states: Mapping[int, BioticStateInput]) -> None:
        if self.last_daily_update_day is not None:
            if day < self.last_daily_update_day:
                raise ValueError("Maize physics cannot move backwards in date")
            if day == self.last_daily_update_day:
                return
        phen_weather = weather["phenology"]
        canopy_weather = weather["canopy"]
        yield_weather = weather["yield"]
        for item in (phen_weather, canopy_weather, yield_weather):
            if item.day != day:
                raise ValueError("Maize weather date must match its daily tick")
        tmin = _finite(phen_weather.air_temp_min_c, "minimum temperature")
        tmax = _finite(phen_weather.air_temp_max_c, "maximum temperature")
        if tmin > tmax:
            raise ValueError("Maize minimum temperature exceeds maximum temperature")
        solar = _finite(canopy_weather.solar_rad_mj_m2, "solar radiation", 0)
        rain = _finite(yield_weather.rain_mm, "rainfall", 0)
        wind = _finite(yield_weather.wind_ms, "wind speed", 0)
        temperature = _finite(yield_weather.air_temp_mean_c, "mean temperature")
        # Validate every ridge before any mutation, so invalid input is atomic.
        for rid, phen in self.phenology.states.items():
            if not phen.planted or self.yield_recovery.states[rid].harvested:
                continue
            soil, management, biotic = soil_states[rid], management_states[rid], biotic_states[rid]
            _finite(soil.top_temp_c, "soil temperature")
            _finite(soil.top_vwc, "surface VWC", 0, 1)
            _finite(soil.root_vwc, "root VWC", 0, 1)
            _finite(management.nutrient_stress, "nutrient multiplier", 0, 1)
            _finite(management.stand_fraction, "stand fraction", 0, 1)
            for name in ("weed_pressure", "insect_pressure", "disease_pressure"):
                _finite(getattr(biotic, name), name, 0, 1)
        p = self.params
        daily_gdd = max(0.0, (_clip(tmin, p.base_temp_c, p.upper_temp_c)
                             + _clip(tmax, p.base_temp_c, p.upper_temp_c)) / 2 - p.base_temp_c)
        for rid, phen in self.phenology.states.items():
            yld = self.yield_recovery.states[rid]
            # The environmental adapter consumes yesterday's increment once.
            # Mature/harvested/bare ridges must not keep reusing a stale flux.
            self.canopy.states[rid].daily_biomass_g_m2 = 0.0
            if not phen.planted or yld.harvested or day <= phen.planting_date:
                continue
            soil, management, biotic = soil_states[rid], management_states[rid], biotic_states[rid]
            water = _clip((soil.root_vwc - p.wilting_root_vwc)
                          / (p.unstressed_root_vwc - p.wilting_root_vwc))
            phen.days_after_planting = (day - phen.planting_date).days
            if not yld.r6_reached:
                self._advance_phenology(phen, day, daily_gdd, soil)
                self._advance_canopy(rid, solar, temperature, water, management, biotic)
                yld.biological_yield_g_m2 = self.canopy.states[rid].yield_potential_g_m2
            if phen.stage == MaizeStage.R6_MATURITY:
                if not yld.r6_reached:
                    yld.r6_reached = True
                    yld.maturity_date = day
                    yld.grain_moisture_frac = p.initial_mature_grain_moisture
                else:
                    self._advance_drydown(yld, temperature, solar, rain, wind)
                days_late = max(0, (day - yld.maturity_date).days - 10)
                yld.field_loss_fraction = _clip(
                    0.0015 * days_late + 0.03 * biotic.disease_pressure
                    + 0.02 * biotic.insect_pressure, 0, 0.25,
                )
            yld.last_daily_update_day = day
        self.last_daily_update_day = day

    def _advance_phenology(self, phen: MaizePhenologyState, day: date,
                           daily_gdd: float, soil: SoilStateInput) -> None:
        p = self.params
        phen.last_daily_gdd = daily_gdd
        phen.accumulated_gdd += daily_gdd
        if not phen.emerged:
            moisture = _clip(min(soil.top_vwc / 0.18, (0.55 - soil.top_vwc) / 0.20))
            soil_gdd = _clip(soil.top_temp_c - p.base_temp_c, 0, p.upper_temp_c - p.base_temp_c)
            phen.emergence_thermal_time += soil_gdd * moisture
            target = p.emergence_gdd + abs(phen.seed_depth_cm - 4.5) * 8
            if phen.emergence_thermal_time < target:
                return
            phen.emerged = True
            phen.emergence_date = day
            phen.effective_development_gdd = p.emergence_gdd
        else:
            phen.effective_development_gdd += daily_gdd
        phen.stage = MaizeStage.VE
        for stage, threshold in p.stage_thresholds:
            if phen.effective_development_gdd >= threshold:
                phen.stage = stage
        if phen.stage == MaizeStage.R6_MATURITY:
            phen.maturity_date = day

    def _advance_canopy(self, rid: int, solar: float, temperature: float,
                        water: float, management: ManagementStateInput,
                        biotic: BioticStateInput) -> None:
        p, phen, canopy = self.params, self.phenology.states[rid], self.canopy.states[rid]
        canopy.daily_biomass_g_m2 = 0.0
        if not phen.emerged:
            return
        canopy.initialized = True
        canopy.stand_fraction = min(canopy.stand_fraction, management.stand_fraction)
        density_ratio = canopy.planting_density_plants_m2 * canopy.stand_fraction / p.density_opt_plants_m2
        density_factor = _clip(density_ratio) * exp(-0.35 * max(0, density_ratio - 1.0))
        biotic_factor = _clip(1 - 0.35 * biotic.weed_pressure
                              - 0.30 * biotic.insect_pressure - 0.45 * biotic.disease_pressure)
        thermal_factor = _clip((temperature - 5) / 15) * _clip((42 - temperature) / 12)
        stress = water * management.nutrient_stress * biotic_factor
        canopy.cumulative_stress_days += 1 - stress
        gdd = phen.effective_development_gdd
        leaf_fraction = _clip((gdd - p.emergence_gdd) / (p.gdd_to_vt - p.emergence_gdd))
        senescence = 1.0 - 0.85 * _clip((gdd - p.gdd_to_r3) / (p.gdd_to_r6 - p.gdd_to_r3))
        target_lai = p.max_lai * leaf_fraction * senescence * sqrt(density_factor)
        canopy.lai = max(0, min(target_lai, canopy.lai + 0.24 * (0.15 + stress)))
        canopy.canopy_cover = 1 - exp(-0.55 * canopy.lai)
        apar = solar * 0.48 * canopy.canopy_cover
        canopy.cumulative_apar_mj_m2 += apar
        canopy.daily_biomass_g_m2 = apar * p.rue_g_mj_apar * stress * thermal_factor
        canopy.aboveground_biomass_g_m2 += canopy.daily_biomass_g_m2
        # Kernel-set damage near tasseling/silking persists after stress relief.
        if p.gdd_to_vt - 60 <= gdd <= p.gdd_to_r2:
            canopy.kernel_set_fraction *= 1 - 0.06 * (1 - min(water, management.nutrient_stress))
        fill_fraction = _clip((gdd - p.gdd_to_r1) / (p.gdd_to_r6 - p.gdd_to_r1))
        potential = canopy.aboveground_biomass_g_m2 * p.harvest_index * fill_fraction * canopy.kernel_set_fraction
        canopy.yield_potential_g_m2 = min(
            p.max_biological_yield_g_m2,
            max(canopy.yield_potential_g_m2, potential),
        )
        canopy.ndvi_proxy = _clip(0.18 + 0.70 * (1 - exp(-0.65 * canopy.lai))
                                 - 0.08 * (1 - stress), 0.10, 0.90)

    def _advance_drydown(self, state: MaizeYieldState, temperature: float,
                          solar: float, rain: float, wind: float) -> None:
        p = self.params
        drying = (p.base_drydown_per_day + 0.00012 * solar + 0.0003 * wind)
        drying *= _clip((temperature - 2) / 18, 0, 1.5)
        drying *= 1.0 if rain == 0 else 0.3
        rewetting = min(0.015, rain * 0.0006)
        state.grain_moisture_frac = _clip(
            state.grain_moisture_frac - drying + rewetting,
            p.min_field_grain_moisture, p.initial_mature_grain_moisture,
        )

    def settle_harvest(self, day: date,
                       harvest_actions_by_ridge: Mapping[int, HarvestActionInput]) -> None:
        ridges = self._validate_ridges(list(harvest_actions_by_ridge))
        for rid in ridges:
            state, action = self.yield_recovery.states[rid], harvest_actions_by_ridge[rid]
            _finite(action.machine_quality, "machine quality", 0, 1)
            if self.last_daily_update_day is not None and day < self.last_daily_update_day:
                raise ValueError("Maize harvest cannot precede the current simulation date")
            if state.harvested:
                raise ValueError(f"Maize ridge {rid} has already been harvested")
            if not state.r6_reached:
                raise ValueError(f"Maize ridge {rid} has not reached R6 maturity")
            if action.pass_completed and state.grain_moisture_frac > self.params.max_harvest_moisture_frac:
                raise ValueError(f"Maize ridge {rid} grain is too wet for harvest")
        for rid in ridges:
            state, action = self.yield_recovery.states[rid], harvest_actions_by_ridge[rid]
            if not action.pass_completed:
                continue
            moisture = state.grain_moisture_frac
            state.machine_loss_fraction = _clip(
                0.025 + (1 - action.machine_quality) * 0.10
                + max(0, moisture - 0.24) * 0.4 + max(0, 0.13 - moisture) * 0.3,
                0, 0.25,
            )
            recovered_dry_matter = state.biological_yield_g_m2 * (
                1 - state.field_loss_fraction
            ) * (1 - state.machine_loss_fraction)
            state.recovered_yield_g_m2_at_market_moisture = recovered_dry_matter / (
                1 - self.params.market_moisture_frac
            )
            state.harvested, state.harvest_date = True, day
            state.drying_required = moisture > self.params.drying_required_moisture
            state.tags = ["maize_harvest_settled"]
            self.phenology.states[rid].planted = False

    def biotic_stage_factors(self, ridge_id: int) -> tuple[float, float, float]:
        """Native-stage pressure modifiers, not soybean stage aliases."""
        phen = self.phenology.states[ridge_id]
        if not phen.planted:
            return (1.0, 0.15, 0.15)
        if phen.stage in (MaizeStage.PLANTED_PRE_EMERGENCE, MaizeStage.VE,
                          MaizeStage.V3, MaizeStage.V6):
            return (1.1, 0.5, 0.4)
        if phen.stage in (MaizeStage.V12, MaizeStage.VT, MaizeStage.R1_SILKING):
            return (0.65, 1.15, 0.8)
        if phen.stage == MaizeStage.R6_MATURITY:
            return (0.5, 0.6, 0.7)
        return (0.5, 1.0, 1.1)

    def _validate_ridges(self, ridge_ids: Sequence[int]) -> list[int]:
        ridges = list(ridge_ids)
        if len(set(ridges)) != len(ridges):
            raise ValueError("Maize operation contains duplicate ridge IDs")
        if any(isinstance(rid, bool) or not isinstance(rid, int)
               or rid not in self.phenology.states for rid in ridges):
            raise ValueError("Maize operation contains an unknown ridge ID")
        return ridges

    def get_state(self) -> dict[str, Any]:
        """Return a detached, JSON-native snapshot, including the daily cursor."""
        def encode(value: Any) -> Any:
            if isinstance(value, date):
                return value.isoformat()
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, dict):
                return {str(key): encode(item) for key, item in value.items()}
            if isinstance(value, list):
                return [encode(item) for item in value]
            return value
        return encode({
            "version": 1, "parameters": asdict(self.params),
            "last_daily_update_day": self.last_daily_update_day,
            "phenology": {rid: asdict(state) for rid, state in self.phenology.states.items()},
            "canopy": {rid: asdict(state) for rid, state in self.canopy.states.items()},
            "yield_recovery": {rid: asdict(state) for rid, state in self.yield_recovery.states.items()},
        })

    def load_state(self, snapshot: Mapping[str, Any]) -> None:
        """Restore a matching native snapshot, validating before replacing state."""
        if snapshot.get("version") != 1 or snapshot.get("parameters") != asdict(self.params):
            raise ValueError("Maize snapshot version or cultivar parameters do not match")
        restored: dict[str, dict[int, Any]] = {}
        for name, state_type in (("phenology", MaizePhenologyState),
                                 ("canopy", MaizeCanopyState),
                                 ("yield_recovery", MaizeYieldState)):
            states = {}
            for key, raw in snapshot[name].items():
                values = deepcopy(dict(raw))
                for field_name in ("planting_date", "emergence_date", "maturity_date",
                                   "harvest_date", "last_daily_update_day"):
                    if values.get(field_name) is not None:
                        values[field_name] = date.fromisoformat(values[field_name])
                if name == "phenology":
                    values["stage"] = MaizeStage(values["stage"])
                rid = int(key)
                if values["ridge_id"] != rid:
                    raise ValueError("Maize snapshot ridge identity does not match")
                for field_name, value in values.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        _finite(value, f"snapshot {name}.{field_name}", 0)
                states[rid] = state_type(**values)
            if set(states) != set(self.phenology.states):
                raise ValueError("Maize snapshot ridge count does not match")
            restored[name] = states
        cursor = snapshot.get("last_daily_update_day")
        cursor_day = date.fromisoformat(cursor) if cursor is not None else None
        for name, states in restored.items():
            getattr(self, name).states = states
        self.last_daily_update_day = cursor_day
