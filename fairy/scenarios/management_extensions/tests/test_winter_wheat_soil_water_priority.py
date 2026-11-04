"""The soil priority case publishes comparable measurements and retains legacy inputs."""

import json

import pytest

from fairy.controllers.engine import Engine
from fairy.scenarios.management_extensions.L3.scenario_winter_wheat_soil_water_priority import (
    REFERENCE_PATH,
    ScenarioWinterWheatSoilWaterPriority,
)
from fairy.scenarios.management_extensions.winter_wheat_workflow import WheatOracleTrial


def test_legacy_soil_water_fingerprint_and_workflow_stay_available():
    scene = ScenarioWinterWheatSoilWaterPriority(legacy=True)
    scene.setup()
    assert scene.farm.bundle.season.deadline.isoformat() == "2020-07-15"
    assert scene.resources.water_stock_m3 == 1000
    assert scene.input_fingerprint() == scene.ORACLE_REFERENCE["input_fingerprint"]
    assert len(Engine(None, scene).build_oracle_workflow(run_oracle=False)) == 155
    assert (
        "available_water_fraction" not in scene.farm.inspect_blocks(0, 0)["blocks"][0]
    )


def test_soil_priority_reports_native_relative_water_before_irrigation():
    scene = ScenarioWinterWheatSoilWaterPriority()
    trial = WheatOracleTrial(scene)
    bare = scene.farm.inspect_blocks(0, 0)["blocks"][0]
    assert bare["available_water_fraction"] is None
    with REFERENCE_PATH.open(encoding="utf-8") as stream:
        steps = json.load(stream)["steps"]
    for app, method, args, _ in steps:
        if (app, method) == ("irrigation", "irrigate"):
            break
        trial.call(app, method, **args)
    else:
        pytest.fail("The Oracle has no irrigation")

    measurements = scene.farm.inspect_blocks(0, 8)["blocks"]
    shallow, deep = measurements[0], measurements[8]
    assert shallow["available_water_fraction"] < deep["available_water_fraction"]
    for block in (shallow, deep):
        backend = scene.farm.backends[block["block_id"]]
        soil = backend.bundle.manifest["native_soil_parameters"]
        low, high = soil["SMW"], soil["SMFCF"]
        native_depth = backend.values["RD"]
        assert block["root_depth_cm"] == pytest.approx(native_depth, abs=0.05)
        assert block["available_water_fraction"] == pytest.approx(
            (block["SM"] - low) / (high - low), abs=0.0005
        )
        assert block["available_water_mm"] == pytest.approx(
            (block["SM"] - low) * native_depth * 10, abs=0.05
        )
        assert block["net_mm_to_field_capacity"] == pytest.approx(
            (high - block["SM"]) * native_depth * 10, abs=0.05
        )
