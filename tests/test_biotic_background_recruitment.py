"""Background pressure is optional; declared inoculation and treatment still act."""
from datetime import date, timedelta

import pytest

from fairy.physics.biotic_pressure_engine import (
    BioticPressureEngine, BioticPressureParameters, BioticCropInput,
    BioticSoilInput, BioticWeatherInput, GrowthStage, TreatmentApplication, TreatmentType,
)


FIELDS = ("weed_pressure", "insect_pressure", "disease_pressure")


def closed_engine():
    return BioticPressureEngine(num_ridges=1,
        params=BioticPressureParameters(recruitment_fraction=0),
        initial_weed_pressure=0, initial_insect_pressure=0, initial_disease_pressure=0)


def favorable_day(engine, offset, treatments=None):
    return engine.update_day(
        BioticWeatherInput(date(2026, 6, 1) + timedelta(days=offset), 27, 0),
        {0: BioticCropInput(GrowthStage.V2, canopy_cover=0, weed_stage_multiplier=1,
                           insect_stage_multiplier=1, disease_stage_multiplier=1)},
        {0: BioticSoilInput(.35, .30)}, treatments_by_ridge={0: treatments or []})


def test_zero_seed_source_remains_zero_through30_favorable_days():
    engine = closed_engine()
    for day in range(30):
        favorable_day(engine, day)
    assert all(getattr(engine.states[0], key) == 0 for key in FIELDS)
    assert engine.growth_stress_multiplier(0) == 1


def test_declared_positive_pressure_grows_and_real_treatments_suppress_it_without_background_input():
    untreated, managed = closed_engine(), closed_engine()
    for engine in [untreated, managed]:
        engine.set_pressure([0], weed_pressure=.4, insect_pressure=.4, disease_pressure=.4)
        for day in range(4):
            favorable_day(engine, day)
        assert all(getattr(engine.states[0], key) > .4 for key in FIELDS)
    favorable_day(untreated, 4)
    favorable_day(managed, 4, [TreatmentApplication(kind) for kind in
        [TreatmentType.HERBICIDE, TreatmentType.INSECTICIDE, TreatmentType.FUNGICIDE]])
    for key in FIELDS:
        assert 0 < getattr(managed.states[0], key) < getattr(untreated.states[0], key)
    assert managed.growth_stress_multiplier(0) > untreated.growth_stress_multiplier(0)
    for day in range(5, 10):
        favorable_day(untreated, day);favorable_day(managed, day)
    assert all(getattr(managed.states[0], key) < getattr(untreated.states[0], key) for key in FIELDS)


def test_legacy_default_background_trace_is_unchanged():
    # Frozen before making recruitment configurable: default V2,27C,dry
    # weather and moist soil, ten physical days, zero initial pressures.
    engine = BioticPressureEngine(num_ridges=1, initial_weed_pressure=0,
        initial_insect_pressure=0, initial_disease_pressure=0)
    for day in range(10):
        engine.update_day(BioticWeatherInput(date(2026, 6, 1) + timedelta(days=day), 27, 0),
            {0: BioticCropInput(GrowthStage.V2, canopy_cover=0)}, {0: BioticSoilInput(.35, .30)})
    assert engine.params.recruitment_fraction == .01
    assert engine.states[0].weed_pressure == pytest.approx(.006129514505244467)
    assert engine.states[0].insect_pressure == 0
    assert engine.states[0].disease_pressure == pytest.approx(.0012131101339905147)


@pytest.mark.parametrize("fraction", [-.01, 1.01, float("nan"), True])
def test_invalid_recruitment_fraction_rejected(fraction):
    with pytest.raises(ValueError, match="recruitment_fraction"):
        BioticPressureParameters(recruitment_fraction=fraction)
