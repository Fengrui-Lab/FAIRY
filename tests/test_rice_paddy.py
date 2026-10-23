from __future__ import annotations

import copy
import json

import pytest

pytest.importorskip("pcse")

from fairy.apps.paddy.models import default_soil
from fairy.apps.paddy.world import PaddyWorldApp
from fairy.apps.paddy.operations import PaddyOpsApp
from fairy.apps.paddy.machinery import PaddyMachineryApp
from fairy.controllers.engine import Engine
from fairy.physics.rice_backend import RiceWofostBackend, load_rice_parameters
from fairy.physics.simulation_unit import SimulationUnit
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.rice.scenarios import RiceScenario, audit_world, configuration, reference_checkpoints
from fairy.scenarios.fos.provenance import validate_baseline_provenance

WEATHER = dict(tmin_c=23., tmax_c=31., humidity_pct=75., rain_mm=0., radiation_mj_m2=18., wind_ms=2.)


def backend(**kwargs):
    return RiceWofostBackend(SimulationUnit("p1", "paddy_plot", 1000.), "2026-01-01", default_soil(), WEATHER, **kwargs)


def ready_world(label):
    field, weather = configuration("normal")
    world = PaddyWorldApp(field=field, weather=weather)
    world.load_state(copy.deepcopy(reference_checkpoints("normal")[label]))
    return world, PaddyOpsApp(world)


def test_actual_81_crop_and_explicit_completion():
    from pcse.crop.wofost81 import Wofost81
    from pcse.crop.assimilation import WOFOST81_Assimilation
    b = backend()
    b.apply("transplant", day="2026-01-01")
    assert isinstance(b.model.crop, Wofost81)
    assert isinstance(b.model.crop.assim, WOFOST81_Assimilation)
    crop, provenance = load_rice_parameters()
    assert crop["DVSI"] == .16 and crop["TDWI"] == 50
    assert crop["AMAX_REF"] == 40 and crop["KN"] == .4
    assert provenance["completion"]["status"] == "uncalibrated_structural_transfer"


def test_water_balance_overflow_drain_root_growth_and_maturity():
    b = backend()
    b.apply("water", amount_mm=200.)
    assert b.water.ledger()["overflow_mm"] == 50
    assert b.apply("water", amount_mm=30., drain=True) == 30
    assert b.water.ledger()["surface_water_mm"] == 120
    b.apply("day", day="2026-01-01", weather=WEATHER)
    pre = b.water.ledger()
    b.apply("transplant", day="2026-01-02")
    assert b.water.ledger() == pre
    b.apply("puddle", sope_cm_day=1., ksub_cm_day=.2)
    for _ in range(120):
        if b.water.states.SS < 2:
            b.apply("water", amount_mm=40.)
        b.apply("day", day=b.model.day.isoformat(), weather=WEATHER)
        assert abs(b.water.audit()["balance_residual_mm"]) < 1e-6
    assert b.maturity and b.crop_values["RD"] == 60
    crop = copy.deepcopy(b.crop_values)
    b.apply("day", day=b.model.day.isoformat(), weather=WEATHER)
    assert b.crop_values == crop


def test_drought_and_timed_irrigation_reach_native_crop():
    outputs = []
    for policy in ("dry", "rescue", "wet"):
        b = backend()
        b.apply("transplant", day="2026-01-01")
        b.apply("puddle", sope_cm_day=1., ksub_cm_day=.2)
        stress = []
        for day in range(105):
            if (policy == "wet" or policy == "rescue" and day >= 50) and b.water.states.SS < 2:
                b.apply("water", amount_mm=40.)
            b.apply("day", day=b.model.day.isoformat(), weather=WEATHER)
            if b.last_rates["RFTRA"] is not None:
                stress.append(b.last_rates["RFTRA"])
        outputs.append((b.crop_values["TWSO"], sum(stress)))
    assert outputs[0][0] < outputs[1][0] < outputs[2][0]
    assert outputs[0][1] < outputs[2][1]


def test_no_negative_water_or_impossible_drain():
    b = backend()
    assert b.apply("water", amount_mm=20., drain=True) == 0
    for _ in range(80):
        b.apply("day", day=b.model.day.isoformat(), weather=WEATHER)
    assert b.water.ledger()["surface_water_mm"] >= 0
    with pytest.raises(ValueError):
        b.apply("water", amount_mm=float("nan"))


def test_cross_midnight_canal_job_and_unequal_plot_areas():
    world = PaddyWorldApp(weather={"rain_mm": 0.})
    ops = PaddyOpsApp(world)
    world.channel("supply").flow_m3_hour = 3.
    ops.irrigate("p1", 100.)
    assert len(world.daily_records) >= 2
    assert world.channel("supply").withdrawn_m3 == pytest.approx(100 / .9)
    assert world.backends["p1"].water.ledger()["irrigation_mm"] == pytest.approx(100)
    assert world.backends["p2"].water.ledger()["irrigation_mm"] == 0
    assert audit_world(world)["success"]
    ops.irrigate("p2", 100.)
    assert world.channel("supply").delivered_m3 == pytest.approx(250)
    assert audit_world(world)["success"]


@pytest.mark.parametrize("operation,args", [
    ("irrigate", ("unknown", 10.)), ("irrigate", ("p1", -1.)),
    ("irrigate", ("p1", 100000.)), ("drain", ("p1", 10.)),
    ("soak", ("p1", 24)), ("puddle_and_level", ("p1",)),
    ("transplant", ("p1", "ir72_standard")), ("harvest", ("p1",)),
    ("load_seedlings", ("ir72_standard", 300000)), ("unload_grain", ("p1",)),
    ("dry_and_store", ("p1",)),
])
def test_rejected_operations_do_not_mutate(operation, args):
    world = PaddyWorldApp()
    ops = PaddyOpsApp(world)
    before = world.get_state()
    with pytest.raises(ValueError):
        getattr(ops, operation)(*args)
    assert world.get_state() == before


def test_soak_requires_elapsed_wet_time_not_flag():
    world = PaddyWorldApp()
    ops = PaddyOpsApp(world)
    ops.irrigate("p1", 100.)
    with pytest.raises(ValueError, match="24 wet hours"):
        ops.puddle_and_level("p1")
    ops.soak("p1", 24)
    assert world.plot("p1").soaked_hours < 24
    ops.soak("p1", 24)
    PaddyMachineryApp(world).attach_implement("tractor", "puddler")
    ops.puddle_and_level("p1")
    assert world.plot("p1").puddled
    assert world.backends["p1"].water.params.KSUB == .2


def test_transplant_stock_density_and_water_continuity():
    world, ops = ready_world("before_transplant")
    before = world.backends["p1"].water.ledger()
    ops.load_seedlings("ir72_standard", 75000)
    with pytest.raises(ValueError, match="standard density"):
        ops.transplant("p1", "ir72_standard", row_spacing_cm=30.)
    ops.transplant("p1", "ir72_standard")
    assert world.plot("p1").seedlings_planted == 75000
    assert world.backends["p1"].water.ledger() == before
    with pytest.raises(ValueError):
        ops.transplant("p1", "ir72_standard")
    assert audit_world(world)["success"]


def test_checkpoints_continue_exactly_and_reject_wrong_provenance():
    world, _ = ready_world("management_start")
    payload = json.loads(json.dumps(world.get_state()))
    field, weather = configuration("normal")
    restored = PaddyWorldApp(field=field, weather=weather)
    restored.load_state(payload)
    for w in (world, restored):
        ops = PaddyOpsApp(w)
        ops.irrigate("p1", 27.)
        w.run_job(5 * 86400)
    assert world.get_state() == restored.get_state()
    payload["backends"]["p1"]["provenance"]["pcse_version"] = "invalid"
    with pytest.raises(ValueError, match="checksum"):
        restored.load_state(payload)
    wrong = PaddyWorldApp(weather={"rain_mm": 0.})
    with pytest.raises(ValueError, match="configuration"):
        wrong.load_state(world.get_state())


def test_harvest_unload_store_preserve_dry_mass():
    world, ops = ready_world("before_harvest")
    ops.harvest("p1")
    p = world.plot("p1")
    wet = p.harvested_dry_kg / (1 - p.grain_moisture_pct / 100)
    ops.unload_grain("p1")
    result = ops.dry_and_store("p1")
    assert result["stored_kg_at_14pct"] == pytest.approx(p.harvested_dry_kg / .86)
    assert result["evaporated_water_kg"] + result["stored_kg_at_14pct"] == pytest.approx(wet)
    assert audit_world(world)["success"]


@pytest.mark.parametrize("scenario_id", [
    "scenario_rice_l1_" + name for name in ("irrigate", "drain", "puddle", "transplant", "harvest")
] + ["scenario_rice_l2_" + name for name in ("establishment", "irrigation_management", "harvest_storage")]
  + ["scenario_rice_l3_" + name for name in ("normal", "water_limit", "late_rain")])
def test_registered_oracles_replay_through_engine(scenario_id):
    cls = get_scenario_class(scenario_id)
    build = Engine(None, cls())
    workflow = build.build_oracle_workflow()
    # Building a dynamic oracle executes only its isolated planning world.
    assert len(build.scenario.get_typed_app(PaddyWorldApp).actions) == build.scenario._initial_action_count
    replay = Engine(None, cls())
    replay.replay_workflow(workflow)
    assert replay.evaluate().success
    assert replay.outcome_summary()["crop_backend_provenance"]["model"] == "Wofost81_NWLP_PADDY"


def test_model_and_parameter_fingerprints_prevent_mixed_baselines():
    a, b = PaddyWorldApp(), PaddyWorldApp(weather={"rain_mm": 0.})
    with pytest.raises(ValueError, match="mismatch"):
        validate_baseline_provenance({"crop_backend_provenance": a.crop_backend_provenance()},
                                    b.crop_backend_provenance(), "rice.json")


def test_legacy_not_silently_used_for_rice():
    with pytest.raises(ValueError, match="require WOFOST"):
        RiceScenario(crop_backend="legacy")


def test_rice_baseline_focus_projection_and_no_action(monkeypatch, tmp_path):
    from fairy.scenarios.rice.evaluation import build_baseline, compare_outcome, project_outcome
    sid = "scenario_rice_l1_harvest"
    baseline = build_baseline(sid)
    engine = Engine(None, get_scenario_class(sid)())
    engine.run_scenario_oracle(run_oracle=True)
    world = engine.scenario.get_typed_app(PaddyWorldApp)
    before = world.get_state()
    result = compare_outcome(engine.scenario, baseline)
    assert result["focus_unit_ids"] == ["p1"]
    assert result["agent"]["area_m2"] == 1000
    assert result["relative_gain"]["harvested_dry_kg"] == pytest.approx(1)
    assert result["relative_gain"]["biological_dry_kg"] is None
    assert result["donothing"]["harvested_dry_kg"] == 0
    assert world.get_state() == before
    (tmp_path / f"{sid}.json").write_text(json.dumps(baseline))
    monkeypatch.setenv("FOS_ORACLE_BASELINE_DIR", str(tmp_path))
    assert engine.evaluate().metadata["rice_outcome"] == result
    wrong = copy.deepcopy(baseline)
    wrong["initial_checkpoint_sha256"] = "wrong"
    with pytest.raises(ValueError, match="checkpoint"):
        compare_outcome(engine.scenario, wrong)
    growing, _ = ready_world("after_transplant")
    with pytest.raises(RuntimeError, match="native maturity"):
        project_outcome(growing, max_days=1)


def test_registry_without_pcse_and_clear_runtime_dependency():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-c", '''
import builtins
original_import = builtins.__import__
def without_pcse(name, *args, **kwargs):
    if name == "pcse" or name.startswith("pcse."):
        raise ImportError("PCSE deliberately unavailable")
    return original_import(name, *args, **kwargs)
builtins.__import__ = without_pcse
import fairy.physics.paddy_waterbalance
from fairy.scenarios.registry import list_scenarios, get_scenario_class
assert "scenario_rice_l3_normal" in list_scenarios()
try:
    get_scenario_class("scenario_rice_l3_normal")().setup()
except RuntimeError as exc:
    assert "pip install" in str(exc)
else:
    raise AssertionError("Rice silently ran without PCSE")
'''], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_rice_controller_uses_crop_context_and_live_tools():
    from types import SimpleNamespace as NS
    from fairy.controllers.agent_builder import build_controller_agent
    from fairy.controllers.agent_config import get_farm_world_system_prompt
    for mode in ("fairy", "are"):
        prompt = get_farm_world_system_prompt(mode, crop="rice")
        assert "PaddyOpsApp" in prompt and "soybean" not in prompt and "64 ridges" not in prompt

    class ScriptedLLM:
        provider, model = "openai", "scripted-rice-test"

        def __init__(self):
            self.calls = 0

        def chat_completion(self, messages, tools=None):
            assert "transplanted rice" in str(messages)
            self.calls += 1
            call = NS(id="irrigate", type="function", function=NS(name="PaddyOpsApp__irrigate",
                          arguments=json.dumps({"plot_id": "p1", "water_mm": 30.})))
            message = NS(content=None, tool_calls=[call]) if self.calls == 1 else NS(content="done", tool_calls=None)
            return NS(choices=[NS(message=message)], usage=None)

    scenario = get_scenario_class("scenario_rice_l1_irrigate")()
    scenario.setup()
    agent = build_controller_agent("farm_baseline_react", llm=ScriptedLLM(), toolsets=scenario.apps)
    engine = Engine(agent, scenario)
    engine.run_scenario_agent(max_tool_calls=5, timeout_seconds=30, setup_scenario=False)
    assert engine.evaluate().success
