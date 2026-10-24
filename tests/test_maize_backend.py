"""Native maize parity, management response and postharvest accounting."""
from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest

from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.physics import (
    CropStage, HarvestAction, ManagementAction, ManagementActionType,
    PhenologyWeatherInput, PlantingConfig, SeedType, SoilWeatherInput,
    YieldGrowthInput, YieldPhenologyInput, YieldRecoveryEngine,
    YieldWeatherInput,
)
from fairy.physics.crop_profiles import get_crop_profile, maize_yield_parameters
from fairy.physics.wofost_backend import WofostBackend, WofostConfig

START = date(2026, 5, 1)
AREA = 268 * 0.75


def _planted():
    physics = FarmPhysicsState(num_ridges=1)
    physics.phenology.plant_ridges(
        [0], PlantingConfig(planting_date=START, seed_type=SeedType.MAIZE_201)
    )
    physics.management.states[0].stand_fraction = 1.0
    return physics


def _forcing(offset, rain_scale=1.0):
    mean = 21.0 + (offset % 9) * 0.5
    return SoilWeatherInput(
        day=START + timedelta(days=offset), air_temp_mean_c=mean,
        air_temp_min_c=mean - 6, air_temp_max_c=mean + 6,
        rain_mm=(12.0 if offset % 4 == 0 else 0.0) * rain_scale,
        solar_rad_mj_m2=16.0 + offset % 7, wind_ms=1.5 + (offset % 3) * 0.3,
    )


@pytest.mark.parametrize("limited", ["normal", "water", "nitrogen"])
def test_maize_daily_native_parity_with_timed_water_and_n(limited):
    pytest.importorskip("pcse")
    from pcse.base import ParameterProvider, WeatherDataProvider
    from pcse.models import Wofost81_NWLP_CWB_CNB

    physics = _planted()
    backend = WofostBackend(WofostConfig(
        crop_name="maize", initial_available_n_kg_ha=5 if limited == "nitrogen" else 50,
        base_soil_n_kg_ha=15 if limited == "nitrogen" else 50,
        soil_n_mineralization_fraction=.002 if limited == "nitrogen" else .025,
    ))
    forcing = [_forcing(i, .15 if limited == "water" else 1.0) for i in range(160)]
    irrigation_day, n_day = START + timedelta(days=20), START + timedelta(days=35)

    def advance(weather):
        actions = []
        if weather.day == irrigation_day:
            actions.append(ManagementAction(ManagementActionType.IRRIGATION, amount=25))
        if weather.day == n_day:
            actions.append(ManagementAction(ManagementActionType.FERTIGATION, amount=1,
                                           metadata={"kg_per_ridge": 3.0}))
        backend.advance_day(physics, weather.day, weather,
                            actions_by_ridge={0: actions}, ridge_area_m2=AREA)

    advance(forcing[0])
    specification = backend._runs[0].specification
    provider = WeatherDataProvider()
    for weather in forcing:
        provider._store_WeatherDataContainer(
            backend._weather_container(weather.day, vars(weather), 55), weather.day
        )
    management = [{START: {
        "CropCalendar": {
            "crop_name": "maize", "variety_name": "Grain_maize_201",
            "crop_start_date": START, "crop_start_type": "sowing",
            "crop_end_date": None, "crop_end_type": "maturity", "max_duration": 366,
        },
        "TimedEvents": [
            {"event_signal": "irrigate", "name": "Irrigation", "comment": "25 mm",
             "events_table": [{irrigation_day: {"amount": 2.5, "efficiency": .92}}]},
            {"event_signal": "apply_n", "name": "Topdress", "comment": "3 kg product/ridge",
             "events_table": [{n_day: {"N_amount": 3 * .46 * 10000 / AREA, "N_recovery": .7}}]},
        ], "StateEvents": None,
    }}, {START + timedelta(days=366 + 3660): None}]
    variables = ["DVS", "LAI", "TAGP", "TWSO", "SM", "NAVAIL", "DOM", "NfixTotal", "TOTIRR"]
    native = Wofost81_NWLP_CWB_CNB(
        ParameterProvider(cropdata=copy.deepcopy(specification["crop_parameters"]),
                          soildata=copy.deepcopy(specification["soil_parameters"]),
                          sitedata=copy.deepcopy(specification["site_parameters"])),
        provider, management, summary_vars=variables,
    )
    maturity_boundary = None
    observed_stages = set()
    for i, weather in enumerate(forcing[:-1]):
        if i:
            advance(weather)
        native.run(days=1)
        final = native.get_summary_output()[-1] if native.crop is None else None
        for name in variables:
            expected = (final[name] if final is not None and name not in {"SM", "NAVAIL", "TOTIRR"}
                        else native.get_variable(name))
            actual = backend._runs[0].pcse[name]
            if name == "DOM":
                assert actual == expected
            else:
                assert actual == pytest.approx(expected, rel=1e-11, abs=1e-11), (weather.day, name)
        phen = physics.phenology.states[0]
        observed_stages.add(phen.stage)
        assert phen.is_mature == (backend._runs[0].pcse["DOM"] is not None)
        if final is not None and maturity_boundary is None:
            maturity_boundary = native.day
        if maturity_boundary is not None and native.day >= maturity_boundary + timedelta(days=7):
            break
    assert maturity_boundary is not None
    assert observed_stages == {CropStage.PLANTED_PRE_EMERGENCE, CropStage.VEGETATIVE,
                               CropStage.REPRODUCTIVE, CropStage.MATURE}
    assert backend._runs[0].pcse["NfixTotal"] == 0
    assert backend._runs[0].cumulative_irrigation_mm == 25
    assert backend._runs[0].cumulative_fertilizer_kg == 3
    assert backend._runs[0].cumulative_n_kg_ha == pytest.approx(3 * .46 * 10000 / AREA)
    restored = WofostBackend.from_state(backend.export_state())
    assert restored.snapshot() == backend.snapshot()


@pytest.mark.parametrize("limitation", ["water", "nitrogen"])
def test_maize_management_improves_yield_under_corresponding_limitation(limitation):
    pytest.importorskip("pcse")
    outcomes = []
    for managed in (False, True):
        physics = _planted()
        backend = WofostBackend({
            "crop_name": "maize", "initial_available_n_kg_ha": 5 if limitation == "nitrogen" else 100,
            "base_soil_n_kg_ha": 15 if limitation == "nitrogen" else 100,
            "soil_n_mineralization_fraction": .002 if limitation == "nitrogen" else .025,
        })
        stress_days = 0
        for offset in range(130):
            weather = _forcing(offset, .15 if limitation == "water" else 1.0)
            actions = []
            if managed and offset in (20, 40, 60, 80):
                actions = ([ManagementAction(ManagementActionType.IRRIGATION, amount=25)]
                           if limitation == "water" else
                           [ManagementAction(ManagementActionType.FERTIGATION, amount=1,
                                             metadata={"kg_per_ridge": 2})])
            backend.advance_day(physics, weather.day, weather, actions_by_ridge={0: actions},
                                ridge_area_m2=AREA)
            output = backend._runs[0].pcse
            stress_name = "RFTRA" if limitation == "water" else "RFRGRL"
            if 0 < output["DVS"] < 1.9 and output[stress_name] < .95:
                stress_days += 1
        assert physics.phenology.states[0].is_mature
        outcomes.append((output["TWSO"], stress_days))
    assert outcomes[0][1] > 0
    assert outcomes[1][0] > outcomes[0][0] * 1.1


def test_maize_yield_uses_native_maturity_and_dry_matter_without_soybean_shatter():
    engine = YieldRecoveryEngine(1, maize_yield_parameters())
    biological = 800.0
    growth = {0: YieldGrowthInput(biological)}
    # A reproductive crop is not harvestable even if it already has grain mass.
    before = engine.update_day(
        YieldWeatherInput(START, 20, 0, 18, 2),
        {0: YieldPhenologyInput(CropStage.REPRODUCTIVE, None)}, growth,
        harvest_actions_by_ridge={0: HarvestAction()},
    )[0]
    assert not before.harvested
    for i in range(30):
        result = engine.update_day(
            YieldWeatherInput(START + timedelta(days=i + 1), 20, 0, 18, 2),
            {0: YieldPhenologyInput(CropStage.MATURE, START)}, growth,
        )[0]
        assert result.field_loss_fraction == 0
        assert result.recovered_yield_bu_ac_at_market_moisture is None
        assert not any("shatter" in tag or "pod" in tag for tag in result.tags)
    assert result.grain_moisture_frac < .14
    assert result.harvest_ready
    result = engine.update_day(
        YieldWeatherInput(START + timedelta(days=31), 20, 0, 18, 2),
        {0: YieldPhenologyInput(CropStage.MATURE, START)}, growth,
        harvest_actions_by_ridge={0: HarvestAction()},
    )[0]
    state = engine.states[0]
    assert result.harvested
    assert state.recovered_yield_g_m2_at_market_moisture * .86 == pytest.approx(
        biological * (1 - state.machine_loss_fraction)
    )


def test_maize_identity_guards_and_density():
    profile = get_crop_profile("maize")
    assert profile.reference_density_plants_m2 == pytest.approx(6.666666666666667)
    assert WofostConfig(crop_name="maize").variety_name == "Grain_maize_201"
    with pytest.raises(ValueError, match="variety_name"):
        WofostConfig(crop_name="maize", variety_name="Soybean_901")
    with pytest.raises(ValueError, match="profiles"):
        WofostConfig(crop_name="maize", cultivar_profile="heilongjiang_heinong84_complete_v1")
    with pytest.raises(ValueError, match="MAIZE_201"):
        WofostConfig(crop_name="maize", cultivar_map={"STANDARD": "Grain_maize_201"})
    with pytest.raises(ValueError, match="Grain_maize_201"):
        WofostConfig(crop_name="maize", cultivar_map={"MAIZE_201": "Grain_maize_202"})
    with pytest.raises(ValueError, match="does not match"):
        WofostConfig(cultivar_map={"MAIZE_201": "Soybean_901"})
    with pytest.raises(ValueError, match="does not match"):
        WofostConfig(parameter_overrides={"MAIZE_201": {"TSUM1": 600}})
    physics = _planted()
    with pytest.raises(ValueError, match="native WOFOST"):
        physics.phenology.update_day(PhenologyWeatherInput(day=START, air_temp_min_c=16,
                                                         air_temp_max_c=28))


def test_maize_backend_rejects_soybean_seed_and_preserves_own_parameters():
    pytest.importorskip("pcse")
    backend = WofostBackend({"crop_name": "maize"})
    physics = _planted()
    physics.phenology.states[0].seed_type = SeedType.STANDARD
    with pytest.raises(ValueError, match="does not match"):
        backend.advance_day(physics, START, _forcing(0))
    assert backend.snapshot()["provenance"]["crop_data"]["sha256"] == (
        "f1bf8e3202418f294873bb3236727e07a10cd2b91c297b3660d46341a84f469d"
    )
