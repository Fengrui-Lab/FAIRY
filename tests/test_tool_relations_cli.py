from __future__ import annotations

from copy import deepcopy
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fairy import cli
from fairy.agents.agent.agent import Agent
from fairy.agents.agent.toolset_builder import build_toolset
from fairy.apps.app import App
from fairy.controllers.app_agent import AppAgent
from fairy.scenarios.workflow import Workflow
from fairy.tool_utils import app_tool
from scripts import iclr_validation_runner as runner


class RelationExampleApp(App):
    @app_tool()
    def read_value(self, count: int = 1) -> dict:
        """Return the requested number of example values.

        Relation:
            Read example values before preparing an example report.

        Args:
            count: Number of values to return.
        """
        return {"count": count}


class FakeLLM:
    provider = "test"
    model = "test-model"

    def __init__(self) -> None:
        self.received_tools = []

    def chat_completion(self, messages, tools=None):
        self.received_tools.append(tools)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="Done.", tool_calls=[]),
                finish_reason="stop",
            )],
            usage=None,
        )


class ToolRelationsCLITests(unittest.TestCase):
    def _run_cli(self, flags: list[str], *, a2a: bool = False, llm_builder=None):
        app = RelationExampleApp()
        scenario = SimpleNamespace(apps=[app], setup=Mock(), seed=0)
        argv = ["fairy", "--agent", "--scenario", "schema-test", *flags]
        if a2a:
            argv.extend(["--a2a", "true", "--a2a-app-prop", "1"])

        # Exercise argument parsing and real controller/A2A construction without
        # running a scenario, contacting an LLM, or creating/removing artifacts.
        with ExitStack() as stack:
            stack.enter_context(patch("sys.argv", argv))
            stack.enter_context(redirect_stdout(StringIO()))
            stack.enter_context(patch.object(cli, "get_scenario_class", return_value=lambda **_: scenario))
            stack.enter_context(patch.object(cli.BaseLLM, "llm_builder", side_effect=llm_builder or (lambda _: FakeLLM())))
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
            agent = engine.call_args.kwargs["agent"]
            report = write_json.call_args.args[1]
        return agent, scenario, report

    def test_cli_default_on_and_explicit_modes_reach_generated_schemas(self) -> None:
        for flags, expected in (([], True), (["--tool-relations", "on"], True),
                                (["--tool-relations", "off"], False)):
            with self.subTest(flags=flags):
                agent, _, report = self._run_cli(flags)
                function = agent.tool_schemas[0]["function"]
                self.assertEqual(agent.include_tool_relations, expected)
                self.assertEqual("Read example values before" in function["description"], expected)
                self.assertIn("Return the requested number", function["description"])
                self.assertEqual(
                    function["parameters"]["properties"]["count"],
                    {"type": "integer", "description": "Number of values to return."},
                )
                self.assertEqual(function["parameters"]["required"], [])
                self.assertEqual(report["tool_relations"], "on" if expected else "off")

    def test_cli_mode_reaches_real_a2a_expert_schema(self) -> None:
        for mode in ("on", "off"):
            with self.subTest(mode=mode):
                agent, scenario, report = self._run_cli(["--tool-relations", mode], a2a=True)
                wrapper = scenario.apps[0]
                self.assertIsInstance(wrapper, AppAgent)
                self.assertEqual(agent.include_tool_relations, mode == "on")
                expert = wrapper.app_agent
                self.assertEqual(expert.include_tool_relations, mode == "on")
                function = next(
                    schema["function"] for schema in expert.tool_schemas
                    if schema["function"]["name"].endswith("__read_value")
                )
                self.assertEqual("Read example values before" in function["description"], mode == "on")
                self.assertTrue(report["a2a"]["enabled"])
                self.assertEqual(report["tool_relations"], mode)

    def test_invalid_cli_mode_fails_before_scenario_lookup(self) -> None:
        with patch("sys.argv", ["fairy", "--tool-relations", "unknown"]), \
                patch.object(cli, "get_scenario_class") as lookup, \
                redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
            cli.main()
        self.assertEqual(error.exception.code, 2)
        lookup.assert_not_called()

    def test_vllm_main_cli_thinking_defaults_and_explicit_overrides(self) -> None:
        real_builder = cli.BaseLLM.llm_builder
        for flags, expected in (([], False), (["--enable-thinking", "true"], True),
                                (["--enable-thinking", "false"], False)):
            with self.subTest(flags=flags), patch("fairy.agents.llm.vllm_client.OpenAI") as sdk:
                agent, _, report = self._run_cli(["--provider", "vllm", *flags], llm_builder=real_builder)
                agent.llm.chat_completion([])
                self.assertEqual(sdk.return_value.chat.completions.create.call_args.kwargs["extra_body"],
                                 {"chat_template_kwargs": {"enable_thinking": expected}})
                self.assertIs(report["llm_config"]["enable_thinking_override"], expected)
                unconfigured = real_builder({"provider": "vllm", "model": "test-model"})
                unconfigured.chat_completion([])
                self.assertIsNone(unconfigured.enable_thinking)
                self.assertNotIn("extra_body", sdk.return_value.chat.completions.create.call_args.kwargs)


class ToolRelationsRunnerTests(unittest.TestCase):
    def test_runner_settings_reach_child_schema_request_and_results(self) -> None:
        cases = (
            ([], {}, "on", None),
            (["--tool-relations", "off"], {}, "off", None),
            (["--config", "config.json"], {"tool_relations": "off"}, "off", None),
            (["--config", "config.json", "--tool-relations", "on"],
             {"tool_relations": "off"}, "on", None),
            (["--config", "config.json"], {"enable_thinking": False}, "on", False),
            (["--config", "config.json"], {"enable_thinking": True}, "on", True),
            (["--config", "config.json"], {"enable_thinking": None}, "on", None),
            (["--config", "config.json", "--enable-thinking", "false"],
             {"enable_thinking": True}, "on", False),
            (["--config", "config.json", "--enable-thinking", "true", "--a2a", "true", "--a2a-app-prop", "1"],
             {"enable_thinking": False}, "on", True),
            (["--config", "config.json", "--a2a", "true", "--a2a-app-prop", "1"],
             {"enable_thinking": False}, "on", False),
            (["--a2a", "true", "--a2a-app-prop", "1"], {}, "on", None),
            (["--a2a", "true", "--a2a-app-prop", "1", "--a2a-provider", "qwen"], {}, "on", None),
        )
        for flags, config, expected, thinking in cases:
            main_thinking = False if thinking is None else thinking
            with self.subTest(flags=flags), ExitStack() as stack:
                argv = ["runner", "--phase", "test", "--output-root", "/tmp/fairy-test",
                        "--families", "farm_baseline_react", "--scenarios", "schema-test",
                        "--provider", "vllm", *flags]
                stack.enter_context(patch("sys.argv", argv))
                stack.enter_context(redirect_stdout(StringIO()))
                stack.enter_context(patch.object(Path, "mkdir"))
                stack.enter_context(patch.object(Path, "exists", return_value=False))
                stack.enter_context(patch.object(Path, "read_text", return_value=json.dumps(config)))
                stack.enter_context(patch.object(Path, "open", side_effect=lambda *a, **k: StringIO()))
                process = stack.enter_context(patch.object(runner.subprocess, "Popen"))
                stack.enter_context(patch.object(runner, "_wait_for_cell_process", return_value=(0, False, False)))
                csv_write = stack.enter_context(patch.object(runner, "_write_results_csv"))
                self.assertIs(runner._parse_args(argv[1:]).enable_thinking, thinking)
                self.assertEqual(runner.main(), 0)
                command = process.call_args.args[0]
                self.assertEqual(command[command.index("--tool-relations") + 1], expected)
                self.assertEqual(csv_write.call_args.args[1][0]["tool_relations"], expected)
                self.assertIs(csv_write.call_args.args[1][0]["enable_thinking"], main_thinking)
                if thinking is None:
                    self.assertNotIn("--enable-thinking", command)
                else:
                    self.assertEqual(command[command.index("--enable-thinking") + 1], str(thinking).lower())
            # Feed the actual generated child arguments into real CLI/schema
            # construction, with scenario execution and artifact I/O mocked.
            real_builder = cli.BaseLLM.llm_builder
            with patch("fairy.agents.llm.vllm_client.OpenAI") as sdk, \
                    patch("fairy.agents.llm.qwen_client.OpenAI") as qwen_sdk:
                agent, scenario, report = ToolRelationsCLITests()._run_cli(command[3:], llm_builder=real_builder)
                clients = [(agent.llm, main_thinking)]
                if report["a2a"]["enabled"]:
                    clients.append((scenario.apps[0].app_agent.llm, thinking))
                for client, client_thinking in clients:
                    client.chat_completion([{"role": "user", "content": "Test"}], tools=[])
                    client_sdk = qwen_sdk if client.provider == "qwen" else sdk
                    request = client_sdk.return_value.chat.completions.create.call_args.kwargs
                    self.assertIs(client.enable_thinking, client_thinking)
                    if client_thinking is None:
                        self.assertNotIn("extra_body", request)
                    else:
                        self.assertEqual(request["extra_body"], {"chat_template_kwargs": {"enable_thinking": client_thinking}})
            self.assertEqual(agent.include_tool_relations, expected == "on")
            self.assertEqual(report["tool_relations"], expected)
            self.assertIs(report["llm_config"]["enable_thinking_override"], main_thinking)

    def test_invalid_thinking_cli_value_or_provider_fails_before_lookup(self) -> None:
        cases = (
            ["--provider", "vllm", "--enable-thinking", "invalid"],
            ["--provider", "deepseek", "--enable-thinking", "false"],
            ["--provider", "vllm", "--enable-thinking", "false", "--a2a", "true", "--a2a-provider", "qwen"],
        )
        for flags in cases:
            with self.subTest(flags=flags), patch("sys.argv", ["fairy", "--agent", "-s", "schema-test", *flags]), \
                    patch.object(cli, "get_scenario_class") as lookup, \
                    redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
                cli.main()
            self.assertEqual(error.exception.code, 2)
            lookup.assert_not_called()

    def test_invalid_config_mode_fails_before_launch(self) -> None:
        for value in ("invalid", None, False, []):
            with self.subTest(value=value), \
                    patch.object(Path, "read_text", return_value=json.dumps({"tool_relations": value})), \
                    patch.object(runner.subprocess, "Popen") as launch, \
                    redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
                runner._parse_args(["--config", "config.json", "--phase", "test",
                                    "--output-root", "/tmp/fairy-test", "--families", "test",
                                    "--scenarios", "schema-test"])
            self.assertEqual(error.exception.code, 2)
            launch.assert_not_called()


class ToolSchemaLifecycleTests(unittest.TestCase):
    def test_schema_is_built_once_and_reused_across_llm_calls(self) -> None:
        llm = FakeLLM()
        app = RelationExampleApp()
        with patch("fairy.agents.agent.agent.build_toolset", wraps=build_toolset) as build:
            agent = Agent("example", llm, toolsets=[app], include_tool_relations=False)
            schemas = agent.tool_schemas
            agent.set_time_manager(app.time_manager)
            with redirect_stdout(StringIO()):
                self.assertEqual(agent.run("First task"), "Done.")
                self.assertEqual(agent.run("Second task"), "Done.")
            build.assert_called_once()
            self.assertEqual(len(llm.received_tools), 2)
            self.assertTrue(all(received is schemas for received in llm.received_tools))


class OpenAIEndpointTests(unittest.TestCase):
    def test_runner_endpoint_precedence_reaches_http_requests_and_a2a(self) -> None:
        import httpx
        from openai import OpenAI

        cases = (
            ({}, [], {}, "https://api.openai.com/v1"),
            ({}, [], {"OPENAI_BASE_URL": "https://env.example/v1"}, "https://env.example/v1"),
            ({"endpoint": "https://json.example/v1"}, [],
             {"OPENAI_BASE_URL": "https://env.example/v1"}, "https://json.example/v1"),
            ({"endpoint": "https://json.example/v1"}, ["--endpoint", "https://cli.example/v1"],
             {"OPENAI_BASE_URL": "https://env.example/v1"}, "https://cli.example/v1"),
        )
        required = ["--phase", "test", "--output-root", "/tmp/fairy-test",
                    "--families", "farm_baseline_react", "--scenarios", "schema-test",
                    "--provider", "openai", "--config", "config.json"]
        for config, flags, extra_env, expected in cases:
            with self.subTest(config=config, flags=flags), ExitStack() as stack:
                env = {"OPENAI_API_KEY": "test-key", **extra_env}
                stack.enter_context(patch.dict(os.environ, env, clear=True))
                with patch.object(Path, "read_text", return_value=json.dumps(config)):
                    args = runner._parse_args(required + flags)
                provider, endpoint = runner._prepare_provider_env(env, args.provider, args.endpoint)
                self.assertEqual(endpoint, expected)
                command = runner._build_cell_command(
                    runner.CellSpec("farm_baseline_react", "schema-test", 1),
                    args.model, provider, args.output_root, endpoint=endpoint,
                    a2a_enabled=True, a2a_app_prop=1,
                    a2a_endpoint="https://expert.example/v1",
                )
                requests = []
                def respond(request):
                    requests.append(request)
                    return httpx.Response(200, json={
                        "id": "test", "object": "chat.completion", "created": 0,
                        "model": "gpt-4o-mini", "choices": [{"index": 0,
                        "message": {"role": "assistant", "content": "Done"}, "finish_reason": "stop"}],
                    })
                def make_sdk(**kwargs):
                    sdk = OpenAI(http_client=httpx.Client(transport=httpx.MockTransport(respond)), **kwargs)
                    stack.callback(sdk.close)
                    return sdk
                real_builder = cli.BaseLLM.llm_builder
                stack.enter_context(patch("fairy.agents.llm.openai_llm.OpenAI", side_effect=make_sdk))
                agent, scenario, report = ToolRelationsCLITests()._run_cli(command[3:], llm_builder=real_builder)
                agent.llm.chat_completion([{"role": "user", "content": "test"}])
                scenario.apps[0].app_agent.llm.chat_completion([{"role": "user", "content": "test"}])
                self.assertEqual(str(requests[0].url), expected + "/chat/completions")
                self.assertEqual(str(requests[1].url), "https://expert.example/v1/chat/completions")
                self.assertEqual(report["llm_config"]["base_url"].rstrip("/"), expected)

    def test_direct_client_preserves_sdk_fallbacks_and_explicit_key(self) -> None:
        from fairy.agents.llm.openai_llm import OpenAILLM
        for env, endpoint, expected in (
            ({}, None, "https://api.openai.com/v1"),
            ({"OPENAI_BASE_URL": "https://env.example/v1"}, None, "https://env.example/v1"),
            ({"OPENAI_BASE_URL": "https://env.example/v1"}, "https://explicit.example/v1", "https://explicit.example/v1"),
        ):
            with self.subTest(endpoint=endpoint, env=env), patch.dict(os.environ, env, clear=True):
                client = OpenAILLM("gpt-4o-mini", api_key="explicit-test-key", base_url=endpoint)
                try:
                    self.assertEqual(client.base_url.rstrip("/"), expected)
                    self.assertEqual(client.api_client.api_key, "explicit-test-key")
                    self.assertEqual(client.to_dict()["base_url"], client.base_url)
                finally:
                    client.api_client.close()

    def test_reasoning_branch_omits_temperature_and_uses_completion_limit(self) -> None:
        from fairy.agents.llm.openai_llm import OpenAILLM
        for model in sorted(OpenAILLM.CHAT_COMPLETION_MODELS | OpenAILLM.RESPONSES_API_MODELS):
            with self.subTest(model=model), patch("fairy.agents.llm.openai_llm.OpenAI") as sdk:
                client = OpenAILLM(model, temperature=0.6, base_url="https://custom.example/v1")
                client.chat_completion([])
                request = sdk.return_value.chat.completions.create.call_args.kwargs
                if model in OpenAILLM.CHAT_COMPLETION_MODELS:
                    self.assertEqual(request["temperature"], 0.6)
                    self.assertEqual(request["max_tokens"], 2048)
                else:
                    self.assertNotIn("temperature", request)
                    self.assertNotIn("max_tokens", request)
                    self.assertEqual(request["max_completion_tokens"], 2048)


class LLMConfigurationTests(unittest.TestCase):
    def test_runner_json_cli_and_environment_reach_main_and_a2a(self) -> None:
        cases = (
            ({}, [], 0.1, None, 7),
            ({"temperature": 0.6, "agent_llm_call_retries": 2}, [], 0.6, 2, 2),
            ({"temperature": 0.6, "agent_llm_call_retries": 2},
             ["--temperature", "0", "--agent-llm-call-retries", "0"], 0.0, 0, 0),
        )
        for config, flags, temperature, override, retries in cases:
            with self.subTest(config=config, flags=flags), ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {"FAIRY_AGENT_LLM_CALL_RETRIES": "7"}))
                argv = ["runner", "--phase", "test", "--output-root", "/tmp/fairy-test",
                        "--families", "farm_baseline_react", "--scenarios", "schema-test",
                        "--provider", "vllm", "--a2a", "true", "--a2a-app-prop", "1",
                        "--config", "config.json", *flags]
                with ExitStack() as runner_stack:
                    runner_stack.enter_context(patch("sys.argv", argv))
                    runner_stack.enter_context(redirect_stdout(StringIO()))
                    runner_stack.enter_context(patch.object(Path, "mkdir"))
                    runner_stack.enter_context(patch.object(Path, "exists", return_value=False))
                    runner_stack.enter_context(patch.object(Path, "read_text", return_value=json.dumps(config)))
                    runner_stack.enter_context(patch.object(Path, "open", side_effect=lambda *a, **k: StringIO()))
                    process = runner_stack.enter_context(patch.object(runner.subprocess, "Popen"))
                    runner_stack.enter_context(patch.object(runner, "_wait_for_cell_process", return_value=(0, False, False)))
                    csv_write = runner_stack.enter_context(patch.object(runner, "_write_results_csv"))
                    self.assertEqual(runner.main(), 0)
                    command = process.call_args.args[0]
                    row = csv_write.call_args.args[1][0]
                    self.assertEqual(row["temperature"], temperature)
                    self.assertEqual(row["agent_llm_call_retries"], override)
                real_builder = cli.BaseLLM.llm_builder
                with patch("fairy.agents.llm.vllm_client.OpenAI") as sdk:
                    agent, scenario, report = ToolRelationsCLITests()._run_cli(
                        command[3:], llm_builder=real_builder)
                    for current in (agent, scenario.apps[0].app_agent):
                        self.assertEqual(current.max_llm_call_retries, retries)
                        current.llm.chat_completion([], tools=[])
                        request = sdk.return_value.chat.completions.create.call_args.kwargs
                        self.assertEqual(request["temperature"], temperature)
                self.assertEqual(report["response_policy"]["max_llm_call_retries"], retries)
                self.assertEqual(report["llm_config"]["temperature"], temperature)

    def test_agent_retry_count_controls_actual_attempts(self) -> None:
        with patch.dict(os.environ, {"FAIRY_AGENT_LLM_RETRY_SLEEP_S": "0"}):
            for retries in (0, 2):
                agent = Agent("test", FakeLLM(), max_llm_call_retries=retries)
                with patch.object(agent, "chat_completion", side_effect=RuntimeError("failure")) as call:
                    with self.assertRaises(RuntimeError):
                        agent._chat_completion_with_retries([])
                self.assertEqual(call.call_count, retries + 1)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Agent("test", FakeLLM()).max_llm_call_retries, 5)

    def test_invalid_values_fail_before_launch(self) -> None:
        required = ["--phase", "test", "--output-root", "/tmp/fairy-test",
                    "--families", "test", "--scenarios", "test"]
        for flags in (["--agent-llm-call-retries", "-1"],
                      ["--agent-llm-call-retries", "1.5"],
                      ["--temperature", "nan"], ["--temperature", "-0.1"]):
            with self.subTest(flags=flags), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit):
                    runner._parse_args(required + list(flags))
                with patch("sys.argv", ["fairy", *flags]), patch.object(cli, "get_scenario_class") as lookup:
                    with self.assertRaises(SystemExit):
                        cli.main()
                    lookup.assert_not_called()
        for value in (True, 1.5, -1):
            with self.subTest(value=value), patch.object(Path, "read_text", return_value=json.dumps(
                {"agent_llm_call_retries": value}
            )), redirect_stderr(StringIO()):
                with self.assertRaises((ValueError, SystemExit)):
                    runner._parse_args(required + ["--config", "config.json"])


class QwenThinkingConfigurationTests(unittest.TestCase):
    def _run_runner(self, provider, config, flags):
        argv = ["runner", "--phase", "test", "--output-root", "/tmp/fairy-test",
                "--families", "farm_baseline_react", "--scenarios", "schema-test",
                "--provider", provider, "--model", "qwen3.6-flash",
                "--config", "config.json", *flags]
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"QWEN_API_KEY": "test-key"}))
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

    def test_runner_json_cli_defaults_reach_qwen_requests_and_reports(self) -> None:
        cases = (
            ({}, [], False, False),
            ({"enable_thinking": None, "preserve_thinking": None}, [], False, False),
            ({"enable_thinking": False, "preserve_thinking": False}, [], False, False),
            ({"enable_thinking": True}, [], True, False),
            ({"enable_thinking": True, "preserve_thinking": True}, [], True, True),
            ({"enable_thinking": True, "preserve_thinking": True},
             ["--enable-thinking", "false", "--preserve-thinking", "false"], False, False),
            ({"enable_thinking": True, "preserve_thinking": False},
             ["--preserve-thinking", "true"], True, True),
        )
        for provider in ("qwen", "qwen-json"):
            for config, flags, thinking, preserve in cases:
                with self.subTest(provider=provider, config=config, flags=flags):
                    command, row = self._run_runner(provider, config, flags)
                    for name, value in (("enable_thinking", thinking), ("preserve_thinking", preserve)):
                        flag = "--" + name.replace("_", "-")
                        self.assertEqual(command[command.index(flag) + 1], str(value).lower())
                        self.assertIs(row[name], value)
                    real_builder = cli.BaseLLM.llm_builder
                    with patch("fairy.agents.llm.qwen_client.OpenAI") as sdk:
                        agent, _, report = ToolRelationsCLITests()._run_cli(
                            command[3:], llm_builder=real_builder)
                        agent.llm.chat_completion([{"role": "user", "content": "test"}], tools=[])
                        request = sdk.return_value.chat.completions.create.call_args.kwargs
                        self.assertEqual(request["extra_body"], {
                            "enable_thinking": thinking, "preserve_thinking": preserve,
                        })
                        self.assertNotIn("stream", request)
                    self.assertIs(report["llm_config"]["enable_thinking_override"], thinking)
                    self.assertIs(report["llm_config"]["preserve_thinking"], preserve)
                    self.assertEqual(report["llm_config"]["reasoning_history_policy"],
                                     "preserve" if preserve else "exclude")

    def test_invalid_cli_combinations_fail_before_lookup_or_launch(self) -> None:
        cases = [
            ["--provider", "qwen", "--preserve-thinking", "true"],
            ["--provider", "qwen-json", "--enable-thinking", "false", "--preserve-thinking", "true"],
            ["--provider", "qwen", "--preserve-thinking", "invalid"],
        ]
        cases.extend(
            ["--provider", provider, "--preserve-thinking", value]
            for provider in ("openai", "deepseek", "vllm")
            for value in ("true", "false")
        )
        for flags in cases:
            with self.subTest(flags=flags), redirect_stderr(StringIO()):
                with patch("sys.argv", ["fairy", "--agent", "-s", "schema-test", *flags]), \
                        patch.object(cli, "get_scenario_class") as lookup, \
                        self.assertRaises(SystemExit) as error:
                    cli.main()
                self.assertEqual(error.exception.code, 2)
                lookup.assert_not_called()
                with patch.object(runner.subprocess, "Popen") as launch, \
                        self.assertRaises(SystemExit) as error:
                    runner._parse_args(["--phase", "test", "--output-root", "/tmp/fairy-test",
                                        "--families", "test", "--scenarios", "schema-test", *flags])
                self.assertEqual(error.exception.code, 2)
                launch.assert_not_called()

    def test_invalid_json_combinations_fail_before_launch(self) -> None:
        for config in (
            {"provider": "qwen", "preserve_thinking": True},
            {"provider": "qwen-json", "enable_thinking": False, "preserve_thinking": True},
            *({"provider": provider, "preserve_thinking": value}
              for provider in ("openai", "deepseek", "vllm") for value in (True, False)),
        ):
            with self.subTest(config=config), \
                    patch.object(Path, "read_text", return_value=json.dumps(config)), \
                    patch.object(runner.subprocess, "Popen") as launch, \
                    redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
                runner._parse_args(["--config", "config.json", "--phase", "test",
                                    "--output-root", "/tmp/fairy-test", "--families", "test",
                                    "--scenarios", "schema-test"])
            self.assertEqual(error.exception.code, 2)
            launch.assert_not_called()

    def test_unconfigured_direct_client_keeps_server_defaults(self) -> None:
        from fairy.agents.llm.qwen_client import QwenClient

        with patch("fairy.agents.llm.qwen_client.OpenAI") as sdk:
            client = QwenClient("qwen3.6-flash")
            client.chat_completion([{"role": "user", "content": "test"}])
            self.assertIsNone(client.enable_thinking)
            self.assertIsNone(client.preserve_thinking)
            self.assertNotIn("extra_body", sdk.return_value.chat.completions.create.call_args.kwargs)
            self.assertNotIn("preserve_thinking", client.to_dict())
            self.assertNotIn("preserve_thinking", Agent("test", client).llm_config())
            for provider in ("qwen", "qwen-json"):
                agent, _, _ = ToolRelationsCLITests()._run_cli(
                    ["--provider", provider], llm_builder=cli.BaseLLM.llm_builder)
                agent.llm.chat_completion([])
                self.assertEqual(sdk.return_value.chat.completions.create.call_args.kwargs["extra_body"], {
                    "enable_thinking": False, "preserve_thinking": False,
                })
            for thinking in (None, False):
                with self.subTest(thinking=thinking), self.assertRaises(ValueError):
                    QwenClient("qwen3.6-flash", enable_thinking=thinking, preserve_thinking=True)

    def test_qwen_controls_do_not_change_a2a_client_defaults(self) -> None:
        cases = (("qwen", "qwen"), ("qwen-json", "qwen-json"),
                 ("qwen", "vllm"), ("vllm", "qwen"))
        for provider, expert_provider in cases:
            with self.subTest(provider=provider, expert_provider=expert_provider), ExitStack() as stack:
                qwen_sdk = stack.enter_context(patch("fairy.agents.llm.qwen_client.OpenAI"))
                vllm_sdk = stack.enter_context(patch("fairy.agents.llm.vllm_client.OpenAI"))
                flags = ["--provider", provider, "--a2a-provider", expert_provider]
                if provider.startswith("qwen"):
                    flags.extend(["--enable-thinking", "true", "--preserve-thinking", "true"])
                real_builder = cli.BaseLLM.llm_builder
                agent, scenario, report = ToolRelationsCLITests()._run_cli(
                    flags, a2a=True, llm_builder=real_builder)
                agent.llm.chat_completion([])
                main_sdk = qwen_sdk if provider.startswith("qwen") else vllm_sdk
                main_request = main_sdk.return_value.chat.completions.create.call_args.kwargs
                if provider.startswith("qwen"):
                    self.assertEqual(main_request["extra_body"], {
                        "enable_thinking": True, "preserve_thinking": True,
                    })
                else:
                    self.assertEqual(main_request["extra_body"], {"chat_template_kwargs": {"enable_thinking": False}})
                expert = scenario.apps[0].app_agent
                expert.llm.chat_completion([])
                expert_sdk = qwen_sdk if expert_provider.startswith("qwen") else vllm_sdk
                self.assertNotIn("extra_body", expert_sdk.return_value.chat.completions.create.call_args.kwargs)
                self.assertIsNone(expert.llm.enable_thinking)
                self.assertNotIn("preserve_thinking", expert.llm_config())
                self.assertEqual(expert.llm_config()["reasoning_history_policy"], "exclude")
                self.assertTrue(report["a2a"]["enabled"])

    def test_real_sdk_two_tool_rounds_preserve_or_filter_all_reasoning(self) -> None:
        import httpx
        from openai import OpenAI
        from fairy.agents.llm.qwen_client import QwenClient

        for preserve in (False, True):
            with self.subTest(preserve=preserve), ExitStack() as stack:
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
                        "model": "qwen3.6-flash", "choices": [{"index": 0, "message": message,
                        "finish_reason": "tool_calls" if turn <= 2 else "stop"}],
                    })
                def make_sdk(**kwargs):
                    sdk = OpenAI(http_client=httpx.Client(transport=httpx.MockTransport(respond)), **kwargs)
                    stack.callback(sdk.close)
                    return sdk
                stack.enter_context(patch("fairy.agents.llm.qwen_client.OpenAI", side_effect=make_sdk))
                client = QwenClient("qwen3.6-flash", api_key="test-key", enable_thinking=True,
                                    preserve_thinking=preserve, base_url="https://qwen.example/v1")
                app = RelationExampleApp()
                agent = Agent("qwen-test", client, toolsets=[app], max_llm_call_retries=0)
                agent.set_time_manager(app.time_manager)
                tool_name = agent.tool_schemas[0]["function"]["name"]
                with redirect_stdout(StringIO()):
                    self.assertEqual(agent.run("Read twice."), "Done.")
                self.assertEqual(len(requests), 3)
                for turn, request in enumerate(requests):
                    self.assertIs(request["enable_thinking"], True)
                    self.assertIs(request["preserve_thinking"], preserve)
                    self.assertNotIn("extra_body", request)
                    self.assertNotIn("chat_template_kwargs", request)
                    self.assertFalse(request.get("stream", False))
                    assistants = [message for message in request["messages"] if message["role"] == "assistant"]
                    self.assertEqual(len(assistants), turn)
                    for index, message in enumerate(assistants, 1):
                        if preserve:
                            self.assertEqual(message["reasoning_content"], f"Original reasoning {index}.")
                        else:
                            self.assertNotIn("reasoning_content", message)
                        self.assertEqual(message["tool_calls"][0]["id"], f"call_{index}")
                    tool_results = [message for message in request["messages"] if message["role"] == "tool"]
                    self.assertEqual([message["tool_call_id"] for message in tool_results],
                                     [f"call_{index}" for index in range(1, turn + 1)])
                    for index, message in enumerate(tool_results, 1):
                        self.assertEqual(message["content"], str({"count": index}))
                # Filtering the wire request must not remove the SDK response's
                # extension fields from the agent's retained conversation.
                history = [message for message in agent.messages() if getattr(message, "role", None) == "assistant"]
                self.assertEqual([message.reasoning_content for message in history],
                                 [f"Original reasoning {index}." for index in range(1, 4)])
                starts = [event for event in agent.runtime_events if event["event_type"] == "llm_call_start"]
                self.assertEqual(len(starts), 3)
                for event, request in zip(starts, requests):
                    self.assertEqual(event["messages"], request["messages"])
                    self.assertEqual(event["reasoning_history_policy"], "preserve" if preserve else "exclude")
                    self.assertIs(event["llm_config"]["preserve_thinking"], preserve)

    def test_history_preservation_is_qwen_assistant_only_and_nonmutating(self) -> None:
        history = [
            {"role": "system", "content": "System", "reasoning_content": "not assistant"},
            {"role": "user", "content": "Question", "reasoning_content": "not assistant"},
            {"role": "assistant", "content": "Answer", "reasoning_content": "Original reasoning", "time": "metadata"},
            {"role": "assistant", "content": "Another answer", "reasoning_content": ""},
            {"role": "tool", "tool_call_id": "call_1", "content": "Result", "reasoning_content": "not assistant"},
        ]
        original = deepcopy(history)
        for provider, preserve in (("qwen", True), ("qwen", False),
                                   ("openai", True), ("deepseek", True), ("vllm", True)):
            with self.subTest(provider=provider, preserve=preserve):
                llm = FakeLLM()
                llm.provider = provider
                llm.preserve_thinking = preserve
                agent = Agent("test", llm)
                with patch.object(llm, "chat_completion", wraps=llm.chat_completion) as call:
                    agent.chat_completion(history)
                sent = call.call_args.args[0]
                for before, after in zip(history, sent):
                    expected = provider == "qwen" and preserve and before["role"] == "assistant"
                    self.assertEqual("reasoning_content" in after, expected)
                    if expected:
                        self.assertEqual(after["reasoning_content"], before["reasoning_content"])
                    self.assertNotIn("time", after)
                self.assertEqual(history, original)


if __name__ == "__main__":
    unittest.main()
