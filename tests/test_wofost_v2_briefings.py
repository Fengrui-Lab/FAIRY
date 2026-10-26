"""Public V2 task instructions reach the Agent without changing its world."""
from copy import deepcopy
import importlib
import json
from pathlib import Path

import pytest

from fairy.apps.farm_world import FarmWorldApp
from fairy.controllers.engine import Engine


ROOT = Path(__file__).resolve().parents[1]
ROWS = json.loads((ROOT / 'configs/oracles/wofost_scenario_versions.json').read_text())['rows']


def _load(row, detailed):
    module_name = '.'.join(Path(row['wofost_source_path']).with_suffix('').parts)
    cls = getattr(importlib.import_module(module_name), row['wofost_class_name'])
    scene = cls(detailed_briefing=detailed)
    scene.setup()
    return scene, Engine(None, scene)


@pytest.mark.parametrize('row', ROWS, ids=lambda row: row['wofost_id'])
def test_scene_owned_detail_reaches_the_actual_agent_task(row):
    detailed, full_engine = _load(row, True)
    compact, short_engine = _load(row, False)
    text = detailed.__class__.__dict__['DETAILED_BRIEFING']
    assert isinstance(text, str) and len(text) >= 250
    full_task = full_engine._resolve_agent_task()
    short_task = short_engine._resolve_agent_task()
    assert full_task == detailed.reference_briefing()
    assert short_task == compact.reference_briefing()
    assert full_task == short_task + '\n\n' + text
    assert text not in short_task
    for task in (full_task, short_task):
        assert detailed.WORLD.seed_type in task
        assert detailed.reference['location']['name'] in task
        assert detailed.WORLD.timezone_name in task
    if 'SurveyDrone' in text:
        assert 'SurveyDrone' in {app.name for app in detailed.apps}
    quota = detailed.WORLD.irrigation_quota_mm
    if quota is not None:
        assert f'{quota:g}' in text


@pytest.mark.parametrize('row', ROWS, ids=lambda row: row['wofost_id'])
def test_detail_flag_changes_only_task_text_not_initial_world_or_oracle_actions(row):
    plans = []
    worlds = []
    for enabled in (False, True):
        scene, engine = _load(row, enabled)
        farm = scene.get_typed_app(FarmWorldApp)
        before = deepcopy((farm.get_state(), farm.physics.crop_backend.export_state(),
                           engine.time_manager.time()))
        plan = engine.build_oracle_workflow(run_oracle=False)
        assert (farm.get_state(), farm.physics.crop_backend.export_state(),
                engine.time_manager.time()) == before
        worlds.append(before)
        plans.append({name: step.to_dict() for name, step in plan.dag.items()
                      if step.tool_name != 'AgentUserInterface__send_message_to_agent'})
    assert worlds[0] == worlds[1]
    assert plans[0] == plans[1]
