"""PCSE integration against the bundled or explicitly supplied historical inputs."""

from copy import deepcopy
from datetime import timedelta
import os
from pathlib import Path
import pytest

from fairy.scenarios.management_extensions.engines.sugarbeet_inputs import (
    SugarBeetInputs,
)
from fairy.scenarios.management_extensions.engines.sugarbeet_wofost import (
    SugarBeetBackend,
)
from fairy.scenarios.management_extensions.sugarbeet.scenario import DATA_DIR

pytest.importorskip(
    "pcse",
    reason="Actual PCSE dependency is absent; protocol tests are not a substitute",
)


@pytest.fixture
def bundle():
    value = os.getenv("FAIRY_BEET_INPUT_DIR", DATA_DIR / "sugarbeet_demo")
    return SugarBeetInputs(Path(value))


def test_real_pcse_initialization_and_replay(bundle):
    b = SugarBeetBackend(bundle)
    while b.next_day < bundle.cycles[0].sowing_open:
        b.advance_day()
    b.queue("s", "sow")
    b.queue("n1", "fertilize", 20)
    b.queue("n2", "fertilize", 10)
    b.queue("w1", "irrigate", 10)
    b.queue("w2", "irrigate", 15)
    for _ in range(40):
        b.advance_day()
    assert b.values["LAI"] is not None and b.values["SM"] is not None
    assert b.model.parameterprovider["IDSL"] == 0
    restored = SugarBeetBackend.restore(bundle, b.export_state())
    assert restored.export_state() == b.export_state()


def test_native_direct_vs_deferred_adapter(bundle):
    b = SugarBeetBackend(bundle)
    r = b.runtime
    c = bundle.cycles[0]
    provider = r["ParameterProvider"](
        cropdata=deepcopy(b.parameters_by_cycle[c.cycle_id]),
        soildata=deepcopy(bundle.manifest["native_soil_parameters"]),
        sitedata=r["SiteProvider"](**bundle.manifest["native_site_parameters"]),
    )
    direct_cls = r["Model"].__mro__[1]
    direct = direct_cls(
        provider,
        b.weather_provider,
        [
            {
                bundle.season.start: {
                    "CropCalendar": {
                        "crop_name": c.native_name,
                        "variety_name": c.cultivar,
                        "crop_start_date": c.sowing_open,
                        "crop_start_type": "sowing",
                        "crop_end_date": c.harvest_close,
                        "crop_end_type": "harvest",
                        "max_duration": 400,
                    },
                    "TimedEvents": None,
                    "StateEvents": None,
                }
            }
        ],
    )
    end = c.sowing_open + timedelta(days=40)
    while b.next_day < end:
        if b.next_day == c.sowing_open:
            b.queue("s", "sow")
        b.advance_day()
        direct.run(days=1)
    for key in ("SM", "NAVAIL", "LAI", "TAGP", "TWSO"):
        assert b.values[key] == pytest.approx(
            direct.get_variable(key), rel=1e-9, abs=1e-7
        ), key


def test_scene_public_tool_schema_and_shared_factories(bundle):
    from fairy.scenarios.management_extensions.L3.scenario_sugarbeet_full_season import (
        ScenarioSugarBeetFullSeason,
    )

    scene = ScenarioSugarBeetFullSeason(input_dir=bundle.root, calibrating=True, seed=0)
    scene.setup()
    names = {a.name: {t.name for t in a.get_tools()} for a in scene.apps}
    assert {"sow", "fertilize", "harvest_roots", "harvest_blocks"} <= names["Tractor"]
    assert {"get_field_info", "inspect_blocks", "begin_next_cycle"} == names[
        "ArableField"
    ]
    assert scene.farm_environment.get_farm("arable").world is scene.farm
    assert scene.warehouse is scene.farm_environment.warehouse
    assert (
        not scene.validate().success
    )  # an empty field must never pass a full-season task


def test_actual_same_soil_rotation():
    value = os.getenv("FAIRY_ROTATION_INPUT_DIR", DATA_DIR / "wheat_beet_rotation_demo")
    bundle = SugarBeetInputs(value)
    b = SugarBeetBackend(bundle)
    old = b.model.soil
    first = bundle.cycles[0]
    while b.next_day < first.sowing_open:
        b.advance_day()
    b.queue("wheat_sow", "sow")
    b.queue("wheat_N", "fertilize", 120)
    b.queue("wheat_water", "irrigate", 30)
    while b.next_day <= first.harvest_close:
        if b.maturity and b.next_day >= first.harvest_open:
            break
        b.advance_day()
    assert b.maturity, "Reference wheat did not mature: do not certify rotation"
    b.harvest_now("wheat_harvest")
    while b.next_day < bundle.cycles[1].prepare_open:
        b.advance_day()
    before = {
        k: b.model.get_variable(k) for k in ("SM", "NAVAIL", "NSOIL", "W", "WLOW")
    }
    b.begin_next_cycle()
    assert b.model.soil is old and before == {
        k: b.model.get_variable(k) for k in before
    }
    while b.next_day < bundle.cycles[1].sowing_open:
        b.advance_day()
    b.queue("beet_sow", "sow")
    b.advance_day()
    assert b.model.parameterprovider["IDSL"] == 0 and b.model.soil is old
