"""Management-extension adapters for the established trace-rebatch pipeline.

Workflow scores are computed by rebatch_fos_from_traces' existing functions.
This module only supplies crop/season-aware physical and financial snapshots.
No model calls, management-policy search, or automatic harvesting occur here.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
import fcntl
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "fairy.management-replay.v1"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


@lru_cache(maxsize=1)
def management_scenario_ids() -> frozenset[str]:
    from fairy.scenarios.management_extensions import SCENARIO_MODULES
    from fairy.scenarios.scenario import Scenario

    ids = set()
    for name in SCENARIO_MODULES:
        module = importlib.import_module("fairy.scenarios.management_extensions." + name)
        for cls in vars(module).values():
            if (isinstance(cls, type) and issubclass(cls, Scenario)
                    and cls.__module__ == module.__name__):
                ids.add(cls.scenario_id)
    return frozenset(ids)


def is_management_scenario(scenario_id: str) -> bool:
    return scenario_id in management_scenario_ids()


def initial_input_fingerprint(scene):
    provider = getattr(scene, "input_fingerprint", None)
    if callable(provider):
        return provider()
    # The four original maize/SCN extensions predate input_fingerprint().
    # Include their actual initial farm/weather state rather than caching them
    # with an absent fingerprint.
    from fairy.apps.farm_world.multi_farm import farm_world_apps
    farms = farm_world_apps(scene.apps)
    payload = dict(scene_type=type(scene).__module__ + "." + type(scene).__name__,
                   farms={farm.farm_id: farm.get_state() for farm in farms})
    return dict(source="initial_farm_state", sha256=hashlib.sha256(_json(payload).encode()).hexdigest())


def relative_gap(agent: float | None, oracle: float | None) -> dict[str, Any]:
    """Requested signed denominator; never replace Oracle with abs(Oracle)."""
    if agent is None or oracle is None:
        return dict(value=None, percent=None, difference=None, reason="missing_value",
                    negative_denominator=oracle is not None and oracle < 0)
    if not (math.isfinite(agent) and math.isfinite(oracle)):
        return dict(value=None, percent=None, difference=None, reason="nonfinite_value",
                    negative_denominator=False)
    delta = agent - oracle
    ratio = delta / oracle if oracle else None
    return dict(value=ratio, percent=100 * ratio if ratio is not None else None,
                difference=delta, reason=None if oracle else "zero_oracle_denominator",
                negative_denominator=oracle < 0)


def _sum_known(values):
    values = list(values)
    return math.fsum(values) if all(v is not None for v in values) else None


def _record(farm_id, year, crop, biological, recovered, *, cycle_id=None,
            projection="observed", recovered_floor=None, established=True):
    return dict(farm_id=farm_id, year=int(year), cycle_id=cycle_id, crop_id=crop,
                biological_kg=biological, recovered_kg=recovered,
                recovered_floor_kg=recovered_floor, biological_status=projection,
                established=established,
                biological_basis="storage_organ_dry_matter_kg",
                recovered_basis="fresh_root_kg" if crop == "sugarbeet" else "market_moisture_grain_kg")


def _native_projection(backend, end, max_days, extrapolate):
    planted = backend.sown or any(a["kind"] == "sow" for a in backend.pending)
    value = float(backend.values.get("TWSO") or 0)
    if not planted or not extrapolate or backend.maturity or backend.failed:
        return value, "observed" if planted else "not_established"
    if backend.next_day >= end:
        return value, "calendar_end"
    projection = type(backend).restore(backend.bundle, backend.export_state())
    limit = min(end, backend.next_day + timedelta(days=max_days))
    while projection.next_day < limit and not projection.maturity:
        projection.advance_day()
    status = "mature" if projection.maturity else "calendar_end" if limit == end else "day_cap"
    return float(projection.values.get("TWSO") or 0), status


def _beet_records(scene, extrapolate, max_days):
    farm = scene.farm
    area = farm.ridge_area_m2 / 10000
    grouped = defaultdict(list)
    for index, backend in enumerate(farm.backends):
        for cycle in farm.bundle.cycles:
            harvest = backend.harvests.get(cycle.cycle_id)
            active = backend.cycle.cycle_id == cycle.cycle_id
            established = bool(harvest) or (active and (
                backend.sown or any(a["kind"] == "sow" for a in backend.pending)))
            bio, status = 0.0, "not_established"
            if harvest:
                bio, status = float(harvest["native"]["TWSO"]) * area, "harvest_receipt"
            elif active and established:
                try:
                    value, status = _native_projection(
                        backend, cycle.harvest_close + timedelta(days=1), max_days, extrapolate)
                    bio = value * area
                except Exception as exc:
                    bio, status = None, "projection_failed: " + str(exc)
            if cycle.crop == "sugarbeet":
                # Recovered roots are lifted mass, distinct from accepted delivery.
                recovered = sum(b.recovered_net_kg for b in scene.delivery.ledger.batches.values()
                                if b.block_id == index and b.cycle_id == cycle.cycle_id)
                floor = recovered if harvest else None
            else:
                recovered = (float(harvest["native"]["TWSO"]) * area * .95
                             / (1 - scene.resources.storage_moisture_pct / 100)) if harvest else 0.0
                floor = recovered if harvest else None
            grouped[(cycle.cycle_id, cycle.crop, cycle.sowing_open.year)].append(
                (bio, recovered, floor, status, established))
    return [_record(farm.farm_id, year, crop,
                    _sum_known(v[0] for v in values), math.fsum(v[1] for v in values),
                    recovered_floor=_sum_known(v[2] for v in values), cycle_id=cid,
                    projection="; ".join(sorted({v[3] for v in values})),
                    established=any(v[4] for v in values))
            for (cid, crop, year), values in grouped.items()]


def _wheat_records(scene, extrapolate, max_days):
    farm = scene.farm
    area = farm.ridge_area_m2 / 10000
    bios, statuses = [], []
    coupled_projection = getattr(farm, "project_biological_grain_kg", None)
    for backend in farm.backends:
        try:
            value, status = _native_projection(
                backend, backend.bundle.season.deadline + timedelta(days=1), max_days, extrapolate and coupled_projection is None)
            bios.append(value * area)
            statuses.append(status)
        except Exception as exc:
            bios.append(None)
            statuses.append("projection_failed: " + str(exc))
    from fairy.scenarios.management_extensions.evaluation.oracle_comparison import recovered_grain_kg
    recovered = recovered_grain_kg(farm)
    biological = coupled_projection(max_days) if extrapolate and coupled_projection else _sum_known(bios)
    return [_record(farm.farm_id, farm.bundle.season.sowing_open.year, "winter_wheat",
                    biological, recovered,
                    recovered_floor=recovered if all(r.harvested for r in farm._ridges) else None,
                    projection="; ".join(sorted(set(statuses))),
                    established=any(r.planted or r.harvested for r in farm._ridges))]


def _regular_farm_record(scene, farm, year, extrapolate, max_days):
    from fairy.scenarios.fos.evaluation import (
        _compute_recovered_yield_floor_kg, _extrapolate_physics_to_maturity,
    )
    from fairy.scenarios.management_extensions.evaluation.oracle_comparison import recovered_grain_kg

    recovered = recovered_grain_kg(farm)
    projected, status = farm, "observed"
    try:
        states = farm.physics.yield_recovery.states
        immature = any(r.planted and not r.harvested
                       and not (getattr(states.get(i), "r8_reached", False)
                                or getattr(states.get(i), "r6_reached", False))
                       for i, r in enumerate(farm._ridges))
        if extrapolate and immature:
            # Managed weather views delegate attributes and cannot be copied
            # by generic deepcopy. The runtime's checkpoint codec preserves
            # the complete weather/field context in an independent world.
            runtime = getattr(getattr(farm, "_weather_app", None), "runtime", None)
            if runtime is not None:
                detached = type(runtime).load_snapshot(runtime.snapshot())
                projected = detached.farms[farm.farm_id].farm
            else:
                projected = deepcopy(farm)
            detail = _extrapolate_physics_to_maturity(projected, max_days=max_days)
            status = str(detail.get("status"))
            if status in {"error", "failed"}:
                raise ValueError(str(detail))
            if status == "advanced" and not detail.get("reached_maturity"):
                status = "day_cap"
        biological = math.fsum(s.biological_yield_g_m2 for s in
                              projected.physics.yield_recovery.states.values()) * farm.ridge_area_m2 / 1000
    except Exception as exc:
        biological, status = None, "projection_failed: " + str(exc)
    proxy = SimpleNamespace(start_time=scene.start_time, get_typed_app=lambda _: projected)
    floor = (_compute_recovered_yield_floor_kg(proxy, projected.physics, farm.ridge_area_m2)
             if biological is not None else None)
    return _record(farm.farm_id, year, farm.crop_id, biological, recovered,
                   projection=status, recovered_floor=floor,
                   established=any(r.planted or r.harvested for r in farm._ridges))


def _yield_records(scene, extrapolate, max_days):
    from fairy.apps.farm_world.multi_farm import farm_world_apps
    from fairy.scenarios.management_extensions.apps.sugarbeet_farm_app import SugarBeetFarm
    from fairy.scenarios.management_extensions.apps.winter_wheat_farm_app import WinterWheatFarm

    farm = getattr(scene, "farm", None)
    if isinstance(farm, SugarBeetFarm):
        return _beet_records(scene, extrapolate, max_days), "native_root_and_grain_receipts"
    if isinstance(farm, WinterWheatFarm):
        return _wheat_records(scene, extrapolate, max_days), "native_wheat_blocks"
    cycle = getattr(scene, "cycle", None)
    if cycle is not None and hasattr(cycle, "yield_seasons"):
        records = [_record(cycle.farm.farm_id, r["year"], r.get("crop_id", "maize"),
                           r.get("biological_grain_kg"), r.get("recovered_grain_kg"),
                           projection="closed_season_ledger", recovered_floor=r.get("recovered_grain_kg"))
                   for r in cycle.closed]
        if not cycle.closed or cycle.closed[-1]["year"] != cycle.current_year:
            records.append(_regular_farm_record(scene, cycle.farm, cycle.current_year,
                                                extrapolate, max_days))
        return records, "closed_seasons_plus_current_crop"
    records = []
    for farm in farm_world_apps(scene.apps):
        year = farm.simulation_date().year
        records.append(_regular_farm_record(scene, farm, year, extrapolate, max_days))
    if not records:
        raise ValueError("No supported management farm found")
    return records, "existing_fos_yield_recovery"


def _pure_accounts(scene):
    for attr in ("accounts", "cycle"):
        candidate = getattr(scene, attr, None)
        if callable(getattr(candidate, "compute_accounts", None)):
            accounts = candidate.compute_accounts()
            subsidy = getattr(scene, "subsidy", None)
            if subsidy is not None:
                accounts["paid_subsidy"] = subsidy.paid_income()
                accounts["net_operating_margin"] += subsidy.paid_income()
            return accounts
    if callable(getattr(scene, "production_accounts", None)):
        return scene.production_accounts()
    raise ValueError("No operating-account snapshot provider")


def snapshot(scene, env, *, extrapolate=True, max_days=180):
    """Freeze money at actual replay end; project only detached crop copies."""
    validation_error = None
    try:
        validation = scene.validate(env)
        accounts = dict(validation.metadata)
        success, message = validation.success, validation.message
    except Exception as exc:
        validation_error = f"{type(exc).__name__}: {exc}"
        accounts, success, message = _pure_accounts(scene), False, validation_error
    records, source = _yield_records(scene, extrapolate, max_days)
    return dict(schema=SCHEMA, scenario_id=scene.scenario_id,
                records=records, yield_source=source, accounts=accounts,
                task_success=success, task_message=message,
                validation_error=validation_error,
                biological_kg=_sum_known(r["biological_kg"] for r in records),
                recovered_kg=_sum_known(r["recovered_kg"] for r in records),
                recovered_floor_kg=_sum_known(r["recovered_floor_kg"] for r in records),
                extrapolate=extrapolate, max_days=max_days)


@lru_cache(maxsize=1)
def evaluator_digest():
    paths = [Path(__file__), ROOT / "scripts/rebatch_fos_from_traces.py"]
    for relative in ("fairy/scenarios/management_extensions", "fairy/scenarios/fos"):
        paths.extend((ROOT / relative).rglob("*.py"))
    return hashlib.sha256(_json([(str(p.relative_to(ROOT)),
                                 hashlib.sha256(p.read_bytes()).hexdigest())
                                for p in sorted(set(paths))]).encode()).hexdigest()


def oracle_reference(scene, bundle, cache_dir, *, extrapolate, max_days):
    """Execute the same configured Oracle, with an atomic per-context cache."""
    from scripts.rebatch_fos_from_traces import _instantiate_scenario_for_replay
    from fairy.controllers.engine import Engine
    from fairy.scenarios.scenario import Scenario
    from fairy.scenarios.workflow_validation import workflow_from_oracle_events, _normalize_workflow_times

    context = dict(scenario_id=scene.scenario_id, seed=bundle.get("seed"),
                   start_time=bundle.get("start_time"),
                   scenario_kwargs=bundle.get("scenario_kwargs") or {},
                   init_kwargs=bundle.get("init_kwargs") or {},
                   input_fingerprint=getattr(scene, "_replay_initial_fingerprint", None),
                   evaluator_digest=evaluator_digest(), extrapolate=extrapolate, max_days=max_days)
    key = hashlib.sha256(_json(context).encode()).hexdigest()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{scene.scenario_id}__{key[:20]}.json"
    with path.with_suffix(".lock").open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if path.exists():
            data = json.loads(path.read_text())
            if data.get("context") == context and data.get("schema") == SCHEMA:
                return data, path
        oracle = _instantiate_scenario_for_replay(
            scene.scenario_id, bundle.get("start_time"), bundle.get("seed"),
            bundle.get("scenario_kwargs"), bundle.get("init_kwargs"))
        actual_fp = getattr(oracle, "_replay_initial_fingerprint", None)
        if context["input_fingerprint"] != actual_fp:
            raise ValueError("Agent/Oracle initial input fingerprints differ")
        engine = Engine(None, oracle)
        workflow = engine.run_scenario_oracle()
        oracle_env = engine.environment(workflow)
        data = snapshot(oracle, oracle_env, extrapolate=extrapolate, max_days=max_days)
        if not data["task_success"]:
            raise ValueError("Oracle validation failed: " + data["task_message"])
        # Preserve the primary rebatch script's reference-workflow convention.
        metric_wf = (workflow_from_oracle_events(oracle)
                     if type(oracle).oracle_solution is Scenario.oracle_solution else workflow.to_dict())
        _normalize_workflow_times(metric_wf)
        from fairy.scenarios.fos.multi_farm import yield_provenance
        from fairy.scenarios.fos.evaluation import _try_get_farm_world
        data.update(context=context, workflow=metric_wf, executed_workflow=workflow.to_dict(),
                    crop_backend_provenance=yield_provenance(oracle, _try_get_farm_world(oracle)))
        temp = path.with_suffix(f".{os.getpid()}.tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        temp.replace(path)
        return data, path


def comparison(agent, oracle):
    """Legacy mass-sum headline, plus crop/year/farm-qualified decomposition."""
    totals = {}
    for basis in ("biological", "recovered", "recovered_floor"):
        gap = relative_gap(agent.get(basis + "_kg"), oracle.get(basis + "_kg"))
        totals[basis] = {**gap, "loss_pct": -gap["percent"] if gap["percent"] is not None else None}
    details = []
    def group(records):
        grouped = defaultdict(list)
        for r in records:
            grouped[(r["farm_id"], r["year"], r["crop_id"])].append(r)
        return grouped
    aa, oo = group(agent["records"]), group(oracle["records"])
    for key in sorted(aa.keys() | oo.keys()):
        a, o = aa.get(key, []), oo.get(key, [])
        row = dict(zip(("farm_id", "year", "crop_id"), key))
        row["composition_match"] = bool(a and o)
        for basis in ("biological", "recovered"):
            av = _sum_known(r[basis + "_kg"] for r in a)
            ov = _sum_known(r[basis + "_kg"] for r in o)
            gap = relative_gap(av, ov)
            row[basis] = dict(agent_kg=av, oracle_kg=ov, **gap,
                              loss_pct=-gap["percent"] if gap["percent"] is not None else None)
        details.append(row)
    economics = {}
    a, o = agent["accounts"], oracle["accounts"]
    money_matches = a.get("currency") == o.get("currency") and a.get("prices") == o.get("prices")
    for name in ("production_cost", "net_operating_margin"):
        economics[name] = relative_gap(a.get(name), o.get(name)) if money_matches else dict(
            value=None, percent=None, difference=None, reason="currency_or_prices_mismatch",
            negative_denominator=False)
        economics[name].update(agent=a.get(name), oracle=o.get(name))
    return dict(yields=totals, economics=economics, details=details,
                crop_composition_changed={(r["year"], r["crop_id"]) for r in agent["records"] if r["established"]}
                != {(r["year"], r["crop_id"]) for r in oracle["records"] if r["established"]})


def evaluate_management_replay(scene, env, info, bundle, row, cell_out, *,
                               extrapolate, max_days, path_correctness_v2, pc2_tol,
                               oracle_cache_dir=None):
    from scripts.rebatch_fos_from_traces import _add_workflow_columns, _pct
    from fairy.scenarios.workflow import Workflow, WorkflowStep

    env.workflow = Workflow()
    steps = bundle["workflow"].values() if isinstance(bundle["workflow"], dict) else bundle["workflow"]
    for step in steps:
        env.workflow.add_node(WorkflowStep(**step))
    cell_out.mkdir(parents=True, exist_ok=True)
    row.update(scenario=scene.scenario_id, level="level4_multiseason" if ".L4." in type(scene).__module__ else "level3_fullseason",
               detailed_briefing="true" if scene.detailed_briefing else "false",
               detail_status="detail_true" if scene.detailed_briefing else "detail_false")
    for out_key, in_key in (("replayed_events", "n_replayed"), ("replay_executed_actions", "n_executed"),
                            ("replay_restored_error_events", "n_restored_error_events"),
                            ("replay_skipped", "n_skipped"), ("replay_exec_errors", "exec_errors"),
                            ("replay_expected_error_events", "expected_error_events"),
                            ("replay_expected_exec_errors", "expected_exec_errors"),
                            ("replay_exact_timing_steps", "exact_timing_steps"),
                            ("replay_legacy_timing_steps", "legacy_timing_steps")):
        row[out_key] = info[in_key]
    agent = snapshot(scene, env, extrapolate=extrapolate, max_days=max_days)
    oracle, oracle_path = oracle_reference(scene, bundle, oracle_cache_dir or cell_out.parent / "management_oracles",
                                           extrapolate=extrapolate, max_days=max_days)
    comp = comparison(agent, oracle)
    scene._cached_oracle_workflow = oracle["workflow"]
    fos_payload = {"schema": SCHEMA}
    # Generic FOS is retained where its single-season grain representation applies.
    # A native root or closed-crop ledger is not a soybean/R8 yield state.
    native = hasattr(getattr(scene, "farm", None), "backends")
    multiseason = hasattr(getattr(scene, "cycle", None), "yield_seasons")
    if not native and not multiseason:
        try:
            from fairy.scenarios.fos.evaluation import evaluate_fos
            from scripts.rebatch_fos_from_traces import _add_fos_report_columns, _gates_for_scenario
            baseline_dir = cell_out / "fos_baseline"
            baseline_dir.mkdir(exist_ok=True)
            (baseline_dir / f"{scene.scenario_id}.json").write_text(json.dumps({
                "scenario_id": scene.scenario_id,
                "crop_backend_provenance": oracle["crop_backend_provenance"],
                "biological_yield_kg_total": oracle["biological_kg"],
                "recovered_yield_kg_total": oracle["recovered_kg"],
            }))
            generic = evaluate_fos(scene, env, gates=_gates_for_scenario(scene),
                                   extrapolate_to_maturity=extrapolate,
                                   extrapolation_max_days=max_days,
                                   oracle_baseline_dir=baseline_dir)
            _add_fos_report_columns(row, generic)
            fos_payload = generic.to_dict()
            row["generic_fos_status"] = "ok"
        except Exception as exc:
            row["generic_fos_status"] = "not_available: " + str(exc)
    from fairy.scenarios.fos.evaluation import _compute_efficiency, _oracle_tool_count
    efficiency, eb = _compute_efficiency(scene, env, _oracle_tool_count(scene))
    row.update({"efficiency(%)": _pct(efficiency), "tool_inflation": eb.tool_inflation,
                "redundant_reads": eb.redundant_reads, "agent_tool_calls": eb.agent_tool_calls,
                "oracle_tool_calls": eb.oracle_tool_calls})
    for key, basis in (("yield_loss(%)", "biological"), ("recovered_yield_loss(%)", "recovered"),
                       ("recovered_yield_loss_v2(%)", "recovered_floor")):
        value = comp["yields"][basis]["loss_pct"]
        row[key] = "" if value is None else f"{value:.2f}"
    for name, data in (("agent", agent), ("oracle", oracle)):
        row[name + "_biological_kg"] = data["biological_kg"]
        row[name + "_recovered_yield_kg"] = data["recovered_kg"]
        row[name + "_operating_cost_usd"] = data["accounts"].get("production_cost")
        row[name + "_net_operating_return_usd"] = data["accounts"].get("net_operating_margin")
    bio = comp["yields"]["biological"]
    row["yield_preserved_ratio(%)"] = _pct(1 + bio["value"]) if bio["value"] is not None else ""
    for key, name in (("relative_operating_cost_gap(%)", "production_cost"),
                      ("relative_net_operating_return_gap(%)", "net_operating_margin")):
        gap = comp["economics"][name]
        row[key] = "" if gap["percent"] is None else f"{gap['percent']:.2f}"
        row[key.removesuffix("(%)")] = gap["value"]
        row[key.removesuffix("(%)") + "_undefined_reason"] = gap["reason"] or ""
        row[key.removesuffix("(%)") + "_negative_oracle"] = gap["negative_denominator"]
    row.update(physical_replay_verified=True, workflow_metrics_source="strict_replay",
               task_success=agent["task_success"], task_message=agent["task_message"],
               management_evaluation_error=agent["validation_error"] or "",
               yield_aggregation="sum_mass_then_ratio", crop_composition_changed=comp["crop_composition_changed"],
               biological_yield_basis="storage_organ_dry_matter_kg",
               recovered_yield_basis="per_crop_market_grain_or_fresh_root_kg",
               biological_projection_capped=any("day_cap" in r["biological_status"] for r in agent["records"]),
               extrapolation_max_days=max_days,
               management_yield_source=agent["yield_source"], oracle_reference_path=str(oracle_path),
               economic_scope="consumed_inputs_and_enabled_operations; excludes rent, ordinary labour, depreciation, tax",
               generic_fos_status=row.get("generic_fos_status", "not_applicable_native_or_multiseason_grain_state"),
               farm_fos_calibration_scope="unchanged_legacy_soybean_priors; native_sow_and_root_lifting_are_not_calibrated")
    row["biological_yield_shortfall(%)"] = row["yield_loss(%)"]
    row["recovered_yield_shortfall(%)"] = row["recovered_yield_loss(%)"]
    row["currency"] = agent["accounts"].get("currency")
    row["operating_cost_gap_usd"] = comp["economics"]["production_cost"]["difference"]
    row["net_operating_return_gap_usd"] = comp["economics"]["net_operating_margin"]["difference"]
    row["biological_metric_status"] = "ok" if agent["biological_kg"] is not None else "projection_failed"
    row["recovered_v2_status"] = ("ok" if agent["recovered_floor_kg"] is not None
                                  else "not_defined_for_unharvested_native_crop")
    if agent["validation_error"]:
        row["status"] = "validation_error_metrics_recovered"
    elif agent["biological_kg"] is None:
        row["status"] = "partial_metrics"
    details_path = cell_out / "management_metrics.json"
    details_path.write_text(json.dumps(dict(schema=SCHEMA, agent=agent, oracle_reference=str(oracle_path),
                                           comparison=comp), ensure_ascii=False, indent=2, default=str))
    row["management_metrics_path"] = str(details_path)
    fos_path = cell_out / "fos" / f"fos_{scene.scenario_id}.json"
    fos_path.parent.mkdir(exist_ok=True)
    fos_payload["management_metrics_path"] = str(details_path)
    fos_path.write_text(json.dumps(fos_payload, ensure_ascii=False, indent=2))
    row["fos_path"] = str(fos_path)
    _add_workflow_columns(row, scene, env, fos_path,
                          path_correctness_v2=path_correctness_v2, pc2_tol=pc2_tol)
    row["cov(%)"] = row.get("coverage(%)", "")
    row["cov_v1(%)"] = row.get("coverage_v1(%)", "")
    return row


def export_management_tables(rows, out_root):
    """Additional long tables; the established summary_v2.csv remains intact."""
    import csv

    management = [r for r in rows if is_management_scenario(r.get("scenario", ""))]
    if not management:
        return
    present = {r["scenario"] for r in management}
    coverage = dict(registered_scenarios=len(management_scenario_ids()),
                    observed_scenarios=len(present), episode_rows=len(management),
                    missing_scenarios=sorted(management_scenario_ids() - present),
                    physical_replay_verified_rows=sum(r.get("physical_replay_verified") is True for r in management),
                    biological_metric_rows=sum(r.get("yield_loss(%)") not in (None, "") for r in management),
                    recovered_metric_rows=sum(r.get("recovered_yield_loss(%)") not in (None, "") for r in management),
                    workflow_metric_rows=sum(r.get("bfcl_success(%)") not in (None, "") for r in management))
    (out_root / "management_coverage.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2) + "\n")
    details, crops = [], []
    for row in management:
        path = row.get("management_metrics_path")
        if not path:
            continue
        payload = json.loads(Path(path).read_text())
        identity = {key: row.get(key) for key in (
            "cell", "scenario", "model_type_size", "llm_model", "detailed_briefing",
            "status", "cell_dir", "oracle_reference_path")}
        for item in payload["comparison"]["details"]:
            result = {**identity, **{k: v for k, v in item.items() if k not in ("biological", "recovered")}}
            for basis in ("biological", "recovered"):
                result.update({basis + "_" + k: v for k, v in item[basis].items()})
            details.append(result)
        agent = payload["agent"]
        oracle = json.loads(Path(payload["oracle_reference"]).read_text())
        for crop in sorted({r["crop_id"] for r in agent["records"] + oracle["records"]}):
            result = {**identity, "crop_id": crop}
            for basis in ("biological", "recovered"):
                a = _sum_known(r[basis + "_kg"] for r in agent["records"] if r["crop_id"] == crop)
                o = _sum_known(r[basis + "_kg"] for r in oracle["records"] if r["crop_id"] == crop)
                gap = relative_gap(a, o)
                result.update({basis + "_agent_kg": a, basis + "_oracle_kg": o,
                               basis + "_loss_pct": -gap["percent"] if gap["percent"] is not None else None,
                               basis + "_undefined_reason": gap["reason"]})
            crops.append(result)
    for name, data in (("management_yields_by_season.csv", details),
                       ("management_yields_by_crop.csv", crops)):
        keys = list(dict.fromkeys(k for r in data for k in r))
        with (out_root / name).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(data)
    definitions = {
        "schema": SCHEMA,
        "yield_loss(%)": {"paper_name": "Biological Yield Shortfall (BYS)",
                          "formula": "100 * (1 - agent_biological_kg / oracle_biological_kg)",
                          "basis": "storage-organ dry matter; sugarbeet uses root TWSO, not TWRT"},
        "recovered_yield_loss(%)": {"paper_name": "Recovered Yield Shortfall (RYS)",
                                    "formula": "100 * (1 - agent_recovered_kg / oracle_recovered_kg)",
                                    "basis": "actual lifted fresh roots or harvested market-moisture grain; not delivered/stored mass"},
        "relative_operating_cost_gap(%)": {"paper_name": "Relative Operating Cost Gap (ROCG)",
                                           "formula": "100 * (agent_cost - oracle_cost) / oracle_cost"},
        "relative_net_operating_return_gap(%)": {"paper_name": "Relative Net Operating Return Gap (RNRG)",
                                                 "formula": "100 * (agent_return - oracle_return) / oracle_return"},
        "financial_scope": "The scenario's consumed-input cost and net operating margin, including paid subsidies when enabled; not full net farm profit.",
        "undefined": "Empty CSV cells and null JSON values, with reasons; zero Oracle denominators are never replaced by one or epsilon.",
        "negative_oracle_return": "Signed formula is retained. Infer improvement from agent minus Oracle, not the sign of the ratio when Oracle is negative.",
        "aggregation": "Sum compatible mass fields before taking the ratio, as in primary FOS. Grain and roots retain distinct basis metadata. Crop/season tables and composition flag must accompany mixed-product interpretation.",
        "workflow_metrics": "Unchanged rebatch functions and tolerance: coverage/KTC v2 default, exact v1 separate, BFCL exact baseline. COV is an alias, not a new metric.",
        "farm_fos_scope": "Legacy soybean calibration is retained unchanged. Native sow/harvest_roots are not calibrated by these priors; legacy FARM values are not a validated native-crop management score.",
        "oracle_scope": "A validated reference workflow, not a proven global optimum. Negative shortfalls/gaps are retained.",
    }
    (out_root / "management_metric_definitions.json").write_text(
        json.dumps(definitions, ensure_ascii=False, indent=2) + "\n")


def recorded_workflow_env(bundle):
    """Workflow-only fallback. This never asserts that physical replay succeeded."""
    from scripts.rebatch_fos_from_traces import (
        _build_completed_event_from_workflow_step, _iter_fairy_tool_steps,
        _parse_workflow_timestamp, _synthetic_replay_app, _tool_name_parts,
    )
    from fairy.types import EventLog
    events = []
    for step in _iter_fairy_tool_steps(bundle["workflow"]):
        app, method = _tool_name_parts(step["tool_name"])
        events.append(_build_completed_event_from_workflow_step(
            step, _synthetic_replay_app(app), method, step.get("tool_args") or {},
            _parse_workflow_timestamp(step.get("time_before", step.get("time"))),
            step.get("content"), step.get("error_message") if step.get("op_type") == "TOOL_ERROR" else None))
    return SimpleNamespace(event_log=EventLog.from_list_view(events), dump_dir=None)


def workflow_metrics_after_replay_failure(bundle, row, out_root, rel, **options):
    """Retain trace metrics, while leaving unverifiable state metrics empty."""
    from scripts.rebatch_fos_from_traces import _instantiate_scenario_for_replay, _add_workflow_columns
    try:
        scene = _instantiate_scenario_for_replay(bundle["scenario_id"], bundle.get("start_time"),
                                               bundle.get("seed"), bundle.get("scenario_kwargs"),
                                               bundle.get("init_kwargs"))
        oracle, path = oracle_reference(scene, bundle, out_root / "management_oracles",
                                         extrapolate=options["extrapolate"], max_days=options["max_days"])
        scene._cached_oracle_workflow = oracle["workflow"]
        env = recorded_workflow_env(bundle)
        fos_path = out_root / rel / "fos" / f"fos_{scene.scenario_id}.json"
        fos_path.parent.mkdir(parents=True, exist_ok=True)
        fos_path.write_text(json.dumps({"physical_replay_verified": False,
                                        "replay_error": row.get("error")}))
        _add_workflow_columns(row, scene, env, fos_path,
                              path_correctness_v2=options["path_correctness_v2"],
                              pc2_tol=options["pc2_tol"])
        row.update(workflow_metrics_source="recorded_trace_only", physical_replay_verified=False,
                   oracle_reference_path=str(path), fos_path=str(fos_path))
        row["cov(%)"] = row.get("coverage(%)", "")
        row["cov_v1(%)"] = row.get("coverage_v1(%)", "")
    except Exception as exc:
        row["workflow_metrics_error"] = f"{type(exc).__name__}: {exc}"
    return row


def oracle_self_replay_matches(row):
    """Check unrounded comparisons; displayed 0.00 is insufficient evidence."""
    if row.get("status") != "ok" or not row.get("management_metrics_path"):
        return False
    comp = json.loads(Path(row["management_metrics_path"]).read_text())["comparison"]
    gaps = [comp["yields"][basis]["value"] for basis in ("biological", "recovered")]
    gaps.extend(comp["economics"][basis]["value"]
                for basis in ("production_cost", "net_operating_margin"))
    return all(value is not None and math.isfinite(value) and abs(value) < 1e-10 for value in gaps)


def verify_one_oracle(args):
    """Real Oracle execution -> saved trace -> strict state replay, without an LLM."""
    sid, out_root, max_days = args
    from scripts.rebatch_fos_from_traces import _instantiate_scenario_for_replay, replay_one_cell
    import time
    started = time.perf_counter()
    try:
        scene = _instantiate_scenario_for_replay(sid, None, 0, {"seed": 0, "detailed_briefing": True})
        bundle = dict(scenario_id=sid, start_time=scene.start_time, seed=0,
                      scenario_kwargs={"seed": 0, "detailed_briefing": True}, init_kwargs={})
        # The strict replay driver uses this same cache. Avoid executing a
        # second identical multi-year Oracle merely to evaluate its replay.
        baseline, _ = oracle_reference(scene, bundle, out_root / "replay" / "management_oracles",
                                        extrapolate=True, max_days=max_days)
        cell = out_root / "oracle_traces" / sid
        cell.mkdir(parents=True, exist_ok=True)
        (cell / f"{sid}.agent_workflow.json").write_text(
            json.dumps(baseline["executed_workflow"], ensure_ascii=False, indent=2))
        (cell / f"{sid}.run_report.json").write_text(json.dumps({
            "scenario_id": sid, "run_type": "oracle", "artifact_origin": "oracle_replay_selftest",
            "start_time": scene.start_time, "seed": 0, "scenario_kwargs": bundle["scenario_kwargs"],
            "init_kwargs": {}, "status": "completed", "a2a": {"enabled": False},
        }, ensure_ascii=False, indent=2))
        row = replay_one_cell(cell, out_root / "replay", True, max_days)
        row["oracle_self_replay_passed"] = oracle_self_replay_matches(row)
    except Exception as exc:
        row = dict(scenario=sid, status="oracle_verification_failed", error=f"{type(exc).__name__}: {exc}",
                   oracle_self_replay_passed=False)
    row["verification_seconds"] = round(time.perf_counter() - started, 3)
    path = out_root / "verification_rows" / f"{sid}.json"
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2))
    return row
