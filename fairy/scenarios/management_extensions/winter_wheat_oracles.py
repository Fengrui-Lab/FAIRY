"""Offline execution/search for block-managed wheat; scenes contain literal policies."""

from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
import argparse
import json
import traceback
from fairy.scenarios.registry import get_scenario_class
from .apps.winter_wheat_accounts_app import SEED

SCENARIO_IDS = tuple(
    "scenario_l3_winter_wheat_" + s
    for s in ("full_season", "water_limit", "nitrogen_limit", "high_water_price")
)
DEFAULT_INPUTS = Path(__file__).parent / "data/winter_wheat_ncp_2019_2020"

DEFAULT_PLANS = {
    "full_season": dict(
        sowing_date="2019-10-15",
        nitrogen_kg_ha=[60, 70, 60, 40],
        nitrogen_dates=["2019-10-15", "2020-02-27", "2020-04-02", "2020-04-20"],
        irrigation_mm=[50, 50, 50, 50],
        water_dates=["2020-04-02", "2020-04-20", "2020-05-05", "2020-05-20"],
    ),
    "water_limit": dict(
        sowing_date="2019-10-25",
        nitrogen_kg_ha=[33, 132],
        nitrogen_dates=["2019-10-25", "2020-03-10"],
        irrigation_mm=[30, 90],
        water_dates=["2020-03-10", "2020-04-30"],
    ),
    "nitrogen_limit": dict(
        sowing_date="2019-10-25",
        nitrogen_kg_ha=[31.2, 36.4, 31.2, 20.8],
        nitrogen_dates=["2019-10-25", "2020-02-27", "2020-04-02", "2020-04-20"],
        irrigation_mm=[50, 50, 50, 50],
        water_dates=["2020-04-02", "2020-04-20", "2020-05-05", "2020-05-20"],
    ),
}
DEFAULT_PLANS["high_water_price"] = deepcopy(DEFAULT_PLANS["full_season"])


def run_candidate(
    parameters, resources=None, *, scenario_id=SCENARIO_IDS[0], input_dir=None
):
    """Use actual shared devices, including refusals, costs and machine capacities."""
    from dataclasses import replace

    calls = []
    row = dict(parameters=deepcopy(parameters), scenario_id=scenario_id, feasible=False)
    try:
        scene = get_scenario_class(scenario_id)(calibrating=True, input_dir=input_dir)
        if resources:
            scene.resources = replace(scene.resources, **resources)
        scene.setup()
        f = scene.farm

        def call(app, method, **args):
            if (
                app == "tractor"
                and method in {"fertilize", "sow", "harvest_blocks"}
                and scene.tractor._fuel_tank_l < 30
                and scene.warehouse.stock.fuel_liters > 0
            ):
                call(
                    "tractor",
                    "refuel",
                    liters=min(50.0, scene.warehouse.stock.fuel_liters),
                )
            response = getattr(getattr(scene, app), method)(**args)
            calls.append(
                dict(
                    app=app,
                    method=method,
                    arguments=args,
                    response=response,
                    date=f._sim_date,
                )
            )
            if not isinstance(response, dict) or response.get("error"):
                raise RuntimeError(f"{app}.{method}: {response}")
            return response

        def attach(implement):
            if scene.tractor._attached_implement == implement:
                return
            if scene.tractor._attached_implement is not None:
                call("tractor", "detach_implement")
            call("tractor", "attach_implement", implement=implement)

        def goto(day):
            dt = datetime.combine(
                date.fromisoformat(day),
                datetime.min.time(),
                tzinfo=scene.simulation_timezone,
            ).replace(hour=7)
            delta = dt.timestamp() - scene.farm_environment.time_manager.time()
            if delta > 0:
                call("system", "advance_time", seconds=delta)

        def observe():
            call("sensor", "read_root_zone_sensors")
            call("sensor", "read_canopy_sensors")
            call("farm", "inspect_blocks", start_block=0, end_block=f.num_ridges - 1)

        call("farm", "get_field_info")
        call("accounts", "get_accounts")
        call("tractor", "get_status")
        attach("grader")
        call("tractor", "prepare_field")
        sowing = parameters["sowing_date"]
        nd = parameters["nitrogen_dates"]
        wd = parameters["water_dates"]
        ns = parameters["nitrogen_kg_ha"]
        ws = parameters["irrigation_mm"]
        if len(nd) != len(ns) or len(wd) != len(ws):
            raise ValueError("Each dose requires an explicit date")
        actions = {sowing: [("sow", 0)]}
        for d, n in zip(nd, ns):
            if n:
                actions.setdefault(d, []).append(("N", n))
        for d, w in zip(wd, ws):
            if w:
                actions.setdefault(d, []).append(("water", w))
        for d in (
            "2019-11-15",
            "2020-01-15",
            "2020-03-01",
            "2020-05-15",
            "2020-06-01",
            "2020-06-20",
        ):
            actions.setdefault(d, [])
        for d, events in sorted(actions.items()):
            goto(d)
            observe()
            for kind, amount in events:
                if kind == "sow":
                    attach("seeder")
                    for i in range(f.num_ridges):
                        call(
                            "tractor",
                            "load_seeds",
                            seed_type=SEED,
                            count=scene.resources.seeds_per_block,
                        )
                        call("tractor", "sow", start_block=i, end_block=i, depth_cm=3.0)
                elif kind == "N":
                    total = (
                        amount
                        * scene.resources.area_ha
                        / scene.resources.fertilizer_n_fraction
                    )
                    call("tractor", "load_fertilizer", kg=total)
                    per = total / f.num_ridges
                    for start in range(0, f.num_ridges, 10):
                        call(
                            "tractor",
                            "fertilize",
                            start_block=start,
                            end_block=min(start + 9, f.num_ridges - 1),
                            kg_per_block=per,
                        )
                else:
                    call(
                        "irrigation",
                        "irrigate",
                        start_block=0,
                        end_block=f.num_ridges - 1,
                        depth_mm=amount,
                    )
        while (
            any(b.maturity is None for b in f.backends)
            or scene.weather.rainfall_mm > 0
            or f.get_avg_vwc() > 0.35
        ):
            day = f.simulation_date() + timedelta(days=1)
            if day > f.bundle.season.deadline:
                raise ValueError("No legal harvest window before deadline")
            goto(day.isoformat())
        observe()
        attach("harvester")
        for start in range(0, f.num_ridges, 2):
            if scene.tractor._fuel_tank_l < 10:
                call(
                    "tractor",
                    "refuel",
                    liters=min(50.0, scene.warehouse.stock.fuel_liters),
                )
            call(
                "tractor",
                "harvest_blocks",
                start_block=start,
                end_block=min(start + 1, f.num_ridges - 1),
            )
            batch = f"wheat_{start}"
            call("tractor", "unload_grain", batch_id=batch)
            call(
                "warehouse",
                "dry_grain",
                batch_id=batch,
                target_moisture_pct=scene.resources.storage_moisture_pct,
            )
            call("warehouse", "store_grain", batch_id=batch)
        call("accounts", "get_accounts")
        result = scene.validate()
        row.update(
            feasible=result.success,
            outcome=result.metadata,
            message=result.message,
            input_fingerprint=scene.input_fingerprint(),
            tool_calls=calls,
        )
    except Exception as exc:
        row.update(
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(),
            tool_calls=calls,
        )
    return row


def low_input_controls(plan):
    result = {}
    for name, key, factor in (
        ("zero_N", "nitrogen_kg_ha", 0.0),
        ("half_N", "nitrogen_kg_ha", 0.5),
        ("zero_water", "irrigation_mm", 0.0),
        ("half_water", "irrigation_mm", 0.5),
    ):
        row = deepcopy(plan)
        row[key] = [v * factor for v in row[key]]
        result[name] = row
    return result


def verify(scenario_id, output_dir):
    """Run the stock Engine and JSON workflow replay against a fresh physical farm."""
    from fairy.controllers.engine import Engine
    from fairy.scenarios.workflow import Workflow

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    scene = get_scenario_class(scenario_id)()
    scene.setup()
    direct = Engine(None, scene)
    before = scene.farm.get_state()
    plan = direct.build_oracle_workflow(run_oracle=False)
    assert scene.farm.get_state() == before, "Capturing workflow changed physical state"
    plan.save_workflow(str(out / "oracle.json"))
    direct.run_scenario_oracle(run_oracle=True)
    result = direct.evaluate()
    if not result.success:
        raise AssertionError(result.message)
    other = get_scenario_class(scenario_id)()
    other.setup()
    replay = Engine(None, other)
    replay.replay_workflow(Workflow.load_workflow(str(out / "oracle.json")))
    second = replay.evaluate()
    if (
        not second.success
        or second.metadata != result.metadata
        or scene.farm.get_state() != other.farm.get_state()
        or scene.warehouse.get_state() != other.warehouse.get_state()
    ):
        raise AssertionError(
            "Fresh replay changed native blocks, inventory, grain or economics"
        )
    report = dict(
        scenario_id=scenario_id,
        success=True,
        workflow_steps=len(plan),
        native_replay_exact=True,
        evaluation=direct.evaluation_report(),
    )
    (out / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    return report


def _search_job(item):
    sid, label, p = item
    row = run_candidate(p, scenario_id=sid)
    row["candidate_id"] = label
    return row


def search(output_dir, workers=3):
    """Execute the 11 declared plans per configuration on fresh native farms."""
    from concurrent.futures import ProcessPoolExecutor

    if type(workers) is not int or workers < 1:
        raise ValueError("workers must be positive")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)

    jobs = []
    for sid in SCENARIO_IDS:
        suffix = sid.removeprefix("scenario_l3_winter_wheat_")
        base = deepcopy(DEFAULT_PLANS[suffix])
        plans = {"baseline": base, **low_input_controls(base)}
        for sow in ("2019-10-05", "2019-10-15", "2019-10-25"):
            p = deepcopy(base)
            p["sowing_date"] = sow
            p["nitrogen_dates"] = [
                sow if d == base["sowing_date"] else d for d in p["nitrogen_dates"]
            ]
            plans["sow_" + sow] = p
        for scale in (0.8, 1.2):
            p = deepcopy(base)
            p["irrigation_mm"] = [round(x * scale, 5) for x in p["irrigation_mm"]]
            plans["water_" + str(scale)] = p
        p = deepcopy(base)
        p["nitrogen_kg_ha"] = [round(x * 0.8, 5) for x in p["nitrogen_kg_ha"]]
        plans["N_80pct"] = p
        p = deepcopy(base)
        total_n = sum(p["nitrogen_kg_ha"])
        total_w = sum(p["irrigation_mm"])
        p["nitrogen_kg_ha"] = [total_n * 0.2, total_n * 0.5, total_n * 0.3]
        p["nitrogen_dates"] = [p["sowing_date"], "2020-03-10", "2020-04-15"]
        p["irrigation_mm"] = [total_w / 3] * 3
        p["water_dates"] = ["2020-03-10", "2020-04-15", "2020-05-10"]
        plans["three_phase"] = p
        unique = {}
        for label, p in plans.items():
            unique.setdefault(json.dumps(p, sort_keys=True), (sid, label, p))
        jobs.extend(unique.values())
    (root / "candidates.json").write_text(json.dumps(jobs, indent=2))
    all_rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for row in ex.map(_search_job, jobs):
            all_rows.append(row)
            with (root / "trials.jsonl").open("a") as h:
                h.write(json.dumps(row) + "\n")
            print(
                row["scenario_id"],
                row["candidate_id"],
                row["feasible"],
                row.get("error", row.get("outcome", {}).get("net_operating_margin")),
                flush=True,
            )
    selected = {}
    for sid in SCENARIO_IDS:
        rows = [r for r in all_rows if r["scenario_id"] == sid]
        good = [r for r in rows if r["feasible"]]
        if not good:
            raise RuntimeError(sid + " has no feasible workflow")
        best = max(good, key=lambda r: r["outcome"]["net_operating_margin"])
        selected[sid] = {
            "candidate_count": len(rows),
            "feasible_count": len(good),
            "selected": best,
        }
    (root / "selection.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2) + "\n"
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("verify", "run-candidate", "search"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--scenario", choices=SCENARIO_IDS, default=SCENARIO_IDS[0])
    p.add_argument("--parameters", type=Path)
    p.add_argument("--workers", type=int, default=3)
    a = p.parse_args()
    if a.command == "search":
        search(a.output, a.workers)
    elif a.command == "verify":
        for sid in SCENARIO_IDS:
            report = verify(sid, a.output / sid)
            print(sid, report["workflow_steps"], "passed", flush=True)
    else:
        plan = (
            json.loads(a.parameters.read_text())
            if a.parameters
            else DEFAULT_PLANS[a.scenario.removeprefix("scenario_l3_winter_wheat_")]
        )
        row = run_candidate(plan, scenario_id=a.scenario)
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n")
        print(row.get("feasible"), row.get("error", row.get("message")), flush=True)


if __name__ == "__main__":
    main()
