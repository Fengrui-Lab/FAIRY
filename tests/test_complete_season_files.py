"""Each full-season file must be runnable without another scene or its helpers."""
from dataclasses import asdict
from datetime import date
import importlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.scenario import Scenario


SCENARIO_IDS = (
    "scenario_multi_farm_full_season",
    "scenario_multi_farm_full_season_drought_priority",
    "scenario_multi_farm_full_season_staggered_windows",
    "scenario_multi_farm_full_season_weather_risk",
    "scenario_multi_crop_full_season_maize",
    "scenario_multi_crop_full_season_rice",
    "scenario_multi_crop_full_season_mixed",
    "scenario_multi_crop_full_season_staggered",
)
PACKAGE = "fairy.scenarios.farm_world_diverse"
REPOSITORY = Path(__file__).resolve().parents[1]


def _scene_class(module):
    candidates = [
        value for value in vars(module).values()
        if isinstance(value, type)
        and value is not Scenario
        and issubclass(value, Scenario)
        and value.__module__ == module.__name__
    ]
    assert len(candidates) == 1, "One file must define its own concrete scenario"
    return candidates[0]


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_local_scene_configuration_initializes_real_farms_and_clones(scenario_id):
    module = importlib.import_module(f"{PACKAGE}.{scenario_id}")
    scene_class = _scene_class(module)
    assert scene_class.__bases__ == (Scenario,)
    assert get_scenario_class(scenario_id) is scene_class
    for method in ("init_and_populate_apps", "oracle_solution", "validate", "oracle_clone"):
        implementation = scene_class.__dict__[method]
        assert inspect.getsourcefile(implementation) == module.__file__
    for name in ("SeasonFarmPlan", "FieldLayout", "SoilInitialState", "WeatherSchedule",
                 "FarmResources", "SeasonSettings", "parse_farm_config"):
        assert getattr(module, name).__module__ == module.__name__

    first = module.SeasonFarmPlan(
        farm_id="local_a", tool_prefix="LocalA", crop_type="maize",
        layout=module.FieldLayout(ridge_count=2, ridge_length_m=80, ridge_width_m=.75),
        initial_soil=module.SoilInitialState(topsoil_vwc=.31, nutrient_index=.73),
        weather=module.WeatherSchedule(mean_temperature_c=25, normal_daily_rain_mm=3),
        resources=module.FarmResources(irrigation_budget_mm=210, fertilizer_budget_kg=80),
    )
    second = module.SeasonFarmPlan(
        farm_id="local_b", tool_prefix="LocalB", crop_type="rice",
        layout=module.FieldLayout(ridge_count=3, ridge_length_m=90, ridge_width_m=1),
        planting_start_day=7,
    )
    configs = [asdict(first), asdict(second)]
    assert [module.parse_farm_config(config) for config in configs] == [first, second]
    source = scene_class(
        farm_configs=configs, season_length_days=160, monitor_interval_days=4, seed=13,
    )
    clone = source.oracle_clone()
    assert type(clone) is scene_class
    assert clone.scenario_id == source.scenario_id == scenario_id
    assert clone.seed == 13
    assert clone.season_length_days == 160
    assert clone.monitor_interval_days == 4
    assert clone.farm_plans == source.farm_plans == (first, second)
    assert all(type(plan) is module.SeasonFarmPlan for plan in clone.farm_plans)
    assert not clone.apps

    source.setup()
    clone.setup()
    assert clone.fleet is not source.fleet
    assert [site.spec.farm_id for site in source.fleet.sites] == ["local_a", "local_b"]
    first_site, second_site = source.fleet.sites
    first_state = first_site.farm.get_state()
    assert first_state["field_area_m2"] == 120
    assert second_site.farm.get_state()["field_area_m2"] == 270
    assert first_site.farm.crop_type == "maize"
    assert second_site.farm.crop_type == "rice"
    assert first_state["management_regime"]["irrigation_quota_mm_total"] == 210
    assert first_state["management_regime"]["fertilizer_quota_kg"] == 80
    assert all(ridge["soil_vwc"] == .31 and ridge["nutrient_index"] == .73
               and not ridge["planted"] for ridge in first_state["ridges"])


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_legacy_typed_configs_are_rebuilt_as_local_types_and_initialize(scenario_id):
    from fairy.scenarios.farm_world_diverse import full_season_config as legacy

    module = importlib.import_module(f"{PACKAGE}.{scenario_id}")
    foreign_values = {
        "layout": legacy.FieldLayout(ridge_count=2, ridge_length_m=80, ridge_width_m=.75),
        "initial_soil": legacy.SoilInitialState(
            topsoil_vwc=.31, soil_temperature_c=21, nutrient_index=.73,
            pest_pressure=.02, disease_pressure=.03,
        ),
        "weather": legacy.WeatherSchedule(
            mean_temperature_c=25, normal_daily_rain_mm=3,
            drought_days=(5, 7), harvest_rain_days=(6, 6), workable_every_n_days=4,
            late_dry_from_day=8, wind_speed_m_s=1.5, solar_radiation_mj_m2_day=14,
            daily_temperature_range_c=10, dry_relative_humidity_pct=60,
            rainy_relative_humidity_pct=90, rainy_humidity_threshold_mm=6,
            harvest_rain_mm=12, latitude_deg=35, sowing_dry_margin_days=0,
            forcing_buffer_days=3, initial_station_rain_mm=2,
        ),
        "resources": legacy.FarmResources(
            irrigation_budget_mm=210, fertilizer_budget_kg=80,
            drying_capacity_kg_per_day=700, storage_capacity_kg=1400,
        ),
    }
    config = dict(farm_id="compat_a", tool_prefix="CompatA", crop_type="maize", **foreign_values)
    parsed = module.parse_farm_config(config)
    assert type(parsed) is module.SeasonFarmPlan
    for name, type_name in (
        ("layout", "FieldLayout"), ("initial_soil", "SoilInitialState"),
        ("weather", "WeatherSchedule"), ("resources", "FarmResources"),
    ):
        local_value = getattr(parsed, name)
        assert type(local_value) is getattr(module, type_name)
        assert local_value is not foreign_values[name]
        assert asdict(local_value) == asdict(foreign_values[name])

    other_config = config | {
        "farm_id": "compat_b", "tool_prefix": "CompatB", "crop_type": "rice",
        "layout": legacy.FieldLayout(ridge_count=3, ridge_length_m=90, ridge_width_m=1),
        "planting_start_day": 7,
    }
    source = _scene_class(module)(farm_configs=[config, other_config])
    source.setup()
    first_site, second_site = source.fleet.sites
    first_state = first_site.farm.get_state()
    assert first_state["field_area_m2"] == 120
    assert second_site.farm.get_state()["field_area_m2"] == 270
    assert all(ridge["soil_vwc"] == .31 and ridge["soil_temp_c"] == 21
               and ridge["nutrient_index"] == .73 and ridge["pest_pressure"] == .02
               and ridge["disease_pressure"] == .03 for ridge in first_state["ridges"])
    assert first_state["management_regime"]["irrigation_quota_mm_total"] == 210
    assert first_state["management_regime"]["fertilizer_quota_kg"] == 80
    assert first_state["postharvest_market"]["drying_capacity_kg_per_day"] == 700
    assert first_state["postharvest_market"]["storage_capacity_kg"] == 1400
    assert first_site.farm.physics.latitude_deg == 35
    forcing = first_site.farm.physics.weather_generator._day_overrides
    assert forcing[date(2026, 5, 3)].rain_mm == 3
    assert forcing[date(2026, 5, 7)].rain_mm == 12
    assert (forcing[date(2026, 5, 7)].air_temp_min_c,
            forcing[date(2026, 5, 7)].air_temp_max_c) == (20, 30)
    assert forcing[date(2026, 5, 7)].relative_humidity_pct == 90
    assert len(forcing) == source.season_length_days + 3
    assert source.farm_plans[0].weather is not source.farm_plans[1].weather


_ISOLATED_SCENE_SCRIPT = textwrap.dedent("""\
    import importlib
    import importlib.abc
    import json
    import sys

    scenario_id = sys.argv[1]
    target_module = "fairy.scenarios.farm_world_diverse." + scenario_id
    allowed_scene_modules = {
        "fairy.scenarios.scenario", "fairy.scenarios.registry",
        "fairy.scenarios.workflow", "fairy.scenarios.validation_result",
        "fairy.scenarios.farm_world_diverse", target_module,
    }

    class SceneDependencyGuard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith("fairy.scenarios.") and fullname not in allowed_scene_modules:
                raise ImportError("Scene must be complete in one file; forbidden dependency: " + fullname)
            return None

    sys.meta_path.insert(0, SceneDependencyGuard())
    module = importlib.import_module(target_module)
    from fairy.scenarios.registry import get_scenario_class
    scene_class = get_scenario_class(scenario_id)
    assert scene_class.__module__ == target_module
    source = scene_class()
    source.setup()
    assert len(source.fleet.sites) >= 2
    clone = source.oracle_clone()
    assert type(clone) is scene_class
    assert clone.farm_plans == source.farm_plans

    report = {"scenario_id": scenario_id, "farms": len(source.fleet.sites)}
    if scenario_id == "scenario_multi_crop_full_season_mixed":
        from fairy.controllers.engine import Engine
        engine = Engine(None, source)
        workflow = engine.run_scenario_oracle(run_oracle=True)
        result = engine.evaluate()
        assert result.success, result.message
        assert workflow.dag
        assert result.metadata["elapsed_days"] > 30
        assert len(result.metadata["farms"]) == 3
        for details in result.metadata["farms"].values():
            assert details["emerged"] == details["matured"] == details["harvested"]
            assert details["warehouse_grain_kg"] > 0
        report["full_season_success"] = True
    assert not (set(sys.modules) - allowed_scene_modules) & {
        name for name in sys.modules if name.startswith("fairy.scenarios.")
    }
    print(json.dumps(report))
""")


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_scene_runs_with_all_other_scene_implementations_blocked(scenario_id):
    # A fresh process prevents already-imported helpers from hiding a dependency.
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
        str(REPOSITORY), environment.get("PYTHONPATH"),
    )))
    result = subprocess.run(
        [sys.executable, "-c", _ISOLATED_SCENE_SCRIPT, scenario_id],
        cwd=REPOSITORY, env=environment, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.splitlines()[-1])
    assert report["scenario_id"] == scenario_id
    assert report["farms"] >= 2
    if scenario_id == "scenario_multi_crop_full_season_mixed":
        assert report["full_season_success"]
