from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fairy import cli
from fairy.agents.agent.agent import Agent
from fairy.agents.llm.base_llm import BaseLLM
from fairy.agents.llm.deepseek_client import DeepSeekClient
from fairy.apps.app import App
from fairy.scenarios.workflow import Workflow
from fairy.tool_utils import app_tool
from scripts import iclr_validation_runner as runner


class ReadingApp(App):
    @app_tool()
    def read_value(self, count: int = 1) -> dict:
        """Read a value for the tool transport test.

        Args:
            count: Value to return.
        """
        return {"count": count}


class DeepSeekThinkingTests(unittest.TestCase):
    def _run_cli(self, flags: list[str], *, a2a: bool = False):
        scenario = SimpleNamespace(apps=[ReadingApp()], setup=Mock(), seed=0)
        argv = ["fairy", "--agent", "--scenario", "thinking-test", *flags]
        if a2a:
            argv += ["--a2a", "true", "--a2a-app-prop", "1"]
        # Build the real controller/client while preventing network, scenario
        # execution, and all filesystem writes or cleanup operations.
        with ExitStack() as stack:
            stack.enter_context(patch("sys.argv", argv))
            stack.enter_context(redirect_stdout(StringIO()))
            stack.enter_context(patch.object(cli, "get_scenario_class", return_value=lambda **_: scenario))
            stack.enter_context(patch.object(Path, "mkdir"))
            stack.enter_context(patch.object(Path, "exists", return_value=False))
            stack.enter_context(patch.object(cli, "_cleanup_legacy_artifacts"))
            stack.enter_context(patch.object(cli, "_cleanup_repo_side_exports"))
            stack.enter_context(patch.object(Workflow, "save_workflow"))
            stack.enter_context(patch.object(cli, "write_jsonl"))
            write_json = stack.enter_context(patch.object(cli, "write_json"))
            engine = stack.enter_context(patch.object(cli, "Engine"))
            engine.return_value.run_scenario_agent.return_value = Workflow()
            engine.return_value.evaluation_report.return_value = {}
            engine.return_value.outcome_summary.return_value = {}
            cli.main()
            return engine.call_args.kwargs["agent"], scenario, write_json.call_args.args[1]

    def _run_runner(self, provider, config, flags):
        argv = ["runner", "--phase", "test", "--output-root", "/tmp/fairy-thinking-test",
                "--families", "farm_baseline_react", "--scenarios", "thinking-test",
                "--provider", provider, "--model", "deepseek-flash",
                "--config", "config.json", *flags]
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}))
            stack.enter_context(patch("sys.argv", argv))
            stack.enter_context(redirect_stdout(StringIO()))
            stack.enter_context(patch.object(Path, "mkdir"))
            stack.enter_context(patch.object(Path, "exists", return_value=False))
            stack.enter_context(patch.object(Path, "read_text", return_value=json.dumps(config)))
            stack.enter_context(patch.object(Path, "open", side_effect=lambda *a, **k: StringIO()))
            process = stack.enter_context(patch.object(runner.subprocess, "Popen"))
            stack.enter_context(patch.object(runner, "_wait_for_cell_process", return_value=(0, False, False)))
            csv_write = stack.enter_context(patch.object(runner, "_write_results_csv"))
            self.assertEqual(runner.main(), 0)
            return process.call_args.args[0], csv_write.call_args.args[1][0]

    def test_runner_json_cli_precedence_reaches_request_and_reports(self):
        cases = (
            ({}, [], "disabled"),
            ({"thinking": None}, [], "disabled"),
            ({"thinking": "disabled"}, [], "disabled"),
            ({"thinking": "enabled"}, [], "enabled"),
            ({"thinking": "enabled"}, ["--thinking", "disabled"], "disabled"),
            ({"thinking": "disabled"}, ["--thinking", "enabled"], "enabled"),
        )
        for provider in ("deepseek", "deepseek-json"):
            for config, flags, thinking in cases:
                with self.subTest(provider=provider, config=config, flags=flags):
                    command, row = self._run_runner(provider, config, flags)
                    self.assertEqual(command[command.index("--thinking") + 1], thinking)
                    self.assertNotIn("--enable-thinking", command)
                    self.assertNotIn("--preserve-thinking", command)
                    self.assertEqual(row["thinking"], thinking)
                    with patch("fairy.agents.llm.deepseek_client.OpenAI") as sdk:
                        agent, _, report = self._run_cli(command[3:])
                        agent.llm.chat_completion([{"role": "user", "content": "Test"}], tools=[])
                        request = sdk.return_value.chat.completions.create.call_args.kwargs
                        self.assertEqual(request["extra_body"], {"thinking": {"type": thinking}})
                    self.assertEqual(report["llm_config"]["thinking"], thinking)
                    self.assertEqual(report["llm_config"]["reasoning_history_policy"],
                                     "preserve" if thinking == "enabled" else "exclude")

    def test_direct_client_and_cli_default_disable_thinking(self):
        with patch("fairy.agents.llm.deepseek_client.OpenAI") as sdk:
            for kwargs in ({}, {"thinking": None}, {"thinking": "disabled"}):
                with self.subTest(kwargs=kwargs):
                    client = DeepSeekClient("deepseek-flash", **kwargs)
                    client.chat_completion([])
                    self.assertEqual(sdk.return_value.chat.completions.create.call_args.kwargs["extra_body"],
                                     {"thinking": {"type": "disabled"}})
                    self.assertEqual(client.to_dict()["thinking"], "disabled")
            for provider in ("deepseek", "deepseek-json"):
                with self.subTest(provider=provider):
                    agent, _, report = self._run_cli(["--provider", provider])
                    self.assertEqual(agent.llm.thinking, "disabled")
                    self.assertEqual(report["llm_config"]["reasoning_history_policy"], "exclude")

    def test_invalid_direct_client_values_fail_before_sdk_creation(self):
        for value in (True, False, "true", "false", "ENABLED", "", {}, [], 1):
            with self.subTest(value=value), patch("fairy.agents.llm.deepseek_client.OpenAI") as sdk:
                with self.assertRaises(ValueError):
                    DeepSeekClient("deepseek-flash", thinking=value)
                sdk.assert_not_called()

    def test_builder_rejects_thinking_for_other_providers(self):
        for provider in ("openai", "qwen", "qwen-json", "vllm", "llama-api", "anthropic"):
            for value in ("enabled", "disabled"):
                with self.subTest(provider=provider, value=value), self.assertRaises(ValueError):
                    BaseLLM.llm_builder({"provider": provider, "model": "test", "thinking": value})
        with patch("fairy.agents.llm.deepseek_client.OpenAI"):
            for provider in ("deepseek", "deepseek-json"):
                client = BaseLLM.llm_builder({
                    "provider": provider, "model": "deepseek-flash", "thinking": "enabled",
                })
                self.assertEqual(client.thinking, "enabled")

    def test_invalid_cli_and_json_values_or_providers_fail_before_execution(self):
        required = ["--phase", "test", "--output-root", "/tmp/fairy-thinking-test",
                    "--families", "farm_baseline_react", "--scenarios", "thinking-test"]
        cases = [
            ["--provider", "deepseek", "--thinking", "true"],
            ["--provider", "deepseek", "--enable-thinking", "true"],
            ["--provider", "deepseek", "--preserve-thinking", "true"],
        ]
        cases += [
            ["--provider", provider, "--thinking", value]
            for provider in ("qwen", "qwen-json", "vllm", "openai", "llama-api")
            for value in ("enabled", "disabled")
        ]
        for flags in cases:
            with self.subTest(flags=flags), redirect_stderr(StringIO()):
                with patch("sys.argv", ["fairy", "--agent", "-s", "thinking-test", *flags]), \
                        patch.object(cli, "get_scenario_class") as lookup, \
                        self.assertRaises(SystemExit) as error:
                    cli.main()
                self.assertEqual(error.exception.code, 2)
                lookup.assert_not_called()
                with patch.object(runner.subprocess, "Popen") as launch, self.assertRaises(SystemExit):
                    runner._parse_args(required + flags)
                launch.assert_not_called()

        configs = [{"provider": "deepseek", "thinking": value}
                   for value in (True, False, "", "invalid", {}, [], 1)]
        configs += [{"provider": provider, "thinking": "enabled"}
                    for provider in ("qwen", "vllm", "openai")]
        for config in configs:
            with self.subTest(config=config), \
                    patch.object(Path, "read_text", return_value=json.dumps(config)), \
                    redirect_stderr(StringIO()), self.assertRaises((SystemExit, ValueError)):
                runner._parse_args(required + ["--config", "config.json"])

    def test_main_thinking_is_not_inherited_by_a2a(self):
        for expert_provider in ("deepseek", "deepseek-json", "qwen", "vllm"):
            with self.subTest(expert_provider=expert_provider), ExitStack() as stack:
                stack.enter_context(patch("fairy.agents.llm.deepseek_client.OpenAI"))
                stack.enter_context(patch("fairy.agents.llm.qwen_client.OpenAI"))
                stack.enter_context(patch("fairy.agents.llm.vllm_client.OpenAI"))
                agent, scenario, report = self._run_cli([
                    "--provider", "deepseek", "--thinking", "enabled",
                    "--a2a-provider", expert_provider,
                ], a2a=True)
                self.assertEqual(agent.llm.thinking, "enabled")
                expert = scenario.apps[0].app_agent
                if expert_provider.startswith("deepseek"):
                    self.assertEqual(expert.llm.thinking, "disabled")
                else:
                    self.assertIsNone(getattr(expert.llm, "thinking", None))
                self.assertEqual(expert.llm_config()["reasoning_history_policy"], "exclude")
                self.assertTrue(report["a2a"]["enabled"])

    def test_history_keeps_all_assistant_reasoning_only_when_enabled(self):
        history = [
            {"role": "system", "content": "System", "reasoning_content": "not assistant"},
            {"role": "user", "content": "Question", "reasoning_content": "not assistant"},
            {"role": "assistant", "content": "Plain answer", "reasoning_content": "Earlier reasoning", "time": "extra"},
            {"role": "assistant", "content": "Another answer", "reasoning_content": ""},
            {"role": "assistant", "content": "No reasoning", "reasoning_content": None},
            {"role": "tool", "tool_call_id": "call_1", "content": "Result", "reasoning_content": "not assistant"},
        ]
        original = deepcopy(history)
        for provider in ("deepseek", "qwen", "vllm", "openai"):
            for thinking in ("enabled", "disabled"):
                with self.subTest(provider=provider, thinking=thinking):
                    client = SimpleNamespace(provider=provider, thinking=thinking, model="test")
                    agent = Agent("test", client)
                    sent = agent._llm_compatible_messages(history)
                    for before, after in zip(history, sent):
                        keep = (provider == "deepseek" and thinking == "enabled"
                                and before["role"] == "assistant"
                                and before.get("reasoning_content") is not None)
                        self.assertEqual("reasoning_content" in after, keep)
                        if keep:
                            self.assertEqual(after["reasoning_content"], before["reasoning_content"])
                        self.assertNotIn("time", after)
                    self.assertEqual(history, original)

    def test_real_sdk_tool_rounds_and_plain_assistant_history_match_request_logs(self):
        import httpx
        from openai import OpenAI

        for thinking in ("enabled", "disabled"):
            with self.subTest(thinking=thinking), ExitStack() as stack:
                requests = []

                def respond(request):
                    requests.append(json.loads(request.content))
                    turn = len(requests)
                    message = {"role": "assistant", "content": None,
                               "reasoning_content": f"Original reasoning {turn}."}
                    if turn <= 2:
                        message["tool_calls"] = [{"id": f"call_{turn}", "type": "function", "function": {
                            "name": tool_name, "arguments": json.dumps({"count": turn}),
                        }}]
                    else:
                        message["content"] = "Done."
                    return httpx.Response(200, json={
                        "id": f"response_{turn}", "object": "chat.completion", "created": 0,
                        "model": "deepseek-flash", "choices": [{"index": 0, "message": message,
                        "finish_reason": "tool_calls" if turn <= 2 else "stop"}],
                    })

                def make_sdk(**kwargs):
                    sdk = OpenAI(http_client=httpx.Client(transport=httpx.MockTransport(respond)), **kwargs)
                    stack.callback(sdk.close)
                    return sdk

                stack.enter_context(patch("fairy.agents.llm.deepseek_client.OpenAI", side_effect=make_sdk))
                client = DeepSeekClient("deepseek-flash", api_key="test-key", thinking=thinking,
                                        base_url="https://deepseek.example/v1")
                app = ReadingApp()
                agent = Agent("deepseek-test", client, toolsets=[app], max_llm_call_retries=0)
                agent.set_time_manager(app.time_manager)
                tool_name = agent.tool_schemas[0]["function"]["name"]
                with redirect_stdout(StringIO()):
                    self.assertEqual(agent.run("Read twice."), "Done.")
                    self.assertEqual(agent.run("Continue from the prior answer."), "Done.")
                self.assertEqual(len(requests), 4)
                for turn, request in enumerate(requests):
                    self.assertEqual(request["thinking"], {"type": thinking})
                    self.assertNotIn("extra_body", request)
                    self.assertNotIn("enable_thinking", request)
                    self.assertNotIn("preserve_thinking", request)
                    assistants = [m for m in request["messages"] if m["role"] == "assistant"]
                    self.assertEqual(len(assistants), turn)
                    for index, message in enumerate(assistants, 1):
                        if thinking == "enabled":
                            self.assertEqual(message["reasoning_content"], f"Original reasoning {index}.")
                        else:
                            self.assertNotIn("reasoning_content", message)
                        if index <= 2:
                            self.assertEqual(message["tool_calls"][0]["id"], f"call_{index}")
                    tool_results = [m for m in request["messages"] if m["role"] == "tool"]
                    self.assertEqual([m["tool_call_id"] for m in tool_results],
                                     [f"call_{index}" for index in range(1, min(turn, 2) + 1)])
                history = [m for m in agent.messages() if getattr(m, "role", None) == "assistant"]
                self.assertEqual([m.reasoning_content for m in history],
                                 [f"Original reasoning {index}." for index in range(1, 5)])
                starts = [e for e in agent.runtime_events if e["event_type"] == "llm_call_start"]
                self.assertEqual(len(starts), 4)
                for event, request in zip(starts, requests):
                    self.assertEqual(event["messages"], request["messages"])
                    self.assertEqual(event["llm_config"]["thinking"], thinking)
                    self.assertEqual(event["reasoning_history_policy"],
                                     "preserve" if thinking == "enabled" else "exclude")


if __name__ == "__main__":
    unittest.main()
