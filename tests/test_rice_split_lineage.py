"""A child must remain a physical continuation of its installed parent Oracle."""
import copy

import pytest

from fairy.apps.paddy.world import PaddyWorldApp
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.rice import farm_checkpoint_state as artifacts, l3_defaults

LINEAGE = artifacts.load_artifact('split_lineage.json')


@pytest.mark.parametrize('sid', tuple(LINEAGE))
def test_split_executes_exact_source_continuation_and_independent_replay(sid):
    info = LINEAGE[sid]
    scenario = get_scenario_class(sid)(seed=0, detailed_briefing=True)
    scenario.setup()
    engine = Engine(None, scenario)
    world = scenario.get_typed_app(PaddyWorldApp)
    before = world.get_state()
    assert before['sha256'] == info['initial_checkpoint_sha256']
    assert engine._resolve_agent_task() == l3_defaults.split_briefing(sid)
    engine.build_oracle_workflow(run_oracle=False)
    assert world.get_state() == before
    workflow = engine.run_scenario_oracle(run_oracle=True)
    final = world.get_state()
    assert final['sha256'] == info['expected_final_state_sha256']
    replay = Engine(None, get_scenario_class(sid)(seed=0, detailed_briefing=True))
    replay.replay_workflow(workflow)
    assert replay.scenario.get_typed_app(PaddyWorldApp).get_state() == final
    validation = replay.evaluate()
    assert validation.success or validation.metadata.get('failures') == [
        'experimental: decision mechanism has not passed matched-control calibration']


def test_changed_parent_identity_rejects_regular_split_before_tool_execution(monkeypatch):
    from fairy.scenarios.rice import rice_scenario_helpers as helpers
    sid = 'scenario_rice_l1_fertilize'
    scenario = get_scenario_class(sid)()
    scenario.setup()
    before = scenario.get_typed_app(PaddyWorldApp).get_state()
    plan = copy.deepcopy(artifacts.load_oracle_plan(sid))
    plan['source_l3_plan_sha256'] = 'stale-parent'
    monkeypatch.setattr(helpers, 'load_oracle_plan', lambda _: plan)
    with pytest.raises(ValueError, match='differs from installed L3 source'):
        scenario.build_events_flow()
    assert scenario.get_typed_app(PaddyWorldApp).get_state() == before


def test_changed_parent_identity_rejects_challenge_split(monkeypatch):
    real_load = l3_defaults.load_asset
    def stale_load(relative):
        data = copy.deepcopy(real_load(relative))
        if relative.startswith('split_challenges/'):
            data['source_l3_plan_sha256'] = 'stale-parent'
        return data
    monkeypatch.setattr(l3_defaults, 'load_asset', stale_load)
    with pytest.raises(ValueError, match='differs from installed L3 source'):
        get_scenario_class('scenario_rice_l1_channel_clearance')().setup()


@pytest.mark.parametrize('sid', tuple(LINEAGE))
def test_split_briefing_modes_preserve_the_task(sid):
    full = get_scenario_class(sid)(detailed_briefing='true')
    short = get_scenario_class(sid)(detailed_briefing='false')
    full.setup()
    short.setup()
    assert full.scenario_input == l3_defaults.split_briefing(sid, True)
    assert short.scenario_input == l3_defaults.split_briefing(sid, False)
    assert short.scenario_input in full.scenario_input
    assert full._initial_state == short._initial_state
