"""Continuous planted-to-stored seasons exercise the real daily engines."""
from datetime import date, datetime, timedelta, timezone

import pytest

from fairy.apps.farm_world.multi_farm import FarmFleet, FarmSite
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario


def _assert_ok(result):
    assert "error" not in result, result
    return result


def _prepare_and_plant(site):
    tractor, farm, profile = site.tractor, site.farm, site.farm.crop_profile
    _assert_ok(tractor.attach_implement("grader"))
    _assert_ok(tractor.level())
    _assert_ok(tractor.load_fertilizer(100.0))
    _assert_ok(tractor.base_fertilize())
    _assert_ok(tractor.form_ridges(farm.ridge_width_m))
    assert farm.get_farm_overview()["season_phase"] == "planting"
    _assert_ok(tractor.load_seeds(profile.seed_type,
        farm.num_ridges * farm.plants_per_ridge_from_spacing(profile.seed_spacing_cm)))
    _assert_ok(tractor.plant_seeds(0, farm.num_ridges - 1,
        profile.planting_depth_cm, profile.seed_spacing_cm))
    assert all(state.planted and not state.emerged
               for state in farm.physics.phenology.states.values())


def test_three_real_crops_advance_on_shared_clock_from_blank_fields_to_storage():
    sites = [FarmSite.create(crop, crop.title(), crop_type=crop,
        num_ridges=2, field_length_m=80.0) for crop in ("soybean", "maize", "rice")]
    fleet, system = FarmFleet(sites), SystemApp()
    start_day = date(2026, 5, 1)
    engine = Engine(None, Scenario(apps=[*fleet.apps, system],
        start_time=datetime(2026, 5, 1, 7, tzinfo=timezone.utc).timestamp()))
    for site in sites:
        farm = site.farm
        for ridge in farm._ridges:
            ridge.soil_vwc, ridge.soil_temp_c, ridge.nutrient_index = 0.26, 20.0, 0.68
        farm.configure_physics_profile("continuous_season_test", auto_season_phase=True)
        for offset in range(191):
            farm.physics.set_weather_day_override(start_day + timedelta(days=offset),
                26.0, 2.0 if 0 < offset < 110 else 0.0, 2.0, 15.0, 22.0, 30.0)
        site.weather.set_weather("2026-05-01", 26.0, 55.0, 2.0, 0.0,
            15.0 / 0.0864, avg_soil_vwc=0.26)
        assert farm.get_farm_overview()["season_phase"] == "prep"
        _prepare_and_plant(site)

    seen_phases = {site.spec.farm_id: {"prep", "planting"} for site in sites}
    maturity_dates, yields_at_maturity, stored = {}, {}, set()
    for day in range(1, 181):
        _assert_ok(system.advance_time(days=1))
        for site in sites:
            farm, farm_id = site.farm, site.spec.farm_id
            seen_phases[farm_id].add(farm.get_farm_overview()["season_phase"])
            if farm_id in stored:
                continue
            if day in (20, 55):
                _assert_ok(farm.apply_fertigation(0, 1, 0.5, 0.0))
            if day % 7 == 0 and farm.physics.soil.states[0].root_vwc < 0.24:
                _assert_ok(site.field_ops.irrigate(0, 1, 4.0))
            recovery = farm.physics.yield_recovery.states[0]
            if recovery.r8_reached and farm_id not in maturity_dates:
                maturity_dates[farm_id] = recovery.maturity_date
                yields_at_maturity[farm_id] = recovery.biological_yield_g_m2
                assert recovery.biological_yield_g_m2 > 20.0
                assert farm.physics.canopy.states[0].aboveground_biomass_g_m2 > 40.0
            if recovery.r8_reached:
                # Maturity and biological grain survive waiting for another
                # farm's work and for a dry, trafficable harvest window.
                assert recovery.maturity_date == maturity_dates[farm_id]
                assert recovery.biological_yield_g_m2 == yields_at_maturity[farm_id]
                assert farm._ridges[0].growth_stage == farm.crop_profile.mature_stage
            if (recovery.r8_reached and site.weather.rainfall_mm == 0.0
                    and recovery.grain_moisture_frac * 100 <= farm.crop_profile.harvest_moisture_max_pct
                    and site.weather._is_trafficable()):
                result = _assert_ok(site.tractor.harvest(0, 1))
                assert result["grain_kg_added"] > 0
                _assert_ok(site.tractor.unload_grain())
                _assert_ok(farm.dry_grain(farm.crop_profile.storage_moisture_max_pct))
                _assert_ok(farm.store_grain())
                assert farm.get_inventory()["warehouse_grain_kg"] > 0
                assert farm.get_inventory()["harvest_grain_kg"] == 0
                stored.add(farm_id)
        if len(stored) == 3:
            break
    assert stored == {"soybean", "maize", "rice"}
    assert len(set(maturity_dates.values())) > 1
    assert all(phases == {"prep", "planting", "growing", "harvest"}
               for phases in seen_phases.values())
    assert all(site.farm.physics.last_physics_sim_time == pytest.approx(
        engine.time_manager.time(), abs=0.1) for site in sites)


def test_automatic_phase_does_not_override_legacy_scenario_labels():
    site = FarmSite.create("legacy", "Legacy", num_ridges=1)
    engine = Engine(None, Scenario(apps=site.apps,
        start_time=datetime(2026, 5, 1, 7, tzinfo=timezone.utc).timestamp()))
    site.farm.configure_physics_profile("legacy_test")
    site.farm.set_season_phase("prep")
    site.farm._refresh_auto_season_phase(field_prepared=True)
    assert site.farm.get_farm_overview()["season_phase"] == "prep"


def test_planting_windows_are_inclusive_and_optional_latest_date_is_enforced():
    site = FarmSite.create("window", "Window", num_ridges=2)
    engine = Engine(None, Scenario(apps=site.apps,
        start_time=datetime(2026, 5, 1, 0, tzinfo=timezone.utc).timestamp()))
    farm = site.farm
    farm.configure_planting_windows([
        {"start": 0, "end": 0, "earliest_date": "2026-05-02", "latest_date": "2026-05-03"},
        {"start": 1, "end": 1, "earliest_date": "2026-05-02"},
    ])
    assert "not open" in farm.check_planting_window([0])
    engine.time_manager.add_offset(86400)
    assert farm.check_planting_window([0, 1]) is None
    engine.time_manager.add_offset(86400)
    assert farm.check_planting_window([0]) is None
    engine.time_manager.add_offset(86400)
    assert "has closed" in farm.check_planting_window([0])
    assert farm.check_planting_window([1]) is None
    with pytest.raises(ValueError, match="latest_date"):
        farm.configure_planting_windows([{"start": 0, "end": 1,
            "earliest_date": "2026-05-03", "latest_date": "2026-05-02"}])
