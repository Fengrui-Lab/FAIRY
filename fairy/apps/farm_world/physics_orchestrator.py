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
    tick per crossed scene-local date boundary up to target_sim_time. Sub-daily lag
    (no boundary crossed) triggers an immediate-soil-input update when
    irrigation actions are queued. After running, last_physics_sim_time is
    set to target_sim_time, the action queues are drained, and compatibility
    shadows on RidgeState are refreshed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import TYPE_CHECKING, Any, Callable

from fairy.physics import (
    BioticSoilInput, BioticWeatherInput, GrowthWeatherInput,
    ManagementSoilInput, ManagementWeatherInput, PhenologyWeatherInput,
    SoilWeatherInput, YieldWeatherInput,
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
    farm_world_app: "FarmWorldApp", target_sim_time: float,
    *,
    weather_inputs_provider: Callable[[date, bool], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Advance physics to ``target_sim_time``.

    Idempotent when no actions are pending. An equal timestamp still commits
    new actions, without daily evolution. Returns daily-tick and irrigation status.
    """
    physics = farm_world_app._physics
    if physics is None or not physics.engines_active:
        return {"status": "skipped", "reason": "physics_inactive"}

    weather_app = _find_weather_app(farm_world_app)

    # First call seeds engine state from the scenario's initial ridge values.
    if physics.last_physics_sim_time is None:
        physics.crop.initialize_from_ridges(farm_world_app, target_sim_time)
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
                physics, weather_app, target_sim_time, weather_inputs_provider,
                simulation_timezone=farm_world_app.simulation_timezone,
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
    if elapsed < 0.0:
        raise ValueError("Physics time cannot move backwards")
    has_pending = bool(
        physics.pending_management_actions_by_ridge
        or physics.pending_treatments_by_ridge
        or physics.pending_harvest_actions_by_ridge
    )
    if elapsed == 0.0 and not has_pending:
        return {"status": "noop", "day_ticks_run": 0, "elapsed_s": elapsed}

    days_to_run = _dates_between(
        physics.last_physics_sim_time, target_sim_time,
        simulation_timezone=farm_world_app.simulation_timezone,
    )

    subdaily_irrigation_applied = False
    if not days_to_run and has_pending:
        subdaily_irrigation_applied = _run_subdaily_injection(
            physics, weather_app, target_sim_time, weather_inputs_provider,
            simulation_timezone=farm_world_app.simulation_timezone,
        )

    for tick_day in days_to_run:
        weather_inputs = (
            weather_inputs_provider(tick_day, True)
            if weather_inputs_provider is not None
            else None
        )
        _run_daily_tick(farm_world_app, physics, weather_app, tick_day, weather_inputs)

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


def _dates_between(
    t_from: float, t_to: float, *, simulation_timezone: tzinfo = timezone.utc
) -> list[date]:
    """Return scene-local dates strictly after t_from and up to t_to.

    For an irrigation scenario starting at 07:00 local time and waiting 2 hours
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
# Helpers — daily tick
# ---------------------------------------------------------------------------


def _run_daily_tick(farm_world_app, physics, weather_app, day, weather_inputs=None):
    """One environmental update, with explicit crop phases around biotic growth."""
    weather = weather_inputs if weather_inputs is not None else _build_weather_inputs(weather_app, day, physics=physics)
    _apply_biotic_outbreaks_for_day(physics, day)
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
    growth_for_uptake = physics.crop.advance_before_biotics(farm_world_app, physics, day, weather)
    if growth_for_uptake is not None:
        # Settle actual growth once, without aging effects, replaying actions or
        # recomputing today's canopy. The reduced availability feeds the next day.
        physics.management.settle_crop_growth(day, growth_for_uptake)
    physics.biotic.update_day(
        weather=weather["biotic"], crop_by_ridge=physics.crop.biotic_inputs(physics),
        soil_by_ridge={rid: BioticSoilInput(top_vwc=state.top_vwc, root_vwc=state.root_vwc)
                       for rid, state in physics.soil.states.items()},
        treatments_by_ridge=treatments,
    )
    physics.crop.advance_after_biotics(physics, day, weather, harvest)

    # 9. Observation cache regeneration is deferred — observation tools
    # call ObservationModel directly with the current truth on demand.

    # 10. Compatibility-field sync runs once after the loop in the entry
    # point, since multiple daily ticks can happen back-to-back.


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
    generated_day = None
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
        # Push the generated values into WeatherApp so agent reads see them.
        if weather_app is not None:
            weather_app.set_weather(
                date=day.isoformat(),
                temp_c=temp_mean,
                humidity_pct=55.0,  # weather generator doesn't model RH; static default
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
        temp_mean = float(snap.get("temp_c", 18.0))
        rain_mm = float(snap.get("rainfall_mm", 0.0))
        wind_ms = float(snap.get("wind_speed_ms", 1.0))
        solar_w = float(snap.get("solar_radiation", 400.0))
        temp_min = temp_mean - _DEFAULT_DIURNAL_RANGE_C
        temp_max = temp_mean + _DEFAULT_DIURNAL_RANGE_C
        solar_mj = solar_w * _W_PER_M2_TO_MJ_PER_M2_PER_DAY
    else:
        temp_mean = 18.0
        rain_mm = 0.0
        wind_ms = 1.0
        solar_w = 400.0
        temp_min = temp_mean - _DEFAULT_DIURNAL_RANGE_C
        temp_max = temp_mean + _DEFAULT_DIURNAL_RANGE_C
        solar_mj = solar_w * _W_PER_M2_TO_MJ_PER_M2_PER_DAY

    return {
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
                "humidity_pct": 55.0,
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


def _run_subdaily_injection(
    physics, weather_app, target_sim_time, weather_inputs_provider=None, *,
    simulation_timezone=timezone.utc,
):
    """Commit new actions without growth, drydown or daily effect aging."""
    today = datetime.fromtimestamp(target_sim_time, tz=simulation_timezone).date()
    weather = (weather_inputs_provider(today, False) if weather_inputs_provider is not None
               else _build_weather_inputs(weather_app, today, physics=physics, advance_weather=False))
    actions = physics.drain_pending_management_actions()
    treatments = physics.drain_pending_treatments()
    harvest = physics.drain_pending_harvest_actions()
    if actions:
        physics.management.update_day(
            weather=weather["management"], actions_by_ridge=actions,
            soil_by_ridge=_build_management_soil_inputs(physics),
            crop_by_ridge=physics.crop.management_inputs(physics), advance_daily=False,
        )
    if treatments:
        physics.biotic.update_day(
            weather=weather["biotic"], crop_by_ridge=physics.crop.biotic_inputs(physics),
            soil_by_ridge={rid: BioticSoilInput(top_vwc=state.top_vwc, root_vwc=state.root_vwc)
                           for rid, state in physics.soil.states.items()},
            treatments_by_ridge=treatments, advance_daily=False,
        )
    if harvest:
        physics.crop.settle_harvest(physics, today, weather, harvest)
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


def sync_compatibility_fields_from_physics(farm_world_app):
    """Publish native crop projections after the common environmental update."""
    physics = farm_world_app._physics
    if physics is None or not physics.engines_active:
        return
    for ridge in farm_world_app._ridges:
        rid = ridge.ridge_id
        soil = physics.soil.states[rid]
        biotic = physics.biotic.states[rid]
        ridge.soil_vwc = float(soil.top_vwc)
        ridge.soil_temp_c = float(soil.top_temp_c)
        ridge.nutrient_index = float(physics.management.states[rid].nutrient_index)
        ridge.pest_pressure = ridge.pest_pressure_base = float(biotic.insect_pressure)
        ridge.disease_pressure = ridge.disease_pressure_base = float(biotic.disease_pressure)
    physics.crop.sync_public_fields(farm_world_app)


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
