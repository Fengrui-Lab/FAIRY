"""
Physics orchestrator — single integration site for the seven engines.

Daily-tick order (verbatim from
scenario_farm_world_physics/physics_action_tick_integration_guide.md
section "Time advancement should run world ticks"):

  1. apply weather for the day
  2. apply pending management water/nutrient/treatment inputs
  3. update soil moisture and soil temperature
  4. update phenology using weather + soil
  5. initialize canopy growth if emergence occurred
  6. update canopy/biomass using weather + phenology + soil + stress
  7. update biotic pressure using weather + crop stage + canopy + treatment residuals
  8. update yield/recovery if R8 or harvested
  9. generate or update observation caches
  10. sync compatibility fields

Contract:
    advance_physics_time(farm_world_app, target_sim_time) is idempotent.
    It reads farm_world_app.physics.last_physics_sim_time and runs one daily
    tick per crossed UTC date boundary up to target_sim_time. Sub-daily lag
    (no boundary crossed) triggers an immediate-soil-input update when
    irrigation actions are queued. After running, last_physics_sim_time is
    set to target_sim_time, the action queues are drained, and compatibility
    shadows on RidgeState are refreshed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import TYPE_CHECKING, Any

from fairy.physics import (
    BioticCropInput,
    BioticSoilInput,
    BioticWeatherInput,
    CanopyPhenologyInput,
    GrowthSoilInput,
    GrowthWeatherInput,
    ManagementCropInput,
    ManagementSoilInput,
    ManagementStressInput,
    ManagementWeatherInput,
    PhenologySoilInput,
    PhenologyWeatherInput,
    SeedType,
    SoilWeatherInput,
    SoybeanStage,
    YieldGrowthInput,
    YieldPhenologyInput,
    YieldStressInput,
    YieldWeatherInput,
)
from fairy.physics.biotic_pressure_engine import (
    GrowthStage as BioticGrowthStage,
)
from fairy.physics.canopy_biomass_engine import (
    GrowthStage as CanopyGrowthStage,
)
from fairy.physics.canopy_biomass_engine import (
    SeedType as CanopySeedType,
)
from fairy.physics.management_effect_engine import (
    GrowthStage as ManagementGrowthStage,
)
from fairy.physics.yield_recovery_engine import (
    GrowthStage as YieldGrowthStage,
)

if TYPE_CHECKING:
    from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
    from fairy.apps.farm_world.farm_world_app import FarmWorldApp
    from fairy.apps.farm_world.weather_app import WeatherApp


_SECONDS_PER_DAY: float = 86400.0
_DEFAULT_DIURNAL_RANGE_C: float = 5.0
_W_PER_M2_TO_MJ_PER_M2_PER_DAY: float = 0.0864  # 1 W/m^2 * 86400 s * 1e-6


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def advance_physics_time(
    farm_world_app: "FarmWorldApp", target_sim_time: float, *, weather_inputs_provider=None
) -> dict[str, Any]:
    """Advance physics to ``target_sim_time``.

    Idempotent. Returns a status dict describing how many daily ticks ran
    and whether a sub-daily soil update was applied.
    """
    physics = farm_world_app._physics
    if physics is None or not physics.engines_active:
        return {"status": "skipped", "reason": "physics_inactive"}
    physics.ridge_width_m = float(farm_world_app.ridge_width_m)
    physics.field_length_m = float(farm_world_app.field_length_m)

    weather_app = _find_weather_app(farm_world_app)
    simulation_timezone = farm_world_app.simulation_timezone

    # First call seeds engine state from the scenario's initial ridge values.
    if physics.last_physics_sim_time is None:
        if _uses_registered_crop(physics):
            physics.crop.initialize_from_ridges(farm_world_app, target_sim_time)
        else:
            _seed_physics_from_ridges(farm_world_app, target_sim_time)
        subdaily_first_call = False
        # If a tool queued actions before the first advance_physics_time call
        # (e.g. plant_seeds calls advance after queuing), apply them now via
        # the sub-daily injection so the next state read reflects the action.
        if (
            physics.pending_management_actions_by_ridge
            or physics.pending_treatments_by_ridge
            or physics.pending_harvest_actions_by_ridge
        ):
            subdaily_first_call = _run_subdaily_injection(
                physics, weather_app, target_sim_time, weather_inputs_provider, simulation_timezone=simulation_timezone
            )
        sync_compatibility_fields_from_physics(farm_world_app)
        if weather_app is not None and weather_inputs_provider is None:
            avg_vwc = _avg_top_vwc(physics)
            if avg_vwc is not None:
                weather_app.set_avg_soil_vwc(avg_vwc)
        return {
            "status": "initialized",
            "day_ticks_run": 0,
            "subdaily_irrigation": subdaily_first_call,
            "last_physics_sim_time": target_sim_time,
        }

    elapsed = target_sim_time - physics.last_physics_sim_time
    if elapsed < 0:
        return {"status": "noop", "day_ticks_run": 0, "elapsed_s": elapsed}
    has_pending = bool(physics.pending_management_actions_by_ridge
                       or physics.pending_treatments_by_ridge
                       or physics.pending_harvest_actions_by_ridge)
    if elapsed == 0 and not has_pending:
        return {"status": "noop", "day_ticks_run": 0, "elapsed_s": elapsed}

    days_to_run = _dates_between(physics.last_physics_sim_time, target_sim_time, simulation_timezone=simulation_timezone)

    subdaily_irrigation_applied = False
    if not days_to_run and has_pending:
        subdaily_irrigation_applied = _run_subdaily_injection(
            physics, weather_app, target_sim_time, weather_inputs_provider,
            simulation_timezone=simulation_timezone)

    completed_calendar_day = (getattr(physics, "scenario_metadata", None) or {}).get(
        "daily_settlement"
    ) == "completed_calendar_day"
    for boundary_day in days_to_run:
        # Formal reference worlds settle yesterday only after its local
        # midnight has passed. Historical scenarios keep their existing
        # boundary-date convention unless they explicitly opt in.
        tick_day = boundary_day - timedelta(days=1) if completed_calendar_day else boundary_day
        inputs = weather_inputs_provider(tick_day, True) if weather_inputs_provider else None
        _run_daily_tick(farm_world_app, physics, weather_app, tick_day, inputs)

    if completed_calendar_day:
        current_day = datetime.fromtimestamp(target_sim_time, tz=simulation_timezone).date()
        if "wofost_scenario_events" in (getattr(physics, "scenario_metadata", None) or {}):
            from fairy.scenarios.wofost_events import apply_scenario_events_for_day

            apply_scenario_events_for_day(farm_world_app, current_day)
        # Crop/soil states describe the completed day's boundary, while the
        # public station and forecast must describe today's working conditions.
        # Refreshing pinned inputs does not integrate another biological day.
        if weather_inputs_provider is None:
            _build_weather_inputs(weather_app, current_day, physics=physics, advance_weather=False)

    physics.last_physics_sim_time = target_sim_time
    sync_compatibility_fields_from_physics(farm_world_app)
    if weather_app is not None and weather_inputs_provider is None:
        avg_vwc = _avg_top_vwc(physics)
        if avg_vwc is not None:
            weather_app.set_avg_soil_vwc(avg_vwc)

    return {
        "status": "advanced",
        "day_ticks_run": len(days_to_run),
        "subdaily_irrigation": subdaily_irrigation_applied,
        "elapsed_s": elapsed,
        "last_physics_sim_time": target_sim_time,
    }


# ---------------------------------------------------------------------------
# Helpers — date arithmetic
# ---------------------------------------------------------------------------


def _dates_between(t_from: float, t_to: float, *, simulation_timezone=timezone.utc) -> list[date]:
    """Return the list of UTC dates strictly after t_from and up to t_to.

    For the irrigation scenario starting at 07:00 UTC and waiting 2 hours
    to 09:00 same day, this returns []. For a 26-hour wait across midnight,
    it returns [next_day].
    """
    if t_to <= t_from:
        return []
    d_from = datetime.fromtimestamp(t_from, tz=simulation_timezone).date()
    d_to = datetime.fromtimestamp(t_to, tz=simulation_timezone).date()
    if d_to <= d_from:
        return []
    out: list[date] = []
    current = d_from
    while current < d_to:
        current = current + timedelta(days=1)
        out.append(current)
    return out


# ---------------------------------------------------------------------------
# Helpers — initial seeding from scenario state
# ---------------------------------------------------------------------------


def _seed_physics_from_ridges(
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
    today = datetime.fromtimestamp(target_sim_time, tz=farm_world_app.simulation_timezone).date()

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
            phen_state.seed_type = _coerce_seed_type(
                ridge.seed_type or farm_world_app.crop_profile.seed_type
            )
            phen_state.days_after_planting = int(ridge.days_since_planted)
            if _uses_native_maize(physics):
                error = farm_world_app.validate_seed_for_crop(ridge.seed_type)
                if error:
                    raise ValueError(error)
                mapped = SoybeanStage(ridge.growth_stage)
            elif physics.crop_type == "soybean":
                mapped = _map_legacy_growth_stage_to_soybean_stage(ridge.growth_stage)
            else:
                from fairy.physics.crop_physiology import compatibility_stage

                mapped = compatibility_stage(physics.crop_profile, ridge.growth_stage)
                if mapped is None:
                    mapped = SoybeanStage.PLANTED_PRE_EMERGENCE
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
                if physics.crop_type != "soybean" and phen_state.emerged:
                    from fairy.physics.crop_physiology import crop_stage_fraction

                    fraction = max(fraction, crop_stage_fraction(
                        physics.crop_profile, ridge.growth_stage
                    ) or 0.0)
                phen_state.effective_development_gdd = float(
                    seed_params.gdd_to_r8 * fraction
                )
                phen_state.accumulated_gdd = max(
                    phen_state.accumulated_gdd,
                    phen_state.effective_development_gdd,
                )
                if mapped == SoybeanStage.R8 and phen_state.maturity_date is None:
                    phen_state.maturity_date = (
                        phen_state.planting_date
                        if physics.crop_type == "soybean" else
                        min(today, phen_state.planting_date + timedelta(
                            days=physics.crop_profile.stage_thresholds[-1][0]
                        ))
                    )

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
        if (ridge.planted and not canopy_state.initialized
                and not _uses_native_maize(physics)):
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
                seed_type = _coerce_seed_type(
                    ridge.seed_type or farm_world_app.crop_profile.seed_type
                ) or SeedType.STANDARD
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
                if physics.crop_type != "soybean":
                    # Mid-season scenario state is a deliberate snapshot.
                    # Initialize its crop-specific biomass/yield scale rather
                    # than the historical soybean LAI-to-biomass proxy.
                    growth_params = physics.canopy.seed_params[CanopySeedType(seed_type.value)]
                    progress = _phenology_development_fraction(
                        phen_state, physics.phenology.seed_type_params
                    )
                    target_yield = physics.crop_profile.yield_kg_m2 * 1000.0
                    canopy_state.aboveground_biomass_g_m2 = max(
                        canopy_state.aboveground_biomass_g_m2,
                        target_yield * progress / growth_params.harvest_index,
                    )
                    fill = physics.phenology.params.stage_fraction_thresholds[SoybeanStage.R5]
                    canopy_state.yield_potential_g_m2 = target_yield * max(
                        0.0, min(1.0, (progress - fill) / (1.0 - fill))
                    )
                    if phen_stage == SoybeanStage.R8:
                        yld = physics.yield_recovery.states[rid]
                        yld.r8_reached = True
                        yld.maturity_date = phen_state.maturity_date or today
                        yld.biological_yield_g_m2 = canopy_state.yield_potential_g_m2
                        yld.grain_moisture_frac = (
                            float(ridge.grain_moisture_pct) / 100.0
                            if ridge.grain_moisture_pct > 0.0
                            else physics.yield_recovery.params.initial_r8_grain_moisture
                        )

        # Canopy NDVI bridge: scenarios that pre-seed an anomaly NDVI via
        # r.ndvi_proxy (>=0) overwrite the engine's default LAI-derived value.
        if ridge.ndvi_proxy >= 0.0 and canopy_state.initialized:
            canopy_state.ndvi_proxy = float(ridge.ndvi_proxy)


_STAGE_LAI_TARGETS: dict[SoybeanStage, float] = {
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
        ridge_area_m2 = farm_world_app.ridge_area_m2
        if ridge_area_m2 > 0.0:
            return max(0.0, float(ridge.seeds_planted) / ridge_area_m2)

    if ridge.seed_spacing_cm is not None and ridge.seed_spacing_cm > 0.0:
        seed_spacing_m = float(ridge.seed_spacing_cm) / 100.0
        return max(0.0, farm_world_app.rows_per_ridge / (ridge_width_m * seed_spacing_m))

    profile = farm_world_app.crop_profile
    if profile.crop_type == "soybean":
        return 40.0
    return farm_world_app.rows_per_ridge / (ridge_width_m * profile.seed_spacing_cm / 100.0)


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


# ---------------------------------------------------------------------------
# Helpers — daily tick
# ---------------------------------------------------------------------------


def _run_daily_tick(
    farm_world_app: "FarmWorldApp",
    physics: "FarmPhysicsState",
    weather_app: "WeatherApp | None",
    day: date, weather_inputs=None,
) -> None:
    """Run one full daily tick following the integration-guide order."""
    weather = weather_inputs if weather_inputs is not None else _build_weather_inputs(weather_app, day, physics=physics)
    if not _uses_native_maize(physics):
        _apply_biotic_outbreaks_for_day(physics, day)
    if "wofost_scenario_events" in (getattr(physics, "scenario_metadata", None) or {}):
        from fairy.scenarios.wofost_events import apply_scenario_events_for_day

        apply_scenario_events_for_day(farm_world_app, day)

    if _uses_registered_crop(physics):
        _run_registered_crop_daily_tick(farm_world_app, physics, day, weather)
        return

    pending_actions = physics.drain_pending_management_actions()
    pending_treatments = physics.drain_pending_treatments()
    pending_harvest = physics.drain_pending_harvest_actions()

    # 1+2. Management engine consumes today's actions and updates residuals.
    soil_inputs_for_management = _build_management_soil_inputs(physics)
    crop_inputs_for_management = _build_management_crop_inputs(physics)
    physics.management.update_day(
        weather=weather["management"],
        actions_by_ridge=pending_actions,
        soil_by_ridge=soil_inputs_for_management,
        crop_by_ridge=crop_inputs_for_management,
    )

    if physics.crop_backend is not None:
        # Commit newly queued controls before native daily assimilation. The
        # regular biotic update below remains the only daily aging/growth step.
        if pending_treatments:
            _apply_treatments_now(physics, weather, pending_treatments)
            pending_treatments = {}
        for rid, grain in physics.yield_recovery.states.items():
            if grain.harvested:
                physics.phenology.states[rid].planted = False
        humidity = weather.get("humidity_pct", 55.0)
        if "humidity_pct" not in weather and weather_app is not None:
            humidity = float(
                weather_app.get_current_weather_snapshot().get("humidity_pct", 55.0)
            )
        physics.crop_backend.advance_day(
            physics=physics,
            day=day,
            weather=weather["soil"],
            actions_by_ridge=pending_actions,
            density_by_ridge={
                rid: _ridge_planting_density_plants_m2(farm_world_app, rid)
                for rid in physics.phenology.states
            },
            ridge_area_m2=farm_world_app.ridge_area_m2,
            humidity_pct=humidity,
        )
    else:
        # 3. Soil engine consumes today's irrigation as water input.
        irrigation_mm = physics.management.irrigation_mm_by_ridge(pending_actions)
        canopy_cover_by_ridge = {
            rid: state.canopy_cover for rid, state in physics.canopy.states.items()
        }
        physics.soil.update_day(
            weather=weather["soil"],
            irrigation_mm_by_ridge=irrigation_mm,
            canopy_cover_by_ridge=canopy_cover_by_ridge,
        )

        # 4. Phenology consumes weather + soil.
        phenology_soil_inputs = {
            rid: PhenologySoilInput(
                top_temp_c=physics.soil.states[rid].top_temp_c,
                top_vwc=physics.soil.states[rid].top_vwc,
                water_stress=_crop_water_stress(physics, physics.soil.states[rid].root_vwc),
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
            if result.emerged:
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
                stage=CanopyGrowthStage(physics.phenology.states[rid].stage.value),
                development_fraction=_phenology_development_fraction(
                    physics.phenology.states[rid],
                    getattr(physics.phenology, "seed_type_params", None),
                ),
            )
            for rid in physics.phenology.states
        }
        canopy_soil_inputs = {
            rid: GrowthSoilInput(
                water_stress=_crop_water_stress(physics, physics.soil.states[rid].root_vwc),
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
        physics.canopy.update_day(
            weather=weather["canopy"],
            phenology_by_ridge=canopy_phenology_inputs,
            soil_by_ridge=canopy_soil_inputs,
            management_by_ridge=canopy_management_inputs,
        )

    # Maize v1 excludes soybean pest, disease and weed dynamics.
    if not _uses_native_maize(physics):
        # 7. Biotic pressure.
        biotic_crop_inputs = {
            rid: BioticCropInput(
                stage=BioticGrowthStage(physics.phenology.states[rid].stage.value),
                canopy_cover=physics.canopy.states[rid].canopy_cover,
                seed_type=(
                    physics.phenology.states[rid].seed_type.value
                    if physics.phenology.states[rid].seed_type is not None
                    else None
                ),
            )
            for rid in physics.phenology.states
        }
        biotic_soil_inputs = {
            rid: BioticSoilInput(
                top_vwc=physics.soil.states[rid].top_vwc,
                root_vwc=physics.soil.states[rid].root_vwc,
            )
            for rid in physics.soil.states
        }
        physics.biotic.update_day(
            weather=weather["biotic"],
            crop_by_ridge=biotic_crop_inputs,
            soil_by_ridge=biotic_soil_inputs,
            treatments_by_ridge=pending_treatments,
        )

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

    # 9. Observation cache regeneration is deferred — observation tools
    # call ObservationModel directly with the current truth on demand.

    # 10. Compatibility-field sync runs once after the loop in the entry
    # point, since multiple daily ticks can happen back-to-back.


def _run_registered_crop_daily_tick(farm_world_app, physics, day, weather):
    """Advance legacy crop dynamics once; PCSE never enters this path."""
    actions = physics.drain_pending_management_actions()
    treatments = physics.drain_pending_treatments()
    harvest = physics.drain_pending_harvest_actions()
    physics.management.update_day(
        weather=weather["management"], actions_by_ridge=actions,
        soil_by_ridge=_build_management_soil_inputs(physics),
        crop_by_ridge=physics.crop.management_inputs(physics),
    )
    living_cover = {}
    for rid, canopy in physics.canopy.states.items():
        status = physics.crop.project(rid, physics.management.states[rid])
        living_cover[rid] = (canopy.canopy_cover
                             if status.current_planted and status.emerged else 0.0)
    physics.soil.update_day(
        weather=weather["soil"],
        irrigation_mm_by_ridge=physics.management.irrigation_mm_by_ridge(actions),
        canopy_cover_by_ridge=living_cover,
    )
    # Compatibility crop engines retain the historical zero-biomass nutrient
    # input. Native WOFOST nitrogen uptake is owned by its CNB backend path.
    physics.crop.advance_before_biotics(farm_world_app, physics, day, weather)
    physics.biotic.update_day(
        weather=weather["biotic"], crop_by_ridge=physics.crop.biotic_inputs(physics),
        soil_by_ridge={rid: BioticSoilInput(top_vwc=state.top_vwc, root_vwc=state.root_vwc)
                       for rid, state in physics.soil.states.items()},
        treatments_by_ridge=treatments,
    )
    physics.crop.advance_after_biotics(physics, day, weather, harvest)


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


def _build_weather_inputs(
    weather_app: "WeatherApp | None",
    day: date,
    physics: "FarmPhysicsState | None" = None,
    advance_weather: bool = True,
    update_soil_vwc: bool = True,
    align_date_to_tick: bool = False,
) -> dict[str, Any]:
    """Translate the day's weather into per-engine inputs.

    Two pathways:

    1. **Round-4 profile mode**: when ``physics.weather_generator`` is set
       (because ``configure_physics_profile`` matched a registered
       PhysicsProfile), we draw the day's weather deterministically from
       the generator and *push it into WeatherApp* so the agent's
       ``get_current_weather()`` reflects the generated value.

    2. **Round 1+2+3 static mode**: read whatever ``WeatherApp.set_weather``
       last installed.

    All seven engines accept slightly different fields that cover the same
    underlying day. We approximate min/max temp around the mean when the
    static path is in use.
    """
    if weather_app is not None and hasattr(weather_app, "daily_inputs"):
        return weather_app.daily_inputs(day)
    generated_day = None
    yield_relative_humidity_pct = None
    if physics is not None and getattr(physics, "weather_generator", None) is not None:
        try:
            profile = getattr(physics, "profile", None)
            profile_events = getattr(profile, "weather_events", None) or []
            generated_day = _generate_weather_day(
                physics.weather_generator, day, profile_events
            )
        except Exception:  # pragma: no cover — defensive
            generated_day = None

    if generated_day is not None:
        temp_mean = float(generated_day.air_temp_mean_c)
        temp_min = float(generated_day.air_temp_min_c)
        temp_max = float(generated_day.air_temp_max_c)
        rain_mm = float(generated_day.rain_mm)
        wind_ms = float(generated_day.wind_ms)
        solar_mj = float(generated_day.solar_rad_mj_m2)
        solar_w = solar_mj / _W_PER_M2_TO_MJ_PER_M2_PER_DAY
        humidity_pct = (getattr(generated_day, "relative_humidity_pct", None)
                        if getattr(generated_day, "relative_humidity_pct", None) is not None else 55.0)
        yield_relative_humidity_pct = getattr(generated_day, "relative_humidity_pct", None)
        # Push the generated values into WeatherApp so agent reads see them.
        if weather_app is not None:
            weather_app.set_weather(
                date=day.isoformat(),
                temp_c=temp_mean,
                humidity_pct=humidity_pct,
                wind_speed_ms=wind_ms,
                rainfall_mm=rain_mm,
                solar_radiation=solar_w,
                forecast=_build_generated_forecast(
                    physics.weather_generator,
                    day,
                    profile_events,
                ),
                avg_soil_vwc=_avg_top_vwc(physics) if update_soil_vwc else None,
            )
    elif weather_app is not None:
        snap = weather_app.get_current_weather_snapshot()
        # Auto-advance: each daily tick rolls the WeatherApp's narrative date
        # forward by exactly one day, anchored on the snapshot's own date
        # (set by the scenario via `set_weather()`). We deliberately do NOT
        # replace the date with `target_date = day.isoformat()` — sim_time
        # and narrative time are aligned in production (Environment resets
        # the time_manager to scenario.start_time) but can drift in test
        # contexts that bypass the Environment. Anchoring on snap_date keeps
        # the agent-visible weather coherent with what the scenario set up,
        # regardless of how the framework clock is initialised.
        #
        # Forecast consumption: prefer the entry matching the new narrative
        # date, then fall back to entries dated <= target_date for backward
        # compatibility with scenarios that wire forecasts against sim_time.
        snap_date = str(snap.get("date", ""))
        target_date = day.isoformat()
        try:
            current_narrative = date.fromisoformat(snap_date)
            next_narrative_date = (current_narrative + timedelta(days=1)).isoformat()
        except ValueError:
            next_narrative_date = target_date
        if align_date_to_tick:
            # Multi-farm scenes bind every app to one clock. A scenario may
            # already have installed today's weather, so use the actual tick
            # date rather than advancing the station for a second time.
            next_narrative_date = target_date

        if advance_weather and snap_date != next_narrative_date:
            forecast = list(weather_app._weather.forecast)
            next_entry: dict | None = None
            # First pass: pop the entry whose date matches the new narrative
            # date exactly; this is the round-3 happy path.
            for idx, entry in enumerate(forecast):
                if str(entry.get("date", "")) == next_narrative_date:
                    next_entry = forecast.pop(idx)
                    break
            # Fallback: older sim_time-based behaviour — consume any entries
            # dated on or before target_date, take the newest applicable.
            if next_entry is None:
                while forecast and str(forecast[0].get("date", "")) <= target_date:
                    next_entry = forecast.pop(0)
            if next_entry is not None:
                temp_c_new = float(next_entry.get("temp_c", snap.get("temp_c", 18.0)))
                humidity_new = float(
                    next_entry.get("humidity_pct", snap.get("humidity_pct", 55.0))
                )
                wind_new = float(
                    next_entry.get("wind_speed_ms", snap.get("wind_speed_ms", 1.0))
                )
                rain_new = float(
                    next_entry.get("rainfall_mm", snap.get("rainfall_mm", 0.0))
                )
                solar_new = float(
                    next_entry.get(
                        "solar_radiation", snap.get("solar_radiation", 400.0)
                    )
                )
            else:
                temp_c_new = float(snap.get("temp_c", 18.0))
                humidity_new = float(snap.get("humidity_pct", 55.0))
                wind_new = float(snap.get("wind_speed_ms", 1.0))
                rain_new = float(snap.get("rainfall_mm", 0.0))
                solar_new = float(snap.get("solar_radiation", 400.0))
            weather_app.set_weather(
                date=next_narrative_date,
                temp_c=temp_c_new,
                humidity_pct=humidity_new,
                wind_speed_ms=wind_new,
                rainfall_mm=rain_new,
                solar_radiation=solar_new,
                forecast=forecast,
                avg_soil_vwc=_avg_top_vwc(physics) if update_soil_vwc else None,
            )
            snap = weather_app.get_current_weather_snapshot()
        humidity_pct = float(snap.get("humidity_pct", 55.0))
        if snap.get("humidity_pct") is not None:
            yield_relative_humidity_pct = float(snap["humidity_pct"])
        temp_mean = float(snap.get("temp_c", 18.0))
        rain_mm = float(snap.get("rainfall_mm", 0.0))
        wind_ms = float(snap.get("wind_speed_ms", 1.0))
        solar_w = float(snap.get("solar_radiation", 400.0))
        temp_min = temp_mean - _DEFAULT_DIURNAL_RANGE_C
        temp_max = temp_mean + _DEFAULT_DIURNAL_RANGE_C
        solar_mj = solar_w * _W_PER_M2_TO_MJ_PER_M2_PER_DAY
    else:
        humidity_pct = 55.0
        temp_mean = 18.0
        rain_mm = 0.0
        wind_ms = 1.0
        solar_w = 400.0
        temp_min = temp_mean - _DEFAULT_DIURNAL_RANGE_C
        temp_max = temp_mean + _DEFAULT_DIURNAL_RANGE_C
        solar_mj = solar_w * _W_PER_M2_TO_MJ_PER_M2_PER_DAY

    return {
        "humidity_pct": float(humidity_pct),
        "soil": SoilWeatherInput(
            day=day,
            air_temp_mean_c=temp_mean,
            air_temp_min_c=temp_min,
            air_temp_max_c=temp_max,
            rain_mm=rain_mm,
            solar_rad_mj_m2=solar_mj,
            wind_ms=wind_ms,
        ),
        "phenology": PhenologyWeatherInput(
            day=day,
            air_temp_min_c=temp_min,
            air_temp_max_c=temp_max,
            air_temp_mean_c=temp_mean,
        ),
        "canopy": GrowthWeatherInput(
            day=day,
            solar_rad_mj_m2=solar_mj,
            air_temp_mean_c=temp_mean,
        ),
        "biotic": BioticWeatherInput(
            day=day,
            air_temp_mean_c=temp_mean,
            rain_mm=rain_mm,
            is_raining=rain_mm > 0.0,
        ),
        "management": ManagementWeatherInput(
            day=day,
            rain_mm=rain_mm,
            wind_ms=wind_ms,
        ),
        "yield": YieldWeatherInput(
            day=day,
            air_temp_mean_c=temp_mean,
            rain_mm=rain_mm,
            solar_rad_mj_m2=solar_mj,
            wind_ms=wind_ms,
            relative_humidity_pct=yield_relative_humidity_pct,
        ),
    }


def _build_management_soil_inputs(
    physics: "FarmPhysicsState",
) -> dict[int, ManagementSoilInput]:
    return {
        rid: ManagementSoilInput(
            top_vwc=state.top_vwc,
            root_vwc=state.root_vwc,
        )
        for rid, state in physics.soil.states.items()
    }


def _build_management_crop_inputs(
    physics: "FarmPhysicsState",
) -> dict[int, ManagementCropInput]:
    return {
        rid: ManagementCropInput(
            stage=ManagementGrowthStage(physics.phenology.states[rid].stage.value),
            daily_biomass_g_m2=0.0,
        )
        for rid in physics.phenology.states
    }


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


def _uses_registered_crop(physics: "FarmPhysicsState") -> bool:
    """A native PCSE backend takes priority over the legacy dynamics registry."""
    return physics.crop_backend is None and not getattr(physics.crop, "compatibility_proxy", False)


def _uses_native_maize(physics: "FarmPhysicsState") -> bool:
    """Keep native maize rules separate from the legacy multi-crop proxy."""
    backend = physics.crop_backend
    return getattr(getattr(backend, "config", None), "crop_name", None) == "maize"


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


def _crop_water_stress(physics: "FarmPhysicsState", root_vwc: float) -> float:
    """Preserve soybean response; use crop-specific moisture demand elsewhere."""
    if physics.crop_type == "soybean":
        return _compute_water_stress(root_vwc)
    params = physics.soil.params
    return max(0.0, min(1.0, (root_vwc - params.wilting_point_vwc)
        / max(1e-6, params.water_stress_vwc - params.wilting_point_vwc)))


def _compute_biotic_stress(biotic_state: Any) -> float:
    """Translate biotic pressures to a 0–1 growth multiplier."""
    weighted = (
        0.28 * biotic_state.weed_pressure
        + 0.32 * biotic_state.insect_pressure
        + 0.45 * biotic_state.disease_pressure
    )
    return max(0.35, 1.0 - weighted)


def _apply_biotic_outbreaks_for_day(physics: "FarmPhysicsState", day: date) -> None:
    """Inject scheduled biotic outbreaks from the active PhysicsProfile.

    Insect and disease outbreaks raise pressure to a target severity while the
    outbreak is active. Weed outbreaks are modeled as a recruitment flush: they
    add gradual daily pressure rather than overwriting treatment effects.
    """
    profile = getattr(physics, "profile", None)
    if profile is None:
        return
    outbreaks = getattr(profile, "biotic_outbreaks", None) or []
    if not outbreaks:
        return
    start_date = getattr(profile, "start_date", None)
    if start_date is None:
        return
    days_since_start = (day - start_date).days
    if days_since_start < 0:
        return
    from fairy.physics.biotic_pressure_engine import TreatmentType

    for outbreak in outbreaks:
        if not (
            outbreak.start_day_offset
            <= days_since_start
            < outbreak.start_day_offset + outbreak.duration_days
        ):
            continue
        ridge_ids = list(range(outbreak.ridge_start, outbreak.ridge_end + 1))
        if outbreak.pressure_type == TreatmentType.INSECTICIDE:
            physics.biotic.set_pressure(
                ridge_ids, insect_pressure=float(outbreak.severity)
            )
        elif outbreak.pressure_type == TreatmentType.FUNGICIDE:
            physics.biotic.set_pressure(
                ridge_ids, disease_pressure=float(outbreak.severity)
            )
        elif outbreak.pressure_type == TreatmentType.HERBICIDE:
            duration_days = max(1, int(outbreak.duration_days))
            daily_flush = max(0.0, float(outbreak.severity)) / duration_days
            for ridge_id in ridge_ids:
                state = physics.biotic.states.get(ridge_id)
                if state is None:
                    continue
                state.weed_pressure = min(1.0, state.weed_pressure + daily_flush)


def _generate_weather_day(
    weather_generator, day: date, events: list[Any] | None = None
):
    """Generate one day from the WeatherGenerator including event overrides.

    The generator produces a window of days; we ask for a one-day slice
    using a per-day cache to keep day-to-day determinism (re-asking for
    the same date returns the same value across a single physics state).
    """
    cache = getattr(weather_generator, "_day_cache", None)
    if cache is None:
        cache = {}
        try:
            weather_generator._day_cache = cache  # type: ignore[attr-defined]
        except Exception:
            pass
    if day in cache:
        return cache[day]
    days = weather_generator.generate(start_date=day, end_date=day, events=events or [])
    if not days:
        return None
    cache[day] = days[0]
    return days[0]


def _build_generated_forecast(
    weather_generator,
    day: date,
    events: list[Any] | None = None,
    days: int = 7,
) -> list[dict[str, Any]]:
    """Expose deterministic WeatherGenerator future days through WeatherApp."""
    forecast: list[dict[str, Any]] = []
    for offset in range(1, max(1, int(days)) + 1):
        weather_day = _generate_weather_day(
            weather_generator,
            day + timedelta(days=offset),
            events,
        )
        if weather_day is None:
            continue
        forecast.append(
            {
                "date": weather_day.day.isoformat(),
                "temp_c": float(weather_day.air_temp_mean_c),
                "humidity_pct": (getattr(weather_day, "relative_humidity_pct", None)
                                 if getattr(weather_day, "relative_humidity_pct", None) is not None
                                 else 55.0),
                "wind_speed_ms": float(weather_day.wind_ms),
                "rainfall_mm": float(weather_day.rain_mm),
                "solar_radiation": float(
                    weather_day.solar_rad_mj_m2 / _W_PER_M2_TO_MJ_PER_M2_PER_DAY
                ),
            }
        )
    return forecast


def _avg_top_vwc(physics: "FarmPhysicsState | None") -> float | None:
    if physics is None or getattr(physics, "soil", None) is None:
        return None
    states = list(getattr(physics.soil, "states", {}).values())
    if not states:
        return None
    return sum(float(state.top_vwc) for state in states) / len(states)


# ---------------------------------------------------------------------------
# Helpers — sub-daily injection (irrigation, treatments)
# ---------------------------------------------------------------------------


def _apply_treatments_now(physics, weather, treatments):
    crop_inputs = (physics.crop.biotic_inputs(physics) if _uses_registered_crop(physics) else
                  {rid: BioticCropInput(
                      stage=BioticGrowthStage(phen.stage.value),
                      canopy_cover=physics.canopy.states[rid].canopy_cover,
                      seed_type=phen.seed_type.value if phen.seed_type is not None else None)
                   for rid, phen in physics.phenology.states.items()})
    physics.biotic.update_day(
        weather=weather["biotic"],
        crop_by_ridge=crop_inputs,
        soil_by_ridge={rid: BioticSoilInput(top_vwc=state.top_vwc, root_vwc=state.root_vwc)
                       for rid, state in physics.soil.states.items()},
        treatments_by_ridge=treatments, advance_daily=False)


def _settle_harvest_now(physics, weather, harvest):
    if not harvest:
        return
    if _uses_registered_crop(physics):
        physics.crop.settle_harvest(physics, weather["yield"].day, weather, harvest)
        return
    physics.yield_recovery.settle_harvest(
        weather=weather["yield"],
        phenology_by_ridge={rid: YieldPhenologyInput(
            stage=YieldGrowthStage(phen.stage.value), maturity_date=phen.maturity_date)
            for rid, phen in physics.phenology.states.items()},
        growth_by_ridge={rid: YieldGrowthInput(yield_potential_g_m2=state.yield_potential_g_m2,
                                             aboveground_biomass_g_m2=state.aboveground_biomass_g_m2)
                         for rid, state in physics.canopy.states.items()},
        stress_by_ridge={rid: YieldStressInput(disease_severity=state.disease_pressure,
                                              insect_pod_damage=state.insect_pressure)
                         for rid, state in physics.biotic.states.items()},
        harvest_actions_by_ridge=harvest)


def _run_subdaily_injection(physics, weather_app, target_sim_time,
                            weather_inputs_provider=None, *, simulation_timezone=timezone.utc):
    """Commit actions; harvest retains the historical recovery-day update."""
    today = datetime.fromtimestamp(target_sim_time, tz=simulation_timezone).date()
    weather = (weather_inputs_provider(today, False) if weather_inputs_provider else
               _build_weather_inputs(weather_app, today, physics=physics, advance_weather=False))
    actions = physics.drain_pending_management_actions()
    treatments = physics.drain_pending_treatments()
    harvest = physics.drain_pending_harvest_actions()
    if actions:
        physics.management.update_day(weather=weather["management"], actions_by_ridge=actions,
            soil_by_ridge=_build_management_soil_inputs(physics),
            crop_by_ridge=(physics.crop.management_inputs(physics) if _uses_registered_crop(physics)
                           else _build_management_crop_inputs(physics)), advance_daily=False)
    if treatments and not _uses_native_maize(physics):
        _apply_treatments_now(physics, weather, treatments)
    _settle_harvest_now(physics, weather, harvest)
    if physics.crop_backend is not None:
        physics.crop_backend.queue_actions(actions,
            ridge_area_m2=physics.field_length_m * physics.ridge_width_m)
        return False
    irrigation = physics.management.irrigation_mm_by_ridge(actions)
    if irrigation:
        _apply_subdaily_irrigation(physics, irrigation)
    return bool(irrigation)


def _apply_subdaily_irrigation(
    physics: "FarmPhysicsState", irrigation_mm_by_ridge: dict[int, float]
) -> None:
    """Inject pending irrigation directly into soil VWC, bypassing ET.

    Used when a tool calls advance_physics_time inside a sub-daily lag (e.g.
    the irrigation 2-hour wait). The full daily cycle (ET, drainage,
    phenology, canopy) is deferred to the next day boundary; only the
    irrigation inflow is reflected immediately so sensor reads see the
    expected VWC bump.
    """
    for ridge_id, mm in irrigation_mm_by_ridge.items():
        state = physics.soil.states.get(ridge_id)
        if state is None or mm <= 0.0:
            continue
        p = physics.soil.params_for_ridge(ridge_id)
        top_depth_mm = p.top_depth_m * 1000.0
        root_depth_mm = p.root_depth_m * 1000.0
        top_sat = p.saturation_vwc * top_depth_mm
        top_fc = p.field_capacity_vwc * top_depth_mm
        root_sat = p.saturation_vwc * root_depth_mm
        infiltrated = min(
            float(mm) * p.irrigation_efficiency, p.max_infiltration_mm_day
        )
        top_storage = state.top_vwc * top_depth_mm + infiltrated
        if top_storage > top_sat:
            top_storage = top_sat
        # Move the portion above field capacity into the root zone.
        top_excess_above_fc = max(0.0, top_storage - top_fc)
        percolation = p.top_drainage_rate * top_excess_above_fc
        top_storage -= percolation
        root_storage = state.root_vwc * root_depth_mm + percolation
        if root_storage > root_sat:
            root_storage = root_sat
        state.top_vwc = max(
            p.wilting_point_vwc, min(p.saturation_vwc, top_storage / top_depth_mm)
        )
        state.root_vwc = max(
            p.wilting_point_vwc, min(p.saturation_vwc, root_storage / root_depth_mm)
        )


# ---------------------------------------------------------------------------
# Helpers — compatibility sync (physics → RidgeState)
# ---------------------------------------------------------------------------


def sync_compatibility_fields_from_physics(farm_world_app: "FarmWorldApp") -> None:
    """Mirror engine outputs back onto RidgeState fields legacy code reads.

    The mappings follow the integration guide's "Compatibility synchronization"
    table. Pest/disease/yield are exposed as truth-mirror fields here so the
    legacy validators and the sensor cache continue to work; in the long term
    these reads should go through ObservationModel.
    """
    physics = farm_world_app._physics
    if physics is None or not physics.engines_active:
        return

    if _uses_registered_crop(physics):
        for ridge in farm_world_app._ridges:
            rid = ridge.ridge_id
            soil, biotic = physics.soil.states[rid], physics.biotic.states[rid]
            ridge.soil_vwc = float(soil.top_vwc)
            ridge.soil_temp_c = float(soil.top_temp_c)
            ridge.nutrient_index = float(physics.management.states[rid].nutrient_index)
            ridge.pest_pressure = ridge.pest_pressure_base = float(biotic.insect_pressure)
            ridge.disease_pressure = ridge.disease_pressure_base = float(biotic.disease_pressure)
        physics.crop.sync_public_fields(farm_world_app)
        return

    for ridge in farm_world_app._ridges:
        rid = ridge.ridge_id
        soil = physics.soil.states[rid]
        # ridge.soil_vwc represents the 5-cm-depth sensor measurement
        # (per RidgeState comment); that is the top layer in physics terms.
        ridge.soil_vwc = float(soil.top_vwc)
        ridge.soil_temp_c = float(soil.top_temp_c)
        # Public management telemetry must reflect committed physical state.
        # Native daily projection may replace this with its RFRGRL N proxy;
        # same-timestamp fertilizer injection must also be visible immediately.
        ridge.nutrient_index = float(physics.management.states[rid].nutrient_index)

        phen = physics.phenology.states[rid]
        if phen.planted:
            ridge.planted = True
            ridge.days_since_planted = int(phen.days_after_planting)
            if _uses_native_maize(physics):
                ridge.growth_stage = phen.stage.value
            elif physics.crop_type == "soybean":
                ridge.growth_stage = _map_soybean_stage_to_legacy(phen.stage)
            else:
                from fairy.physics.crop_physiology import public_crop_stage

                ridge.growth_stage = public_crop_stage(
                    physics.crop_profile, phen, physics.phenology.seed_type_params
                )

        biotic = physics.biotic.states[rid]
        ridge.pest_pressure = float(biotic.insect_pressure)
        ridge.disease_pressure = float(biotic.disease_pressure)
        # Pest/disease baselines mirror the latent pressure so legacy code
        # reading the *_base fields gets a consistent number.
        ridge.pest_pressure_base = float(biotic.insect_pressure)
        ridge.disease_pressure_base = float(biotic.disease_pressure)

        canopy = physics.canopy.states[rid]
        if canopy.initialized:
            # Leave ridge.ndvi alone — that field is the agent-visible last
            # observation populated by drone/sensor tools through
            # ObservationModel. Truth is in canopy.ndvi_proxy and stays
            # behind the observation boundary.
            yield_scale = (350.0 if physics.crop_type == "soybean" else
                           physics.crop_profile.yield_kg_m2 * 1000.0)
            ridge.yield_potential = float(canopy.yield_potential_g_m2 / yield_scale)
            ridge.yield_potential = max(0.0, min(1.0, ridge.yield_potential))

        yld = physics.yield_recovery.states[rid]
        ridge.harvested = bool(yld.harvested)
        if yld.grain_moisture_frac is not None:
            ridge.grain_moisture_pct = float(yld.grain_moisture_frac * 100.0)
        if yld.harvested:
            ridge.planted = False
            ridge.growth_stage = "BARE"
            ridge.days_since_planted = 0
            ridge.grain_moisture_pct = 0.0
        elif phen.planted:
            mgmt = physics.management.states[rid]
            ridge.stand_fraction = float(mgmt.stand_fraction)


# ---------------------------------------------------------------------------
# Helpers — finding the WeatherApp from the current Environment
# ---------------------------------------------------------------------------


def _find_weather_app(farm_world_app: "FarmWorldApp") -> "WeatherApp | None":
    """Return the WeatherApp attached during scenario init.

    Set by FieldOpsApp / TractorApp / DroneApp / RobotApp __init__ via
    farm_world_app.attach_weather_app(...). Returns None for tests that
    construct FarmWorldApp standalone.
    """
    return getattr(farm_world_app, "_weather_app", None)
