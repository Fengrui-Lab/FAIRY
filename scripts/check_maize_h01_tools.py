#!/usr/bin/env python3
"""Write one auditable local H01 public-tool check, never a full-season run.

The mature specimen is the artificial fixture from test_h01_header_tools.py.
This command does not execute the earlier native recovery probe or any oracle.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys
import traceback


ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def fixture_module():
    path = ROOT / "tests/test_h01_header_tools.py"
    spec = importlib.util.spec_from_file_location("h01_local_check_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def physical_snapshot(farm, weather):
    return {
        "last_physics_sim_time": farm.physics.last_physics_sim_time,
        "native_last_day": str(farm.physics.crop_backend.last_day),
        "soil": {str(rid): asdict(state) for rid, state in farm.physics.soil.states.items()},
        "weather": weather.get_current_weather_snapshot(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path,
                        help="New evidence directory; an existing path is refused")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "identity": "h01-public-tool-local-check-v1",
        "scope": "local public AppTools, artificial mature specimen; not WOFOST full-season output",
        "full_season_runs": 0, "llm_requests": 0, "original_probe_reruns": 0,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "pcse_version": importlib.metadata.version("pcse"),
        "checks": [], "cases": {},
    }
    records = []

    def call(case, app, name, **arguments):
        tool = next(t for t in app.get_tools() if t.name == name)
        started = float(app.time_manager.time())
        payload = tool(**arguments)
        row = dict(case=case, tool=f"{app.name}__{name}", arguments=arguments,
                   started_at=started, completed_at=float(app.time_manager.time()),
                   result=deepcopy(payload))
        records.append(row)
        with (output / "tool_log.jsonl").open("a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        if isinstance(payload, dict) and (payload.get("error") or payload.get("warning")):
            raise AssertionError(f"Unexpected tool refusal/warning in {case}: {payload}")
        return payload

    def check(label, condition):
        result["checks"].append({"name": label, "passed": bool(condition)})
        if not condition:
            raise AssertionError(label)

    try:
        fixtures = fixture_module()
        farm, weather, tractor, clock = fixtures.tools_fixture(hour=23, minute=55)
        control, control_weather, control_tractor, control_clock = fixtures.tools_fixture(hour=23, minute=55)
        before = physical_snapshot(farm, weather)
        receipt = call("inspection_midnight", tractor, "inspect_header")
        control_tractor._bind_farm_context()
        control.advance_physics_time()
        control_tractor._farm_context.advance_time(600)
        control.advance_physics_time()
        after = physical_snapshot(farm, weather)
        control_after = physical_snapshot(control, control_weather)
        check("inspection_consumes_exactly_600_seconds", receipt["duration_seconds"] == 600
              and receipt["inspection_completed_at"] - receipt["started_at"] == 600)
        check("inspection_matches_normal_wait_across_midnight", after == control_after)
        check("inspection_is_a_finding_not_warning_or_repair", receipt["condition"] == "maintenance_required"
              and not {"warning", "error", "q", "q_pass"}.intersection(receipt))
        check("inspection_does_not_harvest", not tractor.harvest_batches
              and not farm.physics.yield_recovery.states[0].harvested)
        result["cases"]["inspection_midnight"] = dict(
            specimen="unplanted native maize farm; one real midnight crossing",
            before=before, after=after, normal_wait_control=control_after,
            maintenance_events=tractor.maintenance_events,
        )
        write_json(output / "new_public_tools.json", [t.to_open_ai() for t in tractor.get_tools()
                   if t.name in {"inspect_header", "service_header"}])

        farm, weather, tractor, clock = fixtures.tools_fixture()
        before_inventory = deepcopy(farm._inventory.to_dict())
        first = call("direct_service_idempotent", tractor, "service_header")
        second = call("direct_service_idempotent", tractor, "service_header")
        state = tractor.get_state()["h01_header"]
        check("service_without_prior_inspection_is_legal", first["status"] == "service_completed"
              and state["last_inspection_at"] is None)
        check("service_consumes_exactly_3600_seconds", first["duration_seconds"] == 3600
              and first["service_completed_at"] - first["started_at"] == 3600)
        check("repeat_service_zero_duration_no_extra_resources", second["status"] == "already_serviceable"
              and second["duration_seconds"] == 0
              and second["service_completed_at"] == second["started_at"]
              and farm._inventory.to_dict() == before_inventory)
        result["cases"]["direct_service_idempotent"] = dict(
            specimen="unplanted native maize farm", header_state=state,
            inventory_before=before_inventory, inventory_after=farm._inventory.to_dict(),
        )

        farm, weather, tractor, clock = fixtures.tools_fixture(ridges=2)
        fixtures.mature_fixture(farm)
        recovery_initial = {str(rid): asdict(state) for rid, state in farm.physics.yield_recovery.states.items()}
        native_actions = []
        original_queue = farm.physics.queue_harvest
        def capture_queue(ridge_id, action):
            native_actions.append(dict(ridge=ridge_id, submitted_at=float(clock.time()), **asdict(action)))
            return original_queue(ridge_id, action)
        farm.physics.queue_harvest = capture_queue
        first_harvest = call("native_recovery_chain", tractor, "harvest", start_ridge=0, end_ridge=0)
        first_state = deepcopy(asdict(farm.physics.yield_recovery.states[0]))
        first_batch = tractor.harvest_batches[0]
        call("native_recovery_chain", tractor, "service_header")
        check("repair_does_not_recompute_existing_recovery", first_state == asdict(farm.physics.yield_recovery.states[0])
              and first_batch == tractor.harvest_batches[0])
        second_harvest = call("native_recovery_chain", tractor, "harvest", start_ridge=1, end_ridge=1)
        batches = tractor.harvest_batches
        action_records = [asdict(a) for a in farm.physics.action_log if a.action_type == "harvest"]
        check("actual_native_actions_use_frozen_qualities", [a["machine_quality"] for a in native_actions] == [.85, .95])
        check("native_action_record_batch_quality_agree", all(
            b["q_pass"] == a["machine_quality"] == r["parameters"]["machine_quality"] == b["action_machine_quality"]
            and b["operation_id"] == r["action_id"]
            for b, a, r in zip(batches, native_actions, action_records)))
        check("native_recovery_ledger_closes", all(
            abs(row["dm_balance_residual_kg"]) < 1e-10 and row["loss_components"]["matches_native"]
            for b in batches for row in b["per_ridge"]))
        check("both_mature_specimens_keep_identical_biological_mass", all(
            row["biological_yield_g_m2"] == 800. for b in batches for row in b["per_ridge"]))
        bin_before_unload = tractor._grain_bin_kg
        unload = call("native_recovery_chain", tractor, "unload_grain")
        dry = call("native_recovery_chain", farm, "dry_grain", target_moisture_pct=14.)
        stored = call("native_recovery_chain", farm, "store_grain")
        check("actual_standard_grain_reaches_store_once", abs(
            farm._inventory.warehouse_grain_kg - bin_before_unload) < .011
            and farm._inventory.harvest_grain_kg == tractor._grain_bin_kg == 0)
        result["cases"]["native_recovery_chain"] = dict(
            specimen="two artificial mature ridges, 800 g DM/m2 each; not a WOFOST yield prediction",
            initial_recovery_states=recovery_initial,
            native_harvest_actions=native_actions, actual_farm_action_records=action_records,
            harvest_batches=batches, maintenance_events=tractor.maintenance_events,
            bin_before_unload_kg=bin_before_unload, final_inventory=farm._inventory.to_dict(),
            final_bin_kg=tractor._grain_bin_kg,
        )
        result["status"] = "passed"
    except Exception:
        result["status"] = "failed"
        result["failure_traceback"] = traceback.format_exc()
    finally:
        result["public_tool_calls"] = len(records)
        result["source_sha256"] = {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [Path(__file__).resolve(), ROOT / "tests/test_h01_header_tools.py",
                         ROOT / "fairy/scenarios/maize/header_maintenance.py",
                         ROOT / "fairy/apps/farm_world/tractor_operations.py",
                         ROOT / "fairy/physics/yield_recovery_engine.py"]
        }
        # Recovery fixtures contain dates; make their display conversion explicit.
        result = json.loads(json.dumps(result, ensure_ascii=False, default=str, allow_nan=False))
        write_json(output / "result.json", result)
    print(json.dumps({"status": result["status"], "output": str(output),
                      "checks": len(result["checks"]), "public_tool_calls": len(records)}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
