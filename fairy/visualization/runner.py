"""Single-owner simulation runner and detached, persistent workbench views."""
from __future__ import annotations

from concurrent.futures import Future
from datetime import datetime, timezone
import hashlib
import importlib.util
import math
import os
from pathlib import Path
import queue
import re
import secrets
import threading
import time
from typing import Any, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from .storage import RunStore, detached, encode

DEFAULT_SCENARIO = "scenario_full_season_hb_base_hn84_std_normal_V2"


class ManagerError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code, self.code, self.message = status_code, code, message
        super().__init__(message)


class _AgentStopped(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def agent_configuration() -> dict:
    model = os.environ.get("FARM_LLM_MODEL", "").strip()
    key = os.environ.get("FARM_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    reason = None
    if not model:
        reason = "请在服务端设置 FARM_LLM_MODEL。"
    elif not key:
        reason = "请在服务端设置 FARM_LLM_API_KEY 或 OPENAI_API_KEY。"
    elif importlib.util.find_spec("openai") is None:
        reason = "请安装 OpenAI SDK。"
    return {"configured": reason is None, "reason": reason, "model": model or None}


class WorkbenchManager:
    def __init__(self, data_dir: str | Path, adapter_factory: Callable | None = None):
        if adapter_factory is None:
            from .adapter import FarmAdapter
            adapter_factory = FarmAdapter
        self._factory = adapter_factory
        self.store = RunStore(data_dir)
        self._lock = threading.RLock()
        self._jobs: queue.Queue = queue.Queue()
        self._active: str | None = None
        self._adapter = None
        self._revision = -1
        self._controller = {"owner": "human", "status": "idle"}
        self._token: str | None = None
        self._pending = 0
        self._creating = False
        self._closed = False
        self._stop_requested = threading.Event()
        self._agent_thread: threading.Thread | None = None
        self._worker = threading.Thread(target=self._work, name="farm-simulation-owner", daemon=True)
        self._worker.start()

    def _work(self):
        while True:
            item = self._jobs.get()
            if item is None:
                if self._adapter is not None:
                    self._adapter.close()
                return
            function, future = item
            try:
                result = function()
            except BaseException as exc:
                future.set_exception(exc)
            else:
                future.set_result(result)

    def _enqueue(self, function: Callable) -> Future:
        future = Future()
        self._jobs.put((function, future))
        return future

    def _ensure_open(self):
        if self._closed:
            raise ManagerError(503, "closed", "运行服务已关闭。")

    def _run(self, run_id: str) -> dict:
        self._ensure_open()
        record = self.store.run(run_id)
        if record is None:
            raise ManagerError(404, "run_not_found", "找不到该实验。")
        return record

    def _require_active(self, run_id: str):
        record = self._run(run_id)
        if self._active != run_id or record["status"] != "active":
            raise ManagerError(409, "run_readonly", "该实验仅供历史回看；请创建新实验。")
        if self._creating:
            raise ManagerError(409, "run_busy", "正在创建实验。")
        return record

    def catalog(self) -> dict:
        try:
            from .adapter import catalog
            result = catalog()
        except ImportError:
            result = {"schema_version": 1, "scenarios": []}
        return {**result, "agent": agent_configuration()}

    def list_runs(self) -> dict:
        with self._lock:
            self._ensure_open()
            return {"runs": self.store.list_runs()}

    def current(self) -> dict | None:
        with self._lock:
            self._ensure_open()
            return self.snapshot(self._active) if self._active else None

    def create_run(self, scenario_id: str = DEFAULT_SCENARIO, seed: int = 0) -> dict:
        if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
            raise ManagerError(422, "invalid_seed", "seed 必须是 0 到 4294967295 之间的整数。")
        with self._lock:
            self._ensure_open()
            if self._creating or self._pending or self._controller["owner"] != "human":
                raise ManagerError(409, "run_busy", "请先停止当前控制者并等待农事完成。")
            self._creating = True
            future = self._enqueue(lambda: self._create(scenario_id, seed))
        try:
            return future.result()
        finally:
            with self._lock:
                self._creating = False

    def _create(self, scenario_id: str, seed: int) -> dict:
        # Construct first; a failed construction must not destroy the old run.
        try:
            adapter = self._factory(scenario_id=scenario_id, seed=seed)
            public_state = detached(adapter.public_state())
            audit_state = detached(adapter.audit_state())
            toolset = detached(adapter.tools)
        except Exception as exc:
            if "adapter" in locals():
                adapter.close()
            if isinstance(exc, ManagerError):
                raise
            raise ManagerError(409, "scenario_unavailable", "场景无法初始化，请检查依赖与场景配置。") from exc
        with self._lock:
            if self._active:
                self.store.status(self._active, "archived")
                self._event("run_archived", {}, self._active)
            if self._adapter is not None:
                self._adapter.close()
            self._adapter = adapter
            self._active = uuid4().hex
            self._revision = -1
            self._controller = {"owner": "human", "status": "idle"}
            self._token = None
            self._stop_requested.clear()
            descriptor = {**detached(adapter.descriptor), "run_id": self._active,
                          "scenario_id": scenario_id, "seed": seed, "created_at": _now(), "status": "active"}
            layout = self._default_layout(public_state)
            self.store.create(descriptor, toolset, layout)
            self._capture(public_state, audit_state)
            self._event("run_created", {"scenario_id": scenario_id, "seed": seed})
            return self.snapshot(self._active)

    def _capture(self, public_state: dict | None = None, audit_state: dict | None = None,
                 command_id: str | None = None, completed_command: dict | None = None) -> None:
        # Only the owner thread calls this; no read endpoint touches the adapter.
        public_state = detached(self._adapter.public_state()) if public_state is None else public_state
        audit_state = detached(self._adapter.audit_state()) if audit_state is None else audit_state
        with self._lock:
            record = self.store.run(self._active)
            self._revision += 1
            common = {"schema_version": 1, "run_id": self._active, "revision": self._revision,
                      "sim_time": float(self._adapter.sim_time), "sim_datetime": self._adapter.sim_datetime}
            previous = self.store.frame(self._active)
            observed_revisions = {o.get("observation_id"): o.get("revision")
                                  for o in (previous or {}).get("observations", [])}
            for observation in public_state.get("observations", []):
                observation["revision"] = observed_revisions.get(observation.get("observation_id"), self._revision)
            descriptor = {**record["descriptor"], "audit_accessed": record["audit_accessed"],
                          "audit_assisted": record["audit_assisted"]}
            public = {**public_state, **common, "descriptor": descriptor, "status": record["status"],
                      "controller": detached(self._controller), "current_command": None,
                      "audit_accessed": record["audit_accessed"], "audit_assisted": record["audit_assisted"]}
            audit = {**audit_state, **common}
            self.store.save_frame(public, audit, command_id, completed_command)

    def _metadata_frame(self, current_command: dict | None = None):
        """Publish control metadata using the last settled state, without sampling."""
        if not self._active or self._closed:
            return
        public = self.snapshot(self._active)
        audit = self.store.frame(self._active, audit=True)
        self._revision += 1
        public.update(revision=self._revision, controller=detached(self._controller), current_command=current_command)
        audit["revision"] = self._revision
        self.store.save_frame(public, audit)

    def snapshot(self, run_id: str, revision: int | None = None) -> dict:
        with self._lock:
            record = self._run(run_id)
            result = self.store.frame(run_id, revision)
            if result is None:
                raise ManagerError(404, "snapshot_not_found", "找不到该历史快照。")
            if revision is None:
                result.update(status=record["status"], audit_accessed=record["audit_accessed"], audit_assisted=record["audit_assisted"])
                result["descriptor"].update(status=record["status"], audit_accessed=record["audit_accessed"], audit_assisted=record["audit_assisted"])
                if self._active == run_id:
                    result["controller"] = detached(self._controller)
                elif record["status"] != "active":
                    result["controller"] = {"owner": "human", "status": "idle"}
                    result["current_command"] = None
            return result

    def audit(self, run_id: str, revision: int | None = None) -> dict:
        with self._lock:
            self._run(run_id)
            result = self.store.frame(run_id, revision, audit=True)
            if result is None:
                raise ManagerError(404, "snapshot_not_found", "找不到该模型诊断快照。")
            # Access metadata does not advance snapshot revisions: subscribing to
            # a diagnostic frame must not trigger an endless audit/refetch loop.
            self.store.flags(run_id, accessed=True)
            self._event("audit_view_opened", {
                "viewer": "local_user", "viewed_revision": result["revision"],
                "viewed_sim_time": result["sim_time"], "scope": "model_diagnostics",
            }, run_id)
            return result

    def tools(self, run_id: str) -> dict:
        with self._lock:
            return {"tools": self._run(run_id)["tools"]}

    def _actor(self, token: str | None) -> str:
        owner = self._controller["owner"]
        if token is not None:
            if self._token is None or not secrets.compare_digest(token, self._token):
                raise ManagerError(403, "invalid_controller_token", "控制令牌无效或已失效。")
            if owner not in {"external", "agent"}:
                raise ManagerError(409, "controller_inactive", "控制者已停止。")
            return owner
        if owner != "human":
            raise ManagerError(409, "controller_busy", "当前由自动控制者操作，请先请求停止。")
        return "human"

    def _mark_intervention(self, run_id: str, actor: str) -> bool:
        assisted = actor == "human" and self.store.run(run_id)["audit_accessed"]
        if assisted:
            self.store.flags(run_id, assisted=True)
        return bool(assisted)

    def submit(self, run_id: str, command_id: str, tool: str, args: dict,
               token: str | None = None) -> dict:
        if not isinstance(command_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", command_id):
            raise ManagerError(422, "invalid_command_id", "command_id 格式无效。")
        if not isinstance(tool, str) or not isinstance(args, dict):
            raise ManagerError(422, "invalid_command", "需要工具名称和参数对象。")
        try:
            payload = encode({"tool": tool, "args": args})
        except (ValueError, TypeError) as exc:
            raise ManagerError(422, "invalid_command", "参数必须为有限 JSON 值。") from exc
        if len(payload) > 65536:
            raise ManagerError(422, "command_too_large", "命令参数过长。")
        with self._lock:
            self._run(run_id)
            previous = self.store.command(run_id, command_id)
            if previous is not None:
                if previous[0] != payload:
                    raise ManagerError(409, "idempotency_conflict", "同一命令 ID 不能使用不同参数。")
                return previous[1]
            record = self._require_active(run_id)
            actor = self._actor(token)
            if self._pending or self._stop_requested.is_set():
                raise ManagerError(409, "run_busy", "已有工具正在执行或控制者正在停止。")
            if tool not in {entry["name"] for entry in record["tools"]}:
                raise ManagerError(422, "unknown_tool", "该场景未提供此工具。")
            assisted = self._mark_intervention(run_id, actor)
            command = {"command_id": command_id, "run_id": run_id, "tool": tool,
                       "args": detached(args), "status": "queued", "actor": actor,
                       "human_intervention_after_audit": assisted, "created_at": _now(), "result": None}
            self.store.save_command(command, payload)
            self._pending = 1
            self._metadata_frame({"command_id": command_id, "tool": tool, "status": "queued"})
            self._event("command_queued", {"command_id": command_id, "tool": tool, "actor": actor})
            self._enqueue(lambda: self._execute(command))
            return detached(command)

    def _execute(self, command: dict) -> None:
        with self._lock:
            command["status"] = "running"
            self.store.save_command(command)
            self._metadata_frame({"command_id": command["command_id"], "tool": command["tool"], "status": "running"})
            self._event("command_started", {"command_id": command["command_id"], "tool": command["tool"]})
        before = float(self._adapter.sim_time)
        try:
            result = detached(self._adapter.execute(command["tool"], command["args"]))
        except Exception:
            result = {"ok": False, "data": None, "error": {"code": "execution_error",
                      "message": "工具执行发生错误，请检查公开状态后决定下一步。", "partial_effects": "unknown"},
                      "time_before": before, "time_after": float(self._adapter.sim_time)}
        command.update(status="completed", result=result,
                       time_before=result.get("time_before", before),
                       time_after=result.get("time_after", float(self._adapter.sim_time)))
        with self._lock:
            try:
                self._capture(command_id=command["command_id"], completed_command=command)
            except Exception:
                # Physics may already have changed. Keep the last confirmed views
                # and make the run read-only; do not manufacture a matched pair.
                command.update(status="interrupted", result={"ok": False, "data": None,
                    "error": {"code": "snapshot_failed", "message": "状态记录失败，该实验已中断。", "partial_effects": "unknown"}})
                self.store.save_command(command)
                self.store.status(command["run_id"], "interrupted")
                self._stop_requested.set()
            finally:
                self._pending = 0
                self._event("command_finished", {"command_id": command["command_id"], "tool": command["tool"],
                            "ok": command["result"].get("ok", False)}, command["run_id"])
                if self._controller["owner"] == "external" and self._stop_requested.is_set():
                    self._release_controller()

    def command(self, run_id: str, command_id: str) -> dict:
        with self._lock:
            self._run(run_id)
            result = self.store.command(run_id, command_id)
            if result is None:
                raise ManagerError(404, "command_not_found", "找不到该命令。")
            return result[1]

    def history(self, run_id: str) -> dict:
        with self._lock:
            self._run(run_id)
            return {"frames": self.store.history(run_id)}

    def observations(self, run_id: str, revision: int | None = None) -> dict:
        with self._lock:
            self._run(run_id)
            if revision is not None:
                if type(revision) is not int or revision < 0:
                    raise ManagerError(422, "invalid_revision", "历史版本必须是非负整数。")
                if self.store.frame(run_id, revision) is None:
                    raise ManagerError(404, "snapshot_not_found", "找不到该历史快照。")
            return {"observations": self.store.observations(run_id, revision)}

    def events(self, run_id: str) -> dict:
        with self._lock:
            self._run(run_id)
            return {"events": self.store.events(run_id)}

    def _event(self, kind: str, data: dict, run_id: str | None = None):
        run_id = run_id or self._active
        if not run_id:
            return
        frame = self.store.frame(run_id)
        self.store.add_event(run_id, {"type": kind, "at": _now(),
            "sim_time": frame["sim_time"] if frame else None,
            "revision": frame["revision"] if frame else None, "data": detached(data)})

    def _acquire(self, run_id: str, owner: str, controller_id: str) -> str:
        self._require_active(run_id)
        if self._pending or self._controller["owner"] != "human":
            raise ManagerError(409, "run_busy", "请等待当前操作或控制者结束。")
        self._mark_intervention(run_id, "human")
        self._token = secrets.token_urlsafe(32)
        self._stop_requested.clear()
        self._controller = {"owner": owner, "status": "running", "controller_id": controller_id}
        self._metadata_frame()
        self._event("controller_acquired", {"owner": owner, "controller_id": controller_id})
        return self._token

    def acquire_external(self, run_id: str, controller_id: str) -> dict:
        if not isinstance(controller_id, str) or not 1 <= len(controller_id.strip()) <= 128:
            raise ManagerError(422, "invalid_controller", "控制者名称需为 1 至 128 个字符。")
        with self._lock:
            token = self._acquire(run_id, "external", controller_id.strip())
            return {"token": token, "snapshot": self.snapshot(run_id)}

    def _release_controller(self, *, summary: str | None = None, error: dict | None = None):
        self._controller = {"owner": "human", "status": "idle"}
        if summary:
            self._controller["summary"] = summary
        if error:
            self._controller["error"] = error
        self._token = None
        self._stop_requested.clear()
        self._metadata_frame()
        self._event("controller_released", {"error": error})

    def stop(self, run_id: str, token: str | None = None) -> dict:
        with self._lock:
            self._require_active(run_id)
            if token is not None:
                self._actor(token)
            else:
                self._mark_intervention(run_id, "human")
            self._event("stop_requested", {"actor": "controller" if token else "human"})
            if self._controller["owner"] == "human":
                return self.snapshot(run_id)
            self._stop_requested.set()
            self._controller["status"] = "stopping"
            if self._controller["owner"] == "external" and not self._pending:
                self._release_controller()
            else:
                self._metadata_frame()
            return self.snapshot(run_id)

    def reset(self, run_id: str) -> dict:
        with self._lock:
            record = self._require_active(run_id)
            self._mark_intervention(run_id, "human")
            scenario_id, seed = record["descriptor"]["scenario_id"], record["descriptor"]["seed"]
        return self.create_run(scenario_id, seed)

    @staticmethod
    def _default_layout(public: dict) -> dict:
        objects = []
        for index, farm in enumerate(public.get("farms", [])):
            farm_id = farm["farm_id"]
            objects.append({"visual_id": f"field-{farm_id}", "binding": {"kind": "farm", "farm_id": farm_id},
                            "label": farm.get("name", farm_id), "position": [index * 120.0, 0, 0],
                            "rotation": [0, 0, 0], "model_url": None})
        for index, device in enumerate(public.get("devices", [])):
            objects.append({"visual_id": f"device-{device['asset_id']}", "binding": {
                "kind": "device", "farm_id": device.get("farm_id"), "asset_id": device["asset_id"]},
                "label": device.get("name", device["asset_id"]), "position": [-12, 0, index * 8.0],
                "rotation": [0, 0, 0], "model_url": None})
        return {"schema_version": 1, "objects": objects}

    def get_layout(self, run_id: str) -> dict:
        with self._lock:
            return self._run(run_id)["layout"]

    def save_layout(self, run_id: str, payload: dict) -> dict:
        with self._lock:
            self._require_active(run_id)
            original = self.store.run(run_id)["layout"]
            if not isinstance(payload, dict) or set(payload) != {"schema_version", "objects"} or payload["schema_version"] != 1:
                raise ManagerError(422, "invalid_layout", "布局格式或版本无效。")
            rows = payload["objects"]
            if not isinstance(rows, list) or len(rows) != len(original["objects"]):
                raise ManagerError(422, "invalid_layout", "布局必须保留全部业务对象。")
            expected = {row["visual_id"]: row["binding"] for row in original["objects"]}
            seen = set()
            for row in rows:
                if not isinstance(row, dict) or set(row) != {"visual_id", "binding", "label", "position", "rotation", "model_url"}:
                    raise ManagerError(422, "invalid_layout", "布局对象字段无效。")
                vid = row["visual_id"]
                if not isinstance(vid, str) or vid in seen or vid not in expected or row["binding"] != expected[vid]:
                    raise ManagerError(422, "invalid_binding", "不能新增、重复或修改业务对象绑定。")
                seen.add(vid)
                if not isinstance(row["label"], str) or not 1 <= len(row["label"]) <= 128:
                    raise ManagerError(422, "invalid_layout", "标签长度应为 1 至 128。")
                for name in ("position", "rotation"):
                    values = row[name]
                    if (not isinstance(values, list) or len(values) != 3 or
                        any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 10000 for v in values)):
                        raise ManagerError(422, "invalid_layout", "位置与旋转必须是三个有限数值。")
                asset = row["model_url"]
                if row["binding"]["kind"] == "farm" and asset is not None:
                    raise ManagerError(422, "invalid_asset", "农田保留可选垄几何；GLB 仅用于设备和传感器。")
                if asset is not None and (not isinstance(asset, str) or not re.fullmatch(r"/models/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\.glb", asset)):
                    raise ManagerError(422, "invalid_asset", "仅支持 /models/ 下的 GLB 模型。")
            self.store.save_layout(run_id, payload)
            self._event("layout_saved", {}, run_id)
            return detached(payload)

    def compare(self, left: str, right: str) -> dict:
        a, b = self.snapshot(left), self.snapshot(right)
        fields = ("scenario_id", "source_commit", "backend", "crop", "cultivar", "seed",
                  "config_fingerprint", "weather_fingerprint", "cultivar_fingerprint",
                  "python_hash_seed", "model_version")
        differences = [{"field": key, "left": a["descriptor"].get(key), "right": b["descriptor"].get(key)}
                       for key in fields if (a["descriptor"].get(key) != b["descriptor"].get(key)
                                             or a["descriptor"].get(key) is None
                                             or b["descriptor"].get(key) is None
                                             or (key == "python_hash_seed" and a["descriptor"].get(key)
                                                 in {"random", "process-randomized"}))]
        def metrics(snapshot):
            ridges = [r for f in snapshot.get("farms", []) for r in f.get("ridges", [])]
            return {"sim_time": snapshot["sim_time"], "planted_ridges": sum(bool(r.get("planted")) for r in ridges),
                    "harvested_ridges": sum(bool(r.get("harvested")) for r in ridges),
                    "observation_count": len(self.store.observations(snapshot["run_id"], snapshot["revision"])),
                    "inventory": {f["farm_id"]: f.get("inventory", {}) for f in snapshot.get("farms", [])},
                    "audit_assisted": snapshot["audit_assisted"]}
        return {"left": a, "right": b, "compatible": not differences, "differences": differences,
                "metrics": {"left": metrics(a), "right": metrics(b)}}

    def start_agent(self, run_id: str, task: str) -> dict:
        if not isinstance(task, str) or not 1 <= len(task.strip()) <= 8000:
            raise ManagerError(422, "invalid_task", "任务长度应为 1 至 8000 字符。")
        ready = agent_configuration()
        if not ready["configured"]:
            raise ManagerError(409, "agent_not_configured", ready["reason"])
        with self._lock:
            token = self._acquire(run_id, "agent", "fairy-llm")
            self._event("agent_started", {"model": ready["model"], "task": task.strip()})
            self._agent_thread = threading.Thread(target=self._run_agent, args=(run_id, token, task.strip()),
                                                  name="farm-agent-controller", daemon=True)
            self._agent_thread.start()
            return {"snapshot": self.snapshot(run_id)}

    def _run_agent(self, run_id: str, token: str, task: str):
        summary, error, llm = None, None, None
        owner = self
        try:
            from fairy.agents.agent.agent import Agent
            from fairy.agents.llm.openai_compatible_client import OpenAICompatibleClient

            def boundary():
                if owner._stop_requested.is_set() or owner._closed:
                    raise _AgentStopped()

            class InteractiveAgent(Agent):
                def before_llm_turn(self, task):
                    boundary()
                    return ""
                def after_llm_message(self, message):
                    boundary()
                def after_tool_response(self, tool_call, tool_response):
                    boundary()
                def log(self, message):
                    pass

            class CachedClock:
                def time(self):
                    return owner.snapshot(run_id)["sim_time"]

            llm = OpenAICompatibleClient(model=os.environ["FARM_LLM_MODEL"],
                api_key=os.environ.get("FARM_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"),
                base_url=os.environ.get("FARM_LLM_BASE_URL"), timeout=20.0, parallel_tool_calls=False)
            llm.api_client = llm.api_client.with_options(max_retries=0)
            agent = InteractiveAgent("FarmWorkbenchAgent", llm, system_message=(
                "You control an existing FAIRY farm simulation using only the supplied public tools. "
                "The farm has already been initialized. Keep the current state; do not reset it. "
                "Inspect tool business results, actual observation coverage and timestamps. "
                "Tool success does not prove delayed crop or irrigation effects. Do not invent observations. "
                "Use explicit time advancement only when needed. Give a concise Chinese final report."))
            schemas = self.tools(run_id)["tools"]
            agent.tool_schemas = [{"type": "function", "function": {
                "name": row["name"], "description": row.get("description", ""), "parameters": row["parameters"]}}
                for row in schemas]
            def wrapper(name):
                def call(**args):
                    boundary()
                    command_id = "agent-" + uuid4().hex
                    owner.submit(run_id, command_id, name, args, token=token)
                    # A timeout in the model API never retries a completed tool.
                    while True:
                        command = owner.command(run_id, command_id)
                        if command["status"] in {"completed", "interrupted"}:
                            return command["result"]
                        time.sleep(0.01)
                return call
            agent.tools_map = {row["name"]: wrapper(row["name"]) for row in schemas}
            agent.tools = list(agent.tools_map.values())
            agent.set_time_manager(CachedClock())
            agent.simulation_timezone = ZoneInfo(self.snapshot(run_id)["descriptor"].get("timezone", "UTC"))
            agent.max_llm_call_retries = 0
            initial = self.snapshot(run_id)
            summary = agent.run(input=task + "\n当前公开状态：\n" + encode(initial), max_tool_calls=80, timeout_seconds=300)
            if isinstance(summary, str):
                for key in ("FARM_LLM_API_KEY", "OPENAI_API_KEY", "FARM_LLM_BASE_URL"):
                    value = os.environ.get(key)
                    if value:
                        summary = summary.replace(value, "[redacted]")
                summary = summary[:8000]
            else:
                summary = None
        except _AgentStopped:
            summary = "已在工具边界停止，保留已完成的操作。"
        except Exception as exc:
            category = type(exc).__name__.lower()
            code = ("timeout" if "timeout" in category else "authentication" if "authentication" in category
                    else "rate_limit" if "ratelimit" in category else "dependency" if "import" in category
                    else "limit" if "limitexceeded" in category else "model_request")
            error = {"code": code, "message": "Agent 已停止，请检查模型配置或执行限制。"}
        finally:
            if llm is not None:
                try:
                    llm.api_client.close()
                except Exception:
                    pass
            with self._lock:
                if not self._closed and self._active == run_id and self._token == token:
                    self._release_controller(summary=summary, error=error)

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._stop_requested.set()
            self._closed = True
        self._jobs.put(None)
        self._worker.join(timeout=60)
        # Do not close storage underneath a worker still finishing a native call.
        if self._worker.is_alive():
            return
        if self._agent_thread and self._agent_thread.is_alive():
            self._agent_thread.join(timeout=25)
        with self._lock:
            if self._active:
                self.store.status(self._active, "interrupted")
            self.store.recover()
            self.store.close()
