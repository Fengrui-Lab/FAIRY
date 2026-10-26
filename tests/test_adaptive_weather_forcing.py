"""Common weather is an input, not a consequence of management read order."""
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timedelta
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from fairy.apps.farm_world import FarmWorldApp, SensorApp, WeatherApp
from fairy.apps.farm_world.physics_orchestrator import _generate_weather_day
from fairy.apps.system import SystemApp
from fairy.physics.weather_engine import (
    MonthlyClimate, WeatherEvent, WeatherGenerator, WeatherGeneratorConfig,
)
from fairy.scenarios.scenario import Scenario
from scripts.adaptive_weather_forcing import (
    FrozenWeatherCompiler, freeze_weather_manifest, install_frozen_weather,
)


START = datetime(2026, 6, 1, 7, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()


def weather_generator(seed=17):
    return WeatherGenerator(WeatherGeneratorConfig(monthly={
        month: MonthlyClimate(20, 40, .4, 20) for month in range(1, 13)
    }), seed=seed)


def scene(*, count=1, shared_weather=False, conflicting=False):
    weather = WeatherApp()
    farms = []
    for i in range(count):
        farm = FarmWorldApp(name=f"Farm{i}", farm_id=f"f{i}", num_ridges=1)
        station = weather if shared_weather else WeatherApp()
        if not shared_weather:
            station.name = f"Weather{i}"
        farm.attach_weather_app(station)
        farm.physics.weather_generator = weather_generator(17 if not conflicting else 17+i)
        farm.physics.profile = SimpleNamespace(weather_events=[
            WeatherEvent("rain_event", date(2026, 6, 2), 3, total_rain_mm=13.37)
        ])
        farms.append(farm)
    return SimpleNamespace(apps=farms, scenario_id="toy", start_time=START, duration=4*86400)


def test_manifest_keeps_existing_cache_without_consuming_original_rng():
    source = scene()
    gen = source.apps[0].physics.weather_generator
    cached = _generate_weather_day(gen, date(2026, 5, 28))
    before = deepcopy(gen.rng.bit_generator.state)
    manifest = freeze_weather_manifest(source)
    assert gen.rng.bit_generator.state == before
    assert manifest["date_start"] == "2026-05-28"
    assert manifest["date_end"] == "2026-06-12"
    assert manifest["forcings"]["forcing_000"]["days"]["2026-05-28"] == asdict(cached) | {"day": "2026-05-28"}


def test_frozen_inputs_are_identical_for_reverse_forecast_and_daily_order():
    source = scene()
    manifest = json.loads(json.dumps(freeze_weather_manifest(source)))
    other = scene()
    install_frozen_weather(source, manifest)
    install_frozen_weather(other, manifest)
    left, right = [value.apps[0].physics.weather_generator for value in (source, other)]
    dates = [date.fromisoformat(d) for d in manifest["forcings"]["forcing_000"]["days"]]
    forward = {d: asdict(_generate_weather_day(left, d, source.apps[0].physics.profile.weather_events)) for d in dates}
    reverse = {d: asdict(_generate_weather_day(right, d, other.apps[0].physics.profile.weather_events)) for d in reversed(dates)}
    assert forward == reverse
    # Direct regeneration reapplies events internally, then the exact pinned
    # input must prevail instead of adding the storm a second time.
    values = left.generate(date(2026, 6, 2), date(2026, 6, 4), source.apps[0].physics.profile.weather_events)
    assert [asdict(v) for v in values] == [forward[v.day] for v in values]


def test_multiple_station_bindings_stay_distinct_and_shared_station_stays_equal():
    distinct = scene(count=2, conflicting=True)
    manifest = freeze_weather_manifest(distinct)
    assert len(manifest["forcings"]) == 2
    install_frozen_weather(distinct, manifest)
    assert manifest["bindings"]["Farm0"]["forcing_id"] != manifest["bindings"]["Farm1"]["forcing_id"]
    common = scene(count=2, shared_weather=True)
    manifest = freeze_weather_manifest(common)
    assert len(manifest["forcings"]) == 1
    install_frozen_weather(common, manifest)
    assert common.apps[0].physics.weather_generator._day_cache == common.apps[1].physics.weather_generator._day_cache


def test_conflicting_shared_station_and_tampered_manifest_fail_before_install():
    with pytest.raises(ValueError, match="conflicting"):
        freeze_weather_manifest(scene(count=2, shared_weather=True, conflicting=True))
    source = scene()
    manifest = freeze_weather_manifest(source)
    manifest["forcings"]["forcing_000"]["days"]["2026-06-02"]["rain_mm"] += 1
    with pytest.raises(ValueError, match="integrity"):
        install_frozen_weather(source, manifest)
    assert not source.apps[0].physics.weather_generator._day_overrides


class NativeWeatherScene(Scenario):
    start_time = START
    duration = 4*86400

    def init_and_populate_apps(self):
        farm = FarmWorldApp(num_ridges=1)
        weather = WeatherApp()
        weather.set_weather("2026-06-01", 20, 55, 2, 0, 250)
        farm.attach_weather_app(weather)
        farm.set_season_phase("full_season")
        farm._sim_date = "2026-06-01"
        farm.physics.engines_active = True
        farm.physics.weather_generator = weather_generator()
        farm.physics.profile = SimpleNamespace(weather_events=[])
        farm.time_manager.reset(start_time=START)
        farm.set_ridge_planted(0, "HEINONG84", 7.9)
        farm._ridges[0].planted_at_sim_time = START
        from fairy.physics.phenology_engine import PlantingConfig, SeedType
        farm.physics.phenology.plant_ridges(
            [0], PlantingConfig(date(2026, 6, 1), SeedType.HEINONG84))
        self.apps = [farm, weather, SensorApp(farm), SystemApp()]


def imports():
    from fairy.agents.agent.toolset_builder import build_toolset
    from fairy.controllers.engine import Engine
    from fairy.scenarios.workflow import Workflow, WorkflowStep
    return {"FarmWorldApp": FarmWorldApp, "WeatherApp": WeatherApp,
            "SensorApp": SensorApp, "SystemApp": SystemApp, "Engine": Engine,
            "Workflow": Workflow, "WorkflowStep": WorkflowStep,
            "build_toolset": build_toolset, "get_scenario_class": lambda sid: NativeWeatherScene}


def test_real_registered_workflow_and_fresh_replay_keep_exact_weather_and_state(tmp_path):
    pytest.importorskip("pcse")
    config = {"cultivar_profile": "heilongjiang_heinong84_complete_v1"}
    compiler = FrozenWeatherCompiler("toy", config, tmp_path, imports())
    compiler.call("initial_soil", "SensorApp__read_soil_sensors", {})
    compiler.call("wait", "SystemApp__advance_time", {"days": 2})
    compiler.call("forecast", "WeatherApp__get_forecast", {})
    compiler.call("soil", "SensorApp__read_soil_sensors", {})
    before = compiler.snapshot_unrecorded(compiler.scenario, compiler.engine)
    assert set(before["farms"]["FarmWorldApp"]["native_backend"]["ridges"]) == {"0"}
    fresh, engine = compiler.fresh()
    replayed = engine.replay_workflow(compiler.workflow)
    assert compiler.snapshot_unrecorded(fresh, engine) == before
    assert [(s.tool_args, s.content, s.time_before, s.time_after) for s in replayed.dag.values()] == [
        (s.tool_args, s.content, s.time_before, s.time_after) for s in compiler.workflow.dag.values()]
    # Exercise an actual rebuild, not setup's ordinary apps-present no-op.
    fresh.apps = []
    fresh.setup()
    actual = fresh.get_typed_app(FarmWorldApp).physics.weather_generator
    for day, value in compiler.forcing_manifest["forcings"]["forcing_000"]["days"].items():
        assert clean_day(_generate_weather_day(actual, date.fromisoformat(day))) == value
    control = FrozenWeatherCompiler("toy", config, tmp_path/"control", imports(),
                                    forcing_manifest=compiler.forcing_manifest)
    assert control.forcing_manifest == compiler.forcing_manifest


def clean_day(day):
    return asdict(day) | {"day": day.day.isoformat()}
