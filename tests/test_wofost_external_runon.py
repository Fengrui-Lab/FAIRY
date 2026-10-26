"""Declared external water is separate from local rain and Agent irrigation."""
from copy import deepcopy
from datetime import date, timedelta
import json

import pytest

from fairy.apps.farm_world import FarmWorldApp
from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
from fairy.physics import ManagementAction, ManagementActionType, PlantingConfig, SeedType, SoilHydraulicModifier, SoilWeatherInput
from fairy.physics.wofost_backend import WofostBackend, WofostConfig


DAY = date(2026, 5, 1)
SOURCE = "Scenario transfer of legacy1.02 capture: declared upslope surface run-on; catchment area/runoff not calibrated"


def config(**extra):
    return WofostConfig(allow_external_runon=True, external_runon_source=SOURCE, **extra)


def physics(*, planted=True, capture=1.02):
    world = FarmWorldApp(num_ridges=1)
    state = world.physics
    state.soil.set_hydraulic_modifiers({0: SoilHydraulicModifier(rainfall_capture_efficiency=capture)})
    if planted:
        plant(state, DAY)
    return world, state


def plant(state, day):
    state.phenology.plant_ridges([0], PlantingConfig(planting_date=day, seed_type=SeedType.STANDARD))
    state.management.states[0].planted = True
    state.management.states[0].stand_fraction = 1.0


def advance(backend, state, day=DAY, *, rain=10, irrigation=0):
    weather = SoilWeatherInput(day=day, air_temp_mean_c=22, air_temp_min_c=16,
                              air_temp_max_c=28, rain_mm=rain, solar_rad_mj_m2=20, wind_ms=2)
    actions = {0: [ManagementAction(ManagementActionType.IRRIGATION, amount=irrigation,
                                   metadata={"water_mm": irrigation})]} if irrigation else {}
    return backend.advance_day(state, day, weather, actions_by_ridge=actions,
                               density_by_ridge={0: 40}, ridge_area_m2=294.8)


def native(backend):
    return backend.snapshot()["ridges"]["0"]


def assert_native_water_balance_closes(backend):
    balance = backend._runs[0].model.soil.waterbalance
    s = balance.states
    error_cm = (s.SSI + s.RAINT + s.TOTIRR + s.WI - s.W + sum(balance._increments_W)
                + s.WLOWI - s.WLOW - s.WTRAT - s.EVWT - s.EVST - s.TSR - s.LOSST - s.SS)
    assert error_cm == pytest.approx(0, abs=1e-8)


@pytest.mark.parametrize("settings", [
    {"allow_external_runon": True},
    {"allow_external_runon": True, "external_runon_source": " "},
    {"allow_external_runon": 1, "external_runon_source": SOURCE},
    {"external_runon_source": SOURCE},
])
def test_external_source_requires_explicit_boolean_permission_and_explanation(settings):
    with pytest.raises(ValueError):
        WofostConfig(**settings)


def test_default_rejects_gain_before_creating_any_native_ridge():
    pytest.importorskip("pcse")
    state = FarmPhysicsState(num_ridges=2)
    state.soil.set_hydraulic_modifiers({1: SoilHydraulicModifier(rainfall_capture_efficiency=1.02)})
    backend = WofostBackend()
    with pytest.raises(ValueError, match="catchment/run-on"):
        backend.bind_physics(state)
    assert not backend.has_started and backend.export_state()["runs"] == {}


def test_declared_source_keeps_native_rain_unchanged_and_no_agent_quota_use():
    pytest.importorskip("pcse")
    world, state = physics()
    backend = WofostBackend(config())
    before = world._management_regime.irrigation_used_mm_total
    actions = deepcopy(state.pending_management_actions_by_ridge)
    advance(backend, state, rain=10)
    run = native(backend)
    assert run["specification"]["site_parameters"]["NOTINF"] == 0
    assert backend._runs[0].model.drv.RAIN == 1  # cm, unmodified10mm weather
    assert backend._runs[0].model.get_variable("RAINT") == 1
    assert run["last_native_inputs"]["external_runon_mm"] == pytest.approx(0.2)
    assert run["last_native_inputs"]["external_runon_source"] == SOURCE
    assert run["last_native_inputs"]["irrigation_mm"] == 0
    assert run["cumulative_irrigation_mm"] == 0
    assert run["cumulative_external_runon_mm"] == pytest.approx(0.2)
    assert run["pcse"]["TOTIRR"] == pytest.approx(0.02)  # only external source, cm
    assert world._management_regime.irrigation_used_mm_total == before
    assert state.pending_management_actions_by_ridge == actions
    assert run["native_TOTIRR_balance_error_mm"] == pytest.approx(0, abs=1e-10)
    assert_native_water_balance_closes(backend)
    journal = backend.export_state()["runs"]["0"]["journal"][0]
    assert journal["weather"]["rain_mm"] == 10
    assert journal["external_runon_mm"] == pytest.approx(0.2)
    assert journal["external_runon_source"] == SOURCE
    assert run["last_native_inputs"]["native_TOTIRR_includes_external_runon"] is True
    assert backend.snapshot()["provenance"]["external_runon"]["source"] == SOURCE


def test_simultaneous_irrigation_and_runon_are_combined_once_with_separate_ledgers():
    pytest.importorskip("pcse")
    world, state = physics()
    backend = WofostBackend(config())
    # This counter is normally written by the successful public irrigation App.
    world.record_irrigation_use(5)
    advance(backend, state, rain=10, irrigation=5)
    run = native(backend)
    assert run["last_native_inputs"]["irrigation_mm"] == 5
    assert run["cumulative_irrigation_mm"] == 5
    assert run["cumulative_native_management_effective_irrigation_mm"] == pytest.approx(4.6)
    assert run["cumulative_external_runon_mm"] == pytest.approx(0.2)
    assert run["last_native_inputs"]["native_effective_irrigation_signal_mm"] == pytest.approx(4.8)
    assert run["pcse"]["TOTIRR"] == pytest.approx(0.48)
    assert world._management_regime.irrigation_used_mm_total == 5
    assert_native_water_balance_closes(backend)


def test_native_runon_checkpoint_roundtrip_and_following_daily_balance_match():
    pytest.importorskip("pcse")
    _, state = physics()
    backend = WofostBackend(config())
    for offset in range(24):
        advance(backend, state, DAY + timedelta(days=offset), rain=10 if offset % 3 == 0 else 0,
                irrigation=4 if offset == 12 else 0)
        assert_native_water_balance_closes(backend)
    payload = json.loads(json.dumps(backend.export_state()))
    restored = WofostBackend.from_state(payload)
    assert restored.snapshot() == backend.snapshot()
    clone = deepcopy(state)
    for offset in range(24, 29):
        day = DAY + timedelta(days=offset)
        advance(backend, state, day, rain=5)
        advance(restored, clone, day, rain=5)
        assert_native_water_balance_closes(backend)
        assert_native_water_balance_closes(restored)
    assert restored.snapshot() == backend.snapshot()


def test_preplant_external_water_is_audited_in_initial_soil_not_reapplied_at_sowing():
    pytest.importorskip("pcse")
    _, state = physics(planted=False)
    backend = WofostBackend(config())
    advance(backend, state, DAY - timedelta(days=1), rain=10)
    saved = json.loads(json.dumps(backend.export_state()))
    backend = WofostBackend.from_state(saved)
    history = backend.snapshot()["preplant_external_runon_inputs"]["0"]
    assert history[0]["external_runon_mm"] == pytest.approx(0.2)
    plant(state, DAY)
    advance(backend, state, rain=0)
    run = native(backend)
    assert run["specification"]["preplant_external_runon_inputs"] == history
    assert run["cumulative_external_runon_mm"] == 0
    assert run["pcse"]["TOTIRR"] == 0
    assert_native_water_balance_closes(backend)


def test_optin_without_capture_gain_does_not_change_native_dynamics():
    pytest.importorskip("pcse")
    _, first = physics(capture=1)
    _, second = physics(capture=1)
    default, opted = WofostBackend(), WofostBackend(config())
    for offset in range(8):
        day = DAY + timedelta(days=offset)
        for backend, state in ((default, first), (opted, second)):
            advance(backend, state, day, rain=5, irrigation=2 if offset == 4 else 0)
        assert native(default)["pcse"] == native(opted)["pcse"]
    assert "external_runon_mm" not in native(default)["last_native_inputs"]
    assert "preplant_external_runon_inputs" not in default.snapshot()


def test_conflicting_local_rainfall_loss_override_is_rejected():
    pytest.importorskip("pcse")
    _, state = physics()
    backend = WofostBackend(config(site_overrides={"NOTINF": 0.1}))
    with pytest.raises(ValueError, match="NOTINF=0"):
        backend.bind_physics(state)
    assert backend.export_state()["runs"] == {}


def test_checkpoint_rejects_runon_amount_without_its_recorded_source_ratio():
    pytest.importorskip("pcse")
    _, state = physics()
    backend = WofostBackend(config())
    advance(backend, state, rain=10)
    saved = json.loads(json.dumps(backend.export_state()))
    saved["runs"]["0"]["journal"][0]["external_runon_mm"] = 10
    with pytest.raises(ValueError, match="declared source/rainfall ratio"):
        WofostBackend.from_state(saved)
