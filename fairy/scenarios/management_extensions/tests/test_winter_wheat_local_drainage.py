"""Surface drainage has a measured, replayable effect isolated to its scenario."""

import json

import pytest

from fairy.scenarios.management_extensions.L3.scenario_winter_wheat_full_season import (
    ScenarioWinterWheatFullSeason,
)
from fairy.scenarios.management_extensions.L3.scenario_winter_wheat_local_drainage import (
    LOW_BLOCKS,
    REFERENCE_PATH,
    STORM_RAIN_ADDITIONS_MM,
    ScenarioWinterWheatLocalDrainage,
)
from fairy.scenarios.management_extensions.engines.winter_wheat_waterlogging import (
    WaterloggingWheatBackend,
)
from fairy.scenarios.management_extensions.winter_wheat_workflow import WheatOracleTrial


def test_drainage_and_storm_are_scenario_local():
    original = ScenarioWinterWheatFullSeason()
    original.setup()
    local = ScenarioWinterWheatLocalDrainage()
    local.setup()

    assert (
        original.input_fingerprint() == original.ORACLE_REFERENCE["input_fingerprint"]
    )
    assert "Drainage" not in {app.name for app in original.apps}
    assert "Drainage" in {app.name for app in local.apps}
    assert {
        i
        for i, b in enumerate(local.farm.backends)
        if isinstance(b, WaterloggingWheatBackend)
    } == set(LOW_BLOCKS)
    assert [b.parameters["IOX"] for b in original.farm.backends] == [0] * 16
    for i, backend in enumerate(local.farm.backends):
        assert backend.parameters["IOX"] == int(i in LOW_BLOCKS)
    actual_additions = {
        day: new.rain_mm - original.input_bundle.weather[day].rain_mm
        for day, new in local.input_bundle.weather.rows.items()
        if new != original.input_bundle.weather[day]
    }
    assert actual_additions == pytest.approx(STORM_RAIN_ADDITIONS_MM)


def test_ponding_drainage_retries_and_pending_checkpoint():
    scene = ScenarioWinterWheatLocalDrainage(calibrating=True)
    trial = WheatOracleTrial(scene)
    with REFERENCE_PATH.open(encoding="utf-8") as stream:
        steps = json.load(stream)["steps"]
    for app, method, args, _ in steps:
        if (app, method) == ("drainage", "drain"):
            break
        trial.call(app, method, **args)
    else:
        pytest.fail("Oracle does not use the drainage tool")

    block = args["block_id"]
    with pytest.raises(ValueError, match="no connected"):
        scene.drainage.drain(0, 5.0, "normal_block")
    ponding = scene.drainage.inspect_blocks(block, block)["blocks"][0]
    assert ponding["ponding_depth_mm"] > 0
    result = scene.drainage.drain(**args)
    epoch = scene.farm_environment.time_manager.time()
    assert scene.drainage.drain(**args) == result
    assert scene.farm_environment.time_manager.time() == epoch
    queued = scene.drainage.inspect_blocks(block, block)["blocks"][0]
    assert queued["root_zone_vwc"] == ponding["root_zone_vwc"]
    assert queued["unreserved_ponding_mm"] == pytest.approx(
        ponding["ponding_depth_mm"] - result["accepted_depth_mm"]
    )

    restored = ScenarioWinterWheatLocalDrainage(calibrating=True)
    restored.setup()
    restored.farm_environment.time_manager.reset(epoch)
    for app in (scene.farm, scene.drainage):
        saved = json.loads(json.dumps(app.get_state()))
        (restored.farm if app is scene.farm else restored.drainage).load_state(saved)
    scene.system.advance_time(days=1)
    restored.system.advance_time(days=1)
    assert restored.farm.get_state() == scene.farm.get_state()
    assert restored.drainage.get_state() == scene.drainage.get_state()

    ledger = restored.drainage.compute_accounts()
    assert ledger["pumped_volume_m3"] == pytest.approx(result["pumped_volume_m3"])
    assert ledger["native_settled_volume_m3"] == pytest.approx(
        result["pumped_volume_m3"]
    )
    assert ledger["total_cost_usd"] == pytest.approx(result["cost_usd"])
