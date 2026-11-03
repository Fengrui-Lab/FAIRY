"""Extension contracts use additional plots and seasons, not duplicated scenarios."""

from datetime import date
from typing import ClassVar

import pytest

from fairy.apps.farm_world.warehouse_app import GrainBatch
from fairy.controllers.engine import Engine
from fairy.scenarios.management_extensions.apps.season_cycle_app import AnnualCropSeason
from fairy.scenarios.management_extensions.L3.scenario_joint_maize_soybean_operating_margin import (
    ScenarioJointCropOperatingMargin,
)
from fairy.scenarios.management_extensions.L4.scenario_two_year_maize_soil_carryover import (
    TwoYearMaizeScenario,
)


def test_third_plot_can_repeat_crop_without_overwriting_stock_or_accounts():
    class ThreeFields(ScenarioJointCropOperatingMargin):
        scenario_id = "test_three_fields"
        fields = ScenarioJointCropOperatingMargin.fields + (
            {
                **ScenarioJointCropOperatingMargin.fields[0],
                "farm_id": "maize_east",
                "ridge_count": 4,
                "app_name": "MaizeEastField",
            },
        )

    scene = ThreeFields(calibrating=True)
    scene.setup()
    Engine(None, scene)
    assert set(scene.irrigation) == {"maize", "soybean", "maize_east"}
    assert len(scene.farm_environment.farms) == 3
    assert scene.warehouse.stock.seed_stock["MAIZE_201"] == 20 * 1340
    for farm, amount in zip(scene.farms, (100.0, 200.0, 300.0)):
        scene.warehouse.grain_batches[farm.farm_id] = GrainBatch(
            batch_id=farm.farm_id,
            origin_farm_id=farm.farm_id,
            crop_id=farm.crop_id,
            cultivar_id="MAIZE_201" if farm.crop_id == "maize" else "SOYBEAN_901",
            ridge_ids=[0],
            quantity_kg=amount,
            moisture_pct=13.0,
            status="stored",
        )
    account = scene.accounts.compute_accounts()
    assert account["stored_kg_by_crop"] == {"maize": 400.0, "soybean": 200.0}
    assert account["currency"] == "USD"
    assert account["stored_grain_value"] == pytest.approx((400*2.16 + 200*4.32)/7.1757)
    scene.farms[2]._management_regime.irrigation_used_mm_total = 100.0
    assert scene.accounts.compute_accounts()["water_m3"] == pytest.approx(80.4)
    scene.calibrating = False
    with pytest.raises(ValueError, match="no calibrated Oracle"):
        scene.build_events_flow()  # Never borrow the two-field benchmark.


def test_three_seasons_use_declared_dates_and_validate_horizon():
    class ThreeSeasons(TwoYearMaizeScenario):
        scenario_id = "test_three_seasons"
        field: ClassVar[dict] = {**TwoYearMaizeScenario.field, "ridge_count": 1}
        seasons = TwoYearMaizeScenario.seasons + (
            AnnualCropSeason(date(2028, 5, 5), date(2028, 10, 31)),
        )
        horizon_days = 920

    scene = ThreeSeasons(calibrating=True)
    scene.setup()
    assert [s.year for s in scene.cycle.seasons] == [2026, 2027, 2028]
    assert len(scene.cycle.farm.physics.profile.weather_events) == 3
    assert scene.duration == 920 * 86400
    with pytest.raises(ValueError, match="horizon"):

        class TooShort(ThreeSeasons):
            horizon_days = 550

        TooShort(calibrating=True)
