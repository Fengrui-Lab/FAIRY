"""The 53 reviewed short descriptions must reach the actual agent task source."""
import hashlib
import json
import logging.config
import re
from copy import deepcopy
from pathlib import Path

import pytest

from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class


EXPERT_HASHES = json.loads(
    Path(__file__).with_name("fixtures").joinpath("briefing_mode_expert_hashes.json").read_text()
)


def basic_briefings():
    return {sid: get_scenario_class(sid).__dict__["BASIC_BRIEFING"] for sid in EXPERT_HASHES}

# These failures were present in the pre-change audit. Do not bypass frozen
# checkpoint validation just to exercise prompt selection in an invalid world.
KNOWN_CHECKPOINT_ERRORS = {
    "scenario_maize_l2_compound_water_n_limit":
        "Replayed soil nitrogen state changes disagree with the saved audit record",
}


@pytest.fixture(scope="module", autouse=True)
def local_pcse_log(tmp_path_factory):
    """PCSE otherwise writes outside the workspace at import time."""
    original = logging.config.dictConfig
    log_path = str(tmp_path_factory.mktemp("briefing-pcse") / "pcse.log")

    def configure(config):
        from copy import deepcopy
        config = deepcopy(config)
        for handler in config.get("handlers", {}).values():
            if "filename" in handler:
                handler["filename"] = log_path
        return original(config)

    logging.config.dictConfig = configure
    yield
    logging.config.dictConfig = original


def test_reviewed_scope_and_no_operation_parameters_in_short_text():
    assert len(basic_briefings()) == 53
    assert set(basic_briefings()) == set(EXPERT_HASHES)
    for scenario_id, text in basic_briefings().items():
        assert not scenario_id.startswith(("scenario_tangyan5_", "scenario_farm_world_", "scenario_l1_hb_", "scenario_l2_hb_"))
        assert not re.search(r"播深|深度|密度|株距|公斤|千克|毫米|小时|分钟|厘米|%|每趟|DEMO|预算|配额|≤|≥", text)


@pytest.mark.parametrize("scenario_id", sorted(EXPERT_HASHES))
def test_modes_reach_agent_and_keep_original_expert_description(scenario_id):
    cls = get_scenario_class(scenario_id)
    assert cls().detailed_briefing is True
    scenes = []
    for mode in (False, True):
        scene = cls(detailed_briefing=mode)
        try:
            scene.setup()
        except ValueError as exc:
            if str(exc) == KNOWN_CHECKPOINT_ERRORS.get(scenario_id):
                pytest.xfail(f"Pre-existing checkpoint mismatch: {exc}")
            raise
        task = Engine(None, scene)._resolve_agent_task()
        assert task == scene.scenario_input
        if mode:
            assert hashlib.sha256(task.encode()).hexdigest() == EXPERT_HASHES[scenario_id]
        else:
            assert task == basic_briefings()[scenario_id]
            assert not re.search(r"\d+(?:\.\d+)?\s*(?:kg|公斤|毫米|mm|cm|厘米|%)", scene.additional_system_prompt or "")
        if scenario_id.startswith(("scenario_multiobjective_", "scenario_multiseason_")):
            assert scene.additional_system_prompt == task
        # Setup is idempotent, including the selected captured event.
        scene.setup()
        assert Engine(None, scene)._resolve_agent_task() == task
        scenes.append(scene)
    assert [(type(a), a.name) for a in scenes[0].apps] == [(type(a), a.name) for a in scenes[1].apps]


@pytest.mark.parametrize("scenario_id", sorted(EXPERT_HASHES))
def test_invalid_mode_is_not_silently_truthy(scenario_id):
    for value in ("false", "fasle", 0, 1, None):
        with pytest.raises(ValueError, match="detailed_briefing must be a JSON boolean"):
            get_scenario_class(scenario_id)(detailed_briefing=value)


@pytest.mark.parametrize("scenario_id", [
    "scenario_multi_farm_uneven_planting",
    "scenario_multiseason_scn_continue_maize",
    "scenario_two_farm_wofost_soil_water_diagnosis_V2",
])
@pytest.mark.parametrize("mode", [False, True])
def test_explicit_task_override_reaches_agent(scenario_id, mode):
    custom = "自定义任务：只检查当前田块，等待后续安排。"
    scene = get_scenario_class(scenario_id)(detailed_briefing=mode, scenario_input=custom)
    scene.setup()
    assert Engine(None, scene)._resolve_agent_task() == custom


@pytest.mark.parametrize("scenario_id", [
    "scenario_multi_farm_uneven_planting",
    "scenario_multiseason_scn_continue_maize",
    "scenario_two_farm_wofost_soil_water_diagnosis_V2",
])
def test_mode_keeps_initial_world_and_reference_actions(scenario_id):
    states, plans = [], []
    for mode in (False, True):
        scene = get_scenario_class(scenario_id)(detailed_briefing=mode)
        scene.setup()
        engine = Engine(None, scene)
        state = deepcopy([app.get_state() for app in scene.apps])
        plan = engine.build_oracle_workflow(run_oracle=False)
        assert [app.get_state() for app in scene.apps] == state
        states.append(state)
        plans.append({name: step.to_dict() for name, step in plan.dag.items()
                      if step.tool_name != "AgentUserInterface__send_message_to_agent"})
    assert states[0] == states[1]
    assert plans[0] == plans[1]


def test_weather_schema_compatibility_does_not_hide_other_checkpoint_changes(monkeypatch):
    scene = get_scenario_class("scenario_maize_l3_zonal_water_priority")()
    export = scene.export_checkpoint

    def changed_checkpoint(label):
        checkpoint = export(label)
        checkpoint["farm"]["sim_time"] += 1
        return checkpoint

    monkeypatch.setattr(scene, "export_checkpoint", changed_checkpoint)
    with pytest.raises(ValueError, match="Challenge initial checkpoint differs"):
        scene.setup()
