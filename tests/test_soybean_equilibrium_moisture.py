"""EMC evidence, daily dynamics and compatibility of opt-in soybean drydown."""
from dataclasses import asdict
from datetime import date, timedelta
import json
from math import exp

import pytest

from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs
from fairy.apps.farm_world.runtime_state import decode_state, encode_state
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.physics.yield_recovery_engine import (
    GrowthStage, HarvestAction, YieldGrowthInput, YieldPhenologyInput,
    YieldRecoveryEngine, YieldRecoveryParameters, YieldWeatherInput,
    soybean_equilibrium_moisture_frac,
)


DAY = date(2019, 9, 13)


def mature_engine(*, moisture=.30, mode="soybean_equilibrium", dry_mass=400):
    engine = YieldRecoveryEngine(1, YieldRecoveryParameters(
        grain_moisture_mode=mode, biological_yield_is_dry_matter=True,
    ))
    state = engine.states[0]
    state.r8_reached, state.maturity_date = True, DAY
    state.grain_moisture_frac = moisture
    state.biological_yield_g_m2 = dry_mass
    return engine


def step(engine, offset=0, *, rh=70., temp=10., rain=0., harvest=False):
    return engine.update_day(
        YieldWeatherInput(DAY + timedelta(days=offset), temp, rain, 15., 1., rh),
        {0: YieldPhenologyInput(GrowthStage.R8, DAY)},
        {0: YieldGrowthInput(engine.states[0].biological_yield_g_m2)},
        harvest_actions_by_ridge={0: HarvestAction()} if harvest else None,
    )[0]


@pytest.mark.parametrize("temp_f,rh,emc", [
    (32, 50, .100), (32, 90, .198), (40, 70, .135),
    (50, 70, .132), (50, 80, .157), (60, 70, .130),
    (70, 80, .152), (80, 90, .187),
])
def test_emc_matches_published_ndsu_table(temp_f, rh, emc):
    assert soybean_equilibrium_moisture_frac((temp_f - 32) / 1.8, rh) == pytest.approx(emc)


def test_emc_interpolates_both_temperature_and_humidity():
    # 45 F / 75% lies midway among the four published 40/50 F, 70/80% values.
    assert soybean_equilibrium_moisture_frac((45 - 32) / 1.8, 75) == pytest.approx(
        (.135 + .160 + .132 + .157) / 4,
    )


def test_outside_table_is_bounded_and_explicitly_tagged():
    assert soybean_equilibrium_moisture_frac(-10, 100) == .198
    assert soybean_equilibrium_moisture_frac(40, 0) == .086
    result = step(mature_engine(), rh=95, temp=-2)
    assert "soybean_emc_input_clamped_to_published_table" in result.tags


@pytest.mark.parametrize("rh", [None, -1, 101, float("nan"), float("inf")])
def test_opt_in_never_fabricates_missing_or_invalid_humidity(rh):
    with pytest.raises(ValueError, match="humidity"):
        step(mature_engine(), rh=rh)


def test_first_order_response_conserves_seed_dry_matter_and_never_jumps_to_emc():
    engine = mature_engine()
    step(engine)
    state = engine.states[0]
    emc = .132
    ratio = emc / (1 - emc) + (.30 / .70 - emc / (1 - emc)) * exp(-1 / 5)
    assert state.grain_moisture_frac == pytest.approx(ratio / (1 + ratio))
    assert emc < state.grain_moisture_frac < .30
    assert state.biological_yield_g_m2 == 400
    assert not state.harvested


def test_drying_slows_near_equilibrium_and_humid_air_can_rewet():
    dry, wet = mature_engine(), mature_engine(moisture=.10)
    daily_drops = []
    previous = .30
    for offset in range(30):
        step(dry, offset)
        step(wet, offset, rh=90.)
        daily_drops.append(previous - dry.states[0].grain_moisture_frac)
        previous = dry.states[0].grain_moisture_frac
    assert all(a > b > 0 for a, b in zip(daily_drops, daily_drops[1:]))
    assert dry.states[0].grain_moisture_frac == pytest.approx(.132, abs=.001)
    assert .19 < wet.states[0].grain_moisture_frac < .194
    assert wet.states[0].wet_dry_cycles_after_r8 == 1


def test_no_fixed_harvest_date_is_imposed_under_wet_or_dry_air():
    dry, wet = mature_engine(), mature_engine()
    for offset in range(14):
        step(dry, offset)
        step(wet, offset, rh=90.)
    assert dry.states[0].grain_moisture_frac < .18
    assert wet.states[0].grain_moisture_frac > .18


def test_light_rain_does_not_perpetually_reset_mature_grain_to_35_percent():
    engine = mature_engine()
    for offset in range(30):
        step(engine, offset, rh=75, rain=.1)
    assert .14 < engine.states[0].grain_moisture_frac < .16
    assert engine.states[0].biological_yield_g_m2 == 400


def test_liquid_rain_uptake_is_bounded_by_wet_basis_cap_and_actual_water_mass():
    engine = mature_engine(moisture=.132)
    step(engine, rain=1000000)
    assert engine.states[0].grain_moisture_frac == pytest.approx(.132 + .035)

    # Deliberately large dry mass makes the incoming rainwater limit binding;
    # this checks units, not a proposed soybean field-yield configuration.
    massive = mature_engine(moisture=.132, dry_mass=1_000_000)
    result = step(massive, rain=.01)
    before_water = 1_000_000 * .132 / (1 - .132)
    after = massive.states[0].grain_moisture_frac
    after_water = 1_000_000 * after / (1 - after)
    assert after_water - before_water == pytest.approx(.01 * 1000)
    assert "rain_rewetting_limited_by_incoming_water" in result.tags


def test_repeated_same_day_reads_and_harvest_do_not_dry_grain_again():
    engine = mature_engine(moisture=.15)
    step(engine)
    after = engine.states[0].grain_moisture_frac
    step(engine)
    assert engine.states[0].grain_moisture_frac == after
    step(engine, harvest=True)
    assert engine.states[0].grain_moisture_frac == after
    assert engine.states[0].harvested


def test_legacy_default_keeps_old_drydown_numbers_and_ignores_optional_humidity():
    legacy, supplied = mature_engine(mode="legacy"), mature_engine(mode="legacy")
    step(legacy, rh=None, temp=20)
    step(supplied, rh=99, temp=20)
    assert legacy.states[0].grain_moisture_frac == pytest.approx(.2847)
    step(legacy, 1, rh=None, temp=20, rain=5)
    step(supplied, 1, rh=99, temp=20, rain=5)
    assert legacy.states[0].grain_moisture_frac == pytest.approx(.2889)
    assert asdict(legacy.states[0]) == asdict(supplied.states[0])
    assert YieldRecoveryParameters().grain_moisture_mode == "legacy"


def test_exact_pinned_humidity_reaches_yield_input_without_display_rounding():
    physics = FarmPhysicsState(num_ridges=1)
    physics.set_weather_day_override(
        DAY, air_temp_mean_c=16, rain_mm=2, wind_ms=2,
        solar_rad_mj_m2=15, relative_humidity_pct=73.25,
    )
    weather = WeatherApp()
    values = _build_weather_inputs(weather, DAY, physics, advance_weather=False)
    assert values["yield"].relative_humidity_pct == 73.25
    assert weather.get_current_weather_snapshot()["humidity_pct"] == 73.2
    assert values["yield"].rain_mm == values["soil"].rain_mm == 2


def test_absent_weather_keeps_missing_yield_rh_rather_than_manufacturing_55_percent():
    assert _build_weather_inputs(None, DAY)["yield"].relative_humidity_pct is None


def test_checkpoint_retains_mode_parameters_and_replays_next_day_exactly():
    engine = mature_engine()
    for offset in range(4):
        step(engine, offset, rh=78, rain=2)
    payload = json.loads(json.dumps(encode_state(engine), allow_nan=False))
    restored = decode_state(payload)
    assert asdict(restored.params) == asdict(engine.params)
    assert restored.params.grain_moisture_mode == "soybean_equilibrium"
    assert asdict(step(restored, 4, rh=83, rain=0)) == asdict(step(engine, 4, rh=83, rain=0))
    assert asdict(restored.states[0]) == asdict(engine.states[0])


def test_old_parameter_checkpoint_defaults_to_legacy_instead_of_enabling_new_mode():
    payload = encode_state(YieldRecoveryParameters())
    payload["fields"].pop("grain_moisture_mode")
    payload["fields"].pop("soybean_equilibrium_time_constant_days")
    restored = decode_state(json.loads(json.dumps(payload)))
    assert restored.grain_moisture_mode == "legacy"
    assert restored.soybean_equilibrium_time_constant_days == 5.


@pytest.mark.parametrize("config", [
    {"grain_moisture_mode": "typo"},
    {"soybean_equilibrium_time_constant_days": 0},
    {"soybean_equilibrium_time_constant_days": float("nan")},
])
def test_invalid_equilibrium_configuration_fails_explicitly(config):
    with pytest.raises(ValueError):
        YieldRecoveryParameters(**config)
