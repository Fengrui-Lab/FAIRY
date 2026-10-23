"""Scientific-direction and accounting contracts of the reduced maize model."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from fairy.crops.catalog import MAIZE
from fairy.crops.maize import MaizeCropModel, MaizeParameters, MaizeStage
from fairy.physics.canopy_biomass_engine import GrowthWeatherInput
from fairy.physics.phenology_engine import PhenologyWeatherInput
from fairy.physics.yield_recovery_engine import HarvestAction, YieldWeatherInput


START = date(2026, 5, 5)


def weather(day: date, *, temperature: float = 22.0,
            rain: float = 0.0, solar: float = 20.0) -> dict:
    return {
        "phenology": PhenologyWeatherInput(
            day, temperature - 5, temperature + 5, temperature,
        ),
        "canopy": GrowthWeatherInput(day, solar, temperature),
        "yield": YieldWeatherInput(day, temperature, rain, solar, 2.0),
    }


def inputs(count: int = 2, *, water: float = 0.28,
           nutrient: float = 1.0, soil_temp: float = 23.0,
           stand: float = 1.0, disease: float = 0.0) -> tuple[dict, dict, dict]:
    return (
        {rid: SimpleNamespace(top_temp_c=soil_temp, top_vwc=0.26, root_vwc=water)
         for rid in range(count)},
        {rid: SimpleNamespace(nutrient_stress=nutrient, stand_fraction=stand)
         for rid in range(count)},
        {rid: SimpleNamespace(weed_pressure=0.0, insect_pressure=0.0,
                              disease_pressure=disease) for rid in range(count)},
    )


def planted(count: int = 2, *, density: float = 6.5,
            stand: float = 1.0) -> MaizeCropModel:
    model = MaizeCropModel(count)
    model.plant(list(range(count)), START, "MAIZE_EARLY_2026", 4.5,
                {rid: stand for rid in range(count)},
                {rid: density for rid in range(count)})
    return model


def advance(model: MaizeCropModel, first: int = 1, last: int = 140,
            **stress: float) -> None:
    state_inputs = inputs(len(model.phenology.states), **stress)
    for offset in range(first, last + 1):
        day = START + timedelta(days=offset)
        model.update_day(day, weather(day), *state_inputs)


def test_complete_native_stage_sequence_and_no_maturity_before_r6() -> None:
    model = planted()
    observed = []
    state_inputs = inputs()
    for offset in range(1, 140):
        day = START + timedelta(days=offset)
        model.update_day(day, weather(day), *state_inputs)
        phen, canopy, grain = (component.states[0] for component in (
            model.phenology, model.canopy, model.yield_recovery,
        ))
        if not observed or observed[-1] != phen.stage:
            observed.append(phen.stage)
        assert grain.r6_reached == (phen.stage == MaizeStage.R6_MATURITY)
        if not grain.r6_reached:
            assert phen.maturity_date is None
            assert grain.grain_moisture_frac is None
        assert 0 <= canopy.canopy_cover <= 1
        assert 0 <= canopy.yield_potential_g_m2 <= model.params.max_biological_yield_g_m2
    assert observed == list(MaizeStage)[1:]
    assert 0 < model.yield_recovery.states[0].biological_yield_g_m2
    assert model.phenology.states[0].seed_type == "MAIZE_EARLY_2026"
    assert model.params.market_moisture_pct == pytest.approx(MAIZE.market_moisture_pct)


def test_cold_soil_prevents_emergence_despite_air_heat_then_starts_at_ve() -> None:
    model = planted()
    advance(model, last=90, soil_temp=8.0)
    assert not model.phenology.states[0].emerged
    assert model.phenology.states[0].accumulated_gdd > 1000
    assert model.canopy.states[0].aboveground_biomass_g_m2 == 0
    assert not model.yield_recovery.states[0].r6_reached
    advance(model, first=91, last=97)
    assert model.phenology.states[0].stage == MaizeStage.VE
    assert not model.yield_recovery.states[0].r6_reached


def test_daily_biomass_flux_is_zero_after_maturity_and_harvest() -> None:
    model = planted()
    advance(model)
    assert model.yield_recovery.states[0].r6_reached
    assert model.canopy.states[0].daily_biomass_g_m2 == 0.0
    model.settle_harvest(START + timedelta(days=140), {0: HarvestAction()})
    advance(model, first=141, last=142)
    assert model.canopy.states[0].daily_biomass_g_m2 == 0.0


def test_unplanted_ridges_stay_bare() -> None:
    model = MaizeCropModel(2)
    advance(model)
    assert all(not state.planted for state in model.phenology.states.values())
    assert all(state.aboveground_biomass_g_m2 == 0 for state in model.canopy.states.values())
    assert all(state.grain_moisture_frac is None for state in model.yield_recovery.states.values())


def test_daily_update_idempotence_and_reverse_date_rejected() -> None:
    model = planted()
    advance(model)
    snapshot = model.get_state()
    day = START + timedelta(days=140)
    model.update_day(day, weather(day, rain=50), *inputs(water=0.12))
    assert model.get_state() == snapshot
    with pytest.raises(ValueError, match="backwards"):
        model.update_day(day - timedelta(days=1), weather(day), *inputs())
    assert model.get_state() == snapshot


@pytest.mark.parametrize("stress", [
    {"water": 0.12}, {"nutrient": 0.2}, {"disease": 0.9},
])
def test_water_nutrient_and_disease_reduce_biomass_and_grain(stress: dict) -> None:
    healthy, affected = planted(), planted()
    advance(healthy)
    advance(affected, **stress)
    assert affected.canopy.states[0].aboveground_biomass_g_m2 < healthy.canopy.states[0].aboveground_biomass_g_m2
    assert affected.yield_recovery.states[0].biological_yield_g_m2 < healthy.yield_recovery.states[0].biological_yield_g_m2


def test_water_stress_near_silking_has_lasting_kernel_set_effect() -> None:
    early, silking, healthy = planted(), planted(), planted()
    for offset in range(1, 141):
        day = START + timedelta(days=offset)
        for model, start in ((early, 15), (silking, 51), (healthy, 1000)):
            root_water = 0.12 if start <= offset < start + 10 else 0.28
            model.update_day(day, weather(day), *inputs(water=root_water))
    assert silking.canopy.states[0].kernel_set_fraction < early.canopy.states[0].kernel_set_fraction
    assert early.canopy.states[0].kernel_set_fraction == healthy.canopy.states[0].kernel_set_fraction
    assert silking.yield_recovery.states[0].biological_yield_g_m2 < early.yield_recovery.states[0].biological_yield_g_m2


def test_density_and_failed_stand_affect_maize_without_soybean_population() -> None:
    normal, sparse, failed = planted(), planted(density=2), planted(stand=0)
    for model in (normal, sparse, failed):
        advance(model)
    assert sparse.yield_recovery.states[0].biological_yield_g_m2 < normal.yield_recovery.states[0].biological_yield_g_m2
    assert failed.yield_recovery.states[0].biological_yield_g_m2 == 0
    assert failed.canopy.states[0].lai == 0


def test_harvest_settles_current_moisture_once_and_preserves_dry_matter() -> None:
    model = planted()
    advance(model)
    day = START + timedelta(days=140)
    state = model.yield_recovery.states[0]
    moisture_before = state.grain_moisture_frac
    untouched = model.get_state()["yield_recovery"]["1"]
    cursor = model.last_daily_update_day
    model.settle_harvest(day, {0: HarvestAction(machine_quality=0.8)})
    assert state.grain_moisture_frac == moisture_before
    assert model.last_daily_update_day == cursor
    assert model.get_state()["yield_recovery"]["1"] == untouched
    recovered_dry_matter = state.biological_yield_g_m2 * (
        1 - state.field_loss_fraction
    ) * (1 - state.machine_loss_fraction)
    assert state.recovered_yield_g_m2_at_market_moisture * (
        1 - model.params.market_moisture_frac
    ) == pytest.approx(recovered_dry_matter)
    assert state.recovered_yield_g_m2_at_market_moisture <= model.max_recoverable_yield_g_m2
    assert not model.phenology.states[0].planted
    with pytest.raises(ValueError, match="already been harvested"):
        model.settle_harvest(day, {0: HarvestAction()})
    # Daily evolution also leaves harvested biomass and grain untouched.
    harvested = model.get_state()["yield_recovery"]["0"]
    advance(model, first=141, last=142)
    assert model.get_state()["yield_recovery"]["0"] == harvested


def test_premature_or_wet_harvest_rejected_without_state_mutation() -> None:
    model = planted()
    advance(model, last=40)
    snapshot = model.get_state()
    with pytest.raises(ValueError, match="R6"):
        model.settle_harvest(START + timedelta(days=40), {0: HarvestAction()})
    assert model.get_state() == snapshot
    for offset in range(41, 131):
        advance(model, first=offset, last=offset)
        if model.yield_recovery.states[0].r6_reached:
            break
    snapshot = model.get_state()
    with pytest.raises(ValueError, match="too wet"):
        model.settle_harvest(START + timedelta(days=offset), {0: HarvestAction()})
    assert model.get_state() == snapshot


def test_rain_rewets_mature_grain_without_generating_extra_grain() -> None:
    dry, wet = planted(), planted()
    advance(dry, last=130)
    wet.load_state(dry.get_state())
    biological = dry.yield_recovery.states[0].biological_yield_g_m2
    day = START + timedelta(days=131)
    dry.update_day(day, weather(day), *inputs())
    wet.update_day(day, weather(day, rain=30), *inputs())
    assert wet.yield_recovery.states[0].grain_moisture_frac > dry.yield_recovery.states[0].grain_moisture_frac
    assert wet.yield_recovery.states[0].biological_yield_g_m2 == biological


def test_native_snapshot_round_trip_continues_the_same_trajectory() -> None:
    original, restored = planted(), MaizeCropModel(2)
    advance(original, last=65)
    snapshot = json.loads(json.dumps(original.get_state(), allow_nan=False))
    restored.load_state(snapshot)
    assert restored.get_state() == original.get_state()
    assert isinstance(restored.phenology.states[0].stage, MaizeStage)
    assert restored.phenology.states[0].planting_date == START
    for model in (original, restored):
        advance(model, first=66)
        model.settle_harvest(START + timedelta(days=140), {0: HarvestAction()})
    assert restored.get_state() == original.get_state()
    snapshot["phenology"]["0"]["accumulated_gdd"] = 123456
    assert restored.phenology.states[0].accumulated_gdd != 123456


@pytest.mark.parametrize("change", ["version", "parameters", "ridge_count"])
def test_incompatible_snapshots_rejected_atomically(change: str) -> None:
    model = planted()
    advance(model, last=65)
    baseline = model.get_state()
    incoming = json.loads(json.dumps(baseline))
    if change == "version":
        incoming["version"] = 2
    elif change == "parameters":
        incoming["parameters"]["market_moisture_frac"] = 0.155
    else:
        del incoming["canopy"]["1"]
    with pytest.raises(ValueError):
        model.load_state(incoming)
    assert model.get_state() == baseline


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1])
def test_invalid_input_does_not_poison_other_ridges(bad: float) -> None:
    model = planted()
    advance(model, last=30)
    baseline = model.get_state()
    soil, management, biotic = inputs()
    management[1].nutrient_stress = bad
    day = START + timedelta(days=31)
    with pytest.raises(ValueError):
        model.update_day(day, weather(day), soil, management, biotic)
    assert model.get_state() == baseline
    with pytest.raises(ValueError):
        model.update_day(day, weather(day, solar=bad), *inputs())
    assert model.get_state() == baseline


@pytest.mark.parametrize("kwargs", [
    {"gdd_to_r6": 700.0}, {"market_moisture_frac": 1.0},
    {"max_lai": float("nan")}, {"density_opt_plants_m2": 0},
    {"cultivar_id": "FAKE_REAL_CULTIVAR"},
])
def test_invalid_model_parameters_are_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        replace(MaizeParameters(), **kwargs)


def test_unknown_cultivar_or_duplicate_ridge_never_falls_back_to_soybean() -> None:
    model = MaizeCropModel(2)
    baseline = model.get_state()
    for ridges, seed in (([0], "STANDARD"), ([0, 0], "MAIZE_EARLY_2026"),
                         ([0, 4], "MAIZE_EARLY_2026")):
        with pytest.raises(ValueError):
            model.plant(ridges, START, seed, 4.5, {0: 1}, {0: 6.5})
        assert model.get_state() == baseline


def test_extreme_radiation_cannot_exceed_bin_reservation_bound() -> None:
    model = planted()
    for offset in range(1, 141):
        day = START + timedelta(days=offset)
        model.update_day(day, weather(day, solar=10000), *inputs())
    model.settle_harvest(day, {0: HarvestAction()})
    assert model.yield_recovery.states[0].biological_yield_g_m2 == model.params.max_biological_yield_g_m2
    assert model.yield_recovery.states[0].recovered_yield_g_m2_at_market_moisture <= model.max_recoverable_yield_g_m2


def test_explicit_full_replant_resets_only_target_crop_and_keeps_cursor() -> None:
    model = planted()
    advance(model, last=40)
    before = model.get_state()
    day = START + timedelta(days=40)
    with pytest.raises(ValueError, match="already has a planted crop"):
        model.plant([0], day, "MAIZE_EARLY_2026", 4.5, {0: 1}, {0: 6.5})
    model.plant([0], day, "MAIZE_EARLY_2026", 4.5, {0: 0.9}, {0: 7},
                replace_existing=True)
    assert model.last_daily_update_day == day
    assert model.phenology.states[0].stage == MaizeStage.PLANTED_PRE_EMERGENCE
    assert model.phenology.states[0].planting_date == day
    assert model.canopy.states[0].aboveground_biomass_g_m2 == 0
    assert model.canopy.states[0].planting_density_plants_m2 == 7
    assert model.canopy.states[0].stand_fraction == 0.9
    for component in ("phenology", "canopy", "yield_recovery"):
        assert model.get_state()[component]["1"] == before[component]["1"]


def test_nonfinite_snapshot_is_rejected_atomically() -> None:
    model = planted()
    advance(model, last=40)
    before = model.get_state()
    incoming = model.get_state()
    incoming["canopy"]["1"]["lai"] = float("nan")
    with pytest.raises(ValueError, match="snapshot canopy.lai"):
        model.load_state(incoming)
    assert model.get_state() == before
