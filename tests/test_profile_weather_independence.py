"""Scenario weather must not be rewritten to accommodate an Oracle calendar."""

from dataclasses import asdict
from datetime import date
import hashlib
import json

import pytest

from fairy.apps.farm_world.physics_orchestrator import _generate_weather_day
from fairy.physics.profiles import get_profile
from fairy.physics.weather_engine import WeatherGenerator


def _profile(name):
    profile = get_profile(name)
    assert profile is not None
    return profile


def _generator(profile):
    return WeatherGenerator(profile.to_weather_generator_config(), seed=profile.rng_seed)


def test_seed_only_nutrition_profile_keeps_background_weather():
    profile = _profile("harbin_l3_rhizobia_nodulation_failure_nutrition_seed_1702")
    start, end = date(2026, 7, 20), date(2026, 9, 21)
    actual = _generator(profile).generate(start, end, profile.weather_events)
    background = _generator(profile).generate(start, end)

    assert actual == background
    assert any(day.rain_mm > 0 for day in actual)


def test_named_late_harvest_rain_survives_daily_runtime_generation():
    profile = _profile("harbin_l3_laterain_insect_risk_seed_1723")
    actual = _generate_weather_day(
        _generator(profile), date(2026, 10, 10), profile.weather_events
    )

    assert actual.rain_mm > 0
    assert "post_window_laterain_insect_harvest_rain" in actual.weather_tags


def test_named_rootzone_recharge_is_not_erased_by_an_oracle_window():
    profile = _profile("harbin_l3_r5_heat_stress_without_soil_drought_seed_1726")
    actual = _generate_weather_day(
        _generator(profile), date(2026, 8, 1), profile.weather_events
    )

    assert actual.rain_mm > 0
    assert "pre_heat_rootzone_recharge" in actual.weather_tags


@pytest.mark.parametrize("day, delta", [(date(2026, 8, 5), 7.0), (date(2026, 8, 20), 0.0)])
def test_only_the_named_heat_pulse_changes_temperature(day, delta):
    profile = _profile("harbin_l3_r5_heat_stress_without_soil_drought_seed_1726")
    actual = _generator(profile).generate(day, day, profile.weather_events)[0]
    background = _generator(profile).generate(day, day)[0]

    assert actual.air_temp_mean_c == pytest.approx(background.air_temp_mean_c + delta)
    assert actual.air_temp_min_c == pytest.approx(background.air_temp_min_c + delta)
    assert actual.air_temp_max_c == pytest.approx(background.air_temp_max_c + delta)


def test_explicit_drought_stays_dry_without_a_second_hidden_solar_boost():
    profile = _profile("harbin_l3_split_irrigation_schedule_power_limit_seed_1731")
    day = date(2026, 8, 3)
    actual = _generator(profile).generate(day, day, profile.weather_events)[0]
    background = _generator(profile).generate(day, day)[0]

    assert actual.rain_mm == 0
    assert "split_irrigation_dry_spell" in actual.weather_tags
    assert actual.solar_rad_mj_m2 == round(background.solar_rad_mj_m2 * 1.10, 2)


@pytest.mark.parametrize(
    "name, before_sha256",
    [
        ("harbin_baseline_2026_seed_101", "f108d5637d14f22c5075df0d164c734ee28a531e71ceffa57ba16b63724a8500"),
        ("harbin_l3_high_weed_seedbank_seed_1518", "a922c8ad86842af1b69158d844b96ee43a8e924fdb88c954fb8a79021a2797f8"),
        ("harbin_l3_hn84_dryr5r6_waterlimit_seed_1526", "1f6d5ada8429c3e3352775fa4378ea32848d3b2356d1af31ce1b29e759b98a3f"),
    ],
)
def test_earlier_profiles_keep_their_complete_weather_trace(name, before_sha256):
    # Captured before removing seed>=1700 injection. These profiles contain
    # no rain_event, so an independent fix to event rainfall splitting does
    # not freeze that old bug into this profile-level regression.
    profile = _profile(name)
    trace = _generator(profile).generate(
        date(2026, 5, 5), date(2026, 10, 31), profile.weather_events
    )
    encoded = json.dumps(
        [asdict(day) for day in trace], sort_keys=True, default=str, separators=(",", ":")
    ).encode()

    assert hashlib.sha256(encoded).hexdigest() == before_sha256


def test_existing_normal_hn84_keeps_its_explicit_wet_august_definition():
    profile = _profile("harbin_hb_base_hn84_std_normal_seed_1101")

    assert profile.monthly_climate[8].precip_mm == pytest.approx(110 * 1.65)
    assert [
        (event.event_type, event.start_date, event.duration_days, event.total_rain_mm, event.label)
        for event in profile.weather_events
    ] == [
        ("rain_event", date(2026, 8, 2), 3, 42.0, "normal_podfill_rain"),
        ("rain_event", date(2026, 8, 18), 2, 30.0, "normal_late_podfill_rain"),
    ]
