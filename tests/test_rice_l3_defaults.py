"""Regression coverage for installed L3 defaults and source-derived splits."""
import json
from pathlib import Path

import pytest

from fairy.apps.paddy.world import PaddyWorldApp
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.rice import l3_defaults
from fairy.scenarios.crop_challenges.catalog import TASKS
from fairy.scenarios.crop_challenges.runtime import CropChallengeScenario

SIDS=tuple(json.loads((l3_defaults.ROOT/'manifest.json').read_text())['scenarios'])

@pytest.mark.parametrize('sid',SIDS)
def test_default_l3_uses_new_task_and_pure_frozen_oracle(sid,monkeypatch):
    def reject(*args,**kwargs):
        pytest.fail('Default setup must not execute agronomic work')
    monkeypatch.setattr(PaddyWorldApp,'run_job',reject)
    s=get_scenario_class(sid)(detailed_briefing=True,seed=0)
    s.setup();world=s.get_typed_app(PaddyWorldApp);before=world.get_state()
    engine=Engine(None,s)
    assert engine._resolve_agent_task()==l3_defaults.detailed_briefing(sid)
    assert not world.actions and all(not p.planted for p in world.field.plots)
    manifest=json.loads((l3_defaults.ROOT/'manifest.json').read_text())
    assert len(s.events)-1==manifest['scenarios'][sid]['tool_calls']
    engine.build_oracle_workflow(run_oracle=False)
    assert world.get_state()==before

@pytest.mark.parametrize('sid',SIDS)
def test_detail_false_does_not_use_the_new_long_task(sid):
    s=get_scenario_class(sid)(detailed_briefing=False,seed=0);s.setup()
    assert s.scenario_input
    assert s.scenario_input!=l3_defaults.detailed_briefing(sid)

@pytest.mark.parametrize('sid',[sid for sid in TASKS if sid.startswith('scenario_rice_') and '_l3_' not in sid])
def test_challenge_l1_l2_use_new_source_snapshots_and_standard_plan_loader(sid):
    cls=get_scenario_class(sid)
    assert cls.init_and_populate_apps.__name__ == "_init_split_default"
    assert cls.build_events_flow is CropChallengeScenario.build_events_flow


def test_default_l3_briefing_checksum_rejects_modified_text(tmp_path,monkeypatch):
    manifest=json.loads((l3_defaults.ROOT/'manifest.json').read_text())
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    (tmp_path/'detailed_briefings.json').write_text('{}')
    monkeypatch.setattr(l3_defaults,'ROOT',tmp_path)
    with pytest.raises(ValueError,match='checksum mismatch'):
        l3_defaults.detailed_briefing(SIDS[0])
