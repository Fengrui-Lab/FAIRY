"""Offline native management exploration and replay checks for winter wheat.

Runtime scenes execute their own literal workflows. This module is never called
by scene initialization and never substitutes a yield function for PCSE.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import traceback
import argparse
import json

from .apps.winter_wheat_app import WheatResources, WinterWheatApp, WinterWheatRuntime
from .engines.winter_wheat_wofost import InputBundle, WinterWheatBackend

DEFAULT_INPUTS = Path(__file__).parent / "data/winter_wheat_ncp_2019_2020"
SCENARIO_IDS = (
    "scenario_l3_winter_wheat_full_season",
    "scenario_l3_winter_wheat_water_limit",
    "scenario_l3_winter_wheat_nitrogen_limit",
    "scenario_l3_winter_wheat_high_water_price",
)


def run_candidate(parameters, resources=None, *, input_dir=None):
    """Execute a fresh native field; retain infeasibility and the actual tool calls."""
    parameters = dict(parameters)
    calls = []
    result = {"parameters": parameters, "feasible": False}
    try:
        bundle = InputBundle(input_dir or DEFAULT_INPUTS)
        runtime = WinterWheatRuntime(
            WinterWheatBackend(bundle), WheatResources(**(resources or {}))
        )
        app = WinterWheatApp(runtime)

        def call(method, **args):
            response = getattr(app, method)(**args)
            if not isinstance(response, dict) or response.get("error"):
                raise RuntimeError(f"{method}: {response}")
            calls.append(
                {"method": method, "arguments": args, "date": runtime.today.isoformat()}
            )
            return response

        call("get_field_info")
        call("get_accounts")
        call("observe")
        call("prepare_field", operation_id="prepare")
        sowing = parameters.get("sowing_date", "2019-10-10")
        n_dates = parameters.get("nitrogen_dates", [sowing, "2020-03-10", "2020-04-15"])
        water_dates = parameters.get(
            "water_dates", [sowing, "2020-03-10", "2020-04-15"]
        )
        nitrogen = parameters["nitrogen_kg_ha"]
        water = parameters["irrigation_mm"]
        if len(n_dates) != len(nitrogen) or len(water_dates) != len(water):
            raise ValueError("Each dose requires an explicit management date")
        actions = {sowing: [("sow", {"operation_id": "sow"})]}
        for index, (day, amount) in enumerate(zip(n_dates, nitrogen)):
            if amount:
                actions.setdefault(day, []).append(
                    (
                        "apply_nitrogen",
                        {"operation_id": f"nitrogen_{index}", "nitrogen_kg_ha": amount},
                    )
                )
        for index, (day, amount) in enumerate(zip(water_dates, water)):
            if amount:
                actions.setdefault(day, []).append(
                    ("irrigate", {"operation_id": f"water_{index}", "depth_mm": amount})
                )
        for day in (
            "2019-11-15",
            "2020-01-15",
            "2020-03-01",
            "2020-04-01",
            "2020-05-15",
            "2020-06-01",
            "2020-06-20",
        ):
            actions.setdefault(day, [])
        for day, events in sorted(actions.items()):
            delta = (date.fromisoformat(day) - runtime.today).days
            if delta < 0:
                raise ValueError("Candidate dates must remain ordered")
            if delta:
                call("wait", days=delta)
            call("observe")
            for method, args in events:
                call(method, **args)
        # This is a search-time stopping check. Exported workflows contain the
        # resulting explicit wait, and still require native DOM before harvest.
        extra = 0
        while runtime.backend.snapshot()["stage"] != "MATURE":
            if runtime.today >= bundle.season.deadline:
                raise ValueError("No native maturity within the scenario horizon")
            runtime.wait(1)
            extra += 1
        if extra:
            calls.append(
                {
                    "method": "wait",
                    "arguments": {"days": extra},
                    "date": runtime.today.isoformat(),
                }
            )
            call("observe")
        call("harvest", operation_id="harvest")
        call("dry_grain", operation_id="dry")
        call("store_grain", operation_id="store")
        call("get_accounts")
        outcome = runtime.outcome_summary()
        result.update(
            feasible=outcome["operational_success"],
            outcome=outcome,
            resources=asdict(runtime.resources),
            native_provenance=app.crop_backend_provenance(),
            tool_calls=calls,
        )
    except Exception as exc:
        result.update(
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(),
            tool_calls=calls,
        )
    return result


def verify(scenario_id, output_dir):
    """Execute and replay the real Engine, then resume a winter checkpoint."""
    from copy import deepcopy
    from fairy.controllers.engine import Engine
    from fairy.scenarios.registry import get_scenario_class
    from fairy.scenarios.workflow import Workflow

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cls = get_scenario_class(scenario_id)
    scene = cls()
    scene.setup()
    direct = Engine(None, scene)
    before = scene.world.get_state()
    workflow = direct.build_oracle_workflow(run_oracle=False)
    if scene.world.get_state() != before:
        raise AssertionError("Oracle capture mutated the native world")
    if len(workflow) != scene.ORACLE_REFERENCE["workflow_steps"]:
        raise AssertionError("Frozen workflow step count differs")
    path = output_dir / "oracle.json"
    workflow.save_workflow(str(path))
    direct.run_scenario_oracle(run_oracle=True)
    result = direct.evaluate()
    if not result.success:
        raise AssertionError(result.message)
    state = scene.world.get_state()
    replay_scene = cls()
    replay_scene.setup()
    replay = Engine(None, replay_scene)
    replay.replay_workflow(Workflow.load_workflow(str(path)))
    replay_result = replay.evaluate()
    if (
        not replay_result.success
        or replay_scene.world.get_state() != state
        or replay_result.metadata != result.metadata
    ):
        raise AssertionError(
            "Fresh-instance native state/accounts/evaluation replay differs"
        )

    # Resume after crossing New Year, and continue through leap day.
    cutoff = datetime(2020, 2, 1, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    prefix = Workflow()
    for name, step in direct.scenario.workflow.dag.items():
        if step.time_after is not None and step.time_after >= cutoff:
            break
        prefix.dag[name] = deepcopy(step)
    partial = cls()
    partial.setup()
    control = Engine(None, partial)
    control.replay_workflow(prefix)
    saved = json.loads(json.dumps(partial.world.get_state(), sort_keys=True))
    restored = cls()
    restored.setup()
    restored.world.load_state(saved)
    restored_engine = Engine(None, restored)
    if restored_engine.time_manager.time() != control.time_manager.time():
        raise AssertionError("Restored Engine lost its simulation clock")
    partial.world.wait(days=45)
    restored.world.wait(days=45)
    if partial.world.get_state() != restored.world.get_state():
        raise AssertionError("Winter checkpoint continuation through leap day differs")
    report = {
        "scenario_id": scenario_id,
        "success": True,
        "workflow_steps": len(workflow),
        "native_replay_exact": True,
        "winter_checkpoint_exact": True,
        "evaluation": direct.evaluation_report(),
    }
    (output_dir / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    (output_dir / "final_world.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    )
    return report


def _split_dose(total, pattern):
    a, b = [round(total * f, 3) for f in pattern[:2]]
    return [a, b, round(total - a - b, 3)]


def _search_worker(task):
    sid, index, parameters, resources = task
    row = run_candidate(parameters, resources)
    row.update(scenario_id=sid, candidate_index=index)
    return row


def low_input_controls(parameters):
    """Preserve every management date while reducing the actual dose vector."""
    from copy import deepcopy

    controls = {}
    for label, key, fraction in (
        ("zero_N", "nitrogen_kg_ha", 0.0),
        ("half_N", "nitrogen_kg_ha", 0.5),
        ("zero_water", "irrigation_mm", 0.0),
        ("half_water", "irrigation_mm", 0.5),
    ):
        row = deepcopy(parameters)
        row[key] = [amount * fraction for amount in row[key]]
        controls[label] = row
    return controls


def search(output_dir, workers=3):
    """Reproduce the finite, staged native search; retain every failing trial."""
    from concurrent.futures import ProcessPoolExecutor
    from itertools import product
    import hashlib
    import time
    from fairy.scenarios.registry import get_scenario_class

    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(
            "Choose a new search directory; prior evidence is immutable"
        )
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError("workers must be an integer from 1 through 4")
    output_dir.mkdir(parents=True)
    resources = {sid: asdict(get_scenario_class(sid).resources) for sid in SCENARIO_IDS}
    package = Path(__file__).parent
    paths = [
        Path(__file__),
        package / "apps/winter_wheat_app.py",
        package / "engines/winter_wheat_wofost.py",
        package / "engines/winter_wheat_inputs.py",
        package / "data/winter_wheat_prices_2025.json",
        *DEFAULT_INPUTS.glob("*.*"),
    ]
    manifest = {
        str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
    }
    (output_dir / "search_inputs.json").write_text(
        json.dumps({"source_sha256": manifest, "resources": resources}, indent=2) + "\n"
    )
    rows, seen = [], set()
    indices = {sid: 0 for sid in SCENARIO_IDS}
    selected = {}
    start = time.monotonic()
    for stage in (
        "coarse",
        "calendar",
        "quantities",
        "splits",
        "four_phase",
        "cross_scenario",
        "matched_controls",
    ):
        tasks = []
        for sid in SCENARIO_IDS:
            p = selected[sid]["parameters"] if sid in selected else None
            n_cap = (
                resources[sid]["fertilizer_stock_kg"]
                * resources[sid]["fertilizer_n_fraction"]
                / resources[sid]["area_ha"]
            )
            w_cap = resources[sid]["water_stock_m3"] / (resources[sid]["area_ha"] * 10)
            choices = []
            if stage == "coarse":
                ns = (
                    [0, 30, 60, 90, 110, n_cap]
                    if n_cap < 150
                    else [0, 60, 110, 150, 180, 210, n_cap]
                )
                ws = [w for w in (0, 40, 80, 120, 160, 200, 240) if w <= w_cap]
                for n, w, np, wp in product(
                    ns,
                    ws,
                    [(0.4, 0.4, 0.2), (0.6, 0.4, 0)],
                    [(0.25, 0.375, 0.375), (0, 0.5, 0.5)],
                ):
                    choices.append(
                        {
                            "nitrogen_kg_ha": _split_dose(n, np),
                            "irrigation_mm": _split_dose(w, wp),
                            "sowing_date": "2019-10-10",
                        }
                    )
            elif stage == "calendar":
                for sow, spring, late in product(
                    [
                        "2019-10-05",
                        "2019-10-10",
                        "2019-10-15",
                        "2019-10-20",
                        "2019-10-25",
                    ],
                    ["2020-03-01", "2020-03-10", "2020-03-20"],
                    ["2020-04-01", "2020-04-15", "2020-04-30"],
                ):
                    choices.append(
                        {
                            **p,
                            "sowing_date": sow,
                            "nitrogen_dates": [sow, spring, late],
                            "water_dates": [sow, spring, late],
                        }
                    )
            elif stage == "quantities":
                n, w = sum(p["nitrogen_kg_ha"]), sum(p["irrigation_mm"])
                ns = sorted(
                    {
                        round(max(0.0, min(n_cap, n + d)), 3)
                        for d in (-30, -15, 0, 15, 30)
                    }
                )
                ws = sorted(
                    {
                        round(max(0.0, min(w_cap, w + d)), 3)
                        for d in (-40, -20, 0, 20, 40)
                    }
                )
                np = [x / n for x in p["nitrogen_kg_ha"]] if n else [0.6, 0.4, 0]
                wp = [x / w for x in p["irrigation_mm"]] if w else [0, 0.5, 0.5]
                for n, w in product(ns, ws):
                    choices.append(
                        {
                            **p,
                            "nitrogen_kg_ha": _split_dose(n, np),
                            "irrigation_mm": _split_dose(w, wp),
                        }
                    )
            elif stage == "splits":
                n, w = sum(p["nitrogen_kg_ha"]), sum(p["irrigation_mm"])
                for nb, nl, wa, ws in product(
                    [0.2, 0.4, 0.6, 0.8],
                    [0.0, 0.2],
                    [0.0, 0.25, 0.4],
                    [0.25, 0.5, 0.75],
                ):
                    if nb + nl <= 1:
                        choices.append(
                            {
                                **p,
                                "nitrogen_kg_ha": _split_dose(n, [nb, 1 - nb - nl, nl]),
                                "irrigation_mm": _split_dose(
                                    w, [wa, (1 - wa) * ws, (1 - wa) * (1 - ws)]
                                ),
                            }
                        )
            elif stage == "four_phase":
                # Independent Agent validation found a productive fourth
                # spring input window. Keep that original run unchanged and
                # compare this explicit candidate family in fresh native fields.
                ns = [60, 90, 110, n_cap] if n_cap < 150 else [150, 180, 210, n_cap]
                ws = [w for w in (40, 80, 120, 160, 200, 240) if w <= w_cap]
                for sow, n, w in product(
                    ["2019-10-05", "2019-10-15", "2019-10-25"], ns, ws
                ):
                    doses = [round(n * fraction / 230, 3) for fraction in (60, 70, 60)]
                    doses.append(round(n - sum(doses), 3))
                    choices.append(
                        {
                            "sowing_date": sow,
                            "nitrogen_kg_ha": doses,
                            "nitrogen_dates": [
                                sow,
                                "2020-02-27",
                                "2020-04-02",
                                "2020-04-20",
                            ],
                            "irrigation_mm": [w / 4] * 4,
                            "water_dates": [
                                "2020-04-02",
                                "2020-04-20",
                                "2020-05-05",
                                "2020-05-20",
                            ],
                        }
                    )
            elif stage == "cross_scenario":
                choices.extend(selected[other]["parameters"] for other in SCENARIO_IDS)
            else:
                choices.extend(low_input_controls(p).values())
            for parameters in choices:
                key = (sid, json.dumps(parameters, sort_keys=True))
                # Keep explicit matched controls even if a coarse trial happened to match.
                if key in seen and stage != "matched_controls":
                    continue
                seen.add(key)
                indices[sid] += 1
                tasks.append((sid, indices[sid], parameters, resources[sid]))
        with (
            (output_dir / f"{stage}_candidates.jsonl").open("w") as stream,
            ProcessPoolExecutor(max_workers=workers) as pool,
        ):
            for row in pool.map(_search_worker, tasks):
                row["stage"] = stage
                rows.append(row)
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
        for sid in SCENARIO_IDS:
            feasible = [r for r in rows if r["scenario_id"] == sid and r["feasible"]]
            if not feasible:
                raise RuntimeError(f"No feasible native candidate for {sid}")
            selected[sid] = max(
                feasible,
                key=lambda r: (
                    r["outcome"]["net_operating_margin"],
                    -r["candidate_index"],
                ),
            )
        print(
            json.dumps(
                {
                    "stage": stage,
                    "executed": len(tasks),
                    "seconds": round(time.monotonic() - start),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    result = {
        sid: {
            "candidate_count": sum(r["scenario_id"] == sid for r in rows),
            "feasible_count": sum(
                r["scenario_id"] == sid and r["feasible"] for r in rows
            ),
            "selected": selected[sid],
        }
        for sid in SCENARIO_IDS
    }
    (output_dir / "selection.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    check = subs.add_parser("verify")
    check.add_argument("--scenario", choices=("all", *SCENARIO_IDS), default="all")
    check.add_argument("--output", type=Path, required=True)
    explore = subs.add_parser("search")
    explore.add_argument("--output", type=Path, required=True)
    explore.add_argument("--workers", type=int, default=3)
    candidate = subs.add_parser("run-candidate")
    candidate.add_argument("--scenario", choices=SCENARIO_IDS, required=True)
    candidate.add_argument("--parameters", type=Path, required=True)
    candidate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "verify":
        for sid in SCENARIO_IDS if args.scenario == "all" else (args.scenario,):
            report = verify(sid, args.output / sid)
            m = report["evaluation"]["validation"]["metadata"]
            print(
                json.dumps(
                    {
                        "scenario_id": sid,
                        "success": True,
                        "workflow_steps": report["workflow_steps"],
                        "stored_grain_kg": m["stored_grain_kg"],
                        "production_cost": m["production_cost"],
                        "net_operating_margin": m["net_operating_margin"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    elif args.command == "search":
        search(args.output, args.workers)
    else:
        from fairy.scenarios.registry import get_scenario_class

        cls = get_scenario_class(args.scenario)
        params = json.loads(args.parameters.read_text())
        row = run_candidate(params, asdict(cls.resources))
        if args.output.exists():
            raise FileExistsError(args.output)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n")
        if not row["feasible"]:
            raise SystemExit(row["error"])


if __name__ == "__main__":
    main()
