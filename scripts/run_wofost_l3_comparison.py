"""Replay unchanged formal L3 oracle tools with legacy and/or WOFOST physics.

Builds one canonical workflow per scenario using run_oracle=False, then uses
Engine.replay_workflow on fresh original scenarios. Instrumentation only reads
tool results and completed daily ticks; it does not replace gates, weather,
calibration, scenario definitions, or model calculations. A validate() returning
None is explicitly insufficient: completion is checked against all 64 ridges,
tool failures, and safe warehouse storage. FOS is intentionally left for a
separate evaluation against a baseline with matching backend provenance.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import inspect
import json
import platform
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import date, datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fairy.apps.farm_world import FarmWorldApp, TractorApp
from fairy.apps.farm_world.farm_world_app import FIELD_LENGTH_M
from fairy.apps.farm_world import physics_orchestrator
from fairy.controllers import engine as engine_module
from fairy.controllers.engine import Engine
from fairy.scenarios.fos.provenance import crop_backend_provenance
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.workflow import Workflow, WorkflowStep

DEFAULT_SCENARIOS = (
    "scenario_full_season_hb_base_hn84_std_normal",
    "scenario_full_season_hb_dryr5r6_hn84_water_limit",
)


def _safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "value"):
        return _safe(value.value)
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(item) for item in value]
    if value is None or isinstance(value, (str, float, int, bool)):
        return value
    return str(value)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_safe(value), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _workflow_hash(workflow: Workflow) -> str:
    # Only the unchanged executable contract; output content/timestamps are not
    # model inputs to Engine.replay_workflow and are deliberately excluded.
    calls = [{"name": name, "tool_name": step.tool_name, "tool_args": step.tool_args,
              "depends_on": step.depends_on} for name, step in workflow.dag.items()]
    return hashlib.sha256(json.dumps(_safe(calls), sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def _tool_errors(value: Any, location: str = "$", depth: int = 0) -> list[dict[str, Any]]:
    if depth > 30:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                return _tool_errors(json.loads(stripped), location, depth + 1)
            except (ValueError, TypeError):
                return []
        return []
    found = []
    if isinstance(value, dict):
        if value.get("error"):
            found.append({"path": location + ".error", "content": value["error"]})
        if str(value.get("status", "")).lower() in {"error", "failed", "failure", "blocked"}:
            found.append({"path": location + ".status", "content": value})
        if value.get("success") is False:
            found.append({"path": location + ".success", "content": value})
        for key, item in value.items():
            if key not in {"error", "status", "success"}:
                found.extend(_tool_errors(item, f"{location}.{key}", depth + 1))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_tool_errors(item, f"{location}[{index}]", depth + 1))
    return found


class ReplayAudit:
    def __init__(self, engine: Engine, source: Workflow, output_dir: Path):
        self.engine = engine
        self.source = source
        self.output_dir = output_dir
        self.calls = []
        self.daily_rows = []
        self.ever_planted: set[int] = set()
        self.ever_r8: set[int] = set()
        self.stored_ridges: set[int] = set()
        self.storage_warnings = []
        self._source_tools = [(name, step) for name, step in source.dag.items() if step.tool_name]
        self._stream = None

    def farm(self) -> FarmWorldApp:
        return self.engine.scenario.get_typed_app(FarmWorldApp)

    def observe(self) -> None:
        physics = self.farm().physics
        for rid, state in physics.phenology.states.items():
            if state.planted or state.planting_date is not None:
                self.ever_planted.add(rid)
            if physics.yield_recovery.states[rid].r8_reached or state.maturity_date is not None:
                self.ever_r8.add(rid)

    def daily(self, physics: Any, forcing_day: date) -> None:
        self.observe()
        native_runs = getattr(physics.crop_backend, "_runs", {})
        basis = "dry_matter" if physics.yield_recovery.params.biological_yield_is_dry_matter else "legacy_yield_proxy"
        for rid, phen in physics.phenology.states.items():
            canopy, soil, recovery = (physics.canopy.states[rid], physics.soil.states[rid],
                                      physics.yield_recovery.states[rid])
            native = native_runs.get(rid)
            pcse = native.pcse if native is not None else {}
            self.daily_rows.append({
                "forcing_day": forcing_day.isoformat(), "ridge_id": rid,
                "seed_type": _safe(phen.seed_type), "stage": phen.stage.value,
                "planted": phen.planted, "emerged": phen.emerged,
                "emergence_date": _safe(phen.emergence_date), "maturity_date": _safe(phen.maturity_date),
                "r8_reached": recovery.r8_reached, "harvested": recovery.harvested,
                "harvest_date": _safe(recovery.harvest_date),
                "lai_m2_m2": canopy.lai, "root_vwc": soil.root_vwc, "top_vwc": soil.top_vwc,
                "aboveground_biomass_g_m2": canopy.aboveground_biomass_g_m2,
                "yield_potential_g_m2": canopy.yield_potential_g_m2,
                "biological_yield_g_m2": recovery.biological_yield_g_m2,
                "biological_yield_basis": basis,
                "field_loss_fraction": recovery.field_loss_fraction,
                "machine_loss_fraction": recovery.machine_loss_fraction,
                "grain_moisture_fraction": recovery.grain_moisture_frac,
                "recovered_yield_g_m2_at_market_moisture": recovery.recovered_yield_g_m2_at_market_moisture,
                "native_DVS": pcse.get("DVS"), "native_TSUM": pcse.get("TSUM"),
                "native_TWSO_kg_dm_ha": pcse.get("TWSO"), "native_TAGP_kg_dm_ha": pcse.get("TAGP"),
                "native_NAVAIL_kg_n_ha": pcse.get("NAVAIL"), "native_RFTRA": pcse.get("RFTRA"),
                "native_RFRGRL": pcse.get("RFRGRL"),
                "cumulative_irrigation_mm": (native.cumulative_irrigation_mm if native else
                                               physics.management.states[rid].cumulative_irrigation_mm),
                "cumulative_fertilizer_kg": native.cumulative_fertilizer_kg if native else None,
            })

    @contextmanager
    def instrument(self):
        original_builder = engine_module.build_toolset
        original_tick = physics_orchestrator._run_daily_tick
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._stream = (self.output_dir / "runtime_log.jsonl").open("w", encoding="utf-8")

        def observed_tick(farm, physics, weather_app, day):
            result = original_tick(farm, physics, weather_app, day)
            if farm is self.farm():
                self.daily(physics, day)
            return result

        def instrumented_builder(*args, **kwargs):
            tools, schemas, mapping = original_builder(*args, **kwargs)
            wrapped = {}
            for tool_name, function in mapping.items():
                @wraps(function)
                def call(*tool_args, _name=tool_name, _function=function, **tool_kwargs):
                    index = len(self.calls)
                    step_name = self._source_tools[index][0] if index < len(self._source_tools) else None
                    before = self.engine.time_manager.time()
                    started = time.perf_counter()
                    record = {"index": index, "step_name": step_name, "tool_name": _name,
                              "tool_args": copy.deepcopy(tool_kwargs), "sim_timestamp_before": before}
                    try:
                        content = _function(*tool_args, **tool_kwargs)
                        errors = _tool_errors(content)
                        record.update(content=content, tool_error_details=errors,
                                      status="tool_error" if errors else "ok")
                        if _name.endswith("__store_grain") and isinstance(content, dict) and not errors:
                            if content.get("warning"):
                                self.storage_warnings.append(content["warning"])
                            elif float(content.get("moved_kg", 0)) > 0:
                                self.stored_ridges.update(int(rid) for rid in content.get("batch_ridge_ids", []))
                        return content
                    except Exception as exc:
                        record.update(status="exception", content={"error": str(exc)},
                                      exception_type=type(exc).__name__, traceback=traceback.format_exc())
                        raise
                    finally:
                        record.update(sim_timestamp_after=self.engine.time_manager.time(),
                                      wall_seconds=time.perf_counter() - started)
                        record["sim_elapsed_seconds"] = record["sim_timestamp_after"] - before
                        record = _safe(record)
                        self.calls.append(record)
                        self._stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                        self._stream.flush()
                        self.observe()
                wrapped[tool_name] = call
            return tools, schemas, wrapped

        engine_module.build_toolset = instrumented_builder
        physics_orchestrator._run_daily_tick = observed_tick
        try:
            yield
        finally:
            engine_module.build_toolset = original_builder
            physics_orchestrator._run_daily_tick = original_tick
            self._stream.close()


def run_case(scenario_id: str, backend: str, source: Workflow, *, output_dir: Path,
             backend_options: dict[str, Any]) -> dict[str, Any]:
    scenario_class = get_scenario_class(scenario_id)
    scenario = scenario_class(crop_backend=backend,
                              crop_backend_options=backend_options if backend == "wofost" else {})
    engine = Engine(agent=None, scenario=scenario)
    # Setup is the unmodified scenario's normal setup and is a no-op when
    # Engine.replay_workflow subsequently invokes it again.
    scenario.setup()
    engine._register_scenario_apps()
    farm = scenario.get_typed_app(FarmWorldApp)
    initial_provenance = crop_backend_provenance(farm.physics)
    audit = ReplayAudit(engine, source, output_dir)
    audit.observe()
    error = None
    started = time.perf_counter()
    try:
        with audit.instrument():
            replayed = engine.replay_workflow(source)
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        replayed = Workflow()
        for record in audit.calls:
            original = source.dag.get(record["step_name"])
            replayed.add_node(WorkflowStep(
                name=record["step_name"], tool_name=record["tool_name"], tool_args=record["tool_args"],
                content=record["content"], depends_on=list(original.depends_on) if original else [],
                error_stage="tool_exception" if record["status"] == "exception" else None))
    replayed.save_workflow(str(output_dir / "replay.json"))
    _write_json(output_dir / "engine_runtime_log.json", engine.run_log)
    _write_json(output_dir / "errors.json", {"replay_exception": error,
        "tool_errors": [item for item in audit.calls if item["status"] != "ok"],
        "storage_warnings": audit.storage_warnings})
    if audit.daily_rows:
        with (output_dir / "daily.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(audit.daily_rows[0]))
            writer.writeheader()
            writer.writerows(audit.daily_rows)

    physics = farm.physics
    native_runs = getattr(physics.crop_backend, "_runs", {})
    ridge_area = FIELD_LENGTH_M * farm.ridge_width_m
    final_ridges = []
    for rid, phen in physics.phenology.states.items():
        recovery = physics.yield_recovery.states[rid]
        native = native_runs.get(rid)
        final_ridges.append({"ridge_id": rid, "ever_planted": rid in audit.ever_planted,
            "ever_r8": rid in audit.ever_r8, "safely_stored": rid in audit.stored_ridges,
            "phenology": vars(phen), "soil": vars(physics.soil.states[rid]),
            "canopy": vars(physics.canopy.states[rid]), "yield_recovery": vars(recovery),
            "late_harvest_days": ((recovery.harvest_date - recovery.maturity_date).days
                                  if recovery.harvest_date and recovery.maturity_date else None),
            "native": ({"pcse": native.pcse, "specification": native.specification,
                        "maturity_snapshot": native.maturity_snapshot,
                        "native_model_day": native.model.day, "native_days": len(native.journal)}
                       if native else None)})
    tractor = scenario.get_typed_app(TractorApp)
    inventory = farm._inventory.to_dict()
    tool_errors = [item for item in audit.calls if item["status"] != "ok"]
    expected = set(range(64))
    harvested = {rid for rid, state in physics.yield_recovery.states.items() if state.harvested}
    storage_complete = (audit.stored_ridges == expected and inventory["warehouse_grain_kg"] > 0
                        and inventory["harvest_grain_kg"] <= .01 and tractor._grain_bin_kg <= .01
                        and not audit.storage_warnings)
    checks = {"original_field_has_64_ridges": farm.num_ridges == 64,
              "all_64_ever_planted": audit.ever_planted == expected,
              "all_64_reached_r8": audit.ever_r8 == expected,
              "all_64_harvested": harvested == expected,
              "zero_tool_errors_or_exceptions": not tool_errors and error is None,
              "safe_storage_completed_for_all_64": storage_complete,
              "all_original_tool_calls_replayed": len(audit.calls) == len(audit._source_tools),
              "native_engine_count_matches_backend": len(native_runs) == (64 if backend == "wofost" else 0)}
    generic = engine.evaluation_report(replayed)
    source_file = Path(inspect.getfile(scenario_class))
    dry = physics.yield_recovery.params.biological_yield_is_dry_matter
    summary = {"scenario_id": scenario_id, "crop_backend": backend,
        "strict_success": all(checks.values()), "strict_checks": checks,
        "generic_validation": generic["validation"],
        "generic_validation_limit": "Inherited Scenario.validate() may return None and be reported successful; only strict_checks establish completion.",
        "canonical_workflow_sha256": _workflow_hash(source),
        "scenario_source_path": str(source_file), "scenario_source_sha256": hashlib.sha256(source_file.read_bytes()).hexdigest(),
        "python_version": platform.python_version(), "wall_seconds": time.perf_counter() - started,
        "simulation_end_utc": datetime.fromtimestamp(engine.time_manager.time(), timezone.utc).isoformat(),
        "counts": {"ridges": farm.num_ridges, "ever_planted": len(audit.ever_planted),
                   "ever_r8": len(audit.ever_r8), "harvested": len(harvested),
                   "safely_stored_ridges": len(audit.stored_ridges), "native_engines": len(native_runs),
                   "tool_calls": len(audit.calls), "tool_errors_or_exceptions": len(tool_errors),
                   "daily_ticks": len({row["forcing_day"] for row in audit.daily_rows})},
        "metrics": {"ridge_area_m2": ridge_area,
            "biological_yield_kg_engine_basis": sum(s.biological_yield_g_m2 for s in physics.yield_recovery.states.values()) * ridge_area / 1000,
            "biological_yield_basis": "dry_matter" if dry else "legacy_yield_proxy",
            "biological_yield_kg_dm_total": sum(s.biological_yield_g_m2 for s in physics.yield_recovery.states.values()) * ridge_area / 1000 if dry else None,
            "recovered_yield_kg_at_market_moisture_total": sum(s.recovered_yield_g_m2_at_market_moisture for s in physics.yield_recovery.states.values()) * ridge_area / 1000,
            "market_moisture_fraction": physics.yield_recovery.params.market_moisture_frac,
            "mean_field_loss_fraction": sum(s.field_loss_fraction for s in physics.yield_recovery.states.values()) / farm.num_ridges,
            "mean_machine_loss_fraction": sum(s.machine_loss_fraction for s in physics.yield_recovery.states.values()) / farm.num_ridges,
            "maturity_dates": sorted({str(s.maturity_date) for s in physics.yield_recovery.states.values() if s.maturity_date}),
            "harvest_dates": sorted({str(s.harvest_date) for s in physics.yield_recovery.states.values() if s.harvest_date}),
            "inventory": inventory, "combine_grain_bin_kg": tractor._grain_bin_kg},
        "crop_backend_provenance": initial_provenance,
        "final_crop_backend_provenance": crop_backend_provenance(physics),
        "replay_exception": error,
        "fos": {"evaluated": False, "reason": "Use matching backend baseline for separate FOS evaluation; raw comparison does not share a cross-backend denominator."},
        "artifacts": {name: str(output_dir / name) for name in (
            "daily.csv", "runtime_log.jsonl", "engine_runtime_log.json", "replay.json", "errors.json", "final_state.json", "summary.json")}}
    _write_json(output_dir / "final_state.json", {"ridges": final_ridges, "inventory": inventory,
        "management_regime": farm._management_regime.to_dict(), "postharvest_market": farm._postharvest_market.to_dict()})
    _write_json(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", "--case", action="append", dest="scenarios",
                        help="Scenario ID; repeat for multiple cases. Defaults to the two original formal L3 scenarios.")
    parser.add_argument("--backend", choices=("legacy", "wofost", "both"), default="both")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workflow", type=Path, help="Replay an existing canonical workflow; requires one scenario")
    parser.add_argument("--wofost-config", type=Path, help="Optional JSON object; no calibration is inferred")
    args = parser.parse_args()
    scenarios = args.scenarios or list(DEFAULT_SCENARIOS)
    if args.workflow and len(scenarios) != 1:
        parser.error("--workflow requires exactly one --scenario")
    options = json.loads(args.wofost_config.read_text(encoding="utf-8")) if args.wofost_config else {}
    if not isinstance(options, dict):
        parser.error("--wofost-config must contain a JSON object")
    output_dir = args.output_dir.expanduser().resolve()
    summaries = []
    for sid in scenarios:
        common = output_dir / sid
        canonical_path = common / "canonical_workflow.json"
        if args.workflow:
            workflow = Workflow.load_workflow(str(args.workflow))
        else:
            build_engine = Engine(agent=None, scenario=get_scenario_class(sid)())
            workflow = build_engine.build_oracle_workflow(run_oracle=False)
        _write_json(canonical_path, workflow.to_dict())
        _write_json(common / "workflow_provenance.json", {
            "scenario_id": sid, "tool_contract_sha256": _workflow_hash(workflow),
            "built_with_run_oracle": False, "canonical_workflow": str(canonical_path),
            "source_workflow": str(args.workflow) if args.workflow else None,
            "policy": "Original captured oracle tool names/arguments, dependencies and order; Engine.replay_workflow timing semantics. No added waiting, extrapolation, gate bypass or calibration."})
        for backend in (("legacy", "wofost") if args.backend == "both" else (args.backend,)):
            summary = run_case(sid, backend, workflow, output_dir=common / backend, backend_options=options)
            summaries.append(summary)
            print(json.dumps({"scenario_id": sid, "backend": backend,
                              "strict_success": summary["strict_success"], "counts": summary["counts"],
                              "summary": str(common / backend / "summary.json")}, ensure_ascii=False), flush=True)
    _write_json(output_dir / "comparison_summary.json", {"runs": summaries,
        "all_strict_success": all(item["strict_success"] for item in summaries),
        "comparison_note": "Same canonical tools, original scenarios and tool gates; different crop models and biological mass bases. No cross-backend FOS denominator."})
    return 0 if all(item["strict_success"] for item in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
