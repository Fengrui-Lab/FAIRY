"""Run the two frozen H01 public-tool policies; never call a model API.

The accepted W01/N01 controller stays unchanged.  This runner adds one public
inspection/maintenance decision between its N01 growth and harvest routines.
Private snapshots below are write-only diagnostics, never policy inputs.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

import run_maize_basic_reference as base


SCENARIO_ID = "scenario_maize_l3_basic_h01_v0"
RUNNER_VERSION = "h01-reference-v0.1"
RESOURCE_DIR = ROOT / "fairy/scenarios/maize/basic_h01_v0"
INSPECT_TOOL = "TractorApp__inspect_header"
SERVICE_TOOL = "TractorApp__service_header"
POLICIES = {"A": "inspect_then_service", "B": "inspect_only"}
INSPECTION_RULE = (
    "Immediately after the unchanged growth controller first observes all 64 "
    "ridges MATURE in public farm overview, before the first harvest call. "
    "This is not a claim to identify the earliest physically legal harvest time."
)
EVENT_GRAPH_POLICY = "briefing_only; no validated H01 static oracle"
RESOURCE_FILES = (
    "task_card.json", "evaluation_contract.json", "agent_task.zh.txt",
    "parameter_freeze.json",
)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity() -> dict:
    """Content identity; timestamps and the chosen arm do not enter this hash."""
    from fairy.contracts.cli import fingerprint

    paths = [
        Path(__file__), SCRIPTS / "run_maize_basic_reference.py",
        SCRIPTS / "summarize_maize_h01.py",
        ROOT / "fairy/scenarios/maize/basic_management.py",
        ROOT / "fairy/scenarios/maize/scenario_basic_h01_v0.py",
        base.DATA / "schedule.json",
    ]
    paths += [RESOURCE_DIR / name for name in RESOURCE_FILES]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError("Missing frozen H01 input: " + ", ".join(missing))
    native = fingerprint()
    return {
        "runner_version": RUNNER_VERSION,
        "files": {str(path.relative_to(ROOT)): file_sha256(path) for path in paths},
        "native_runtime": native["source_hash"],
        "dependencies": native["dependencies"],
        "python_version": native["python_version"],
        "inspection_rule": INSPECTION_RULE,
        "event_graph_policy": EVENT_GRAPH_POLICY,
    }


def require_matching_gate(gate: dict, current_identity: dict) -> None:
    if (
        gate.get("status") != "passed"
        or gate.get("scenario_id") != SCENARIO_ID
        or gate.get("candidate") != "H01"
        or gate.get("identity") != current_identity
        or gate.get("identity_sha256") != base.digest(current_identity)
    ):
        raise RuntimeError("Stale or mismatched H01 preflight; no farm actions executed")


def setup_scenario():
    from fairy.scenarios.maize.scenario_basic_h01_v0 import BasicH01Scenario
    from fairy.controllers.engine import Engine
    from fairy.scenarios.registry import get_scenario_class

    registered = get_scenario_class(SCENARIO_ID)
    if registered is not BasicH01Scenario:
        raise RuntimeError("Registered H01 ID does not resolve to the frozen candidate")
    scenario = registered(seed=0)
    scenario.setup()
    engine = Engine(None, scenario)
    schedule = json.loads((base.DATA / "schedule.json").read_text())
    anchor = datetime.datetime.fromisoformat(schedule["grid_anchor"]).timestamp()
    if anchor != scenario.start_time:
        raise RuntimeError("Explicit development-grid anchor does not match scene start")
    return scenario, engine


def check_native_task(actual_task: str, scenario_input: str, frozen_task: str) -> dict:
    """Honor only the existing Engine event-briefing str.strip() contract."""
    if scenario_input != frozen_task:
        raise RuntimeError("Scenario input differs from the exact frozen H01 task file")
    normalized = frozen_task.strip()
    if actual_task != normalized:
        raise RuntimeError("Actual Engine task differs from its native-normalized frozen H01 task")
    return {
        "native_task_normalization": "Engine briefing str.strip()",
        "raw_task_utf8_sha256": hashlib.sha256(frozen_task.encode("utf-8")).hexdigest(),
        "normalized_task_utf8_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "actual_engine_task_utf8_sha256": hashlib.sha256(actual_task.encode("utf-8")).hexdigest(),
    }


def public_interface(scenario, engine) -> dict:
    from fairy.agents.agent.toolset_builder import build_toolset
    from fairy.controllers.agent_builder import FARM_AGENT_HIDDEN_TOOL_NAMES

    _, public_schemas, public_map = build_toolset(
        list(scenario.apps), excluded_tool_names=FARM_AGENT_HIDDEN_TOOL_NAMES
    )
    _, reference_schemas, reference_map = build_toolset(list(scenario.apps))
    if not {INSPECT_TOOL, SERVICE_TOOL}.issubset(public_map):
        raise RuntimeError("H01 inspection and service must be Agent-public tools")
    extra = sorted(set(reference_map) - set(public_map))
    if set(extra) - {"AgentUserInterface__send_message_to_agent"}:
        raise RuntimeError("Reference menu contains additional hidden action tools: " + str(extra))
    task = engine._resolve_agent_task()
    expected_task = (RESOURCE_DIR / "agent_task.zh.txt").read_text()
    task_identity = check_native_task(task, scenario.scenario_input, expected_task)
    if getattr(scenario, "event_graph_policy", None) != EVENT_GRAPH_POLICY:
        raise RuntimeError("H01 event-graph declaration differs from the frozen runner")
    return {
        "scenario_id": SCENARIO_ID,
        "task": task,
        "scenario_input": scenario.scenario_input,
        **task_identity,
        "additional_system_prompt": getattr(scenario, "additional_system_prompt", None),
        "task_source": "event_briefing" if engine._agent_briefing_from_events() else "scenario_input",
        "event_graph_policy": EVENT_GRAPH_POLICY,
        "agent_tool_schemas": public_schemas,
        "reference_tool_schemas": reference_schemas,
        "reference_only_tools": extra,
        "start_time": scenario.start_time,
        "inspection_rule": INSPECTION_RULE,
        "no_llm_called": True,
    }


class H01Executor(base.Executor):
    """Remember the last *public* observation without another sensor read."""

    last_public_observation = None

    def observe(self, kind, grid_id=None):
        observed = super().observe(kind, grid_id)
        self.last_public_observation = observed
        return observed


def inspect_and_branch(executor, arm: str) -> dict:
    if arm not in POLICIES:
        raise base.PilotStop("Unknown H01 policy arm")
    observed = executor.last_public_observation
    ridges = (observed or {}).get("crop", {}).get("ridges_overview", [])
    if (
        len(ridges) != 64
        or {row.get("ridge_id") for row in ridges} != set(range(64))
        or any(row.get("growth_stage") != "MATURE" or row.get("harvested") for row in ridges)
    ):
        raise base.PilotStop("Header inspection requires the common public all-mature preharvest observation")
    decision = {
        "event": "h01_header_decision", "arm": arm, "policy": POLICIES[arm],
        "inspection_rule": INSPECTION_RULE,
        "observation_id": observed["id"],
        "public_observed_at": observed["time"],
        "inspection_requested_at": executor.now(),
    }
    inspected = executor.required(INSPECT_TOOL)
    condition = inspected.get("condition")
    if inspected.get("status") != "inspection_completed" or condition not in {
        "maintenance_required", "serviceable"
    }:
        raise base.PilotStop("Unknown or incomplete header inspection receipt")
    decision["inspection_receipt"] = inspected
    # Capture the common prefix before the two policies can differ.
    decision["common_prefix_calls"] = executor.calls
    decision["common_prefix_sha256"] = base.digest(executor.events)
    executor.log({**decision, "event": "h01_inspection_completed"})
    if arm == "A" and condition == "maintenance_required":
        serviced = executor.required(SERVICE_TOOL)
        if serviced.get("status") != "service_completed" or serviced.get("condition") != "serviceable":
            raise base.PilotStop("Header service did not establish serviceable condition")
        decision["service_receipt"] = serviced
        decision["action"] = "service"
    else:
        decision["service_receipt"] = None
        decision["action"] = "retain_condition" if arm == "B" else "already_serviceable"
    decision["continued_at"] = executor.now()
    executor.log(decision)
    return decision


def diagnostic_initial(scenario, engine) -> dict:
    """Read-only audit export, deliberately outside the public controller."""
    apps = {app.name: app for app in scenario.apps}
    names = ("FarmWorldApp", "TractorApp", "SensorApp", "WeatherApp")
    return {
        "purpose": "pair initial-state audit only; not a restored/checkpoint-validated mother trajectory",
        "scenario_id": SCENARIO_ID,
        "seed": scenario.seed,
        "simulation_time": engine.time_manager.time(),
        "specification": dataclasses.asdict(scenario.spec),
        "apps": {name: apps[name].get_state() for name in names},
    }


def diagnostic_final(scenario) -> tuple[dict, dict]:
    """Export existing native history without from_state or advancing physics."""
    from fairy.apps.farm_world import FarmWorldApp

    farm = scenario.get_typed_app(FarmWorldApp)
    physics = farm.physics
    backend = physics.crop_backend
    apps = {app.name: app for app in scenario.apps}
    diagnostic = {
        "purpose": "offline audit only; never read by a reference decision",
        "native_snapshot": backend.snapshot(),
        "action_log": physics.action_log,
        "pending_management_actions_by_ridge": physics.pending_management_actions_by_ridge,
        "pending_harvest_actions_by_ridge": physics.pending_harvest_actions_by_ridge,
        "yield_recovery_by_ridge": physics.yield_recovery.states,
        "tractor_state": apps["TractorApp"].get_state(),
        "sensor_state": apps["SensorApp"].get_state(),
        "weather_state": apps["WeatherApp"].get_state(),
    }
    return diagnostic, backend.export_state()


def error_record(stage: str, error: BaseException) -> dict:
    return {
        "stage": stage, "type": type(error).__name__, "message": str(error),
        "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__)),
    }


def preflight(gate_path: Path) -> int:
    if gate_path.exists():
        raise RuntimeError("Preflight output already exists; use a new gate path")
    result = {"candidate": "H01", "scenario_id": SCENARIO_ID, "status": "failed"}
    try:
        current_identity = identity()
        scenario, engine = setup_scenario()
        interface = public_interface(scenario, engine)
        result.update(
            status="passed", identity=current_identity,
            identity_sha256=base.digest(current_identity),
            public_interface=interface,
            public_interface_sha256=base.digest(interface),
            checks=["registered candidate setup", "public H01 tool menu",
                    "exact scenario input; Engine briefing str.strip() only",
                    "explicit development grid", "briefing graph only; no static replay"],
            model_api_calls=0, fullseason_runs=0,
        )
    except BaseException as error:
        result["failure"] = error_record("preflight", error)
    base.save(gate_path, result)
    return 0 if result["status"] == "passed" else 1


def run(arm: str, gate_path: Path, output: Path) -> int:
    # One invocation, one fresh output.  Failed runs retain their directory and
    # are never silently replaced or retried by this entry point.
    output.mkdir(parents=True, exist_ok=False)
    scenario = engine = executor = None
    failures = []
    controller_completed = False
    evaluation = None
    stage = "gate"
    try:
        current_identity = identity()
        gate = json.loads(gate_path.read_text())
        require_matching_gate(gate, current_identity)
        stage = "setup_and_interface"
        scenario, engine = setup_scenario()
        interface = public_interface(scenario, engine)
        if base.digest(interface) != gate.get("public_interface_sha256"):
            raise RuntimeError("Actual public interface differs from preflight; no farm actions executed")
        base.save(output / "actual_public_interface.json", interface)
        stage = "initial_diagnostics"
        base.save(output / "initial_state.json", diagnostic_initial(scenario, engine))
        started = {
            "runner_version": RUNNER_VERSION,
            "scenario_id": SCENARIO_ID, "candidate": "H01", "arm": arm,
            "policy": POLICIES[arm], "seed": 0,
            "identity": current_identity, "identity_sha256": base.digest(current_identity),
            "gate_sha256": file_sha256(gate_path),
            "initial_state_sha256": file_sha256(output / "initial_state.json"),
            "reference_only": True, "model_api_calls": 0,
            "inspection_rule": INSPECTION_RULE, "event_graph_policy": EVENT_GRAPH_POLICY,
            "simulation_start_time": scenario.start_time,
            "reference_inputs": {
                "target_external_n_kg_ha": 120,
                "base_fertilizer_product_kg": 120 * 1.2864 / .46,
                "artificial_water_mm": 0,
                "these_are_reference_actions_not_task_acceptance_rules": True,
            },
            "no_automatic_fullseason_retry": True,
        }
        base.save(output / "started.json", started)
        executor = H01Executor(scenario, engine, output)
        stage = "public_establishment"
        base.setup_operations(executor, 120 * 1.2864 / .46)
        stage = "public_growth_management"
        base.manage(executor, "none")
        stage = "public_header_decision"
        decision = inspect_and_branch(executor, arm)
        base.save(output / "header_decision.json", decision)
        stage = "public_harvest_and_storage"
        base.harvest(executor)
        controller_completed = True
    except BaseException as error:
        failures.append(error_record(stage, error))
    finally:
        if scenario is not None:
            for name, producer in (
                ("workflow.json", lambda: scenario.workflow.to_dict()),
                ("evaluation.json", lambda: scenario.validate().to_dict()),
            ):
                try:
                    payload = producer()
                    base.save(output / name, payload)
                    if name == "evaluation.json":
                        evaluation = payload
                except BaseException as error:
                    failures.append(error_record("export_" + name, error))
            try:
                diagnostics, native_state = diagnostic_final(scenario)
                base.save(output / "diagnostic_final.json", diagnostics)
                base.save(output / "native_backend_state.json", native_state)
            except BaseException as error:
                failures.append(error_record("export_native_diagnostics", error))
        status = {
            "runner_version": RUNNER_VERSION, "scenario_id": SCENARIO_ID,
            "arm": arm, "policy": POLICIES[arm],
            "controller_completed": controller_completed,
            "evaluation_available": evaluation is not None,
            "execution_complete": (evaluation or {}).get("metadata", {}).get("execution_complete"),
            "production_success": (evaluation or {}).get("metadata", {}).get("production_success"),
            "tool_calls": executor.calls if executor is not None else 0,
            "failures": failures, "model_api_calls": 0,
            "native_history_replayed": False,
            "full_farm_checkpoint_validated": False,
            "no_automatic_fullseason_retry": True,
        }
        base.save(output / "run_status.json", status)
    return 0 if controller_completed and not failures and status["execution_complete"] is True else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "run"))
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--arm", choices=tuple(POLICIES))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action == "preflight":
        if args.arm is not None or args.output is not None:
            parser.error("preflight uses a common gate, not a policy arm or run output")
        return preflight(args.gate)
    if args.arm is None or args.output is None:
        parser.error("run requires --arm A|B and a new --output directory")
    return run(args.arm, args.gate, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
