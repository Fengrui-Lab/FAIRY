"""Formal-world and stock-PCSE parity, not measured field-yield validation.

The four whole-season cases execute real registered farm tools through Engine.
An independent stock WOFOST engine then receives the original crop YAML, pinned
NASA daily data, declared soil/site assumptions and actual tool-delivered doses.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, time, timedelta
import json
import math

import pytest
import yaml

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp
from fairy.apps.system import SystemApp
from wofost_model_experiments import ModelExperimentEngine
from fairy.scenarios.wofost_events import PressureEvent, install_scenario_events, scenario_events_snapshot
from fairy.scenarios.wofost_farm import DATA, FarmDefinition, WofostReferenceScenario, load_official_reference
from fairy.types import EventRegisterer


REFERENCES = [
    ("lille", "SOYBEAN_901", "Europe/Paris", date(2019, 4, 28)),
    ("clermont_ferrand", "SOYBEAN_902", "Europe/Paris", date(2019, 4, 28)),
    ("valladolid", "SOYBEAN_903", "Europe/Madrid", date(2019, 4, 30)),
    ("bologna", "SOYBEAN_905", "Europe/Rome", date(2019, 4, 30)),
]


class ReferenceWorld(WofostReferenceScenario):
    WORLD = FarmDefinition(reference_id="lille", seed_type="SOYBEAN_901",
        timezone_name="Europe/Paris", sowing_date=date(2019, 4, 28),
        end_date=date(2019, 11, 15), external_biotic_coupling=False)
    DESCRIPTION = "Pinned official WOFOST model reference; no field-trial yield claim."

    def build_events_flow(self):
        install_scenario_events(self, getattr(self, "test_events", []))
        with EventRegisterer.capture_mode() as events:
            self.get_typed_app(AgentUserInterface).send_message_to_agent(self.reference_briefing())
        return events

    def run_experiment(self, session):
        self.test_policy(session)


def make_world(reference=REFERENCES[0], **world_changes):
    reference_id, seed, zone, sowing = reference
    world = replace(ReferenceWorld.WORLD, reference_id=reference_id,
        seed_type=seed, timezone_name=zone, sowing_date=sowing)
    world = replace(world, **world_changes)
    cls = type("DeclaredReferenceWorld", (ReferenceWorld,), {"WORLD": world})
    return cls()


def official_crop(variety):
    manifest = json.loads((DATA / "manifest.json").read_text())
    raw = yaml.safe_load((DATA / manifest["crop_source"]["path"]).read_text())
    values = raw["CropParameters"]["Varieties"][variety]
    return {key: value[0] for key, value in values.items() if key != "Metadata"}


def prepare_and_sow(session, scene):
    """Use warehouse transfers, actual prep work and the real planter."""
    def call(label, method, **args):
        return session.call(label, "TractorApp__" + method, args)

    call("grader", "attach_implement", implement="grader")
    call("level", "level")
    call("detach_grader", "detach_implement")
    call("fertilizer_payload", "load_fertilizer", kg=20.)
    base = call("base_fertilizer", "base_fertilize")
    call("furrower", "attach_implement", implement="furrower")
    call("ridges", "form_ridges", ridge_width_m=scene.WORLD.ridge_width_m)
    call("detach_furrower", "detach_implement")
    farm = scene.get_typed_app(FarmWorldApp)
    count = int(40 * farm.field_area_m2)
    call("seed_payload", "load_seeds", seed_type=scene.WORLD.seed_type, count=count)
    planted = call("sowing", "plant_seeds", start_ridge=0,
        end_ridge=scene.WORLD.num_ridges-1, depth_cm=4.,
        seed_spacing_cm=100. * farm.crop_profile.rows_per_ridge / (40. * farm.ridge_width_m))
    assert planted["seeds_used"] == count
    return base


def next_morning(session, scene, day):
    target = datetime.combine(day, time(7), scene.simulation_timezone).timestamp()
    session.advance_to("next_morning", target)


@pytest.mark.parametrize("reference", REFERENCES, ids=[r[0] for r in REFERENCES])
def test_ordinary_world_defaults_to_explicit_native_backend_without_runner_injection(reference):
    scene = make_world(reference)
    assert scene.crop_backend == "wofost"
    scene.setup()
    engine = ModelExperimentEngine(None, scene)
    farm = scene.get_typed_app(FarmWorldApp)
    weather = scene.get_typed_app(WeatherApp)
    assert farm.physics.crop_backend_name == "wofost"
    config = farm.physics.crop_backend.config
    assert config.cultivar_map == {scene.WORLD.seed_type: scene.reference["variety"]}
    assert config.require_explicit_cultivar_parameters is True
    assert config.parameter_overrides == {} and config.cultivar_profile is None
    assert config.external_biotic_coupling is False
    assert farm.physics.scenario_metadata["daily_settlement"] == "completed_calendar_day"
    assert farm.physics.scenario_metadata["field_trial_validation"] is False
    assert farm.physics.scenario_metadata["parameter_overrides"] == {}
    assert farm.num_ridges == 24 and farm.ridge_area_m2 == pytest.approx(294.8)
    assert farm.field_area_m2 == pytest.approx(7075.2)
    assert farm.physics.soil.params.root_depth_m == 1.2
    assert farm.physics.soil.params.rainfall_capture_efficiency == 1.
    assert farm.simulation_timezone == weather.simulation_timezone == scene.simulation_timezone
    assert datetime.fromtimestamp(engine.start_time, scene.simulation_timezone).isoformat().endswith("07:00:00+02:00")
    assert scene.get_typed_app(SystemApp).get_current_time()["current_datetime"] == f"{scene.WORLD.sowing_date} 07:00:00"
    assert len(scene.events) == 1 and "0.7075 ha" in scene.reference_briefing()


@pytest.mark.parametrize("reference", REFERENCES, ids=[r[0] for r in REFERENCES])
def test_world_pins_every_public_weather_day_and_forecast_without_unit_or_date_shift(reference):
    from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs

    scene = make_world(reference, num_ridges=1)
    scene.setup()
    ModelExperimentEngine(None, scene)
    farm, weather = scene.get_typed_app(FarmWorldApp), scene.get_typed_app(WeatherApp)
    row, daily = load_official_reference(reference[0])
    original = json.loads((DATA / row["source_path"]).read_text())["properties"]["parameter"]
    for record in daily:
        day = date.fromisoformat(record["date"])
        generated = farm.physics.weather_generator._day_overrides[day]
        key = day.strftime("%Y%m%d")
        assert generated.rain_mm == record["rain_mm"] == original["PRECTOTCORR"][key]
        assert generated.solar_rad_mj_m2 == record["shortwave_mj_m2_day"] == original["ALLSKY_SFC_SW_DWN"][key]
        assert generated.air_temp_min_c == record["tmin_c"] == original["T2M_MIN"][key]
        assert generated.air_temp_max_c == record["tmax_c"] == original["T2M_MAX"][key]
        assert generated.air_temp_mean_c == (record["tmin_c"] + record["tmax_c"]) / 2
        assert generated.relative_humidity_pct == record["relative_humidity_pct"] == original["RH2M"][key]
        assert generated.wind_ms == record["wind_2m_m_s"] == original["WS2M"][key]
    day = scene.WORLD.sowing_date
    first = _build_weather_inputs(weather, day, physics=farm.physics, advance_weather=False)
    snapshot = deepcopy(weather.get_current_weather())
    second = _build_weather_inputs(weather, day, physics=farm.physics, advance_weather=False)
    assert first["soil"] == second["soil"]
    assert weather.get_current_weather() == snapshot
    assert snapshot["date"] == day.isoformat()
    tomorrow = next(item for item in daily if item["date"] == (day+timedelta(days=1)).isoformat())
    forecast = next(item for item in weather.get_forecast()["forecast"] if item["date"] == tomorrow["date"])
    assert forecast["rainfall_mm"] == tomorrow["rain_mm"]
    assert forecast["solar_radiation"] * .0864 == pytest.approx(tomorrow["shortwave_mj_m2_day"])


def test_fixed_world_rejects_a_hidden_backend_override_or_mismatched_seed_identity():
    with pytest.raises(ValueError, match="declares its native configuration"):
        ReferenceWorld(crop_backend_options={"parameter_overrides": {"*": {"TSUM1": 1}}})
    with pytest.raises(ValueError, match="does not match"):
        make_world(seed_type="SOYBEAN_902")


def test_completed_day_starts_native_at_real_sowing_and_keeps_public_calendar_current():
    scene = make_world(num_ridges=1)

    def plan(session):
        prepare_and_sow(session, scene)
        assert not scene.get_typed_app(FarmWorldApp).physics.crop_backend.has_started
        next_morning(session, scene, scene.WORLD.sowing_date+timedelta(days=1))

    scene.test_policy = plan
    engine = ModelExperimentEngine(None, scene)
    engine.run_experiment()
    farm = scene.get_typed_app(FarmWorldApp)
    run = farm.physics.crop_backend._runs[0]
    assert run.specification["start_date"] == run.specification["planting_date"] == "2019-04-28"
    assert run.model.day == date(2019, 4, 29)
    assert [entry["day"] for entry in run.journal] == ["2019-04-28"]
    assert run.specification["soil_parameters"]["RDMSOL"] == 120.
    assert run.specification["crop_parameters"] == official_crop("Soybean_901")
    assert len(run.specification["crop_parameters"]) == 78
    assert scene.get_typed_app(SystemApp).get_current_time()["current_datetime"] == "2019-04-29 07:00:00"
    assert scene.get_typed_app(WeatherApp).get_current_weather()["date"] == "2019-04-29"


def test_scenes_without_completed_day_opt_in_keep_the_historical_clock_convention():
    scene = make_world(num_ridges=1)

    def plan(session):
        farm = scene.get_typed_app(FarmWorldApp)
        farm.physics.scenario_metadata.pop("daily_settlement")
        prepare_and_sow(session, scene)
        next_morning(session, scene, date(2019, 4, 29))

    scene.test_policy = plan
    ModelExperimentEngine(None, scene).run_experiment()
    run = scene.get_typed_app(FarmWorldApp).physics.crop_backend._runs[0]
    assert run.specification["planting_date"] == "2019-04-28"
    assert run.specification["start_date"] == "2019-04-29"
    assert run.journal[0]["day"] == "2019-04-29" and run.model.day == date(2019, 4, 30)


def test_formal_tool_workflow_fresh_replay_keeps_native_state_responses_and_clock_exact():
    scene = make_world(num_ridges=1)

    def plan(session):
        prepare_and_sow(session, scene)
        session.call("real_irrigation", "FieldOpsApp__irrigate", {"start": 0, "end": 0, "hours": 1.})
        next_morning(session, scene, date(2019, 4, 30))
        session.call("final_station", "WeatherApp__get_current_weather")

    scene.test_policy = plan
    engine = ModelExperimentEngine(None, scene)
    recorded = engine.run_experiment()
    fresh_scene = make_world(num_ridges=1)
    fresh_scene.test_policy = lambda session: pytest.fail("Replay must execute the saved registered tools")
    fresh_engine = ModelExperimentEngine(None, fresh_scene)
    replayed = fresh_engine.replay_workflow(recorded)
    assert scene.get_typed_app(FarmWorldApp).physics.crop_backend.snapshot() == fresh_scene.get_typed_app(FarmWorldApp).physics.crop_backend.snapshot()
    assert scene.get_typed_app(WeatherApp).get_current_weather() == fresh_scene.get_typed_app(WeatherApp).get_current_weather()
    assert engine.time_manager.time() == fresh_engine.time_manager.time()
    columns = ("tool_name", "tool_args", "content", "op_type", "time_before", "time_after")
    assert [tuple(getattr(step, column) for column in columns) for step in recorded.dag.values()] == [
        tuple(getattr(step, column) for column in columns) for step in replayed.dag.values()]


def stock_weather_provider(scene):
    """Convert original pinned daily fields independently of the adapter."""
    from pcse.base import WeatherDataContainer, WeatherDataProvider
    from pcse.util import reference_ET

    provider = WeatherDataProvider()
    location = scene.reference["location"]
    for row in scene.daily_weather:
        day = date.fromisoformat(row["date"])
        temp = (row["tmin_c"]+row["tmax_c"]) / 2
        vapor = max(.06, 6.108 * math.exp(17.27*temp/(temp+237.3))*row["relative_humidity_pct"]/100)
        irrad = row["shortwave_mj_m2_day"]*1e6
        e0, es0, et0 = reference_ET(DAY=day, LAT=location["latitude"], ELEV=location["elevation_m"],
            TMIN=row["tmin_c"], TMAX=row["tmax_c"], IRRAD=irrad, VAP=vapor,
            WIND=row["wind_2m_m_s"], ANGSTA=.29, ANGSTB=.49, ETMODEL="PM")
        container = WeatherDataContainer(DAY=day, LAT=location["latitude"], LON=location["longitude"],
            ELEV=location["elevation_m"], TMIN=row["tmin_c"], TMAX=row["tmax_c"], TEMP=temp,
            VAP=vapor, IRRAD=irrad, RAIN=row["rain_mm"]/10, WIND=row["wind_2m_m_s"],
            E0=e0/10, ES0=es0/10, ET0=et0/10)
        provider._store_WeatherDataContainer(container, day)
    return provider


@pytest.mark.parametrize("reference", REFERENCES, ids=[r[1] for r in REFERENCES])
def test_whole_formal_season_matches_unmodified_stock_wofost_with_actual_tool_water_and_n(reference):
    pytest.importorskip("pcse")
    from pcse.base import ParameterProvider
    from pcse.input import WOFOST81SiteDataProvider_Classic
    from pcse.models import Wofost81_NWLP_CWB_CNB

    scene = make_world(reference, num_ridges=1, irrigation_quota_mm=40.)
    history, supplied = [], {}

    def supply(day, *, irrigation=0., fertilizer=0.):
        daily = supplied.setdefault(day, {"irrigation_mm": 0., "fertilizer_kg": 0.})
        daily["irrigation_mm"] += irrigation
        daily["fertilizer_kg"] += fertilizer

    def plan(session):
        base = prepare_and_sow(session, scene)
        supply(session.today, fertilizer=base["fertilizer_used_kg"])
        farm = scene.get_typed_app(FarmWorldApp)
        # Deliberately large pressures cannot alter a native-reference crop.
        farm.physics.biotic.set_pressure([0], weed_pressure=.8,
            insect_pressure=.8, disease_pressure=.8)
        topdress_done = False
        water_done = set()
        day = scene.WORLD.sowing_date
        while day < scene.WORLD.end_date:
            offset = (day-scene.WORLD.sowing_date).days
            if not topdress_done and offset >= 25 and farm._ridges[0].soil_vwc <= .35:
                dose = session.call("actual_topdress", "TractorApp__apply_fertilizer",
                    {"start_ridge": 0, "end_ridge": 0, "kg_per_ridge": .4})
                supply(day, fertilizer=dose["fertilizer_used_kg"])
                topdress_done = True
            for earliest, mm in ((40, 8.), (80, 12.)):
                if earliest not in water_done and offset >= earliest and farm._ridges[0].soil_vwc < .30:
                    receipt = session.call("actual_water", "FieldOpsApp__irrigate",
                        {"start": 0, "end": 0, "hours": mm/5.})
                    assert receipt["status"] == "irrigation_started"
                    supply(day, irrigation=receipt["estimated_water_mm_per_ridge"])
                    water_done.add(earliest)
                    break
            tomorrow = day+timedelta(days=1)
            next_morning(session, scene, tomorrow)
            run = farm.physics.crop_backend._runs[0]
            assert run.model.day == tomorrow
            history.append((day, deepcopy(run.pcse), deepcopy(run.journal[-1])))
            day = tomorrow
        assert topdress_done
        assert water_done == {40, 80}

    scene.test_policy = plan
    engine = ModelExperimentEngine(None, scene)
    workflow = engine.run_experiment()
    farm = scene.get_typed_app(FarmWorldApp)
    backend, world = farm.physics.crop_backend, scene.WORLD
    specification = backend._runs[0].specification
    crop = official_crop(scene.reference["variety"])
    assert len(crop) == 78 and specification["crop_parameters"] == crop
    assert specification["density_plants_m2"] == 40.
    assert specification["start_date"] == specification["planting_date"] == world.sowing_date.isoformat()
    soil = {"SMW": world.wilting_point_vwc, "SMFCF": world.field_capacity_vwc,
        "SM0": world.saturation_vwc, "CRAIRC": .06,
        "SOPE": world.infiltration_mm_day/10, "KSUB": world.infiltration_mm_day/10,
        "K0": world.infiltration_mm_day/10, "RDMSOL": world.soil_depth_m*100}
    site = dict(WOFOST81SiteDataProvider_Classic(WAV=(world.initial_vwc-world.wilting_point_vwc)*120,
        SMLIM=world.initial_vwc, CO2=420., NAVAILI=world.initial_available_n_kg_ha,
        NSOILBASE=world.base_soil_n_kg_ha, NSOILBASE_FR=.025,
        NOTINF=0., SSI=0., SSMAX=0., IFUNRN=0))
    assert specification["soil_parameters"] == soil
    assert specification["site_parameters"] == site
    water_events, n_events = [], []
    for day, dose in sorted(supplied.items()):
        if dose["irrigation_mm"]:
            water_events.append({day: {"amount": dose["irrigation_mm"]/10, "efficiency": .92}})
        if dose["fertilizer_kg"]:
            n_events.append({day: {"N_amount": dose["fertilizer_kg"]*.46*10000/farm.ridge_area_m2,
                "N_recovery": .7}})
    timed = [{"event_signal": name, "name": name, "comment": "Actual registered tool delivery",
        "events_table": table} for name, table in (("irrigate", water_events), ("apply_n", n_events))]
    management = [{world.sowing_date: {"CropCalendar": {"crop_name": "soybean",
        "variety_name": scene.reference["variety"], "crop_start_date": world.sowing_date,
        "crop_start_type": "sowing", "crop_end_date": None, "crop_end_type": "maturity",
        "max_duration": 366}, "TimedEvents": timed, "StateEvents": None}},
        {world.sowing_date+timedelta(days=4026): None}]
    names = ["DVS", "LAI", "TAGP", "TWSO", "SM", "NAVAIL", "DOM"]
    native = Wofost81_NWLP_CWB_CNB(ParameterProvider(cropdata=crop, soildata=soil, sitedata=site),
        stock_weather_provider(scene), management, summary_vars=names)
    assert type(native) is Wofost81_NWLP_CWB_CNB
    daily_rows = {row["date"]: row for row in scene.daily_weather}
    for day, actual, entry in history:
        assert entry["day"] == day.isoformat()
        row = daily_rows[day.isoformat()]
        assert entry["weather"] == {"air_temp_min_c": row["tmin_c"], "air_temp_max_c": row["tmax_c"],
            "air_temp_mean_c": (row["tmin_c"]+row["tmax_c"])/2, "rain_mm": row["rain_mm"],
            "solar_rad_mj_m2": row["shortwave_mj_m2_day"], "wind_ms": row["wind_2m_m_s"]}
        assert entry["humidity_pct"] == row["relative_humidity_pct"]
        dose = supplied.get(day, {"irrigation_mm": 0., "fertilizer_kg": 0.})
        assert entry["inputs"]["irrigation_mm"] == pytest.approx(dose["irrigation_mm"])
        assert entry["inputs"]["fertilizer_kg"] == pytest.approx(dose["fertilizer_kg"])
        assert entry["inputs"]["n_kg_ha"] == pytest.approx(dose["fertilizer_kg"]*.46*10000/farm.ridge_area_m2)
        assert entry["external_growth_factor"] == 1.
        native.run(days=1)
        assert native.day == day+timedelta(days=1)
        summary = native.get_summary_output()[-1] if native.crop is None else None
        for name in names:
            expected = summary[name] if summary is not None and name not in {"SM", "NAVAIL"} else native.get_variable(name)
            if name == "DOM":
                assert actual[name] == expected
            else:
                assert actual[name] == pytest.approx(expected, rel=1e-11, abs=1e-11), f"{reference[1]} {day} {name}"
    assert len(history) == (world.end_date-world.sowing_date).days
    assert native.get_summary_output()[-1]["DOM"] is not None
    assert backend._runs[0].maturity_snapshot["TWSO"] > 0
    assert farm._management_regime.irrigation_used_mm_total == 20.
    assert backend._runs[0].cumulative_irrigation_mm == 20.
    assert sum(step.tool_name == "FieldOpsApp__irrigate" for step in workflow.dag.values()) == 2
    assert engine.time_manager.time() == engine.start_time+scene.duration


def test_completed_day_long_jump_and_daily_steps_inject_events_once_and_match_native_state():
    worlds = []
    for jump in (False, True):
        scene = make_world(num_ridges=1)
        start = scene.WORLD.sowing_date
        scene.test_events = [PressureEvent("daily_disease", "farm", 0, 0,
            start, start+timedelta(days=4), "disease", .1, mode="add", repeat="daily")]

        def plan(session):
            prepare_and_sow(session, scene)
            if jump:
                next_morning(session, scene, start+timedelta(days=3))
            else:
                for offset in (1, 2, 3):
                    next_morning(session, scene, start+timedelta(days=offset))

        scene.test_policy = plan
        ModelExperimentEngine(None, scene).run_experiment()
        farm = scene.get_typed_app(FarmWorldApp)
        state = deepcopy(farm.physics.crop_backend.snapshot())
        ledger = scenario_events_snapshot(farm)
        assert farm.physics.crop_backend._runs[0].model.day == start+timedelta(days=3)
        assert scene.get_typed_app(WeatherApp).get_current_weather()["date"] == (start+timedelta(days=3)).isoformat()
        # Today's injection is already public; another subdaily read/refresh
        # must not reapply it before tomorrow settles today's growth.
        before = farm.physics.biotic.states[0].disease_pressure
        farm.advance_physics_time()
        assert farm.physics.biotic.states[0].disease_pressure == before
        worlds.append((state, ledger, before))
    assert worlds[0] == worlds[1]


def test_completed_day_uses_local_midnights_across_the_autumn_clock_change():
    scene = make_world(num_ridges=1, sowing_date=date(2019, 10, 26))
    elapsed = []

    def plan(session):
        prepare_and_sow(session, scene)
        next_morning(session, scene, date(2019, 10, 27))
        elapsed.append(session.now)
        next_morning(session, scene, date(2019, 10, 28))
        elapsed.append(session.now)

    scene.test_policy = plan
    ModelExperimentEngine(None, scene).run_experiment()
    run = scene.get_typed_app(FarmWorldApp).physics.crop_backend._runs[0]
    assert elapsed[0]-scene.start_time == 25*3600
    assert elapsed[1]-elapsed[0] == 24*3600
    assert [entry["day"] for entry in run.journal] == ["2019-10-26", "2019-10-27"]
    assert run.model.day == date(2019, 10, 28)
