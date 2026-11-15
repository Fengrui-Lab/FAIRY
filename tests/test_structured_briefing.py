from __future__ import annotations

from contextlib import ExitStack, contextmanager, redirect_stdout
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fairy import cli
from fairy.controllers.agent_builder import ResearchARESimulationAgent
from fairy.controllers.agent_config import ResearchAgentProfileConfig
from fairy.controllers.engine import Engine
from fairy.scenarios.farm_world_fullseason_v2 import harbin_l3_context_briefings as briefing
from fairy.scenarios.farm_world_fullseason_v2 import harbin_l3_structured_briefings as structured
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.workflow import Workflow
from fairy.time_manager import TimeManager


ROOT = Path(__file__).resolve().parents[1]
G = "reusable_operational_guidelines"
P = "scenario_specific_plan"
PILOTS = (
    "scenario_full_season_hb_organic_residue_weed_establishment",
    "scenario_full_season_hb_organic_patch_weed_mechanical_capacity",
    "scenario_full_season_hb_micronutrient_deficiency_flowering_patch",
)


class FakeLLM:
    model = "test"
    provider = "test"

    def __init__(self):
        self.requests = []

    def chat_completion(self, messages, tools=None):
        self.requests.append(json.loads(json.dumps(messages)))
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="Done.", tool_calls=[]),
                finish_reason="stop",
            )],
            usage=None,
        )


def spec(scenario_id: str = PILOTS[0]) -> SimpleNamespace:
    return SimpleNamespace(
        scenario_id=scenario_id,
        briefing_text="Base task: planting weather seedbed.",
        detailed_briefing_text="Detailed task.",
        description="cold spring planting weather seedbed",
        profile_name="heihe50",
        primary_metric="yield",
    )


def build(target, components, **options):
    return briefing.build_l3_context_briefing(
        target, "structured_true", {"components": components, **options}
    )


@contextmanager
def virtual_json_file(path: Path, payload):
    """Provide one JSON file without writing or deleting test artifacts."""
    read_text = Path.read_text
    read_bytes = Path.read_bytes
    is_file = Path.is_file

    def read(current, *args, **kwargs):
        if current == path:
            return json.dumps(payload, ensure_ascii=False)
        return read_text(current, *args, **kwargs)

    def exists(current):
        return current == path or is_file(current)

    def read_raw(current):
        if current == path:
            return json.dumps(payload, ensure_ascii=False).encode()
        return read_bytes(current)

    with patch.object(Path, "read_text", read), patch.object(Path, "read_bytes", read_raw), \
            patch.object(Path, "is_file", exists):
        yield


class LegacyBriefingTests(unittest.TestCase):
    def test_existing_modes_keep_prechange_output(self):
        # Captured before this change at 3c4e51b, using the shipped skill cards.
        expected = {
            "false": "d0edf1c7509810fa1df55ee9274b8de41c1750bd590b3fd99b11a6137cb90a8f",
            "true": "8c3f12fa196e441ae3dd82a0f382423c21a0cdb95ec987a2573253a82b72536f",
            "kwoo": "a2ddba60bd49e9e33fc716eed67d1a2e512833afc5e4b204bae45ac9492b3942",
            "library": "8084dbf436c42c9982763878975601b0c3e37d9309699d9d0795295f21baa1ba",
            "l2_human_same": "fdf5a9c9ce167bf099af59b4cb98c5f399168e1042f6abf1e1489e706dbdaefd",
            "l2_human_differ": "d8b160a0d3270ce51ac8fee04ecec4645c7e61966f7b8d8bc75c57d2aeeb8f99",
            "l2_textsim_differ": "08a6a3beceb6ee92c9e15f9a82b20dea6f8fe1987f6c70fce5c857b7b523015d",
            "l2_textsim_grouped_differ": "0eaae006145fed838ec295030bc47eab8d6d393731beb34468c782e7dce215e1",
        }
        workflow_hash = "53a3abdbe15712eb537be2f2fd7b6a7c89971243248bf5d9cc59ff7396d16535"
        for mode in (
            "l2_pathsim_differ", "l2_pathsim_grouped_differ", "l3_pathsim_same",
            "l3_pathsim_differ", "l3_textsim_differ", "l3_textdiff_differ",
        ):
            expected[mode] = workflow_hash
        target = spec("scenario_full_season_hb_coldspring_planting_window_heihe50")
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(briefing, "_load_kwoo_context", return_value="Fixed Kwoo."), \
                patch.object(briefing, "_load_retrieved_context", return_value="Fixed workflow."):
            for mode, digest in expected.items():
                with self.subTest(mode=mode):
                    value = briefing.build_l3_context_briefing(target, mode)
                    self.assertEqual(sha256(value.encode()).hexdigest(), digest)

    def test_existing_aliases_and_none_keep_meaning(self):
        for value, expected in (
            (True, "true"), (False, "false"), (None, "true"),
            ("human", "true"), ("detail_true", "true"), ("off", "false"),
            ("detail_false", "false"), ("library_context", "library"),
            ("l3_textdiff_differ", "l3_textsim_differ"),
        ):
            with self.subTest(value=value):
                self.assertEqual(briefing.normalize_briefing_mode(value), expected)
        with self.assertRaises(ValueError):
            briefing.normalize_briefing_mode("invalid")

    def test_legacy_context_map_needs_no_new_source_metadata(self):
        target = spec()
        path = ROOT / "virtual_context_map.json"
        with virtual_json_file(path, {"contexts": {target.scenario_id: "Workflow."}}), \
                patch.dict(os.environ, {briefing.RETRIEVED_CONTEXT_ENV_VAR: str(path)}, clear=True):
            self.assertEqual(
                briefing.build_l3_context_briefing(target, "l3_pathsim_differ"),
                target.briefing_text + "\n\nRetrieved workflow context:\nWorkflow.",
            )
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            briefing.build_l3_context_briefing(target, "l3_pathsim_differ")


class StructuredBriefingTests(unittest.TestCase):
    def test_four_combinations_have_independent_content_and_stable_order(self):
        for scenario_id in PILOTS:
            target = spec(scenario_id)
            with self.subTest(scenario_id=scenario_id):
                base = briefing.build_l3_context_briefing(target, False)
                empty = build(target, [])
                guidelines = build(target, [G])
                plan = build(target, [P])
                combined = build(target, [G, P])
                self.assertEqual(empty, base)
                self.assertEqual(build(target, [P, G, P]), combined)
                self.assertEqual(combined, guidelines + plan[len(base):])
                self.assertGreater(len(guidelines), len(base))
                self.assertGreater(len(plan), len(base))
                self.assertEqual(guidelines.strategy_task, base)
                self.assertEqual(plan.strategy_task, combined.strategy_task)
                self.assertNotIn("reusable_operational_guidelines", combined.strategy_task)

    def test_empty_configuration_does_not_read_components(self):
        read_bytes = Path.read_bytes

        def read(current):
            if current.name in {"plans.json", "guides.json", "scenario_guidelines.json"}:
                raise AssertionError("unexpected component read")
            return read_bytes(current)

        with patch.object(Path, "read_bytes", read):
            self.assertEqual(
                briefing.build_l3_context_briefing(spec(), "structured_true"),
                spec().briefing_text,
            )

    def test_missing_unselected_component_is_ignored_but_selected_is_error(self):
        read_bytes = Path.read_bytes
        for missing, components in (("plans.json", [G]), ("guides.json", [P])):
            def read(current):
                if current.name == missing:
                    raise FileNotFoundError(str(current))
                return read_bytes(current)

            with self.subTest(missing=missing), patch.object(Path, "read_bytes", read):
                self.assertGreater(len(build(spec(), components)), len(spec().briefing_text))
                with self.assertRaises(FileNotFoundError):
                    build(spec(), [G, P])

    def test_packaged_guidelines_always_bind_two_external_sources(self):
        path = structured._KNOWLEDGE_ROOT
        manifest = json.loads((path / "manifest.json").read_text())
        mappings = json.loads((path / "scenario_guidelines.json").read_text())["scenarios"]
        guides = json.loads((path / "guides.json").read_text())["guides"]
        plans = json.loads((path / "plans.json").read_text())["plans"]
        self.assertEqual(set(mappings), set(manifest["scenario_ids"]))
        self.assertEqual(set(plans), set(manifest["scenario_ids"]))
        self.assertEqual(len(mappings), 90)
        for target, record in mappings.items():
            for selected in record["selected_guides"]:
                with self.subTest(target=target, guide=selected["guide_id"]):
                    sources = {item["scenario_id"] for item in selected["source_evidence"]}
                    self.assertEqual(len(sources), 2)
                    self.assertNotIn(target, sources)
                    self.assertTrue(sources <= set(manifest["scenario_ids"]))
                    for source in selected["source_evidence"]:
                        self.assertIn(source, guides[selected["guide_id"]]["source_evidence"])

    def test_local_guideline_sources_stay_in_metadata_not_prompt(self):
        for scenario_id in PILOTS:
            with self.subTest(scenario_id=scenario_id):
                value = build(spec(scenario_id), [G])
                self.assertNotIn("来源：", value)
                metadata = value.metadata["guidelines"]
                self.assertTrue(metadata["selected_guides"])
                for guide in metadata["selected_guides"]:
                    self.assertEqual(len(guide["source_evidence"]), 2)
                    for source in guide["source_evidence"]:
                        self.assertNotIn(source["scenario_id"], value)
                body = value.split("<reusable_operational_guidelines>\n", 1)[1]
                body = body.split("\n</reusable_operational_guidelines>", 1)[0]
                self.assertEqual(metadata["text_sha256"], sha256(body.encode()).hexdigest())
                self.assertEqual(
                    value.metadata["briefing_sha256"], sha256(value.encode()).hexdigest()
                )

    def test_invalid_configuration_fails_explicitly(self):
        invalid = (
            {"components": "scenario_specific_plan"},
            {"components": ["unknown"]},
            {"components": [G], "guidelines": {"source": "unknown"}},
            {"components": [G], "guidelines": {"source": "library", "mode": "true"}},
            {"components": [G], "guidelines": {"source": "library", "mode": "l2_human_same"}},
            {"components": [G], "guidelines": {"source": "library", "mode": "l2_textsim_differ", "top_k": 0}},
            {"components": [G], "guidelines": {"source": "library", "mode": "l2_textsim_differ", "top_k": True}},
            {"components": [G], "guidelines": {"source": "library", "mode": "l2_textsim_grouped_differ", "top_k": 2}},
            {"components": [], "unknown_option": True},
        )
        for config in invalid:
            with self.subTest(config=config), self.assertRaises((TypeError, ValueError)):
                briefing.build_l3_context_briefing(spec(), "structured_true", config)

    def test_new_configuration_is_not_silently_applied_to_old_modes(self):
        for mode in (False, True, "library"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                briefing.build_l3_context_briefing(spec(), mode, {"components": [P]})

    def test_library_replaces_guidelines_and_does_not_change_plan(self):
        target = spec()
        options = {"guidelines": {"source": "library", "mode": "l2_textsim_differ", "top_k": 2}}
        default = build(target, [G])
        replacement = build(target, [G], **options)
        plan = build(target, [P])
        combined = build(target, [G, P], **options)
        self.assertNotEqual(default, replacement)
        self.assertIn("L2_TEXTSIM_DIFFER", replacement)
        self.assertEqual(combined, replacement + plan[len(target.briefing_text):])
        self.assertEqual(combined.strategy_task, plan.strategy_task)

    def test_library_guideline_sources_are_hidden_only_in_structured_mode(self):
        target = spec("scenario_full_season_hb_coldspring_planting_window_heihe50")
        modes = ("l2_human_differ", "l2_textsim_differ", "l2_textsim_grouped_differ")
        with patch.dict(os.environ, {}, clear=True):
            for mode in modes:
                with self.subTest(mode=mode):
                    value = build(target, [G], guidelines={"source": "library", "mode": mode})
                    old_value = briefing.build_l3_context_briefing(target, mode)
                    for field in ("source_l3", "source_library", "source_l2"):
                        self.assertNotIn(f"- {field}:", value)
                        self.assertIn(f"- {field}:", old_value)
                    self.assertIn("- constraints:", value)
                    self.assertIn("- oracle_event_template:", value)
                    sources = value.metadata["guidelines"]["sources"]
                    self.assertTrue(sources)
                    for source in sources:
                        self.assertTrue(source["scenario_id"])
                        self.assertTrue(source["source_library"])
                        self.assertTrue(source["skill_id"])
                        self.assertNotIn(source["scenario_id"], value)

    def test_explicit_top_k_does_not_mutate_or_use_global_override(self):
        target = spec()
        env = {briefing.TEXTSIM_TOP_K_ENV_VAR: "9"}
        with patch.dict(os.environ, env, clear=True):
            value = build(target, [G], guidelines={
                "source": "library", "mode": "l2_textsim_differ", "top_k": 2,
            })
            self.assertEqual(value.count("### Skill:"), 2)
            self.assertEqual(dict(os.environ), env)

    def test_grouped_library_guidelines_preserve_group_quotas(self):
        value = build(spec(), [G], guidelines={
            "source": "library", "mode": "l2_textsim_grouped_differ",
        })
        self.assertEqual(value.count("### Skill:"), 4)
        self.assertEqual(value.count("- farming_group: `establishment`"), 1)
        self.assertEqual(value.count("- farming_group: `management`"), 2)
        self.assertEqual(value.count("- farming_group: `harvest`"), 1)
        self.assertTrue(all(source["scenario_id"] != spec().scenario_id
                            for source in value.metadata["guidelines"]["sources"]))

    def test_map_guidelines_require_external_sources(self):
        target = spec()
        path = ROOT / "virtual_structured_context_map.json"
        mode = "l3_pathsim_differ"
        options = {"guidelines": {"source": "library", "mode": mode, "context_path": str(path)}}
        payload = {
            "mode": mode,
            "contexts": {target.scenario_id: "1) External example."},
            "sources": {target.scenario_id: [{"scenario_id": PILOTS[1], "score": 0.7}]},
        }
        with virtual_json_file(path, payload):
            value = build(target, [G], **options)
            self.assertIn("External example.", value)
            self.assertEqual(value.strategy_task, target.briefing_text)
        for bad_sources in ({}, {target.scenario_id: [{"scenario_id": target.scenario_id}]}):
            with self.subTest(sources=bad_sources), \
                    virtual_json_file(path, {**payload, "sources": bad_sources}), \
                    self.assertRaises(ValueError):
                build(target, [G], **options)
        with virtual_json_file(path, {**payload, "mode": "l3_textsim_differ"}), \
                self.assertRaises(ValueError):
            build(target, [G], **options)

    def test_map_source_fields_are_hidden_without_changing_workflow_code(self):
        target = spec()
        source_id = PILOTS[1]
        path = ROOT / "virtual_guideline_provenance_map.json"
        workflow = (
            "```text\n"
            "1) Observe the field.\n"
            "- source_l3: literal tool payload, not provenance\n"
            "2) Treat only confirmed patches.\n"
            "```"
        )
        for mode in (
            "l2_pathsim_differ", "l2_pathsim_grouped_differ",
            "l3_pathsim_differ", "l3_textsim_differ",
        ):
            if mode.startswith("l2_"):
                header = (
                    "### Skill: example\n"
                    f"- source_l3: `{source_id}`\n"
                    "- source_library: `example_library`\n"
                    "- source_l2: `example_l2`\n"
                    "- constraints: Confirm before acting."
                )
            else:
                header = f"## Retrieved L3: `{source_id}`\n- textsim_score: 0.7"
            context = f"来源：{source_id}\n{header}\n\n{workflow}"
            sources = [{"scenario_id": source_id, "score": 0.7}]
            payload = {
                "mode": mode,
                "contexts": {target.scenario_id: context},
                "sources": {target.scenario_id: sources},
            }
            with self.subTest(mode=mode), virtual_json_file(path, payload), \
                    patch.dict(os.environ, {briefing.RETRIEVED_CONTEXT_ENV_VAR: str(path)}, clear=True):
                value = build(target, [G], guidelines={
                    "source": "library", "mode": mode, "context_path": str(path),
                })
                self.assertNotIn("来源：", value)
                self.assertNotIn(source_id, value)
                self.assertNotIn("- source_library:", value)
                self.assertNotIn("- source_l2:", value)
                self.assertEqual(value.count("- source_l3:"), 1)
                self.assertIn(workflow, value)
                if mode.startswith("l3_"):
                    self.assertIn("## Reference workflow", value)
                self.assertEqual(value.metadata["guidelines"]["sources"], sources)
                self.assertEqual(
                    briefing.build_l3_context_briefing(target, mode),
                    target.briefing_text + "\n\nRetrieved workflow context:\n" + context,
                )

    def test_first_model_request_has_full_briefing_but_strategy_excludes_guidelines(self):
        target = spec()
        path = ROOT / "virtual_strategy_context_map.json"
        payload = {
            "mode": "l3_pathsim_differ",
            "contexts": {target.scenario_id: "1) FOREIGN-REFERENCE-ONLY"},
            "sources": {target.scenario_id: [{"scenario_id": PILOTS[1], "score": 0.7}]},
        }
        for components in ([], [G], [P], [G, P]):
            with self.subTest(components=components), virtual_json_file(path, payload):
                task = build(target, components, guidelines={
                    "source": "library", "mode": "l3_pathsim_differ", "context_path": str(path),
                })
                llm = FakeLLM()
                agent = ResearchARESimulationAgent(
                    "test", llm,
                    controller_profile=ResearchAgentProfileConfig.for_family("farm_rewoo_modular"),
                    toolsets=[],
                )
                agent.set_time_manager(TimeManager())
                with patch.object(agent._strategy, "build_context", wraps=agent._strategy.build_context) as strategy, \
                        redirect_stdout(StringIO()):
                    self.assertEqual(agent.run(task), "Done.")
                strategy.assert_called_once_with(task.strategy_task)
                self.assertNotIn("FOREIGN-REFERENCE-ONLY", task.strategy_task)
                self.assertEqual(len(llm.requests), 1)
                user = next(message["content"] for message in llm.requests[0] if message["role"] == "user")
                self.assertTrue(user.startswith(str(task)))
                self.assertEqual("FOREIGN-REFERENCE-ONLY" in user, G in components)
                self.assertEqual(agent.briefing_metadata, task.metadata)


class StructuredScenarioTests(unittest.TestCase):
    def test_cli_passes_components_to_initial_request_and_run_report(self):
        for mode in ("structured_true", False):
            kwargs = {"detailed_briefing": mode}
            if mode == "structured_true":
                kwargs["structured_briefing"] = {"components": [G, P]}
            llm = FakeLLM()
            with self.subTest(mode=mode), ExitStack() as stack:
                stack.enter_context(patch("sys.argv", [
                    "fairy", "--agent", "--scenario", PILOTS[0],
                    "--controller", "farm_baseline_react", "--scenario-kwargs", json.dumps(kwargs),
                ]))
                stack.enter_context(redirect_stdout(StringIO()))
                stack.enter_context(patch.object(cli.BaseLLM, "llm_builder", return_value=llm))
                stack.enter_context(patch.object(Path, "mkdir"))
                stack.enter_context(patch.object(Path, "exists", return_value=False))
                stack.enter_context(patch.object(cli, "_cleanup_legacy_artifacts"))
                stack.enter_context(patch.object(cli, "_cleanup_repo_side_exports"))
                stack.enter_context(patch.object(cli, "_append_live_progress"))
                stack.enter_context(patch.object(Workflow, "save_workflow"))
                stack.enter_context(patch.object(cli, "write_jsonl"))
                # Keep real scenario setup, controller, Engine and first LLM request;
                # evaluation/export and artifact writers are outside this smoke test.
                stack.enter_context(patch.object(Engine, "evaluation_report", return_value={}))
                write = stack.enter_context(patch.object(cli, "write_json"))
                cli.main()
                report = write.call_args.args[1]
            self.assertEqual(len(llm.requests), 1)
            user = next(m["content"] for m in llm.requests[0] if m["role"] == "user")
            self.assertEqual(report["scenario_kwargs"], kwargs)
            if mode == "structured_true":
                metadata = report["structured_briefing"]
                self.assertEqual(metadata["components"], [G, P])
                self.assertEqual(metadata["scenario_id"], PILOTS[0])
                self.assertEqual(metadata["briefing_sha256"], sha256(metadata["briefing_text"].encode()).hexdigest())
                self.assertTrue(user.startswith(metadata["briefing_text"]))
                self.assertIn("<reusable_operational_guidelines>", user)
                self.assertIn("<scenario_specific_plan>", user)
                for resource in [metadata["plan"]["resource"], *metadata["guidelines"]["resources"]]:
                    self.assertEqual(len(resource["sha256"]), 64)
                self.assertEqual(len(metadata["plan"]["provenance"]["sha256"]), 64)
            else:
                self.assertNotIn("structured_briefing", report)
                self.assertNotIn("<reusable_operational_guidelines>", user)
                self.assertNotIn("<scenario_specific_plan>", user)

    def test_all_formal_scenarios_support_empty_and_full_configuration(self):
        ids = (ROOT / "scripts/fullseason/formal_90_scenario_ids.txt").read_text().splitlines()
        ids = [s.strip() for s in ids if s.strip() and not s.startswith("#")]
        self.assertEqual(len(ids), 90)
        for scenario_id in ids:
            with self.subTest(scenario_id=scenario_id), redirect_stdout(StringIO()):
                cls = get_scenario_class(scenario_id)
                false = cls(detailed_briefing=False)
                empty = cls(detailed_briefing="structured_true")
                full = cls(detailed_briefing="structured_true", structured_briefing={"components": [G, P]})
                for scenario in (false, empty, full):
                    scenario.setup()
                base = Engine(None, false)._agent_briefing_from_events()
                empty_task = Engine(None, empty)._agent_briefing_from_events()
                full_task = Engine(None, full)._agent_briefing_from_events()
                self.assertEqual(empty_task, base)
                self.assertTrue(full_task.startswith(base))
                self.assertGreater(len(full_task), len(base))
                self.assertTrue(full_task.strategy_task)
                self.assertNotEqual(full_task.strategy_task, str(full_task))

    def test_unsupported_scenario_cannot_fall_back_to_true(self):
        scenario_id = "scenario_farm_world_field_prep"
        with self.assertRaises(ValueError):
            get_scenario_class(scenario_id)(detailed_briefing="structured_true")
        with self.assertRaises(ValueError):
            build(spec(scenario_id), [])

    def test_staggered_plan_retains_class_local_planting_windows(self):
        value = build(spec("scenario_full_season_heinong84_staggered_planting"), [P])
        for date in ("2026-05-05", "2026-05-12", "2026-05-19"):
            self.assertIn(date, value)
        self.assertIn("不能同日提前播完", value)


if __name__ == "__main__":
    unittest.main()
