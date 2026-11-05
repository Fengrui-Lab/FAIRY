from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from fairy import cli


class StopBeforeModel(Exception):
    pass


def test_pathsim_flags_reach_main_model_and_context_loader(monkeypatch, tmp_path):
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"mode": "l3_pathsim_same", "contexts": {"test_scene": "oracle workflow"}}))
    monkeypatch.setenv("FARM_FAIRY_RETRIEVED_CONTEXT_PATH", "previous-value")
    monkeypatch.setattr(cli, "get_scenario_class", lambda _name: lambda **_kwargs: object())
    captured = {}

    def capture_config(config):
        captured.update(config)
        raise StopBeforeModel

    monkeypatch.setattr(cli.BaseLLM, "llm_builder", capture_config)
    monkeypatch.setattr(sys, "argv", [
        "fairy.cli", "-s", "test_scene", "--agent", "--provider", "vllm",
        "--scenario-kwargs", '{"detailed_briefing":"l3_pathsim_same"}',
        "--retrieved-context-path", str(context), "--enable-thinking", "false",
        "--request-timeout-seconds", "600", "--parallel-tool-calls", "false",
        "--output-dir", str(tmp_path / "output"),
    ])
    with pytest.raises(StopBeforeModel):
        cli.main()
    assert captured["enable_thinking"] is False
    assert captured["timeout"] == 600
    assert captured["parallel_tool_calls"] is False
    from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_context_briefings import _load_retrieved_context
    assert _load_retrieved_context("test_scene", "l3_pathsim_same") == "oracle workflow"


@pytest.mark.parametrize("payload", [
    {"mode": "l3_pathsim_same", "contexts": {}},
    {"mode": "l3_pathsim_same", "contexts": {"test_scene": " "}},
    {"mode": "l3_pathsim_differ", "contexts": {"test_scene": "oracle workflow"}},
    [],
])
def test_invalid_context_rejected_before_scenario_construction(monkeypatch, tmp_path, payload):
    context = tmp_path / "context.json"
    context.write_text(json.dumps(payload))

    def unexpected_construction(**kwargs):
        pytest.fail("Invalid context must be rejected before scenario construction")

    monkeypatch.setattr(cli, "get_scenario_class", lambda _name: unexpected_construction)
    monkeypatch.setattr(sys, "argv", [
        "fairy.cli", "-s", "test_scene", "--agent",
        "--scenario-kwargs", '{"detailed_briefing":"l3_pathsim_same"}',
        "--retrieved-context-path", str(context),
    ])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
