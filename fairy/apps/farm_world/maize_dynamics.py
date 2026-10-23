"""Native maize/environment bridge; environmental engine loops stay shared."""
from __future__ import annotations
from dataclasses import replace
from fairy.crops.catalog import get_crop_definition
from fairy.crops.maize import MaizeCropModel, MaizeParameters
from fairy.crops.runtime import CropStatus, PlantingEvent, CropObservationTraits, ReplantPlan
from fairy.physics import ManagementCropInput, BioticCropInput

class MaizeDynamics:
    """Native maize state, integrated through the same environmental phases."""
    def __init__(self, num_ridges: int):
        definition = get_crop_definition("maize")
        self.model = MaizeCropModel(num_ridges, planting_rules=definition.planting_rules)
        self.phenology = self.model.phenology
        self.canopy = self.model.canopy
        self.yield_recovery = self.model.yield_recovery
        self.observation_traits = CropObservationTraits(
            unstressed_root_vwc=self.model.params.unstressed_root_vwc,
            diagnosed_pest_type=None, diagnosed_disease_type=None,
        )

    def validate_planting(self, event: PlantingEvent):
        self.model.validate_planting(event)

    def plant(self, event: PlantingEvent):
        self.model.plant_event(event)

    def prepare_replant(self, event, management_states, full_replant=False):
        event = replace(event, replace_existing=True)
        self.validate_planting(event)
        if not full_replant and any(self.phenology.states[rid].emerged for rid in event.ridge_ids):
            raise ValueError("Established crop gap-filling is not supported; full_replant=True resets the complete target ridge")
        before = {rid: max(0.0, min(1.0, float(management_states[rid].stand_fraction)))
                  for rid in event.ridge_ids}
        after = {rid: 1.0 for rid in event.ridge_ids}
        return ReplantPlan(event, event.ridge_ids, before, after)

    def apply_replant(self, plan, management_states):
        self.plant(replace(plan.event, stand_fraction_by_ridge=plan.stand_after,
                           replace_existing=True))
        for rid, stand in plan.stand_after.items():
            management_states[rid].planted = True
            management_states[rid].stand_fraction = stand

    @property
    def max_recoverable_yield_g_m2(self):
        return self.model.max_recoverable_yield_g_m2

    def apply_seed_growth_overrides(self, physics, overrides):
        if overrides:
            raise ValueError("Soybean seed_growth_overrides cannot configure this crop model")

    def initialize_from_ridges(self, world, target_sim_time):
        physics = world.physics
        for ridge in world._ridges:
            rid = ridge.ridge_id
            if ridge.planted and not self.phenology.states[rid].planted:
                raise ValueError("An established crop requires a complete crop physics snapshot")
            soil = physics.soil.states[rid]
            soil.top_vwc = soil.root_vwc = float(ridge.soil_vwc)
            soil.top_temp_c = soil.root_temp_c = float(ridge.soil_temp_c)
            biotic = physics.biotic.states[rid]
            biotic.insect_pressure = float(ridge.pest_pressure_base)
            biotic.disease_pressure = float(ridge.disease_pressure_base)
            management = physics.management.states[rid]
            management.nutrient_index = float(ridge.nutrient_index)
            if ridge.planted:
                management.planted = True
                management.stand_fraction = float(ridge.stand_fraction)
        physics.last_physics_sim_time = target_sim_time

    def management_inputs(self, physics):
        return {rid: ManagementCropInput(stage=state.stage.value,
                    daily_biomass_g_m2=self.canopy.states[rid].daily_biomass_g_m2)
                for rid, state in self.phenology.states.items()}

    def biotic_inputs(self, physics):
        result = {}
        for rid, state in self.phenology.states.items():
            weed, insect, disease = self.model.biotic_stage_factors(rid)
            result[rid] = BioticCropInput(stage=state.stage.value, seed_type=state.seed_type,
                canopy_cover=self.canopy.states[rid].canopy_cover,
                weed_stage_multiplier=weed, insect_stage_multiplier=insect,
                disease_stage_multiplier=disease, aphid_diagnostics_enabled=False)
        return result

    def advance_before_biotics(self, world, physics, day, weather):
        # The maize model historically consumes pressures at the start of the
        # day. Keep that explicit phase rather than silently shifting yields.
        self.model.update_day(day, weather, physics.soil.states,
                              physics.management.states, physics.biotic.states)

    def advance_after_biotics(self, physics, day, weather, harvest_actions):
        if harvest_actions:
            self.settle_harvest(physics, day, weather, harvest_actions)

    def settle_harvest(self, physics, day, weather, harvest_actions):
        self.model.settle_harvest(day, harvest_actions)

    def project(self, ridge_id, management):
        phen = self.phenology.states[ridge_id]
        canopy = self.canopy.states[ridge_id]
        recovery = self.yield_recovery.states[ridge_id]
        planted = bool(phen.planted and not recovery.harvested)
        return CropStatus(
            current_planted=planted, emerged=bool(planted and phen.emerged),
            current_stand=float(management.stand_fraction) if planted and phen.emerged else 0.0,
            harvested=bool(recovery.harvested),
            stage="BARE" if recovery.harvested else phen.stage.value,
            days_since_planted=int(phen.days_after_planting) if planted else 0,
            grain_moisture_pct=float(recovery.grain_moisture_frac * 100) if planted and recovery.grain_moisture_frac is not None else 0.0,
            # Both numerator and denominator are biological grain dry matter;
            # the machinery bound separately includes standard-moisture water.
            yield_potential=min(1.0, max(0.0, canopy.yield_potential_g_m2 / self.model.params.max_biological_yield_g_m2)) if canopy.initialized else 0.0,
        )

    def sync_public_fields(self, world):
        physics = world.physics
        for ridge in world._ridges:
            rid = ridge.ridge_id
            management = physics.management.states[rid]
            status = self.project(rid, management)
            ridge.stand_fraction = status.current_stand
            ridge.harvested = status.harvested
            ridge.planted = status.current_planted
            ridge.growth_stage = status.stage
            ridge.days_since_planted = status.days_since_planted
            ridge.grain_moisture_pct = status.grain_moisture_pct
            if self.canopy.states[rid].initialized:
                ridge.yield_potential = status.yield_potential

    def get_state(self):
        return self.model.get_state()

    def load_state(self, state):
        self.model.load_state(state)
