"""H01 public-tool boundary tests; no full-season run or field calibration."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from dataclasses import replace
import json

import pytest

from fairy.apps.farm_world import FarmWorldApp, WeatherApp
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.physics import SoybeanStage
from fairy.scenarios.maize.header_maintenance import HeaderMaintenanceTractorApp
from fairy.time_manager import SimulationTimeManager


def tools_fixture(*, header=True, ridges=1, hour=8, minute=0):
    farm = FarmWorldApp(num_ridges=ridges, ridge_width_m=.75)
    farm.configure_crop_backend("wofost", crop_name="maize")
    weather = WeatherApp()
    weather.set_weather(date="2026-05-01", temp_c=22., humidity_pct=55.,
                        wind_speed_ms=2., rainfall_mm=0., solar_radiation=240.)
    tractor = (HeaderMaintenanceTractorApp if header else TractorApp)(farm, weather, name="TractorApp")
    clock = SimulationTimeManager()
    clock.reset(datetime(2026, 5, 1, hour, minute,
                         tzinfo=farm.simulation_timezone).timestamp())
    for app in (farm, weather, tractor):
        app.register_time_manager(clock)
    for ridge in farm._ridges:
        ridge.soil_vwc = .27
        ridge.soil_temp_c = 20.
    tractor.configure_harvest(max_grain_moisture_pct=25.)
    farm.advance_physics_time()
    return farm, weather, tractor, clock


def mature_fixture(farm, *, moisture=.24):
    """Mature recovery specimen, like existing native tool tests; not WOFOST output."""
    for rid, ridge in enumerate(farm._ridges):
        ridge.planted = True
        ridge.seed_type = "MAIZE_201"
        ridge.growth_stage = "MATURE"
        ridge.grain_moisture_pct = moisture * 100
        phen = farm.physics.phenology.states[rid]
        phen.planted = phen.emerged = True
        phen.stage = SoybeanStage.MATURE
        phen.maturity_date = date(2026, 5, 1)
        farm.physics.canopy.states[rid].yield_potential_g_m2 = 800.
        farm.physics.canopy.states[rid].aboveground_biomass_g_m2 = 1600.
        recovery = farm.physics.yield_recovery.states[rid]
        recovery.r8_reached = True
        recovery.maturity_date = phen.maturity_date
        recovery.grain_moisture_frac = moisture
        recovery.biological_yield_g_m2 = 800.


def public(tractor, name, **arguments):
    tool = next(item for item in tractor.get_tools() if item.name == name)
    return tool(**arguments)


def test_tools_are_candidate_only_and_inspection_is_a_timed_write():
    farm, _, tractor, clock = tools_fixture()
    _, _, old, _ = tools_fixture(header=False)
    new = {t.name: t for t in tractor.get_tools()}
    old_names = {t.name for t in old.get_tools()}
    assert set(new) - old_names == {"inspect_header", "service_header"}
    assert new["inspect_header"].write_operation is True
    assert new["inspect_header"].to_open_ai()["function"]["name"] == "TractorApp__inspect_header"
    before = clock.time()
    recovery_before = deepcopy(vars(farm.physics.yield_recovery.states[0]))
    result = public(tractor, "inspect_header")
    assert result["status"] == "inspection_completed"
    assert result["condition"] == "maintenance_required"
    assert result["duration_seconds"] == clock.time() - before == 600
    assert not {"warning", "error", "q", "q_pass"}.intersection(result)
    assert vars(farm.physics.yield_recovery.states[0]) == recovery_before
    assert tractor.harvest_batches == []


def test_service_is_optional_to_inspect_and_repeat_is_zero_cost():
    farm, _, tractor, clock = tools_fixture()
    before = clock.time()
    inventory = farm._inventory.to_dict()
    first = public(tractor, "service_header")
    assert first["status"] == "service_completed"
    assert first["condition"] == "serviceable"
    assert first["duration_seconds"] == clock.time() - before == 3600
    after = clock.time()
    second = public(tractor, "service_header")
    assert second["status"] == "already_serviceable"
    assert second["duration_seconds"] == clock.time() - after == 0
    assert farm._inventory.to_dict() == inventory
    assert tractor.get_state()["h01_header"]["last_inspection_at"] is None
    saved = json.loads(json.dumps(tractor.get_state()))
    _, _, restored, _ = tools_fixture()
    restored.load_state(saved)
    assert restored.get_state()["h01_header"] == saved["h01_header"]
    restored.reset()
    assert restored.get_state()["h01_header"]["condition"] == "maintenance_required"


def test_inspection_crossing_midnight_evolves_the_same_physics_as_waiting():
    farm, weather, tractor, clock = tools_fixture(hour=23, minute=55)
    control, control_weather, control_tractor, control_clock = tools_fixture(hour=23, minute=55)
    public(tractor, "inspect_header")
    control_tractor._bind_farm_context()
    control.advance_physics_time()
    control_tractor._farm_context.advance_time(600)
    control.advance_physics_time()
    assert clock.time() == control_clock.time()
    assert farm.physics.last_physics_sim_time == clock.time()
    assert farm.physics.crop_backend.last_day == control.physics.crop_backend.last_day
    assert vars(farm.physics.soil.states[0]) == vars(control.physics.soil.states[0])
    assert weather.get_current_weather_snapshot() == control_weather.get_current_weather_snapshot()
    assert tractor.get_state()["h01_header"]["condition"] == "maintenance_required"


def test_failed_service_does_not_repair_or_discard_elapsed_time(monkeypatch):
    farm, _, tractor, clock = tools_fixture()
    original = farm.advance_physics_time
    calls = 0
    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("deliberate end-sync failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(farm, "advance_physics_time", fail_second)
    before = clock.time()
    with pytest.raises(RuntimeError, match="end-sync"):
        public(tractor, "service_header")
    assert clock.time() - before == 3600
    assert tractor.get_state()["h01_header"]["condition"] == "maintenance_required"
    assert tractor.maintenance_events[-1]["status"] == "service_failed"


@pytest.mark.parametrize("repair,q,loss", [(False, .85, .04), (True, .95, .03)])
def test_public_harvest_uses_one_frozen_q_in_native_action_record_and_ledger(monkeypatch, repair, q, loss):
    farm, _, tractor, _ = tools_fixture()
    if repair:
        public(tractor, "service_header")
    mature_fixture(farm)
    sent = []
    original = farm.physics.queue_harvest
    def capture(ridge, action):
        sent.append((ridge, action.machine_quality, action.pass_completed))
        original(ridge, action)
    monkeypatch.setattr(farm.physics, "queue_harvest", capture)
    result = public(tractor, "harvest", start_ridge=0, end_ridge=0)
    assert result["status"] == "ok"
    assert sent == [(0, q, True)]
    batch = tractor.harvest_batches[0]
    record = farm.physics.action_log[-1]
    assert batch["operation_id"] == record.action_id
    assert batch["action_machine_quality"] == batch["q_pass"] == record.parameters["machine_quality"] == q
    row = batch["per_ridge"][0]
    assert row["machine_loss_fraction"] == pytest.approx(loss)
    assert row["biological_yield_g_m2"] == 800.
    assert row["recovered_dm_kg"] == pytest.approx(row["biological_dm_kg"] * (1 - loss))
    assert row["dm_balance_residual_kg"] == pytest.approx(0., abs=1e-10)
    assert row["loss_components"]["matches_native"] is True
    assert not row["loss_components"]["clipping_applied"]
    assert result["grain_kg_added"] == pytest.approx(batch["standard_grain_kg"], abs=.01)
    assert batch["harvest_started_at"] < batch["harvest_finished_at"] == batch["harvest_registered_at"]
    batch["q_pass"] = 0  # The returned audit copy cannot alter device state.
    assert tractor.harvest_batches[0]["q_pass"] == q


def test_harvest_quality_is_snapshotted_before_time_advances(monkeypatch):
    farm, _, tractor, _ = tools_fixture()
    mature_fixture(farm)
    tractor._bind_farm_context()
    original = tractor._farm_context.advance_time
    def change_condition_during_pass(seconds):
        # Controlled callback probes the boundary; no runtime fault process is added.
        tractor._header_condition = "serviceable"
        return original(seconds)
    monkeypatch.setattr(tractor._farm_context, "advance_time", change_condition_during_pass)
    assert public(tractor, "harvest", start_ridge=0, end_ridge=0)["status"] == "ok"
    assert tractor.harvest_batches[0]["q_pass"] == .85
    assert tractor.harvest_batches[0]["condition_at_start"] == "maintenance_required"
    assert farm.physics.yield_recovery.states[0].machine_loss_fraction == pytest.approx(.04)


def test_illegal_harvest_never_captures_quality_or_spends_time():
    farm, _, tractor, clock = tools_fixture()
    mature_fixture(farm, moisture=.26)
    before = clock.time()
    fuel = tractor._fuel_tank_l
    result = public(tractor, "harvest", start_ridge=0, end_ridge=0)
    assert "error" in result
    assert clock.time() == before
    assert tractor._fuel_tank_l == fuel
    assert tractor.harvest_batches == []
    assert tractor._h01_pass is None


def test_service_only_changes_subsequent_passes():
    farm, _, tractor, _ = tools_fixture(ridges=2)
    mature_fixture(farm)
    assert public(tractor, "harvest", start_ridge=0, end_ridge=0)["status"] == "ok"
    first = deepcopy(vars(farm.physics.yield_recovery.states[0]))
    batch = tractor.harvest_batches[0]
    public(tractor, "service_header")
    assert vars(farm.physics.yield_recovery.states[0]) == first
    assert tractor.harvest_batches[0] == batch
    assert public(tractor, "harvest", start_ridge=1, end_ridge=1)["status"] == "ok"
    assert [b["q_pass"] for b in tractor.harvest_batches] == [.85, .95]


def test_ledger_exposes_native_loss_clipping():
    farm, _, tractor, _ = tools_fixture()
    mature_fixture(farm)
    # Local diagnostic boundary only; the production candidate keeps original parameters.
    farm.physics.yield_recovery.params = replace(
        farm.physics.yield_recovery.params, max_machine_loss_fraction=.035)
    assert public(tractor, "harvest", start_ridge=0, end_ridge=0)["status"] == "ok"
    row = tractor.harvest_batches[0]["per_ridge"][0]
    assert row["loss_components"]["raw"] == pytest.approx(.04)
    assert row["loss_components"]["clipped"] == pytest.approx(.035)
    assert row["loss_components"]["clipping_applied"] is True
    assert row["loss_components"]["matches_native"] is True


def test_legacy_device_still_uses_normal_quality_without_header_tools(monkeypatch):
    farm, _, tractor, _ = tools_fixture(header=False)
    mature_fixture(farm)
    sent = []
    original = farm.physics.queue_harvest
    def capture(ridge, action):
        sent.append(action.machine_quality)
        original(ridge, action)
    monkeypatch.setattr(farm.physics, "queue_harvest", capture)
    assert public(tractor, "harvest", start_ridge=0, end_ridge=0)["status"] == "ok"
    assert sent == [.95]
    assert farm.physics.action_log[-1].parameters["machine_quality"] == .95
