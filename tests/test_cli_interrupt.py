"""An interrupted live agent must leave reviewable, replayable run artifacts."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from fairy import cli
from fairy.apps.app import App
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.scenarios.workflow import Workflow
from fairy.tool_utils import app_tool


class CounterApp(App):
    def __init__(self):
        super().__init__()
        self.value = 0

    @app_tool()
    def increment(self, amount: int) -> dict:
        self.value += amount
        return {"value": self.value}

    def get_state(self):
        return {"value": self.value}


class InterruptScenario(Scenario):
    scenario_id = "scenario_interrupt_test"

    def init_and_populate_apps(self):
        self.apps = [CounterApp()]

    def validate(self, env):
        value = self.get_typed_app(CounterApp).value
        return ScenarioValidationResult(success=value == 2, metadata={"value": value})


class InterruptingLLM:
    provider = "vllm"
    model = "fake-interrupt-test"

    def __init__(self):
        self.calls = 0

    def chat_completion(self, messages, tools=None):
        self.calls += 1
        if self.calls == 2:
            raise KeyboardInterrupt
        call = SimpleNamespace(
            id="increment-once", type="function",
            function=SimpleNamespace(name="CounterApp__increment", arguments='{"amount": 1}'),
        )
        message = SimpleNamespace(role="assistant", content=None, tool_calls=[call])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="tool_calls")],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


def test_cli_interrupt_keeps_completed_tools_and_writes_stopped_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    llm = InterruptingLLM()
    monkeypatch.setattr(cli.BaseLLM, "llm_builder", staticmethod(lambda config: llm))
    monkeypatch.setattr(cli, "get_scenario_class", lambda scenario_id: InterruptScenario)
    monkeypatch.setattr(sys, "argv", [
        "fairy.cli", "--scenario", "scenario_interrupt_test", "--agent",
        "--provider", "vllm", "--model", llm.model,
        "--max-tool-calls", "10", "--timeout-seconds", "30",
        "--output-dir", str(tmp_path / "runs"),
    ])

    cli.main()

    stem = tmp_path / "runs" / "scenario_interrupt_test"
    workflow = Workflow.load_workflow(str(stem) + ".agent_workflow.json")
    tool_steps = [step for step in workflow.dag.values() if step.tool_name]
    assert llm.calls == 2
    assert len(tool_steps) == 1
    assert tool_steps[0].tool_name == "CounterApp__increment"
    assert tool_steps[0].tool_args == {"amount": 1}
    replay = Engine(None, InterruptScenario())
    replay.replay_workflow(workflow)
    assert replay.scenario.get_typed_app(CounterApp).value == 1

    report = json.loads(stem.with_suffix(".run_report.json").read_text())
    assert report["status"] == "stopped"
    assert report["stopped_reason"] == report["stop_reason"] == "interrupted"
    assert report["error"] is None
    assert report["metrics"]["tool_call_count"] == 1
    assert report["metrics"]["llm_call_count"] == 1
    assert report["metrics"]["token_usage"]["total_tokens"] == 15
    assert report["evaluation"]["validation"]["success"] is False
    assert report["evaluation"]["validation"]["metadata"]["value"] == 1
    for suffix in (".runtime_log.jsonl", ".progress.jsonl"):
        rows = [json.loads(line) for line in stem.with_suffix(suffix).read_text().splitlines()]
        assert rows[-1]["record_type"] == "agent_run_end"
        assert rows[-1]["status"] == "stopped"
        assert rows[-1]["stopped_reason"] == "interrupted"
        assert rows[-1]["interruption"] == "KeyboardInterrupt"
