"""Actual growth uses nutrient availability once, independently of tool calls.

The coefficient remains an uncalibrated composite-index proxy. These tests
verify data flow, accounting and daily ownership, not a kg-N mass balance.
"""

from copy import deepcopy
from datetime import date, timedelta

import pytest

from fairy.physics.management_effect_engine import (
    ManagementAction,
    ManagementActionType,
    ManagementCropInput,
    ManagementEffectEngine,
    ManagementEffectState,
    ManagementWeatherInput,
)


DAY = date(2026, 7, 10)


def test_unknown_growth_defers_uptake_until_actual_increment_is_available():
    engine = ManagementEffectEngine(num_ridges=2)
    engine.update_day(
        ManagementWeatherInput(DAY),
        crop_by_ridge={
            0: ManagementCropInput(daily_biomass_g_m2=None),
            1: ManagementCropInput(daily_biomass_g_m2=0.0),
        },
    )
    available = engine.params.initial_nutrient_index - engine.params.daily_nutrient_decay
    assert engine.states[0].nutrient_index == available
    assert engine.states[0].last_growth_uptake_day is None
    assert engine.states[1].last_growth_uptake_day == DAY
    assert engine.states[1].daily_growth_uptake_index == 0
    engine.settle_crop_growth(DAY, {0: 20.0})
    actual = engine.states[0]
    assert actual.nutrient_index == pytest.approx(available - 20 * engine.params.nutrient_uptake_coeff)
    assert actual.daily_growth_biomass_g_m2 == 20
    assert actual.daily_growth_uptake_index == pytest.approx(0.0036)
    assert actual.cumulative_growth_uptake_index == pytest.approx(0.0036)
    assert actual.last_growth_uptake_day == DAY
    assert actual.nutrient_stress == pytest.approx(engine._nutrient_stress_from_index(actual.nutrient_index))
    assert engine.states[1].nutrient_index == available


def test_repeated_settlement_and_new_same_day_actions_do_not_double_debit():
    engine = ManagementEffectEngine(num_ridges=1)
    engine.update_day(ManagementWeatherInput(DAY))
    engine.settle_crop_growth(DAY, {0: 20.0})
    before = deepcopy(engine.states)
    # Calendar ownership, rather than another caller's stale biomass value,
    # decides whether a debit has already occurred.
    engine.settle_crop_growth(DAY, {0: 20.0})
    engine.settle_crop_growth(DAY, {0: 99.0})
    assert engine.states == before
    engine.update_day(
        ManagementWeatherInput(DAY),
        {
            0: [ManagementAction(ManagementActionType.FERTIGATION, amount=0.1, metadata={"water_mm": 0.0})],
        },
        crop_by_ridge={0: ManagementCropInput(daily_biomass_g_m2=20.0)},
        advance_daily=False,
    )
    assert engine.states[0].nutrient_index == pytest.approx(before[0].nutrient_index + 0.032)
    assert engine.states[0].cumulative_growth_uptake_index == before[0].cumulative_growth_uptake_index
    engine.settle_crop_growth(DAY, {0: 20.0})
    assert engine.states[0].nutrient_index == pytest.approx(before[0].nutrient_index + 0.032)


def test_later_growth_date_charges_its_increment_and_accumulates_only_uptake():
    engine = ManagementEffectEngine(num_ridges=1)
    for offset, biomass in enumerate((10.0, 20.0, 0.0)):
        day = DAY + timedelta(days=offset)
        engine.update_day(ManagementWeatherInput(day))
        engine.settle_crop_growth(day, {0: biomass})
    state = engine.states[0]
    assert state.nutrient_index == pytest.approx(0.75 - 3 * 0.0008 - 30 * 0.00018)
    assert state.cumulative_growth_uptake_index == pytest.approx(30 * 0.00018)
    assert state.daily_growth_biomass_g_m2 == state.daily_growth_uptake_index == 0
    assert state.last_growth_uptake_day == DAY + timedelta(days=2)


def test_explicit_growth_input_preserves_the_existing_pre_action_debit_order():
    engine = ManagementEffectEngine(num_ridges=1)
    biomass = 12.3456789
    engine.update_day(
        ManagementWeatherInput(DAY),
        crop_by_ridge={
            0: ManagementCropInput(daily_biomass_g_m2=biomass),
        },
    )
    expected = 0.75 - (0.0008 + 0.00018 * biomass)
    assert engine.states[0].nutrient_index == expected
    assert engine.states[0].last_growth_uptake_day == DAY
    assert engine.states[0].daily_growth_biomass_g_m2 == biomass
    engine.settle_crop_growth(DAY, {0: biomass})
    assert engine.states[0].nutrient_index == expected


def test_settlement_before_daily_aging_does_not_cancel_background_depletion():
    engine = ManagementEffectEngine(num_ridges=1)
    engine.settle_crop_growth(DAY, {0: 10.0})
    assert engine.states[0].last_nutrient_decay_day is None
    engine.update_day(
        ManagementWeatherInput(DAY),
        crop_by_ridge={
            0: ManagementCropInput(daily_biomass_g_m2=10.0),
        },
    )
    assert engine.states[0].nutrient_index == pytest.approx(0.75 - 0.0008 - 0.0018)
    assert engine.states[0].cumulative_growth_uptake_index == pytest.approx(0.0018)


def test_subdaily_update_does_not_consume_even_when_growth_is_supplied():
    engine = ManagementEffectEngine(num_ridges=1)
    engine.update_day(
        ManagementWeatherInput(DAY),
        crop_by_ridge={
            0: ManagementCropInput(daily_biomass_g_m2=30.0),
        },
        advance_daily=False,
    )
    state = engine.states[0]
    assert state.nutrient_index == 0.75
    assert state.last_nutrient_decay_day is state.last_growth_uptake_day is None
    assert state.cumulative_growth_uptake_index == 0


def test_growth_settlement_does_not_age_treatments_or_irrigation_memory():
    engine = ManagementEffectEngine(num_ridges=1)
    engine.update_day(
        ManagementWeatherInput(DAY),
        {
            0: [
                ManagementAction(ManagementActionType.FUNGICIDE),
                ManagementAction(ManagementActionType.IRRIGATION, amount=5.0),
            ],
        },
    )
    before = deepcopy(engine.states[0])
    engine.settle_crop_growth(DAY, {0: 30.0})
    after = engine.states[0]
    for field in (
        "fungicide_residual_days_left",
        "days_since_irrigation",
        "recent_irrigation_mm",
        "cumulative_irrigation_mm",
        "cumulative_pesticide_applications",
        "last_nutrient_decay_day",
    ):
        assert getattr(after, field) == getattr(before, field)
    assert set(before.tags) <= set(after.tags)


def test_available_index_limits_actual_debit_and_refreshes_nutrient_tags():
    engine = ManagementEffectEngine(num_ridges=2)
    engine.states[0].nutrient_index = 0.001
    engine.states[1].nutrient_index = 1.051
    engine.states[1].tags = ["fungicide_effect_registered", "nutrient_excess_penalty"]
    engine.settle_crop_growth(DAY, {0: 20.0, 1: 20.0})
    assert engine.states[0].nutrient_index == 0
    assert engine.states[0].daily_growth_uptake_index == pytest.approx(0.001)
    assert engine.states[0].nutrient_stress == engine.params.nutrient_stress_min
    assert "nutrient_stress" in engine.states[0].tags
    assert engine.states[1].nutrient_stress == 1.0
    assert engine.states[1].tags == ["fungicide_effect_registered"]


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf"), -1.0, None, True, "2"])
def test_invalid_later_ridge_rejects_entire_batch_without_partial_debits(invalid):
    engine = ManagementEffectEngine(num_ridges=2)
    before = deepcopy(engine.states)
    with pytest.raises(ValueError, match="finite and nonnegative"):
        engine.settle_crop_growth(DAY, {0: 10.0, 1: invalid})
    assert engine.states == before


@pytest.mark.parametrize("unknown", [2, -1, "1", True])
def test_unknown_ridge_rejects_entire_batch(unknown):
    engine = ManagementEffectEngine(num_ridges=2)
    before = deepcopy(engine.states)
    with pytest.raises(ValueError, match="Unknown growth settlement ridge"):
        engine.settle_crop_growth(DAY, {0: 10.0, unknown: 20.0})
    assert engine.states == before


@pytest.mark.parametrize("cursor", ["last_growth_uptake_day", "last_nutrient_decay_day"])
def test_backdated_later_ridge_rejects_before_modifying_earlier_ridge(cursor):
    engine = ManagementEffectEngine(num_ridges=2)
    setattr(engine.states[1], cursor, DAY + timedelta(days=1))
    before = deepcopy(engine.states)
    with pytest.raises(ValueError, match="backwards"):
        engine.settle_crop_growth(DAY, {0: 10.0, 1: 20.0})
    assert engine.states == before
    with pytest.raises(ValueError, match="backwards"):
        engine.update_day(ManagementWeatherInput(DAY))
    assert engine.states == before


def test_invalid_daily_input_rejects_before_background_aging_any_ridge():
    engine = ManagementEffectEngine(num_ridges=2)
    before = deepcopy(engine.states)
    with pytest.raises(ValueError, match="finite and nonnegative"):
        engine.update_day(
            ManagementWeatherInput(DAY),
            crop_by_ridge={
                0: ManagementCropInput(daily_biomass_g_m2=10.0),
                1: ManagementCropInput(daily_biomass_g_m2=float("nan")),
            },
        )
    assert engine.states == before


def test_old_state_payload_defaults_new_accounting_fields_without_historical_debit():
    payload = vars(ManagementEffectState(0)).copy()
    for name in (
        "last_growth_uptake_day",
        "daily_growth_biomass_g_m2",
        "daily_growth_uptake_index",
        "cumulative_growth_uptake_index",
    ):
        del payload[name]
    restored = ManagementEffectState(**payload)
    assert restored.last_growth_uptake_day is None
    assert restored.cumulative_growth_uptake_index == 0
    engine = ManagementEffectEngine(num_ridges=1)
    engine.states[0] = restored
    engine.settle_crop_growth(DAY, {0: 10.0})
    assert restored.daily_growth_biomass_g_m2 == 10
    assert restored.cumulative_growth_uptake_index == pytest.approx(0.0018)
