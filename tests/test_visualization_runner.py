"""Workbench control and persistence tests; fake dynamics isolate manager semantics."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import random
import os
import sys
import tempfile
import threading
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from fairy.visualization.runner import ManagerError, WorkbenchManager
from fairy.visualization.storage import RunStore


class FakeAdapter:
    instances = []
    entered = threading.Event()
    release = threading.Event()

    def __init__(self, scenario_id, seed):
        self.owner = threading.get_ident()
        self.rng = random.Random(seed)
        self.value = 0
        self.readings = []
        self._time = 0.0
        self.executions = 0
        self.state_reads = 0
        self.descriptor = {"scenario_id": scenario_id, "title": "Test field", "backend": "test-only", "crop": "soybean",
            "cultivar": "test", "location": "test", "timezone": "UTC", "source_commit": "fixture",
            "config_fingerprint": "fixture-config", "weather_fingerprint": "fixture-weather",
            "cultivar_fingerprint": "fixture-cultivar", "python_hash_seed": "0", "model_version": "fixture-1"}
        self.tools = [{"name": name, "description": name, "parameters": {"type": "object", "properties": {}},
                       "operation_type": "read" if name == "observe" else "write"}
                      for name in ("advance", "observe", "reject", "slow")]
        self.instances.append(self)

    def assert_owner(self):
        assert self.owner == threading.get_ident(), "mutable simulation used outside its worker"

    @property
    def sim_time(self):
        self.assert_owner()
        return self._time

    @property
    def sim_datetime(self):
        self.assert_owner()
        return f"test-{self._time}"

    def execute(self, tool, args):
        self.assert_owner()
        before = self._time
        self.executions += 1
        if tool == "slow":
            self.entered.set()
            assert self.release.wait(5), "test did not release slow tool"
            self._time += 5
        elif tool == "advance":
            self._time += args.get("seconds", 1)
            self.value += 1
        elif tool == "observe":
            self.readings.append({"observation_id": f"obs-{len(self.readings)}", "tool": tool,
                "observed_at": self._time, "observed_datetime": self.sim_datetime, "available_at": self._time,
                "coverage": {"farm_id": "farm", "ridge_ids": [0]}, "data": {"measurement": self.rng.random()}})
        ok = tool != "reject"
        return {"ok": ok, "data": {"value": self.value} if ok else None,
                "error": None if ok else {"code": "rejected", "partial_effects": False},
                "time_before": before, "time_after": self._time}

    def public_state(self):
        self.assert_owner()
        self.state_reads += 1
        return {"farms": [{"farm_id": "farm", "name": "Test field", "geometry": {
            "num_ridges": 1, "length_m": 10, "ridge_width_m": 1, "rows_per_ridge": 2},
            "ridges": [{"ridge_id": 0, "planted": self.value > 0, "harvested": False, "growth_stage": "BARE"}],
            "inventory": {"water": 10-self.value}, "management": {}}], "devices": [{"asset_id": "tractor",
            "farm_id": "farm", "kind": "tractor", "name": "tractor", "state": {"fuel": 10}}],
            "observations": list(self.readings)}

    def audit_state(self):
        self.assert_owner()
        return {"farms": [{"farm_id": "farm", "ridges": [{"ridge_id": 0,
            "model_state_day": None, "values": {"root_vwc": .23, "lai": self.value}}]}], "units": {}, "notes": []}

    def close(self):
        self.assert_owner()


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manager = WorkbenchManager(self.tmp.name, FakeAdapter)
        self.run = self.manager.create_run(seed=42)["run_id"]

    def tearDown(self):
        FakeAdapter.release.set()
        self.manager.close()
        self.tmp.cleanup()

    def done(self, command_id):
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            command = self.manager.command(self.run, command_id)
            if command["status"] in {"completed", "interrupted"}:
                return command
            time.sleep(.005)
        self.fail("command did not finish")

    def send(self, name, command_id, args=None, token=None):
        self.manager.submit(self.run, command_id, name, args or {}, token=token)
        return self.done(command_id)

    def test_reads_history_and_audit_do_not_sample_or_advance(self):
        self.send("observe", "observation")
        state = self.manager.snapshot(self.run)
        adapter = FakeAdapter.instances[-1]
        state_reads, rng = adapter.state_reads, adapter.rng.getstate()
        for _ in range(5):
            self.manager.snapshot(self.run)
            self.manager.history(self.run)
            diagnosis = self.manager.audit(self.run)
            self.manager.snapshot(self.run, state["revision"])
        after = self.manager.snapshot(self.run)
        self.assertEqual(state["revision"], after["revision"])
        self.assertEqual(state["sim_time"], diagnosis["sim_time"])
        self.assertEqual(state["observations"], after["observations"])
        self.assertEqual(rng, adapter.rng.getstate())
        self.assertEqual(state_reads, adapter.state_reads)
        self.assertTrue(after["audit_accessed"])
        self.assertFalse(after["audit_assisted"])
        self.assertNotIn("root_vwc", json.dumps(after))

    def test_retries_do_not_repeat_operation_and_conflicts_reject(self):
        self.send("advance", "same", {"seconds": 7})
        for _ in range(4):
            result = self.manager.submit(self.run, "same", "advance", {"seconds": 7})
            self.assertEqual(result["status"], "completed")
        self.assertEqual(self.manager.snapshot(self.run)["sim_time"], 7)
        self.assertEqual(FakeAdapter.instances[-1].executions, 1)
        with self.assertRaises(ManagerError) as ctx:
            self.manager.submit(self.run, "same", "advance", {"seconds": 8})
        self.assertEqual(ctx.exception.code, "idempotency_conflict")

    def test_audit_access_marks_later_human_intervention(self):
        revision = self.manager.snapshot(self.run)["revision"]
        self.manager.audit(self.run, revision)
        command = self.send("advance", "after-audit")
        self.assertTrue(command["human_intervention_after_audit"])
        self.assertTrue(self.manager.snapshot(self.run)["audit_assisted"])
        self.assertFalse(self.manager.snapshot(self.run, revision)["audit_assisted"])
        self.assertTrue(any(e["type"] == "audit_view_opened" for e in self.manager.events(self.run)["events"]))

    def test_controller_exclusive_and_stop_at_tool_boundary(self):
        FakeAdapter.entered.clear()
        FakeAdapter.release.clear()
        grant = self.manager.acquire_external(self.run, "external-test")
        with self.assertRaises(ManagerError):
            self.manager.submit(self.run, "human", "observe", {})
        self.manager.submit(self.run, "slow", "slow", {}, token=grant["token"])
        self.assertTrue(FakeAdapter.entered.wait(2))
        repeated = self.manager.submit(self.run, "slow", "slow", {}, token=grant["token"])
        self.assertEqual(repeated["status"], "running")
        stopped = self.manager.stop(self.run)
        self.assertEqual(stopped["controller"]["status"], "stopping")
        with self.assertRaises(ManagerError):
            self.manager.reset(self.run)
        FakeAdapter.release.set()
        command = self.done("slow")
        self.assertTrue(command["result"]["ok"])
        self.assertEqual(self.manager.snapshot(self.run)["sim_time"], 5)
        self.assertEqual(self.manager.snapshot(self.run)["controller"]["owner"], "human")
        with self.assertRaises(ManagerError):
            self.manager.submit(self.run, "expired", "observe", {}, token=grant["token"])

    def test_reset_archives_old_run_and_keeps_history(self):
        self.send("advance", "first", {"seconds": 11})
        old_run = self.run
        fresh = self.manager.reset(old_run)
        self.run = fresh["run_id"]
        self.assertNotEqual(old_run, self.run)
        self.assertEqual(fresh["sim_time"], 0)
        self.assertEqual(self.manager.snapshot(old_run)["status"], "archived")
        self.assertEqual(self.manager.snapshot(old_run)["sim_time"], 11)
        with self.assertRaises(ManagerError):
            self.manager.submit(old_run, "late", "advance", {})
        comparison = self.manager.compare(old_run, self.run)
        self.assertTrue(comparison["compatible"])
        self.assertNotIn("root_vwc", json.dumps(comparison))

    def test_layout_preserves_bindings_and_does_not_touch_model(self):
        layout = self.manager.get_layout(self.run)
        layout["objects"][0]["position"] = [100, 0, 20]
        layout["objects"][0]["rotation"] = [0, .5, 0]
        self.manager.save_layout(self.run, layout)
        self.assertEqual(self.manager.get_layout(self.run), layout)
        self.assertEqual(self.manager.snapshot(self.run)["sim_time"], 0)
        unsupported = deepcopy(layout)
        unsupported["objects"][0]["model_url"] = "/models/field.glb"
        with self.assertRaises(ManagerError):
            self.manager.save_layout(self.run, unsupported)
        self.assertEqual(self.manager.get_layout(self.run), layout)
        layout["objects"][0]["binding"]["farm_id"] = "invented"
        with self.assertRaises(ManagerError):
            self.manager.save_layout(self.run, layout)

    def test_observation_revision_and_history_are_immutable(self):
        self.send("observe", "sample")
        initial = self.manager.snapshot(self.run)
        self.send("advance", "step")
        now = self.manager.snapshot(self.run)
        self.assertEqual(initial["observations"], now["observations"])
        now["farms"][0]["inventory"]["water"] = -100
        self.assertGreater(self.manager.snapshot(self.run)["farms"][0]["inventory"]["water"], 0)
        self.assertEqual(self.manager.snapshot(self.run, initial["revision"]), initial)

    def test_business_rejection_not_http_success(self):
        rejected = self.send("reject", "no")
        self.assertEqual(rejected["status"], "completed")
        self.assertFalse(rejected["result"]["ok"])
        self.assertEqual(self.manager.snapshot(self.run)["sim_time"], 0)

    def test_restart_does_not_restore_simulation_or_lose_records(self):
        self.send("advance", "persist", {"seconds": 3})
        self.manager.close()
        self.manager = WorkbenchManager(self.tmp.name, FakeAdapter)
        self.assertIsNone(self.manager.current())
        self.assertEqual(self.manager.snapshot(self.run)["status"], "interrupted")
        self.assertEqual(self.manager.snapshot(self.run)["sim_time"], 3)
        self.assertEqual(self.manager.command(self.run, "persist")["status"], "completed")
        with self.assertRaises(ManagerError):
            self.manager.submit(self.run, "continue", "advance", {})

    def test_store_recovery_marks_uncertain_commands_without_replay(self):
        self.manager.store.save_command({"run_id": self.run, "command_id": "lost-reply", "status": "running",
                                       "tool": "advance", "args": {}, "actor": "human"}, "payload")
        self.manager.close()
        self.manager = WorkbenchManager(self.tmp.name, FakeAdapter)
        recovered = self.manager.command(self.run, "lost-reply")
        self.assertEqual(recovered["status"], "interrupted")
        self.assertEqual(recovered["result"]["error"]["partial_effects"], "unknown")

    def test_audit_observer_does_not_mark_autonomous_commands_as_human(self):
        grant = self.manager.acquire_external(self.run, "automated-regression")
        self.manager.audit(self.run)
        result = self.send("advance", "autonomous", token=grant["token"])
        self.assertFalse(result["human_intervention_after_audit"])
        self.assertFalse(self.manager.snapshot(self.run)["audit_assisted"])
        self.manager.stop(self.run, token=grant["token"])
        self.assertFalse(self.manager.snapshot(self.run)["audit_assisted"])
        self.send("observe", "human-after")
        self.assertTrue(self.manager.snapshot(self.run)["audit_assisted"])

    def test_observation_history_retains_replaced_cache_and_truncates_at_revision(self):
        class LatestOnly(FakeAdapter):
            def execute(self, tool, args):
                result = super().execute(tool, args)
                if tool == "observe":
                    self.readings = self.readings[-1:]
                    self.readings[0]["observation_id"] = f"latest-{self.executions}"
                return result

        self.manager.close()
        self.manager = WorkbenchManager(self.tmp.name, LatestOnly)
        self.run = self.manager.create_run(seed=42)["run_id"]
        initial = self.manager.snapshot(self.run)["revision"]
        self.send("observe", "first-sample")
        first_revision = self.manager.snapshot(self.run)["revision"]
        first = self.manager.observations(self.run)["observations"]
        self.send("advance", "between-samples", {"seconds": 10})
        self.send("observe", "second-sample")
        second_revision = self.manager.snapshot(self.run)["revision"]
        adapter = FakeAdapter.instances[-1]
        captured_rng, read_count = adapter.rng.getstate(), adapter.state_reads
        self.assertEqual(len(self.manager.snapshot(self.run)["observations"]), 1)
        complete = self.manager.observations(self.run)["observations"]
        self.assertEqual(len(complete), 2)
        self.assertEqual([r["observed_at"] for r in complete], [0, 10])
        self.assertEqual([r["revision"] for r in complete], [first_revision, second_revision])
        for _ in range(3):
            self.assertEqual(self.manager.observations(self.run, first_revision)["observations"], first)
            self.assertEqual(self.manager.observations(self.run, initial)["observations"], [])
            self.assertEqual(self.manager.observations(self.run)["observations"], complete)
            self.manager.snapshot(self.run)
        self.assertEqual(adapter.state_reads, read_count)
        self.assertEqual(adapter.rng.getstate(), captured_rng)
        with self.assertRaises(ManagerError):
            self.manager.observations(self.run, second_revision+100)
        self.manager.close()
        self.manager = WorkbenchManager(self.tmp.name, LatestOnly)
        self.assertEqual(self.manager.observations(self.run)["observations"], complete)

    def test_observation_table_upgrade_uses_only_saved_public_history(self):
        self.send("observe", "old-schema-sample")
        saved = self.manager.observations(self.run)["observations"]
        self.manager.close()
        import sqlite3
        connection = sqlite3.connect(Path(self.tmp.name) / "workbench.sqlite3")
        with connection:
            connection.execute("DROP TABLE observations")
            connection.execute("PRAGMA user_version=0")
        connection.close()
        self.manager = WorkbenchManager(self.tmp.name, FakeAdapter)
        self.assertEqual(self.manager.observations(self.run)["observations"], saved)
        self.assertNotIn("root_vwc", json.dumps(self.manager.observations(self.run)))

    def test_real_fairy_agent_loop_uses_same_run_and_only_public_context(self):
        # The FAIRY Agent loop is real; only the external provider is replaced.
        from fairy.agents.agent.agent import Agent
        self.send("advance", "before-agent", {"seconds": 13})
        adapter = FakeAdapter.instances[-1]
        requests = []

        class Provider:
            def __init__(self, model, **kwargs):
                self.model, self.provider = model, "fake-test-provider"
                self.parallel_tool_calls = False
                self.api_client = self
                self.index = 0
            def with_options(self, **kwargs):
                return self
            def close(self):
                pass
            def chat_completion(self, messages, tools=None):
                requests.append(json.dumps(messages))
                self.index += 1
                if self.index <= 2:
                    name = "observe" if self.index == 1 else "advance"
                    args = {} if self.index == 1 else {"seconds": 2}
                    call = SimpleNamespace(id=f"call-{self.index}", type="function",
                        function=SimpleNamespace(name=name, arguments=json.dumps(args)))
                    message = SimpleNamespace(role="assistant", content=None, tool_calls=[call])
                    finish = "tool_calls"
                else:
                    message = SimpleNamespace(role="assistant", content="已完成 fixture-key", tool_calls=[])
                    finish = "stop"
                return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)], usage=None)

        module = ModuleType("fairy.agents.llm.openai_compatible_client")
        module.OpenAICompatibleClient = Provider
        with patch.dict(sys.modules, {module.__name__: module}), patch.dict(os.environ, {
                "FARM_LLM_MODEL": "fixture-model", "FARM_LLM_API_KEY": "fixture-key"}), patch(
                "fairy.visualization.runner.agent_configuration", return_value={"configured": True, "model": "fixture-model"}):
            self.manager.start_agent(self.run, "测量一次，再推进两秒。")
            deadline = time.monotonic()+5
            while time.monotonic() < deadline:
                state = self.manager.snapshot(self.run)
                if state["controller"]["owner"] == "human":
                    break
                time.sleep(.01)
            else:
                self.fail("real Agent loop did not finish")
        self.assertEqual(state["run_id"], self.run)
        self.assertEqual(state["sim_time"], 15)
        self.assertIs(FakeAdapter.instances[-1], adapter)
        self.assertEqual(len(state["observations"]), 1)
        self.assertIn("[redacted]", state["controller"]["summary"])
        self.assertNotIn("root_vwc", " ".join(requests))
        self.assertNotIn("fixture-key", " ".join(requests))
        self.assertEqual(len(requests), 3)


if __name__ == "__main__":
    unittest.main()
