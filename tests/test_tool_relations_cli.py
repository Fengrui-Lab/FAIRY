from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from io import StringIO
import json
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
            (["--config", "config.json", "--a2a", "true", "--a2a-app-prop", "1"],
             {"enable_thinking": False}, "on", False),
        )
        for flags, config, expected, thinking in cases:
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
                self.assertEqual(runner.main(), 0)
                command = process.call_args.args[0]
                self.assertEqual(command[command.index("--tool-relations") + 1], expected)
                self.assertEqual(csv_write.call_args.args[1][0]["tool_relations"], expected)
                self.assertIs(csv_write.call_args.args[1][0]["enable_thinking"], thinking)
                if thinking is None:
                    self.assertNotIn("--enable-thinking", command)
                else:
                    self.assertEqual(command[command.index("--enable-thinking") + 1], str(thinking).lower())
            # Feed the actual generated child arguments into real CLI/schema
            # construction, with scenario execution and artifact I/O mocked.
            real_builder = cli.BaseLLM.llm_builder
            with patch("fairy.agents.llm.vllm_client.OpenAI") as sdk:
                agent, scenario, report = ToolRelationsCLITests()._run_cli(command[3:], llm_builder=real_builder)
                clients = [agent.llm]
                if report["a2a"]["enabled"]:
                    clients.append(scenario.apps[0].app_agent.llm)
                for client in clients:
                    client.chat_completion([{"role": "user", "content": "Test"}], tools=[])
                    request = sdk.return_value.chat.completions.create.call_args.kwargs
                    if thinking is None:
                        self.assertNotIn("extra_body", request)
                    else:
                        self.assertEqual(request["extra_body"], {"chat_template_kwargs": {"enable_thinking": thinking}})
            self.assertEqual(agent.include_tool_relations, expected == "on")
            self.assertEqual(report["tool_relations"], expected)
            self.assertIs(report["llm_config"]["enable_thinking_override"], thinking)

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


if __name__ == "__main__":
    unittest.main()
