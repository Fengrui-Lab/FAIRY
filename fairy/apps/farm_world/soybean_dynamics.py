"""Soybean integration and legacy field mappings.

Only these adapters translate native crop stages into common engine inputs and
legacy public fields. They do not advance soil, management or biotic engines;
those environmental transitions have a single owner in physics_orchestrator.
"""
from __future__ import annotations

from datetime import date, timedelta
from math import isfinite
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from fairy.crops.runtime import CropStatus, PlantingEvent, CropObservationTraits, ReplantPlan
from fairy.crops.soybean import SoybeanCropModel
from fairy.physics import (
    BioticCropInput, CanopyPhenologyInput, GrowthSoilInput, ManagementCropInput,
    ManagementStressInput, PhenologySoilInput, SeedType, SoybeanStage,
    YieldGrowthInput, YieldPhenologyInput, YieldStressInput, PlantingConfig,
)
from fairy.physics.biotic_pressure_engine import GrowthStage as BioticGrowthStage
from fairy.physics.canopy_biomass_engine import GrowthStage as CanopyGrowthStage, SeedType as CanopySeedType
from fairy.physics.management_effect_engine import GrowthStage as ManagementGrowthStage
from fairy.physics.yield_recovery_engine import GrowthStage as YieldGrowthStage

if TYPE_CHECKING:
    from fairy.apps.farm_world.crop_dynamics import WeatherInputs
    from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
    from fairy.apps.farm_world.farm_world_app import FarmWorldApp


class SoybeanDynamics:
    """Adapt soybean growth and report actual increments for nutrient settlement."""
    observation_traits = CropObservationTraits(unstressed_root_vwc=0.20, diagnosed_pest_type="aphid", diagnosed_disease_type="leaf_spot")

    def __init__(self, num_ridges: int) -> None:
        self.model = SoybeanCropModel(num_ridges)
        self.phenology = self.model.phenology
        self.canopy = self.model.canopy
        self.yield_recovery = self.model.yield_recovery

    def validate_planting(self, event: PlantingEvent) -> None:
        if len(set(event.ridge_ids)) != len(event.ridge_ids):
            raise ValueError("Planting contains duplicate ridge IDs")
        for rid in event.ridge_ids:
            if type(rid) is not int or rid not in self.phenology.states:
                raise ValueError("Planting contains an unknown ridge ID")
            if (self.phenology.states[rid].planted and not self.yield_recovery.states[rid].harvested
                    and not event.replace_existing):
                raise ValueError(f"Ridge {rid} already has a planted crop")
            for value in (event.depth_cm, event.stand_fraction_by_ridge[rid], event.density_by_ridge[rid]):
                if not isfinite(value) or value < 0:
                    raise ValueError("Planting inputs must be finite and nonnegative")

    def plant(self, event: PlantingEvent) -> None:
        from fairy.physics.canopy_biomass_engine import CanopyBiomassState
        from fairy.physics.yield_recovery_engine import YieldRecoveryState

        self.validate_planting(event)
        self.phenology.plant_ridges(list(event.ridge_ids), PlantingConfig(
            planting_date=event.planting_date, seed_type=_coerce_seed_type(event.seed_type) or SeedType.STANDARD,
            seed_depth_cm=event.depth_cm, planting_quality=1.0, latitude_deg=event.latitude_deg,
        ))
        for rid in event.ridge_ids:
            self.canopy.states[rid] = CanopyBiomassState(ridge_id=rid)
            self.yield_recovery.states[rid] = YieldRecoveryState(ridge_id=rid)

    def prepare_replant(self, event, management_states, full_replant=False):
        event = replace(event, replace_existing=True)
        self.validate_planting(event)
        before = {rid: max(0.0, min(1.0, float(management_states[rid].stand_fraction)))
                  for rid in event.ridge_ids}
        after = {rid: max(value, min(0.92, value + (1.0 - value) * 0.6))
                 for rid, value in before.items()}
        fresh = tuple(rid for rid in event.ridge_ids if full_replant or self.phenology.states[rid].stage in {
            SoybeanStage.NOT_PLANTED, SoybeanStage.PLANTED_PRE_EMERGENCE})
        return ReplantPlan(event, fresh, before, after)

    def apply_replant(self, plan, management_states):
        if plan.fresh_ridge_ids:
            event = replace(plan.event, ridge_ids=plan.fresh_ridge_ids,
                            stand_fraction_by_ridge=plan.stand_after, replace_existing=True)
            self.validate_planting(event)
            self.plant(event)
        for rid, stand in plan.stand_after.items():
            state = management_states[rid]
            state.planted = True
            state.stand_fraction = stand
            state.planting_quality = max(state.planting_quality, stand)
            if rid not in plan.fresh_ridge_ids and "partial_replant_stand_recovery" not in state.tags:
                state.tags.append("partial_replant_stand_recovery")

    @property
    def max_recoverable_yield_g_m2(self):
        # Retain the original machinery reservation while also covering the
        # current crop's actual potential; soybean has no biological hard cap.
        return max(245000.0 / (268.0 * 1.1),
                   *(state.yield_potential_g_m2 for state in self.canopy.states.values()),
                   *(state.biological_yield_g_m2 for state in self.yield_recovery.states.values()))

    def apply_seed_growth_overrides(self, physics, overrides):
        from dataclasses import replace
        for seed_name, raw_updates in overrides.items():
            try:
                seed_type = CanopySeedType(str(seed_name))
            except ValueError:
                seed_type = CanopySeedType[str(seed_name)]
            current = self.canopy.seed_params.get(seed_type)
            if current is None:
                raise ValueError(f"No canopy growth parameters for seed {seed_name!r}")
            valid_fields = set(current.__dataclass_fields__)
            updates = {}
            for key, value in raw_updates.items():
                if key not in valid_fields:
                    raise ValueError(f"Unknown seed growth parameter {key!r} for seed {seed_name!r}")
                updates[key] = float(value)
            self.canopy.seed_params[seed_type] = replace(current, **updates)

    def initialize_from_ridges(self, world, target_sim_time):
        _initialize_soybean_from_ridges(world, target_sim_time)

    def management_inputs(self, physics: FarmPhysicsState) -> dict[int, ManagementCropInput]:
        # Today's growth is computed after management and soil. None explicitly
        # defers uptake; the orchestrator settles the increment returned below.
        # A numeric zero would incorrectly declare that no biomass was grown.
        return {
            rid: ManagementCropInput(
                stage=ManagementGrowthStage(state.stage.value),
                daily_biomass_g_m2=None,
            )
            for rid, state in self.phenology.states.items()
        }

    def biotic_inputs(self, physics):
        return {rid: BioticCropInput(stage=BioticGrowthStage(state.stage.value),
                                    canopy_cover=self.canopy.states[rid].canopy_cover,
                                    seed_type=state.seed_type.value if state.seed_type is not None else None)
                for rid, state in self.phenology.states.items()}

    def advance_before_biotics(
        self,
        farm_world_app: FarmWorldApp,
        physics: FarmPhysicsState,
        day: date,
        weather: WeatherInputs,
    ) -> dict[int, float]:
        for rid, grain in self.yield_recovery.states.items():
            if grain.harvested:
                self.phenology.states[rid].planted = False
        # 4. Phenology consumes weather + soil.
        phenology_soil_inputs = {
            rid: PhenologySoilInput(
                top_temp_c=physics.soil.states[rid].top_temp_c,
                top_vwc=physics.soil.states[rid].top_vwc,
                water_stress=_compute_water_stress(physics.soil.states[rid].root_vwc),
            )
            for rid in physics.soil.states
        }
        phenology_results = physics.phenology.update_day(
            weather=weather["phenology"],
            soil_by_ridge=phenology_soil_inputs,
        )

        _apply_post_planting_cold_stand_penalty(physics, weather)

        # 5. Initialize canopy state for ridges that just emerged.
        for result in phenology_results:
            if result.emerged and not self.yield_recovery.states[result.ridge_id].harvested:
                canopy_state = physics.canopy.states[result.ridge_id]
                if not canopy_state.initialized:
                    phen_state = physics.phenology.states[result.ridge_id]
                    seed_type_value = (
                        phen_state.seed_type.value
                        if phen_state.seed_type is not None
                        else SeedType.STANDARD.value
                    )
                    stand_fraction = (
                        physics.management.states[result.ridge_id].stand_fraction or 1.0
                    )
                    physics.canopy.initialize_ridges(
                        [result.ridge_id],
                        seed_type=CanopySeedType(seed_type_value),
                        initial_stand_fraction=stand_fraction,
                    )

        # 6. Canopy / biomass.
        canopy_phenology_inputs = {
            rid: CanopyPhenologyInput(
                stage=(CanopyGrowthStage.NOT_PLANTED if self.yield_recovery.states[rid].harvested
                       else CanopyGrowthStage(physics.phenology.states[rid].stage.value)),
                development_fraction=_phenology_development_fraction(
                    physics.phenology.states[rid],
                    getattr(physics.phenology, "seed_type_params", None),
                ),
            )
            for rid in physics.phenology.states
        }
        canopy_soil_inputs = {
            rid: GrowthSoilInput(
                water_stress=_compute_water_stress(physics.soil.states[rid].root_vwc),
                root_vwc=physics.soil.states[rid].root_vwc,
            )
            for rid in physics.soil.states
        }
        canopy_management_inputs = {
            rid: ManagementStressInput(
                nutrient_stress=physics.management.states[rid].nutrient_stress,
                biotic_stress=_compute_biotic_stress(physics.biotic.states[rid]),
                stand_fraction=physics.management.states[rid].stand_fraction or 1.0,
                planting_density_plants_m2=_ridge_planting_density_plants_m2(
                    farm_world_app,
                    rid,
                ),
                weed_pressure=physics.biotic.states[rid].weed_pressure,
                insect_pressure=physics.biotic.states[rid].insect_pressure,
                disease_pressure=physics.biotic.states[rid].disease_pressure,
            )
            for rid in physics.management.states
        }
        # Take the baseline after emergence initialization: the seed-funded
        # initial biomass is not new growth drawing on the soil nutrient proxy.
        # Differences retain native precision, unlike rounded diagnostic results.
        biomass_before = {
            rid: state.aboveground_biomass_g_m2 for rid, state in self.canopy.states.items()
        }
        physics.canopy.update_day(
            weather=weather["canopy"],
            phenology_by_ridge=canopy_phenology_inputs,
            soil_by_ridge=canopy_soil_inputs,
            management_by_ridge=canopy_management_inputs,
        )
        return {
            rid: state.aboveground_biomass_g_m2 - biomass_before[rid]
            for rid, state in self.canopy.states.items()
        }

    def advance_after_biotics(self, physics, day, weather, harvest_actions):
        pending_harvest = harvest_actions
        # 8. Yield recovery (cheap; ignores ridges not yet at R5+).
        yield_phenology = {
            rid: YieldPhenologyInput(
                stage=YieldGrowthStage(physics.phenology.states[rid].stage.value),
                maturity_date=physics.phenology.states[rid].maturity_date,
            )
            for rid in physics.phenology.states
        }
        yield_growth = {
            rid: YieldGrowthInput(
                yield_potential_g_m2=state.yield_potential_g_m2,
                aboveground_biomass_g_m2=state.aboveground_biomass_g_m2,
            )
            for rid, state in physics.canopy.states.items()
        }
        yield_stress = {
            rid: YieldStressInput(
                disease_severity=physics.biotic.states[rid].disease_pressure,
                insect_pod_damage=physics.biotic.states[rid].insect_pressure,
            )
            for rid in physics.biotic.states
        }
        physics.yield_recovery.update_day(
            weather=weather["yield"],
            phenology_by_ridge=yield_phenology,
            growth_by_ridge=yield_growth,
            stress_by_ridge=yield_stress,
            harvest_actions_by_ridge=pending_harvest,
        )
        for rid in pending_harvest:
            if self.yield_recovery.states[rid].harvested:
                self.phenology.states[rid].planted = False

    def settle_harvest(self, physics, day, weather, harvest_actions):
        physics.yield_recovery.settle_harvest(
            weather=weather["yield"],
            phenology_by_ridge={
                rid: YieldPhenologyInput(
                    stage=YieldGrowthStage(physics.phenology.states[rid].stage.value),
                    maturity_date=physics.phenology.states[rid].maturity_date,
                )
                for rid in harvest_actions
            },
            growth_by_ridge={
                rid: YieldGrowthInput(
                    yield_potential_g_m2=physics.canopy.states[rid].yield_potential_g_m2,
                )
                for rid in harvest_actions
            },
            stress_by_ridge={
                rid: YieldStressInput(
                    disease_severity=physics.biotic.states[rid].disease_pressure,
                    insect_pod_damage=physics.biotic.states[rid].insect_pressure,
                )
                for rid in harvest_actions
            },
            harvest_actions_by_ridge=harvest_actions,
        )
        for rid in harvest_actions:
            if self.yield_recovery.states[rid].harvested:
                self.phenology.states[rid].planted = False

    def project(self, ridge_id, management):
        phen = self.phenology.states[ridge_id]
        canopy = self.canopy.states[ridge_id]
        grain = self.yield_recovery.states[ridge_id]
        planted = bool(phen.planted and not grain.harvested)
        return CropStatus(
            current_planted=planted, emerged=bool(planted and phen.emerged),
            current_stand=float(management.stand_fraction) if planted and phen.emerged else 0.0,
            harvested=bool(grain.harvested),
            stage="BARE" if grain.harvested else _map_soybean_stage_to_legacy(phen.stage),
            days_since_planted=int(phen.days_after_planting) if planted else 0,
            grain_moisture_pct=float(grain.grain_moisture_frac * 100) if planted and grain.grain_moisture_frac is not None else 0.0,
            yield_potential=max(0.0, min(1.0, canopy.yield_potential_g_m2 / 350.0)) if canopy.initialized else 0.0,
        )

    def sync_public_fields(self, farm_world_app):
        # Legacy field names/rounding stay at this explicit compatibility boundary.
        physics = farm_world_app.physics
        for ridge in farm_world_app._ridges:
            rid = ridge.ridge_id
            phen = physics.phenology.states[rid]
            if phen.planted:
                ridge.planted = True
                ridge.days_since_planted = int(phen.days_after_planting)
                ridge.growth_stage = _map_soybean_stage_to_legacy(phen.stage)

            canopy = physics.canopy.states[rid]
            if canopy.initialized:
                # Leave ridge.ndvi alone — that field is the agent-visible last
                # observation populated by drone/sensor tools through
                # ObservationModel. Truth is in canopy.ndvi_proxy and stays
                # behind the observation boundary.
                ridge.yield_potential = float(canopy.yield_potential_g_m2 / 350.0)
                ridge.yield_potential = max(0.0, min(1.0, ridge.yield_potential))

            yld = physics.yield_recovery.states[rid]
            ridge.harvested = bool(yld.harvested)
            if yld.grain_moisture_frac is not None:
                ridge.grain_moisture_pct = float(yld.grain_moisture_frac * 100.0)
            if yld.harvested:
                ridge.stand_fraction = 0.0
                ridge.planted = False
                ridge.growth_stage = "BARE"
                ridge.days_since_planted = 0
                ridge.grain_moisture_pct = 0.0
            elif phen.planted:
                mgmt = physics.management.states[rid]
                ridge.stand_fraction = float(mgmt.stand_fraction)

    def get_state(self):
        return self.model.get_state()

    def load_state(self, state):
        self.model.load_state(state)

def _initialize_soybean_from_ridges(
    farm_world_app: "FarmWorldApp", target_sim_time: float
) -> None:
    """Seed engine state from the ridge values the scenario set up.

    Most baseline scenarios (irrigation, planting, etc.) configure
    ``r.soil_vwc``, ``r.soil_temp_c``, ``r.growth_stage``, ``r.planted``,
    ``r.days_since_planted``, ``r.seed_type`` directly in
    ``_configure_initial_state``. We mirror those into the engines so the
    first daily tick starts from the scenario's intended world state, not
    from engine defaults (0.25 VWC, NOT_PLANTED).
    """
    physics = farm_world_app.physics
    physics.last_physics_sim_time = target_sim_time
    today = farm_world_app.simulation_date(target_sim_time)

    for ridge in farm_world_app._ridges:
        rid = ridge.ridge_id

        # Soil layer.
        soil_state = physics.soil.states[rid]
        soil_state.top_vwc = float(ridge.soil_vwc)
        soil_state.root_vwc = float(ridge.soil_vwc)
        soil_state.top_temp_c = float(ridge.soil_temp_c)
        soil_state.root_temp_c = float(ridge.soil_temp_c)

        # Phenology layer.
        # Skip if the engine already has explicit planting state (i.e., a
        # previous plant_seeds call has already initialised phenology). This
        # preserves plant_seeds's PLANTED_PRE_EMERGENCE intent against the
        # legacy growth_stage="VE" that set_ridge_planted writes.
        phen_state = physics.phenology.states[rid]
        if ridge.planted and not phen_state.planted:
            phen_state.planted = True
            phen_state.planting_date = today - timedelta(
                days=int(ridge.days_since_planted)
            )
            phen_state.seed_type = _coerce_seed_type(ridge.seed_type)
            phen_state.days_after_planting = int(ridge.days_since_planted)
            mapped = _map_legacy_growth_stage_to_soybean_stage(ridge.growth_stage)
            phen_state.stage = mapped
            phen_state.emerged = mapped not in {
                SoybeanStage.NOT_PLANTED,
                SoybeanStage.PLANTED_PRE_EMERGENCE,
            }
            if phen_state.emerged and phen_state.emergence_date is None:
                phen_state.emergence_date = phen_state.planting_date
            # Seed effective_development_gdd so the engine's
            # _stage_from_effective_gdd doesn't snap back to VE on the next
            # daily tick. We pick the stage's threshold fraction × gdd_to_r8.
            seed_type = phen_state.seed_type
            if (
                seed_type is not None
                and seed_type in physics.phenology.seed_type_params
            ):
                seed_params = physics.phenology.seed_type_params[seed_type]
                fraction = physics.phenology.params.stage_fraction_thresholds.get(
                    mapped, 0.0
                )
                phen_state.effective_development_gdd = float(
                    seed_params.gdd_to_r8 * fraction
                )
                phen_state.accumulated_gdd = max(
                    phen_state.accumulated_gdd,
                    phen_state.effective_development_gdd,
                )
                if mapped == SoybeanStage.R8 and phen_state.maturity_date is None:
                    phen_state.maturity_date = phen_state.planting_date

        # Biotic baseline reflects whatever the scenario configured for pest
        # outbreaks via _configure_initial_state (carries through r.pest_pressure_base).
        biotic_state = physics.biotic.states[rid]
        biotic_state.insect_pressure = max(
            biotic_state.insect_pressure, float(ridge.pest_pressure_base)
        )
        biotic_state.disease_pressure = max(
            biotic_state.disease_pressure, float(ridge.disease_pressure_base)
        )

        # Management bridge: scenarios set r.nutrient_index / r.stand_fraction
        # to describe anomaly blocks. Mirror them into ManagementEffectState
        # so observation tools (canopy NDVI, robot inspect) see the truth.
        # Also set mgmt.planted=True for planted ridges — robot.inspect_emergence
        # only surfaces stand_fraction when mgmt.planted is True.
        mgmt_state = physics.management.states.get(rid)
        if mgmt_state is not None:
            mgmt_state.nutrient_index = float(ridge.nutrient_index)
            if ridge.planted:
                mgmt_state.planted = True
                mgmt_state.stand_fraction = float(ridge.stand_fraction)

        # Canopy initialization for already-emerged crops in the seeded
        # scenario state. Use the phenology engine's stage as the source of
        # truth: if phenology says PLANTED_PRE_EMERGENCE (e.g. a freshly
        # plant_seeds-ed ridge), skip canopy init even though the legacy
        # ridge.growth_stage may temporarily say "VE". Daily ticks will init
        # canopy when emergence actually happens.
        canopy_state = physics.canopy.states[rid]
        if ridge.planted and not canopy_state.initialized:
            phen_stage = phen_state.stage
            if phen_stage in {
                SoybeanStage.NOT_PLANTED,
                SoybeanStage.PLANTED_PRE_EMERGENCE,
            }:
                # Engine has authoritative pre-emergence state — don't init.
                pass
            else:
                # Engine already at a post-emergence stage (or this ridge had
                # planted=True from _configure_initial_state and we just set
                # the engine stage from ridge.growth_stage).
                seed_type = _coerce_seed_type(ridge.seed_type) or SeedType.STANDARD
                physics.canopy.initialize_ridges(
                    [rid],
                    seed_type=CanopySeedType(seed_type.value),
                    initial_stand_fraction=float(ridge.stand_fraction),
                )
                # Fast-forward LAI to a realistic value for the current stage.
                # initialize_ridges always sets LAI ≈ 0.05 (VE-stage); for
                # scenarios that start at R5/R6 we need a mature canopy so
                # ET, NDVI, and biomass observations are sensible, and so
                # post-irrigation soil VWC actually rises (under LAI=0.05
                # the soil engine treats the field as bare and high ET cancels
                # any irrigation gain).
                _fast_forward_canopy_lai_for_stage(canopy_state, phen_stage)

        # Canopy NDVI bridge: scenarios that pre-seed an anomaly NDVI via
        # r.ndvi_proxy (>=0) overwrite the engine's default LAI-derived value.
        if ridge.ndvi_proxy >= 0.0 and canopy_state.initialized:
            canopy_state.ndvi_proxy = float(ridge.ndvi_proxy)

_STAGE_LAI_TARGETS = {
    SoybeanStage.VE: 0.10,
    SoybeanStage.VC: 0.30,
    SoybeanStage.V1: 0.60,
    SoybeanStage.V2: 1.00,
    SoybeanStage.V3: 1.60,
    SoybeanStage.V4_PLUS: 2.50,
    SoybeanStage.R1: 3.50,
    SoybeanStage.R3: 4.00,
    SoybeanStage.R5: 4.50,
    SoybeanStage.R6: 4.50,
    SoybeanStage.R7: 4.00,
    SoybeanStage.R8: 1.50,
}

def _fast_forward_canopy_lai_for_stage(state, stage: SoybeanStage) -> None:
    """Set canopy LAI/cover/biomass/NDVI to typical values for a phenology stage.

    initialize_ridges always emits a VE-stage canopy (LAI ≈ 0.05). Scenarios
    that start mid-season need the canopy "fast-forwarded" so the soil ET
    model treats the ridge correctly and observation tools return sensible
    NDVI/biomass values from day 0.
    """
    target_lai = _STAGE_LAI_TARGETS.get(stage)
    if target_lai is None or target_lai <= state.lai:
        return
    state.lai = float(target_lai)
    # Approximate canopy cover from LAI (Beer-Lambert with k≈0.6).
    import math

    state.canopy_cover = float(min(0.95, 1.0 - math.exp(-0.6 * target_lai)))
    # Aboveground biomass scales roughly linearly with LAI in vegetative,
    # plateaus in reproductive. Use a coarse proxy.
    state.aboveground_biomass_g_m2 = float(target_lai * 180.0)
    # NDVI saturates near 0.9 at high LAI.
    state.ndvi_proxy = float(min(0.92, 0.20 + 0.155 * target_lai))

def _ridge_planting_density_plants_m2(
    farm_world_app: "FarmWorldApp",
    ridge_id: int,
) -> float:
    """Return realized planting density for canopy growth in plants/m2."""
    try:
        ridge = farm_world_app._ridges[ridge_id]
    except (AttributeError, IndexError):
        return 40.0

    ridge_width_m = float(getattr(farm_world_app, "ridge_width_m", 1.1) or 1.1)
    if ridge_width_m <= 0.0:
        return 40.0

    if ridge.seeds_planted > 0:
        from fairy.apps.farm_world.farm_world_app import FIELD_LENGTH_M

        ridge_area_m2 = FIELD_LENGTH_M * ridge_width_m
        if ridge_area_m2 > 0.0:
            return max(0.0, float(ridge.seeds_planted) / ridge_area_m2)

    if ridge.seed_spacing_cm is not None and ridge.seed_spacing_cm > 0.0:
        from fairy.apps.farm_world.farm_world_app import ROWS_PER_RIDGE

        seed_spacing_m = float(ridge.seed_spacing_cm) / 100.0
        return max(0.0, ROWS_PER_RIDGE / (ridge_width_m * seed_spacing_m))

    return 40.0

def _coerce_seed_type(seed_value: str | None) -> SeedType | None:
    if seed_value is None:
        return None
    try:
        return SeedType(seed_value)
    except ValueError:
        return SeedType.STANDARD

def _map_legacy_growth_stage_to_soybean_stage(legacy_stage: str) -> SoybeanStage:
    """Map farm_world.models.GrowthStage values to phenology SoybeanStage.

    Legacy farm_world enum: BARE, VE, V1..V8, R1..R8.
    SoybeanStage:           NOT_PLANTED, PLANTED_PRE_EMERGENCE, VE, VC, V1..V3,
                            V4_PLUS, R1..R8 (R values use longer string codes).
    """
    if not legacy_stage or legacy_stage == "bare":
        return SoybeanStage.NOT_PLANTED
    direct_map = {
        "VE": SoybeanStage.VE,
        "VC": SoybeanStage.VC,
        "V1": SoybeanStage.V1,
        "V2": SoybeanStage.V2,
        "V3": SoybeanStage.V3,
    }
    if legacy_stage in direct_map:
        return direct_map[legacy_stage]
    if legacy_stage.startswith("V"):
        return SoybeanStage.V4_PLUS
    r_map = {
        "R1": SoybeanStage.R1,
        "R3": SoybeanStage.R3,
        "R5": SoybeanStage.R5,
        "R6": SoybeanStage.R6,
        "R7": SoybeanStage.R7,
        "R8": SoybeanStage.R8,
    }
    if legacy_stage in r_map:
        return r_map[legacy_stage]
    if legacy_stage in {"R2"}:
        return SoybeanStage.R1
    if legacy_stage in {"R4"}:
        return SoybeanStage.R3
    return SoybeanStage.NOT_PLANTED

def _map_soybean_stage_to_legacy(stage: SoybeanStage) -> str:
    """Inverse mapping for compatibility shadowing."""
    if stage == SoybeanStage.NOT_PLANTED:
        return "bare"
    if stage == SoybeanStage.PLANTED_PRE_EMERGENCE:
        return "bare"
    if stage == SoybeanStage.V4_PLUS:
        return "V4"
    legacy_map = {
        SoybeanStage.VE: "VE",
        SoybeanStage.VC: "VE",
        SoybeanStage.V1: "V1",
        SoybeanStage.V2: "V2",
        SoybeanStage.V3: "V3",
        SoybeanStage.R1: "R1",
        SoybeanStage.R3: "R3",
        SoybeanStage.R5: "R5",
        SoybeanStage.R6: "R6",
        SoybeanStage.R7: "R7",
        SoybeanStage.R8: "R8",
    }
    return legacy_map.get(stage, "bare")

def _apply_post_planting_cold_stand_penalty(
    physics: "FarmPhysicsState", weather: dict[str, Any]
) -> None:
    """Reduce final stand when cold/wet weather hits before emergence."""
    phenology_weather = weather["phenology"]
    soil_weather = weather["soil"]
    day = phenology_weather.day
    rain_mm = float(getattr(soil_weather, "rain_mm", 0.0) or 0.0)
    min_temp_c = float(getattr(phenology_weather, "air_temp_min_c", 0.0) or 0.0)

    for rid, mgmt_state in physics.management.states.items():
        phen_state = physics.phenology.states.get(rid)
        soil_state = physics.soil.states.get(rid)
        if phen_state is None or soil_state is None:
            continue
        if (
            not mgmt_state.planted
            or not phen_state.planted
            or phen_state.emerged
            or phen_state.planting_date is None
        ):
            continue

        days_after_planting = (day - phen_state.planting_date).days + 1
        if days_after_planting < 1 or days_after_planting > 7:
            continue

        top_temp_c = float(soil_state.top_temp_c)
        top_vwc = float(soil_state.top_vwc)
        penalty = 0.012 * max(0.0, 10.0 - top_temp_c)
        penalty += 0.035 * max(0.0, -min_temp_c)
        if top_temp_c < 10.0 and top_vwc > 0.32:
            penalty += 0.03
        penalty += 0.002 * max(0.0, rain_mm - 10.0)
        if penalty <= 0.0:
            continue

        old_stand = float(mgmt_state.stand_fraction or 1.0)
        new_stand = max(0.35, min(1.0, old_stand - penalty))
        if new_stand >= old_stand:
            continue

        mgmt_state.stand_fraction = new_stand
        mgmt_state.planting_quality = min(
            float(mgmt_state.planting_quality or 1.0), new_stand
        )
        phen_state.planting_quality = min(
            float(phen_state.planting_quality or 1.0), new_stand
        )
        mgmt_state.tags.append(
            f"post_plant_cold_stand_penalty:day={day.isoformat()},stand={new_stand:.3f}"
        )

def _phenology_development_fraction(
    state: Any,
    seed_type_params: Any | None = None,
) -> float:
    """Development fraction in [0, 1] for canopy/yield fill curves."""
    seed_type = getattr(state, "seed_type", None)
    params = None
    if seed_type_params is not None and seed_type is not None:
        params = seed_type_params.get(seed_type)
    if params is not None:
        gdd_to_r8 = float(getattr(params, "gdd_to_r8", 0.0) or 0.0)
        if gdd_to_r8 > 0.0:
            effective_gdd = float(
                getattr(state, "effective_development_gdd", 0.0) or 0.0
            )
            return max(0.0, min(1.0, effective_gdd / gdd_to_r8))

    stage_progress = {
        SoybeanStage.NOT_PLANTED: 0.0,
        SoybeanStage.PLANTED_PRE_EMERGENCE: 0.0,
        SoybeanStage.VE: 0.05,
        SoybeanStage.VC: 0.08,
        SoybeanStage.V1: 0.12,
        SoybeanStage.V2: 0.18,
        SoybeanStage.V3: 0.25,
        SoybeanStage.V4_PLUS: 0.40,
        SoybeanStage.R1: 0.55,
        SoybeanStage.R3: 0.70,
        SoybeanStage.R5: 0.82,
        SoybeanStage.R6: 0.90,
        SoybeanStage.R7: 0.95,
        SoybeanStage.R8: 1.0,
    }
    return stage_progress.get(state.stage, 0.0)

def _compute_water_stress(root_vwc: float) -> float:
    """0–1 multiplier where 1 is no water stress, 0 is severe stress.

    Fixed ramp (wilting 0.12 → “unstressed” 0.22) is historical Farm-ARE canopy
    behaviour. ``SoilEngine`` continues to use ``SoilParameters.wilting_point_vwc``
    / ``water_stress_vwc`` for its internal transpiration factor; keeping this
    mapping unchanged avoids silent yield shifts when scenarios override soil
    hydraulics for water-balance realism (e.g. Tangyan5 Heilongjiang priors).
    """
    if root_vwc >= 0.18:
        return 1.0
    if root_vwc <= 0.12:
        return 0.0
    return (root_vwc - 0.12) / (0.18 - 0.12)

def _compute_biotic_stress(biotic_state: Any) -> float:
    """Translate biotic pressures to a 0–1 growth multiplier."""
    weighted = (
        0.28 * biotic_state.weed_pressure
        + 0.32 * biotic_state.insect_pressure
        + 0.45 * biotic_state.disease_pressure
    )
    return max(0.35, 1.0 - weighted)
