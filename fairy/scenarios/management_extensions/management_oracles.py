"""One offline entry point for management candidate search, export and replay.

Search takes explicit JSON candidate parameters, so changing search resolution or
adding a scene never requires another calibration program. Runtime scenes only
load frozen actions and matching references; they do not invoke this optimizer.
"""

import argparse
import hashlib
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.workflow import Workflow


def stable(value):
    if isinstance(value, dict):
        return {
            k: stable(v) for k, v in value.items() if k not in {"action_id", "op_id"}
        }
    if isinstance(value, (list, tuple)):
        return [stable(v) for v in value]
    if isinstance(value, float):
        return round(value, 9)
    return value


def execute_candidate(scene_class, parameters, *, recorded_tools=None):
    scene = scene_class(calibrating=True)
    scene.setup()
    engine = Engine(None, scene)
    trace = []

    def call(app, method, **args):
        step = {
            "tool_name": app.name + "__" + method,
            "tool_args": args,
            "time_before": engine.time_manager.time(),
        }
        trace.append(step)
        try:
            result = getattr(app, method)(**args)
        except Exception as exc:
            step.update(error=repr(exc), time_after=engine.time_manager.time())
            raise
        step.update(content=result, time_after=engine.time_manager.time())
        if isinstance(result, dict) and (
            result.get("error")
            or result.get("status") in {"failed", "partial", "irrigation_pending"}
        ):
            raise RuntimeError(f"{app.name}.{method}: {result}")
        return result

    row = {
        "candidate": parameters,
        "input_fingerprint": scene.input_fingerprint(),
        "trace": trace,
    }
    try:
        if recorded_tools is None:
            scene.oracle_policy(scene, engine, call, **parameters)
        else:
            # Revalue a historical *management candidate* by actually executing
            # its public tools in a fresh USD scene. Never reuse old tool results.
            apps = {app.name: app for app in scene.apps}
            for step in recorded_tools:
                app_name, method = step["tool_name"].split("__", 1)
                call(apps[app_name], method, **step["tool_args"])
        validation = scene.validate()
        row.update(
            validation.metadata,
            feasible=validation.success,
            error=None if validation.success else validation.message,
        )
    except Exception as exc:  # noqa: BLE001 - retain every failed candidate as evidence
        row.update(feasible=False, error=repr(exc))
    return row


def _grain_value(row):
    """Read either existing account schema without changing scene receipts."""
    return (
        row["stored_grain_value"] if "stored_grain_value" in row else row["grain_value"]
    )


def choose(rows):
    feasible = [r for r in rows if r["feasible"]]
    if not feasible:
        raise RuntimeError("No feasible candidate; do not publish an Oracle")
    selected = max(
        feasible,
        key=lambda r: (
            r["net_operating_margin"],
            -r["water_m3"],
            -r["fertilizer_product_kg"],
        ),
    )
    pareto = [
        r
        for r in feasible
        if not any(
            _grain_value(q) >= _grain_value(r)
            and q["production_cost"] <= r["production_cost"]
            and q["water_m3"] <= r["water_m3"]
            and (
                _grain_value(q) > _grain_value(r)
                or q["production_cost"] < r["production_cost"]
                or q["water_m3"] < r["water_m3"]
            )
            for q in feasible
        )
    ]

    def clean(row):
        return {k: v for k, v in row.items() if k != "trace"}

    rejection_counts = Counter(
        (
            "shared_water_supply_exceeded"
            if "Shared seasonal water supply exceeded" in str(row.get("error"))
            else str(row.get("error") or "unspecified_infeasibility")
        )
        for row in rows
        if not row["feasible"]
    )
    return {
        "rejection_counts": dict(rejection_counts),
        "scope": "Best feasible candidate in the supplied finite search; no claim of global optimum.",
        "candidate_count": len(rows),
        "feasible_count": len(feasible),
        "selected": clean(selected),
        "cropwise_max_kg_not_jointly_attainable": {
            crop: max(r["stored_kg_by_crop"][crop] for r in feasible)
            for crop in feasible[0]["stored_kg_by_crop"]
        },
        "maximum_joint_grain_value": clean(
            max(feasible, key=lambda r: _grain_value(r))
        ),
        "pareto": list(map(clean, pareto)),
    }, selected


def select_candidates(rows, metric):
    if metric == "net_operating_margin":
        return choose(rows)
    feasible = [r for r in rows if r["feasible"]]
    if not feasible:
        raise RuntimeError("No feasible candidate; do not publish an Oracle")
    selected = max(feasible, key=lambda r: r[metric])
    return {
        "scope": "Best feasible candidate in the supplied finite search; no claim of global optimum.",
        "candidate_count": len(rows),
        "feasible_count": len(feasible),
        "rejection_counts": dict(
            Counter(str(r.get("error")) for r in rows if not r["feasible"])
        ),
        "selected": {k: v for k, v in selected.items() if k != "trace"},
    }, selected


def source_manifest(scene):
    root = Path(__file__).parents[3]
    paths = list(Path(__file__).parent.rglob("*.py"))
    paths += list((Path(__file__).parent / "data").rglob("*.json"))
    paths += [
        root / name
        for name in (
            "fairy/controllers/engine.py",
            "fairy/physics/wofost_backend.py",
            "fairy/physics/weather_engine.py",
            "fairy/apps/farm_world/tractor_operations.py",
        )
    ]
    return {
        "input_signature": scene.input_signature(),
        "input_fingerprint": scene.input_fingerprint(),
        "source_sha256": {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths))
        },
    }


def export_candidate(scene, reference, selected, output):
    if (
        not selected["feasible"]
        or selected["input_fingerprint"] != scene.input_fingerprint()
    ):
        raise ValueError(
            "Only a feasible candidate with matching inputs can be published"
        )
    lines = [
        '"""Frozen public-tool Oracle from a recorded finite candidate search."""',
        "from fairy.types import EventRegisterer",
        "from fairy.scenarios.management_extensions.common import capture_step, finish_capture",
        "",
        "def build_events_flow(self):",
        "    if not self.prepare_oracle_capture():",
        "        return []",
        "    apps = {app.name: app for app in self.apps}",
        "    with EventRegisterer.capture_mode() as events:",
        "        previous = None",
    ]
    for i, step in enumerate(selected["trace"]):
        app, method = step["tool_name"].split("__", 1)
        # A scenario briefing must remain live so detail=false and explicit
        # user overrides do not inherit a captured detail=true task string.
        briefing = (
            i == 0 and app == "AgentUserInterface" and method == "send_message_to_agent"
        )
        args = ", ".join(
            f"{k}=self.scenario_input" if briefing and k == "content" else f"{k}={v!r}"
            for k, v in step["tool_args"].items()
        )
        explanation = (
            "传递当前任务说明。"
            if briefing
            else f"执行公开工具 {step['tool_name']}；参数 {step['tool_args']}"
        )
        lines.append(
            f"        previous = capture_step(previous, apps[{app!r}].{method}({args}), 'step{i:04d}', {explanation!r})"
        )
    lines.append("    return finish_capture(self, events)")
    reference.update(
        input_signature=scene.input_signature(),
        input_fingerprint=scene.input_fingerprint(),
        workflow_steps=len(selected["trace"]),
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "oracle_method_draft.py").write_text("\n".join(lines) + "\n")
    (output / "calibration_reference.json").write_text(
        json.dumps(reference, ensure_ascii=False, indent=2, default=str) + "\n"
    )


def verify(scene_class, output):
    scene = scene_class()
    scene.setup()
    engine = Engine(None, scene)
    before = deepcopy(stable(scene.verification_state()))
    workflow = engine.build_oracle_workflow(run_oracle=False)
    assert before == stable(scene.verification_state()), "Oracle capture executed tools"
    path = output / "oracle_workflow.json"
    workflow.save_workflow(str(path))
    engine.run_scenario_oracle(run_oracle=True)
    result = scene.validate()
    assert result.success, result.message
    direct = stable(scene.verification_state())
    replay = scene_class()
    replay.setup()
    fresh = Engine(None, replay)
    replayed = fresh.replay_workflow(Workflow.load_workflow(str(path)))
    replayed.save_workflow(str(output / "replayed_workflow.json"))
    checked = replay.validate()
    assert checked.success, checked.message
    assert direct == stable(replay.verification_state()), "Fresh replay state differs"
    ref = scene.get_oracle_reference()["selected"]
    expected = ref.get(scene.objective_metric, ref.get("stored_grain_kg"))
    assert (
        abs(result.metadata[scene.objective_metric] - expected) < 1e-7
    ), "Frozen reference outcome changed"
    report = {
        "success": True,
        "capture_pure": True,
        "fresh_replay_exact": True,
        "comparison_normalization": {
            "ignored_keys": ["action_id", "op_id"],
            "float_decimal_places": 9,
        },
        "workflow_steps": len(workflow),
        "evaluation": result.to_dict(),
        "replay_evaluation": checked.to_dict(),
    }
    (output / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str)
    )
    (output / "source_manifest.json").write_text(
        json.dumps(source_manifest(scene), ensure_ascii=False, indent=2, default=str)
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("search", "export", "verify"))
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--candidates",
        type=Path,
        help="JSON list of keyword arguments for the scene's public-tool policy",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cls = get_scenario_class(args.scenario)
    if args.action == "verify":
        report = verify(cls, args.output)
        print(
            json.dumps(
                {
                    "success": report["success"],
                    "workflow_steps": report["workflow_steps"],
                }
            )
        )
        return
    scene = cls(calibrating=True)
    scene.setup()
    manifest = source_manifest(scene)
    if args.action == "search":
        if args.candidates is None:
            parser.error("search requires --candidates")
        candidates = json.loads(args.candidates.read_text())
        if (
            not isinstance(candidates, list)
            or not candidates
            or not all(isinstance(c, dict) for c in candidates)
        ):
            raise ValueError(
                "Candidates must be a nonempty JSON list of parameter objects"
            )
        if (args.output / "input_manifest.json").exists():
            raise ValueError("Use a fresh output directory; do not mix searches")
        (args.output / "input_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str)
        )
        rows = []
        for i, parameters in enumerate(candidates):
            row = execute_candidate(cls, parameters)
            rows.append(row)
            (args.output / f"candidate_{i:04d}.json").write_text(
                json.dumps(row, ensure_ascii=False, indent=2, default=str)
            )
            print(
                i,
                row["feasible"],
                row.get(scene.objective_metric),
                row.get("error"),
                flush=True,
            )
    else:
        recorded = json.loads((args.output / "input_manifest.json").read_text())
        if (
            recorded["input_fingerprint"] != scene.input_fingerprint()
            or recorded["source_sha256"] != manifest["source_sha256"]
        ):
            raise ValueError(
                "Search inputs or sources changed; rerun search before export"
            )
        rows = [
            json.loads(p.read_text())
            for p in sorted(args.output.glob("candidate_*.json"))
        ]
    reference, selected = select_candidates(rows, scene.objective_metric)
    reference["candidates"] = [
        {k: v for k, v in row.items() if k != "trace"} for row in rows
    ]
    (args.output / "summary.json").write_text(
        json.dumps(reference, ensure_ascii=False, indent=2, default=str)
    )
    if args.action == "export":
        export_candidate(scene, reference, selected, args.output)


if __name__ == "__main__":
    main()
