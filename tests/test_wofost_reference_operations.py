"""Reference-world helpers use real registered resources and bounded time."""
from dataclasses import replace
from datetime import date, datetime, time, timedelta

import pytest

pytest.importorskip("pcse")

from fairy.apps.farm_world import FarmWorldApp, RobotApp, TractorApp
from fairy.controllers.engine import Engine
from wofost_model_experiments import ModelExperimentSession, ExperimentalFarmTools
from fairy.scenarios.wofost_farm import FarmDefinition, WofostReferenceScenario


def runtime(**options):
    definition = FarmDefinition("lille", "SOYBEAN_901", "Europe/Paris", date(2019, 4, 28), date(2019, 10, 1))
    definition = replace(definition, **options)

    class AuditScene(WofostReferenceScenario):
        WORLD = definition
        DESCRIPTION = "Registered-operation regression"

        def build_events_flow(self):
            self.events = []

    scene = AuditScene()
    scene.setup()
    engine = Engine(agent=None, scenario=scene)
    session = ModelExperimentSession(engine)
    return scene, session, ExperimentalFarmTools(scene, session)


def steps(session, method):
    return [step for step in session.workflow.dag.values()
            if (step.tool_name or "").endswith("__" + method)]


def test_default24_ridges_real_sowing_preserves_exact_official_TDWI_and_zero_background():
    scene, session, tools = runtime()
    farm = scene.get_typed_app(FarmWorldApp)
    assert farm.num_ridges == 24 and farm.field_area_m2 == pytest.approx(7075.2)
    spacing = 100 * 2 / (1.1 * 40)
    assert farm.plants_per_ridge_from_spacing(spacing) == 11792
    assert farm.plants_per_ridge_from_spacing(spacing) / farm.ridge_area_m2 == 40.
    assert farm.physics.biotic.params.recruitment_fraction == 0
    assert all((s.weed_pressure, s.insect_pressure, s.disease_pressure) == (0, 0, 0)
               for s in farm.physics.biotic.states.values())
    tools.implement("mount_grader", "grader")
    tools.call("level", "TractorApp", "level")
    tools.call("detach_grader", "TractorApp", "detach_implement")
    tools.call("load_base", "TractorApp", "load_fertilizer", kg=scene.WORLD.base_fertilizer_kg)
    tools.call("base", "TractorApp", "base_fertilize", total_kg=scene.WORLD.base_fertilizer_kg)
    tools.implement("mount_furrower", "furrower")
    tools.call("ridges", "TractorApp", "form_ridges", ridge_width_m=1.1)
    tools.call("detach_furrower", "TractorApp", "detach_implement")
    tools.load_seeds_for("seed_stock", 4 * 11792)
    tools.call("plant", "TractorApp", "plant_seeds", start_ridge=0, end_ridge=3,
               depth_cm=4., seed_spacing_cm=spacing)
    boundary = datetime.combine(session.today + timedelta(days=1), time(), session.timezone).timestamp()
    session.advance_to("first_completed_native_day", boundary)
    native = farm.physics.crop_backend.snapshot()["ridges"]
    assert len(native) == 4
    for row in native.values():
        assert row["specification"]["density_plants_m2"] == 40.
        assert row["specification"]["crop_parameters"]["TDWI"] == 120.
    assert all((s.weed_pressure, s.insect_pressure, s.disease_pressure) == (0, 0, 0)
               for s in farm.physics.biotic.states.values())


def test_public_ground_confirmation_uses_the_modality_specific_confidence():
    observations = {0: {"disease_present": True, "disease_confidence": .9,
                        "pest_present": True, "pest_confidence": .59,
                        "weed_present": True, "weed_confidence": .6}}
    assert ExperimentalFarmTools.confirmed(observations, "disease") == [0]
    assert ExperimentalFarmTools.confirmed(observations, "insect") == []
    assert ExperimentalFarmTools.confirmed(observations, "weed") == [0]


def test_water_clips_to_real_field_equivalent_quota_and_exhausted_quota_does_no_work():
    scene, session, tools = runtime(irrigation_quota_mm=2.)
    assert tools.water("bounded_water", 0, 3, 20.) is True
    receipt = steps(session, "irrigate")[-1]
    assert receipt.tool_args["hours"] == pytest.approx(2.4)
    assert receipt.content["field_equivalent_irrigation_mm"] == pytest.approx(2.)
    public = tools.inventory("remaining_water")
    assert public["management_regime"]["irrigation_used_mm_total"] == pytest.approx(2.)
    before = session.now
    assert tools.water("exhausted_water", 4, 7, 8.) is False
    assert session.now == before
    assert len(steps(session, "irrigate")) == 1


def test_prepare_spray_detaches_prior_implement_and_loads_only_missing_correct_class(monkeypatch):
    scene, session, tools = runtime()
    tools.implement("prior_implement", "grader")
    monkeypatch.setattr(tools, "ready", lambda *args: ([], {"rainfall_mm": 0, "wind_speed_ms": 2}))
    before = tools.inventory("stock_before")["pesticide_liters"]
    tools.prepare_spray("prepare_fungicide", "disease", 15.2)
    status = tools.call("sprayer_status", "TractorApp", "get_status")
    assert status["attached_implement"] == "sprayer"
    assert status["fungicide_tank_l"] == pytest.approx(15.2)
    assert status["pesticide_tank_l"] == 0
    assert tools.inventory("stock_after")["pesticide_liters"] == pytest.approx(before - 15.2)
    assert len(steps(session, "detach_implement")) == 1
    tools.prepare_spray("already_loaded", "disease", 7.6)
    assert len(steps(session, "load_fungicide")) == 1


def test_insufficient_chemical_is_a_recorded_failure_without_free_tank_payload(monkeypatch):
    scene, session, tools = runtime(warehouse_pesticide_l=1.)
    monkeypatch.setattr(tools, "ready", lambda *args: ([], {}))
    with pytest.raises(RuntimeError, match="Insufficient chemical"):
        tools.prepare_spray("short_chemical", "disease", 15.2)
    failed = steps(session, "load_fungicide")[-1]
    assert failed.content.get("error")
    assert scene.get_typed_app(TractorApp).get_status()["fungicide_tank_l"] == 0
    assert scene.get_typed_app(FarmWorldApp).get_inventory()["pesticide_liters"] == 1.


def test_inspection_charges_low_battery_and_waits_real_completion_time():
    scene, session, tools = runtime()
    robot = scene.get_typed_app(RobotApp)
    robot._battery_pct = 15.
    before = session.now
    result = tools.inspect("low_battery_ground", 0, 3)
    assert set(result) == {0, 1, 2, 3}
    assert len(steps(session, "charge")) == 1
    assert session.now >= before + 3600
    assert robot.check_status()["battery_pct"] == 80.


def test_charge_wait_cannot_cross_scene_deadline_and_no_inspection_is_fabricated():
    scene, session, tools = runtime()
    scene.get_typed_app(RobotApp)._battery_pct = 15.
    before = session.now
    session.deadline = before + 1800
    with pytest.raises(RuntimeError, match="deadline"):
        tools.inspect("late_charge", 0, 3)
    assert session.now == before
    assert len(steps(session, "charge")) == 1
    assert not steps(session, "inspect_crop_health")


def test_empty_common_fuel_store_cannot_create_tractor_fuel():
    scene, session, tools = runtime(warehouse_fuel_l=0, tractor_fuel_l=15)
    with pytest.raises(RuntimeError, match="Insufficient fuel"):
        tools.fuel("empty_fuel")
    assert steps(session, "refuel")[-1].content.get("error")
    assert scene.get_typed_app(TractorApp).get_status()["fuel_tank_l"] == 15
