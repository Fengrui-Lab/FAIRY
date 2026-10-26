"""Treatment quantity affects knockdown and protection without inventing a day."""
from dataclasses import asdict
from datetime import date, timedelta

import pytest

from fairy.physics.biotic_pressure_engine import (
    BioticCropInput, BioticPressureEngine, BioticPressureState, BioticSoilInput,
    BioticWeatherInput, GrowthStage, TreatmentApplication, TreatmentType,
    chemical_dose_efficacy,
)


DAY = date(2026, 7, 20)
CHEMICALS = [
    (TreatmentType.HERBICIDE, "weed_pressure", "herbicide", 8.0, 0.55),
    (TreatmentType.INSECTICIDE, "insect_pressure", "insecticide", 8.0, 0.65),
    (TreatmentType.FUNGICIDE, "disease_pressure", "fungicide", 3.8, 0.45),
]


def update(engine, *, day=DAY, treatment=None, daily=False):
    return engine.update_day(
        BioticWeatherInput(day, 22, 0),
        {0: BioticCropInput(GrowthStage.R3, canopy_cover=0.7)},
        {0: BioticSoilInput(top_vwc=0.3)},
        {0: [treatment]} if treatment is not None else {},
        advance_daily=daily,
    )


@pytest.mark.parametrize("kind,pressure,prefix,reference,reduction", CHEMICALS)
def test_zero_half_reference_doses_have_distinct_knockdown_and_residual(
    kind, pressure, prefix, reference, reduction
):
    final_pressures = []
    for fraction in (0.0, 0.5, 1.0):
        engine = BioticPressureEngine(num_ridges=1)
        setattr(engine.states[0], pressure, 0.8)
        efficacy = chemical_dose_efficacy(kind, fraction * reference)
        update(engine, treatment=TreatmentApplication(kind, efficacy))
        state = engine.states[0]
        assert getattr(state, pressure) == pytest.approx(0.8 * (1 - reduction * fraction))
        assert getattr(state, f"{prefix}_residual_strength") == pytest.approx(fraction)
        assert (getattr(state, f"{prefix}_residual_days_left") > 0) == (fraction > 0)
        assert state.last_daily_update_day is None
        for offset in range(3):
            update(engine, day=DAY + timedelta(days=offset), daily=True)
        final_pressures.append(getattr(state, pressure))
    assert final_pressures[0] > final_pressures[1] > final_pressures[2]


@pytest.mark.parametrize("kind,pressure,prefix,reference,reduction", CHEMICALS)
def test_small_dose_does_not_refresh_a_stronger_expiring_window(
    kind, pressure, prefix, reference, reduction
):
    engine = BioticPressureEngine(num_ridges=1)
    state = engine.states[0]
    setattr(state, f"{prefix}_residual_days_left", 1)
    setattr(state, f"{prefix}_residual_strength", 1.0)
    update(engine, treatment=TreatmentApplication(kind, chemical_dose_efficacy(kind, reference * 1e-6)))
    assert getattr(state, f"{prefix}_residual_days_left") == 1
    assert getattr(state, f"{prefix}_residual_strength") == 1
    update(engine, daily=True)
    assert getattr(state, f"{prefix}_residual_days_left") == 0
    assert getattr(state, f"{prefix}_residual_strength") == 0


def test_same_day_calls_and_roundtrip_preserve_strength_and_pressure_age():
    engine = BioticPressureEngine(num_ridges=1)
    update(engine, treatment=TreatmentApplication(TreatmentType.FUNGICIDE, 0.5))
    update(engine, daily=True)
    before = asdict(engine.states[0])
    update(engine, daily=True)
    assert asdict(engine.states[0]) == before
    restored = BioticPressureEngine(num_ridges=1)
    restored.states[0] = BioticPressureState(**before)
    tomorrow = DAY + timedelta(days=1)
    update(restored, day=tomorrow, daily=True)
    update(engine, day=tomorrow, daily=True)
    assert asdict(restored.states[0]) == asdict(engine.states[0])


def test_historical_active_window_without_strength_restores_full_protection():
    state = BioticPressureState(ridge_id=0, fungicide_residual_days_left=8)
    assert state.fungicide_residual_strength == 1
    assert state.insecticide_residual_strength == state.herbicide_residual_strength == 0


@pytest.mark.parametrize("dose", [-1, float("nan"), float("inf"), True])
def test_invalid_working_fluid_and_efficacy_fail_before_application(dose):
    with pytest.raises(ValueError):
        chemical_dose_efficacy(TreatmentType.FUNGICIDE, dose)
    with pytest.raises(ValueError):
        TreatmentApplication(TreatmentType.FUNGICIDE, dose)


def test_growth_signal_uses_configured_weights_and_rejects_poisoned_pressure():
    engine = BioticPressureEngine(num_ridges=1)
    engine.params.disease_growth_weight = 0.8
    engine.states[0].weed_pressure = engine.states[0].insect_pressure = 0
    engine.states[0].disease_pressure = 0.5
    assert engine.growth_stress_multiplier(0) == pytest.approx(0.6)
    engine.states[0].disease_pressure = float("nan")
    with pytest.raises(ValueError):
        engine.growth_stress_multiplier(0)
