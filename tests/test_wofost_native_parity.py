"""Check the adapter's daily-clock convention against unmodified native PCSE."""
from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest

from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.physics import PlantingConfig, SeedType, SoilWeatherInput


def test_deferred_rate_adapter_matches_unmodified_native_wofost() -> None:
    pytest.importorskip("pcse")
    from pcse.base import ParameterProvider, WeatherDataProvider
    from pcse.models import Wofost81_NWLP_CWB_CNB

    from fairy.physics.wofost_backend import WofostBackend, WofostConfig

    start = date(2026, 5, 1)
    physics = FarmPhysicsState(num_ridges=1)
    physics.phenology.plant_ridges(
        [0], PlantingConfig(planting_date=start, seed_type=SeedType.STANDARD)
    )
    physics.management.states[0].stand_fraction = 1.0
    backend = WofostBackend(WofostConfig(external_biotic_coupling=False))

    # Vary both weather and rainfall so a stale forcing/rate or one-day shift
    # cannot pass merely because every day happens to be identical.
    forcing = []
    for offset in range(170):
        mean = 21.0 + (offset % 9) * 0.5
        forcing.append(
            SoilWeatherInput(
                day=start + timedelta(days=offset),
                air_temp_mean_c=mean,
                air_temp_min_c=mean - 6.0,
                air_temp_max_c=mean + 6.0,
                rain_mm=12.0 if offset % 4 == 0 else 0.0,
                solar_rad_mj_m2=16.0 + offset % 7,
                wind_ms=1.5 + (offset % 3) * 0.3,
            )
        )

    def advance_adapter(weather: SoilWeatherInput) -> None:
        backend.advance_day(
            physics=physics,
            day=weather.day,
            weather=weather,
            actions_by_ridge={},
            density_by_ridge={0: backend.config.reference_density_plants_m2},
            ridge_area_m2=174.2,
            humidity_pct=55.0,
        )

    advance_adapter(forcing[0])
    specification = backend._runs[0].specification
    provider = WeatherDataProvider()
    for weather in forcing:
        values = vars(weather)
        provider._store_WeatherDataContainer(
            backend._weather_container(weather.day, values, 55.0), weather.day
        )
    management = [
        {
            start: {
                "CropCalendar": {
                    "crop_name": "soybean",
                    "variety_name": specification["variety"],
                    "crop_start_date": start,
                    "crop_start_type": "sowing",
                    "crop_end_date": None,
                    "crop_end_type": "maturity",
                    "max_duration": backend.config.max_duration_days,
                },
                "TimedEvents": None,
                "StateEvents": None,
            }
        },
        {start + timedelta(days=backend.config.max_duration_days + 3660): None},
    ]
    state_variables = ["DVS", "LAI", "TAGP", "TWSO", "SM", "NAVAIL", "DOM"]
    native = Wofost81_NWLP_CWB_CNB(
        ParameterProvider(
            cropdata=copy.deepcopy(specification["crop_parameters"]),
            soildata=copy.deepcopy(specification["soil_parameters"]),
            sitedata=copy.deepcopy(specification["site_parameters"]),
        ),
        provider,
        management,
        summary_vars=state_variables,
    )

    maturity_boundary = None
    for offset, weather in enumerate(forcing[:-1]):
        if offset:
            previous_transpiration = backend._runs[0].model.get_variable("WTRAT")
            advance_adapter(weather)
            run = backend._runs[0]
            transpiration_increment = run.model.get_variable("WTRAT") - previous_transpiration
            soil_result = backend._soil_results(physics, weather.day)[0]
            # After crop deletion TRA disappears, but soil's boundary-day WTRA
            # is still charged to its balance. The soil tool must report it.
            assert soil_result.transpiration_mm == pytest.approx(transpiration_increment * 10, abs=1e-10)
        native.run(days=1)
        native_summary = native.get_summary_output()
        native_crop_state = native_summary[-1] if native.crop is None else None
        adapted = backend._runs[0]
        assert adapted.model.day == native.day == weather.day + timedelta(days=1)
        for name in state_variables:
            # Crop states cease to be queryable after native crop deletion.
            # Soil states keep evolving in both models after maturity.
            expected = (
                native_crop_state[name]
                if native_crop_state is not None and name not in {"SM", "NAVAIL"}
                else native.get_variable(name)
            )
            actual = adapted.pcse[name]
            if name == "DOM":
                assert actual == expected
            else:
                assert actual == pytest.approx(expected, rel=1e-11, abs=1e-11), (
                    f"{name} diverged at native boundary {native.day}"
                )
        if native_crop_state is not None and maturity_boundary is None:
            maturity_boundary = native.day
        if maturity_boundary is not None and native.day >= maturity_boundary + timedelta(days=7):
            break

    assert maturity_boundary is not None
    assert backend._runs[0].maturity_snapshot["DOM"] == native.get_summary_output()[-1]["DOM"]
    assert physics.phenology.states[0].maturity_date == maturity_boundary - timedelta(days=1)
