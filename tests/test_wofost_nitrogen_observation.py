"""Root-zone nitrogen telemetry follows real native soil pools and coverage."""
from dataclasses import replace
from datetime import date, datetime, time

import pytest

pytest.importorskip("pcse")

from fairy.apps.farm_world import FarmWorldApp, SensorApp
from fairy.controllers.engine import Engine
from fairy.scenarios.wofost_farm import FarmDefinition, WofostReferenceScenario
from wofost_model_experiments import ModelExperimentSession


class NitrogenObservationScene(WofostReferenceScenario):
    WORLD = FarmDefinition(
        "lille", "SOYBEAN_901", "Europe/Paris", date(2019, 4, 28), date(2019, 11, 15),
        num_ridges=12, initial_available_n_kg_ha=30., base_soil_n_kg_ha=40.,
        base_fertilizer_kg=0., required_field_preparation_ops=("level", "form_ridges"),
    )
    DESCRIPTION = "Native soil nitrogen observation regression"

    def build_events_flow(self):
        return []


def runtime(**changes):
    definition = replace(NitrogenObservationScene.WORLD, **changes)
    cls = type("ConfiguredNitrogenObservationScene", (NitrogenObservationScene,), {"WORLD": definition})
    scene = cls()
    scene.setup()
    engine = Engine(agent=None, scenario=scene)
    return scene, ModelExperimentSession(engine)


def roots(session):
    return session.call("root_zone_observation", "SensorApp__read_root_zone_sensors")["root_zone_sensors"]


def sow(session, scene, last_ridge):
    def tractor(method, **args):
        return session.call(method, "TractorApp__" + method, args)

    tractor("attach_implement", implement="grader")
    tractor("level")
    tractor("detach_implement")
    tractor("attach_implement", implement="furrower")
    tractor("form_ridges", ridge_width_m=scene.WORLD.ridge_width_m)
    tractor("detach_implement")
    farm = scene.get_typed_app(FarmWorldApp)
    tractor("load_seeds", seed_type=scene.WORLD.seed_type,
            count=round((last_ridge + 1) * 40 * farm.ridge_area_m2))
    tractor("plant_seeds", start_ridge=0, end_ridge=last_ridge, depth_cm=4.,
            seed_spacing_cm=100 * farm.crop_profile.rows_per_ridge / (40 * farm.ridge_width_m))
    morning = datetime.combine(date(2019, 4, 29), time(7), session.timezone).timestamp()
    session.advance_to("first_completed_native_day", morning)


def test_unstarted_native_soil_is_unavailable_instead_of_zero_or_configured_initial_value():
    scene, session = runtime()
    readings = roots(session)
    backend = scene.get_typed_app(FarmWorldApp).physics.crop_backend
    assert not backend.has_started
    for reading in readings:
        nitrogen = reading["soil_nitrogen"]
        assert nitrogen["source"] == "PCSE_CNB_model_telemetry"
        assert nitrogen["status"] == "not_started"
        assert nitrogen["coverage_ridges"] == 2 and nitrogen["initialized_ridges"] == 0
        assert nitrogen["native_effective_day"] is None
        assert nitrogen["available_n_kg_ha"] is None
        assert nitrogen["reserve_n_kg_ha"] is None
    assert all("soil_nitrogen" not in reading for reading in
               scene.get_typed_app(SensorApp).read_soil_sensors()["soil_sensors"])


def test_native_zone_means_track_real_pools_through_maturity_without_cross_farm_leakage():
    scene, session = runtime()
    other_scene, other_session = runtime(farm_id="other", initial_available_n_kg_ha=100.)
    sow(session, scene, 3)
    sow(other_session, other_scene, 3)
    farm = scene.get_typed_app(FarmWorldApp)
    first = roots(session)
    other = roots(other_session)
    for index in (0, 1):
        nitrogen = first[index]["soil_nitrogen"]
        ids = range(first[index]["ridge_start"], first[index]["ridge_end"] + 1)
        models = [farm.physics.crop_backend._runs[rid].model for rid in ids]
        assert nitrogen["status"] == "native"
        assert nitrogen["initialized_ridges"] == nitrogen["coverage_ridges"] == 2
        assert nitrogen["native_effective_day"] == "2019-04-28"
        assert nitrogen["available_n_kg_ha"] == pytest.approx(
            sum(model.get_variable("NAVAIL") for model in models) / 2, abs=.000051)
        assert nitrogen["reserve_n_kg_ha"] == pytest.approx(
            sum(model.get_variable("NSOIL") for model in models) / 2, abs=.000051)
        assert other[index]["soil_nitrogen"]["available_n_kg_ha"] - nitrogen["available_n_kg_ha"] == pytest.approx(70.)
    assert all(reading["soil_nitrogen"]["status"] == "not_started" for reading in first[2:])

    session.advance_to("after_native_crop_maturity",
        datetime.combine(date(2019, 10, 15), time(7), session.timezone).timestamp())
    mature = roots(session)
    assert all(run.model.crop is None for run in farm.physics.crop_backend._runs.values())
    assert mature[0]["soil_nitrogen"]["status"] == "native"
    assert mature[0]["soil_nitrogen"]["native_effective_day"] == "2019-10-14"
    assert mature[0]["soil_nitrogen"]["available_n_kg_ha"] == pytest.approx(
        farm.physics.crop_backend._runs[0].model.get_variable("NAVAIL"), abs=.000051)


def test_partial_native_zone_does_not_report_a_partial_average_as_full_coverage():
    scene, session = runtime()
    sow(session, scene, 0)
    readings = roots(session)
    first = readings[0]["soil_nitrogen"]
    assert first["status"] == "partial_native_coverage"
    assert first["coverage_ridges"] == 2 and first["initialized_ridges"] == 1
    assert first["available_n_kg_ha"] is None and first["reserve_n_kg_ha"] is None
    assert first["native_effective_day"] is None
    assert all(reading["soil_nitrogen"]["status"] == "not_started" for reading in readings[1:])


def test_current_day_local_nitrogen_event_is_visible_before_growth_and_fertilizer_enters_next_native_day():
    scene, session = runtime()
    sow(session, scene, 3)
    farm = scene.get_typed_app(FarmWorldApp)
    backend = farm.physics.crop_backend
    before = roots(session)
    original = before[0]["soil_nitrogen"]["available_n_kg_ha"]
    backend.apply_soil_nitrogen_event(event_id="local_cut", day=date(2019, 4, 29),
        ridge_ids=[0], available_n_kg_ha=0., reserve_n_kg_ha=0.)
    changed = roots(session)
    zone = changed[0]["soil_nitrogen"]
    assert zone["status"] == "native"
    assert zone["available_n_kg_ha"] == pytest.approx(original / 2, abs=.000051)
    assert zone["native_effective_day"] == "2019-04-28"
    assert zone["nitrogen_state_effective_day"] == "2019-04-29"
    assert changed[1]["soil_nitrogen"] == before[1]["soil_nitrogen"]

    session.call("load_actual_fertilizer", "TractorApp__load_fertilizer", {"kg": 1.})
    session.call("apply_actual_fertilizer", "TractorApp__apply_fertilizer",
        {"start_ridge": 0, "end_ridge": 0, "kg_per_ridge": 1.})
    assert roots(session)[0]["soil_nitrogen"] == zone
    session.advance_to("settle_native_fertilizer_day",
        datetime.combine(date(2019, 4, 30), time(7), session.timezone).timestamp())
    recovered_n = .46 * .7 * 10000 / farm.ridge_area_m2
    assert backend.native_soil_nitrogen([0])[0]["available_n_kg_ha"] == pytest.approx(recovered_n)
    after = roots(session)[0]["soil_nitrogen"]
    assert after["available_n_kg_ha"] > zone["available_n_kg_ha"]
    assert after["native_effective_day"] == after["nitrogen_state_effective_day"] == "2019-04-29"


def test_legacy_root_zone_response_stays_water_only_and_tool_description_names_model_limits():
    farm = FarmWorldApp(num_ridges=2)
    farm.configure_physics_profile("legacy_nitrogen_observation_test")
    farm.sync_initial_physics_state()
    sensor = SensorApp(farm)
    assert all("soil_nitrogen" not in reading for reading in sensor.read_root_zone_sensors()["root_zone_sensors"])
    tool = next(tool for tool in sensor.get_tools() if tool.name == "read_root_zone_sensors")
    description = tool.to_open_ai()["function"]["description"]
    assert "kg N/ha" in description and "plant nitrogen-deficiency" in description

