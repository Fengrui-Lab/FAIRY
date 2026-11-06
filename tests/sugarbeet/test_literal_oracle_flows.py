"""Published scene graphs must reproduce the independently verified public traces."""

from copy import deepcopy
from importlib import import_module
import json

import pytest

from scripts.sugarbeet_oracle import SCENARIOS
from fairy.scenarios.management_extensions.sugarbeet.scenario import (
    DATA_DIR,
    SugarBeetScenario,
)


def scenario_class(name):
    module, class_name = SCENARIOS[name]
    return getattr(
        import_module("fairy.scenarios.management_extensions." + module), class_name
    )


@pytest.mark.parametrize("name", SCENARIOS)
def test_default_scene_captures_verified_trace_without_external_dispatch(name, monkeypatch):
    def reject_external_dispatch(self):
        raise AssertionError("A default scene must capture its own literal Oracle")

    monkeypatch.setattr(
        SugarBeetScenario, "_build_reference_events_flow", reject_external_dispatch
    )
    cls = scenario_class(name)
    assert "build_events_flow" in cls.__dict__
    scene = cls(seed=0)
    scene.setup()
    assert scene.ORACLE_REFERENCE is not None, "Published reference needs revalidation"
    before = deepcopy([app.get_state() for app in scene.apps])
    scene.build_events_flow()
    assert [app.get_state() for app in scene.apps] == before
    actual = [
        dict(app=event.app.name, tool=event.function.__name__, arguments=event.kwargs)
        for event in scene.events
        if event.app.name != "AgentUserInterface"
    ]
    expected = [
        {key: step[key] for key in ("app", "tool", "arguments")}
        for step in scene.ORACLE_REFERENCE["workflow"]
    ]
    assert actual == expected


def test_explicit_custom_reference_keeps_its_public_workflow_loader(monkeypatch):
    calls = []
    original = SugarBeetScenario._build_reference_events_flow

    def record_custom_dispatch(self):
        calls.append(self.scenario_id)
        return original(self)

    monkeypatch.setattr(
        SugarBeetScenario, "_build_reference_events_flow", record_custom_dispatch
    )
    cls = scenario_class("full_season")
    path = DATA_DIR / "sugarbeet_oracles" / (cls.scenario_id + ".json")
    scene = cls(seed=0, reference_file=path)
    scene.setup()
    assert calls == [cls.scenario_id]
    assert len(scene.events) == len(json.loads(path.read_text())["workflow"]) + 1
