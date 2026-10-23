"""Resource contracts and causal checks for the expanded rice tools."""
from __future__ import annotations

import copy

import pytest

pytest.importorskip("pcse")

from fairy.apps.paddy.drone import PaddyDroneApp
from fairy.apps.paddy.infrastructure import PaddyInfrastructureApp
from fairy.apps.paddy.machinery import PaddyMachineryApp
from fairy.apps.paddy.observations import PaddyObservationApp
from fairy.apps.paddy.operations import PaddyOpsApp
from fairy.apps.paddy.world import PaddyWorldApp
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.rice.scenarios import RiceScenario, configuration, reference_checkpoints, audit_world
from test_rice_paddy import backend, WEATHER


def checkpoint(label, variant="normal"):
    field, weather = configuration(variant)
    w = PaddyWorldApp(field=field, weather=weather)
    w.load_state(copy.deepcopy(reference_checkpoints(variant)[label]))
    return w


def test_public_tool_contract_and_observations_are_not_native_truth():
    s = RiceScenario()
    s.setup()
    counts = {app.name: len(app.get_tools()) for app in s.apps}
    assert counts == {"PaddyWorldApp": 4, "PaddyOpsApp": 16, "PaddyObservationApp": 5,
                      "PaddyMachineryApp": 4, "PaddyInfrastructureApp": 3, "PaddyDroneApp": 3,
                      "WeatherApp": 2, "SystemApp": 3, "AgentUserInterface": 2}
    w = checkpoint("after_transplant")
    obs = PaddyObservationApp(w)
    reports = [w.get_farm_overview(), w.get_inventory(), w.get_plot_state("p1"),
               obs.inspect_crop("p1"), obs.read_water_sensors("p1"),
               obs.inspect_pests("p1"), obs.inspect_establishment("p1"),
               PaddyDroneApp(w).fly_survey(["p1"]), w.get_operation_log()]
    forbidden = {"DVS", "LAI", "TWSO", "TAGP", "RFTRA", "NAVAIL", "crop", "water_ledger"}

    def check(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    for report in reports:
        check(report)
    acquired = w.get_plot_state("p1")["observations"]
    w.run_job(86400)
    assert w.get_plot_state("p1")["observations"] == acquired
    assert obs.read_water_sensors("p1")["timestamp"] > acquired["water:p1"]["timestamp"]


def test_machine_fuel_and_implement_preconditions_are_atomic():
    w = checkpoint("before_puddle")
    machines, ops = PaddyMachineryApp(w), PaddyOpsApp(w)
    machines.detach_implement("tractor")
    before = w.get_state()
    with pytest.raises(ValueError, match="Attach puddler"):
        ops.puddle_and_level("p1")
    with pytest.raises(ValueError, match="capacity"):
        machines.refuel("tractor", 100)
    assert w.get_state() == before
    machines.refuel("tractor", 10)
    machines.attach_implement("tractor", "puddler")
    ops.puddle_and_level("p1")
    assert audit_world(w)["success"]


def test_partial_transplant_starts_native_crop_once_and_rejects_midnight():
    w = checkpoint("before_transplant", "equipment_limit")
    ops = PaddyOpsApp(w)
    PaddyMachineryApp(w).refuel("transplanter", 10)
    ops.load_seedlings("ir72_standard", 37500)
    ops.transplant("p1", "ir72_standard", area_m2=500)
    assert not w.plot("p1").planted and w.backends["p1"].transplant_date is None
    before = w.get_state()
    with pytest.raises(ValueError, match="partial transplant"):
        w.run_job(86400)
    assert w.get_state() == before
    from fairy.apps.system import SystemApp
    system = SystemApp()
    system.register_time_manager(w.time_manager)
    system.attach_farm_world_app(w)
    with pytest.raises(ValueError, match="partial transplant"):
        system.advance_time(days=1)
    assert w.get_state() == before
    ops.load_seedlings("ir72_standard", 37500)
    ops.transplant("p1", "ir72_standard", area_m2=500)
    assert w.plot("p1").planted
    assert sum(e["kind"] == "transplant" for e in w.backends["p1"].journal) == 1
    assert audit_world(w)["success"]


def test_partial_harvest_capacity_and_separate_drying_storage():
    w = checkpoint("before_harvest", "equipment_limit")
    ops = PaddyOpsApp(w)
    PaddyMachineryApp(w).refuel("combine", 10)
    first = ops.harvest("p1", area_m2=400)
    before = w.get_state()
    with pytest.raises(ValueError, match="capacity"):
        ops.harvest("p1")
    assert w.get_state() == before
    batch = w.batch(first["batch_id"])
    dry_mass, original_wet = batch.dry_kg, batch.wet_kg
    ops.unload_grain()
    with pytest.raises(ValueError, match="dry reception"):
        ops.store_grain(batch.batch_id)
    dried = ops.dry_grain(batch.batch_id)
    assert batch.location == "reception" and w.plot("p1").stored_dry_kg == 0
    assert batch.dry_kg == dry_mass
    assert batch.wet_kg + dried["evaporated_water_kg"] == pytest.approx(original_wet)
    assert dried["electricity_kwh"] > 0
    ops.store_grain(batch.batch_id)
    assert batch.location == "stored" and not w.plot("p1").harvested
    assert audit_world(w)["success"]


def test_drying_electricity_and_storage_capacity_fail_before_mutation():
    w = checkpoint("before_dry")
    ops = PaddyOpsApp(w)
    bid = next(b.batch_id for b in w.field.grain_batches if b.location == "reception")
    w.field.electricity_kwh = 0
    before = w.get_state()
    with pytest.raises(ValueError, match="electricity"):
        ops.dry_grain(bid)
    assert w.get_state() == before
    w.field.electricity_kwh = 1000
    ops.dry_grain(bid)
    w.field.storage_capacity_kg = 1
    before = w.get_state()
    with pytest.raises(ValueError, match="capacity"):
        ops.store_grain(bid)
    assert w.get_state() == before


def test_fertilizer_product_mass_reaches_native_n_pool_and_survives_replay():
    w = checkpoint("before_topdress")
    ops = PaddyOpsApp(w)
    machine = PaddyMachineryApp(w)
    if w.machine("tractor").implement != "spreader":
        machine.detach_implement("tractor")
        machine.attach_implement("tractor", "spreader")
    water = w.backends["p1"].water.ledger()["surface_water_mm"]
    if water > 30:
        ops.drain("p1", water - 20)
    ops.load_fertilizer(15)
    before_n = w.backends["p1"].nitrogen.audit()["applied_n_kg_ha"]
    ops.apply_fertilizer("p1", 150)
    assert w.backends["p1"].nitrogen.audit()["applied_n_kg_ha"] - before_n == pytest.approx(69)
    assert audit_world(w)["success"]
    field, weather = configuration("normal")
    restored = PaddyWorldApp(field=field, weather=weather)
    restored.load_state(w.get_state())
    for world in (w, restored):
        world.run_job(5 * 86400)
    assert restored.get_state() == w.get_state()


def native_yield(nitrogen=0., factor=1.):
    b = backend()
    b.apply("transplant", day="2026-01-01")
    b.apply("puddle", sope_cm_day=1., ksub_cm_day=.2)
    b.apply("fertilize", n_kg_ha=nitrogen)
    b.apply("stress", factor=factor)
    for _ in range(120):
        if b.water.states.SS < 2:
            b.apply("water", amount_mm=40.)
        b.apply("day", day=b.model.day.isoformat(), weather=WEATHER)
        assert abs(b.nitrogen.audit()["balance_residual_n_kg_ha"]) < 1e-6
    assert b.maturity
    return b.crop_values["TWSO"]


def test_native_yield_responds_to_nitrogen_and_external_assimilation_loss():
    unfed = native_yield()
    fed = native_yield(140)
    damaged = native_yield(140, .5)
    assert fed > unfed * 1.2
    assert damaged < fed * .9


def test_nitrogen_transport_covers_drain_overflow_and_leak():
    b = backend()
    b.apply("fertilize", n_kg_ha=100)
    for args in ({"amount_mm": 200}, {"amount_mm": 20, "drain": True},
                 {"amount_mm": 10, "drain": True, "leak": True}):
        before = b.nitrogen.audit()["transported_n_kg_ha"]
        b.apply("water", **args)
        assert b.nitrogen.audit()["transported_n_kg_ha"] > before
        assert abs(b.nitrogen.audit()["balance_residual_n_kg_ha"]) < 1e-6


def test_canal_window_blockage_repair_and_bund_leak_affect_physics():
    field, weather = configuration("infrastructure")
    w = PaddyWorldApp(field=field, weather=weather)
    ops, infra = PaddyOpsApp(w), PaddyInfrastructureApp(w)
    before = w.get_state()
    with pytest.raises(ValueError, match="UTC"):
        ops.irrigate("p1", 20)
    assert w.get_state() == before
    w.run_job(6 * 3600)
    blocked = ops.irrigate("p1", 20)["duration_s"]
    infra.clear_channel("supply")
    clear = ops.irrigate("p1", 20)["duration_s"]
    assert blocked > clear * 2
    ops.irrigate("p1", 60)
    w.run_job(86400)
    leaked = w.backends["p1"].water.ledger()["bund_loss_mm"]
    assert leaked > 0
    infra.repair_bund("p1")
    w.run_job(86400)
    assert w.backends["p1"].water.ledger()["bund_loss_mm"] == leaked
    assert w.field.repair_material_kg == 90
    assert audit_world(w)["success"]


def test_gap_filling_preserves_crop_and_recovers_after_delay():
    w = checkpoint("after_transplant", "poor_stand")
    ops = PaddyOpsApp(w)
    p, b = w.plot("p1"), w.backends["p1"]
    ops.load_seedlings("ir72_standard", 18750)
    before_crop = copy.deepcopy(b.crop_values)
    before_date = b.transplant_date
    ops.replant_seedlings("p1", 18750)
    assert b.crop_values == before_crop and b.transplant_date == before_date
    assert p.stand_fraction == .75 and p.pending_stand_recovery == .25
    w.run_job(86400)
    assert p.stand_fraction == .75
    w.run_job(86400)
    assert p.stand_fraction == 1 and p.pending_stand_recovery == 0
    assert sum(e["kind"] == "transplant" for e in b.journal) == 1
    assert audit_world(w)["success"]


def test_treatments_reduce_pressure_and_consume_inputs():
    w = checkpoint("before_treat", "biotic")
    ops, machines = PaddyOpsApp(w), PaddyMachineryApp(w)
    machines.detach_implement("tractor")
    machines.attach_implement("tractor", "sprayer")
    p = w.plot("p1")
    before = (p.pests, p.disease, p.weeds)
    ops.apply_pesticide("p1")
    ops.apply_fungicide("p1")
    pond = w.backends["p1"].water.ledger()["surface_water_mm"]
    if pond > 25:
        ops.drain("p1", pond - 20)
    ops.control_weeds("p1")
    assert all(a < b for a, b in zip((p.pests, p.disease, p.weeds), before))
    assert w.field.insecticide_liters == pytest.approx(9.9)
    assert w.field.fungicide_liters == pytest.approx(9.9)
    w.run_job(86400)
    assert w.backends["p1"].external_factor < 1
    assert audit_world(w)["success"]


def test_drone_battery_weather_and_charging():
    w = checkpoint("after_transplant")
    drone = PaddyDroneApp(w)
    for _ in range(5):
        drone.fly_survey(["p1", "p2"])
    assert drone.check_status()["battery_pct"] == 0
    before = w.get_state()
    with pytest.raises(ValueError, match="Charge"):
        drone.fly_survey(["p1"])
    assert w.get_state() == before
    energy = w.field.electricity_kwh
    drone.charge()
    assert w.field.drone_battery_pct == 100
    assert energy - w.field.electricity_kwh == pytest.approx(.4)
    assert audit_world(w)["success"]
    rainy = PaddyWorldApp(weather={"rain_mm": 20})
    with pytest.raises(ValueError, match="weather"):
        PaddyDroneApp(rainy).fly_survey(["p1"])


def test_waiting_to_harvest_loses_standing_mass():
    w = checkpoint("before_harvest")
    p = w.plot("p1")
    biological = w.backends["p1"].crop_values["TWSO"]
    before = p.field_loss_dry_kg
    w.run_job(3 * 86400)
    assert p.field_loss_dry_kg > before
    assert w.backends["p1"].crop_values["TWSO"] == biological


NEW_SCENARIOS = ["scenario_rice_l1_" + task for task in (
    "observe_water", "refuel", "dry", "store", "fertilize", "scout", "repair_bund", "gap_fill")]
NEW_SCENARIOS += ["scenario_rice_l2_" + task for task in (
    "nutrition_management", "crop_protection", "infrastructure_recovery", "harvest_batches")]
NEW_SCENARIOS += ["scenario_rice_l3_" + variant for variant in (
    "nitrogen_limit", "biotic", "infrastructure", "equipment_limit", "poor_stand")]


@pytest.mark.parametrize("scenario_id", NEW_SCENARIOS)
def test_new_scenarios_replay_and_reject_no_action(scenario_id):
    cls = get_scenario_class(scenario_id)
    scenario = cls()
    scenario.setup()
    reference = Engine(None, scenario)
    assert not reference.evaluate().success
    workflow = reference.run_scenario_oracle(run_oracle=True)
    assert reference.evaluate().success
    replay = Engine(None, cls())
    replay.replay_workflow(workflow)
    assert replay.evaluate().success
    assert reference.scenario.get_typed_app(PaddyWorldApp).get_state() == replay.scenario.get_typed_app(PaddyWorldApp).get_state()
