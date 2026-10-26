"""Generate cached oracle biological-yield baselines for FOS attribution.

Rice IDs (or --scenarios rice) use the area-aware rice_outcome_v2 schema and
native WOFOST 8.1 maturity. They are evaluated by fairy.scenarios.rice.evaluation;
the ridge/R8 FOS description below applies only to the existing soybean tasks.

For each requested scenario this script:
  1. Looks up the scenario class in the registry.
  2. Runs it under oracle mode (queue-based loop, no LLM agent) — i.e.
     plays back the scenario's hard-coded "perfect-management" oracle
     events through the live physics engine.
  3. Extrapolates physics forward to R8 maturity (or `--max-days` cap)
     so the latent biological yield reflects the full season, not the
     partial state at scenario stop time.
  4. Reads `physics.yield_recovery.states[*].biological_yield_g_m2`
     plus per-ridge metadata.
  5. Writes ``oracle_baselines/<scenario_id>.json`` with totals and
     per-ridge details.

The resulting JSON is consumed by `evaluate_fos(...)` (via
``_load_oracle_baseline_biological_kg``) to compute the headline
attribution metric:

    crop_loss_pct = 1 - agent_biological_kg / oracle_biological_kg

This is the "how much yield potential did the agent's decisions
preserve, vs. an optimal-play baseline" number that the FOS Outcome
component reports.

Usage
-----
    python scripts/build_oracle_baselines.py \\
        --scenarios scenario_irrigate_now_physics_action_tick,scenario_physics_disease_after_rain_fungicide \\
        --output-dir oracle_baselines

    # or "all" for every registered farm scenario
    python scripts/build_oracle_baselines.py --scenarios all --output-dir oracle_baselines

Re-running on an existing baseline file is idempotent unless `--force`.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fairy.scenarios.fos.provenance import crop_backend_provenance

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("build_oracle_baselines")

FORMAL_90_SCENARIO_IDS_PATH = (
    REPO_ROOT
    / "scripts/fullseason/formal_90_scenario_ids.txt"
)
SELECTED_L2_L1_20_30_PATH = (
    REPO_ROOT
    / "scripts/fullseason/selected_l2_l1_20_30_scenario_ids.txt"
)
L2_SKILL_SCENARIO_IDS_PATH = (
    REPO_ROOT
    / "scripts/fullseason/l2_skill_scenario_ids.txt"
)
L3_MINI_20_SCENARIO_IDS_PATH = (
    REPO_ROOT
    / "scripts/fullseason/l3_mini_20_scenario_ids.txt"
)


# Match the per-scenario list the FOS validation paper sweep covers, plus
# every round-3 / round-4 scenario that has a registered oracle so the
# baseline directory is paper-complete out of the box.
DEFAULT_SCENARIO_GROUPS: dict[str, list[str]] = {
    # round-1+2 baseline (8)
    "round12": [
        "scenario_farm_world_drone_survey_physics_action_tick",
        "scenario_farm_world_fertilizer_physics_action_tick",
        "scenario_farm_world_field_prep_physics_action_tick",
        "scenario_farm_world_harvest_physics_action_tick",
        "scenario_farm_world_irrigation_physics_action_tick",
        "scenario_farm_world_pesticide_outbreak_physics_action_tick",
        "scenario_farm_world_pesticide_physics_action_tick",
        "scenario_farm_world_planting_physics_action_tick",
    ],
    # round-3 mid-season episodes (8)
    "round3": [
        "scenario_physics_differential_diagnosis_fertigation",
        "scenario_physics_disease_after_rain_fungicide",
        "scenario_physics_emergence_replant_decision",
        "scenario_physics_harvest_moisture_timing",
        "scenario_physics_planting_window_reschedule",
        "scenario_physics_pod_fill_drought_irrigation",
        "scenario_physics_postharvest_drying_storage",
        "scenario_physics_threshold_pest_monitoring",
    ],
    # round-4 fullseason (10)
    "round4": [
        "scenario_full_season_adversarial_weather",
        "scenario_full_season_aphid_threshold",
        "scenario_full_season_balanced",
        "scenario_full_season_cold_spring",
        "scenario_full_season_dry_pod_fill",
        "scenario_full_season_late_harvest_rain_risk",
        "scenario_full_season_heinong60_high_density_baseline",
        "scenario_full_season_mixed_stress_trap",
        "scenario_full_season_nutrient_differential",
        "scenario_full_season_resource_limited",
        "scenario_full_season_wet_june_ab_zoned_disease",
        "scenario_full_season_wet_june_disease",
        "scenario_full_season_heinong84_edge_low_fertility",
        "scenario_full_season_hb_adversarial_multi_event_light",
        "scenario_full_season_hb_heinong60_highdensity_fertigation_irrigation_water_budget",
        "scenario_full_season_hb_base_hn84_std_normal"
    ],
    "tangyan5": [
        "scenario_tangyan5_expert_baseline_full_season",
        "scenario_tangyan5_stress_free_oracle_full_season",
    ],
}

def _formal_fullseason_scenarios() -> list[str]:
    """Return the current formal L3 full-season scenario pool."""
    if not FORMAL_90_SCENARIO_IDS_PATH.exists():
        raise FileNotFoundError(
            "Missing formal full-season scenario list: "
            f"{FORMAL_90_SCENARIO_IDS_PATH}"
        )
    return [
        line.strip()
        for line in FORMAL_90_SCENARIO_IDS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _selected_l2_l1_manifest_rows() -> list[tuple[str, str, str, str]]:
    """Return (level, metric_type, scenario_id, source_path) rows."""
    if not SELECTED_L2_L1_20_30_PATH.exists():
        raise FileNotFoundError(
            "Missing selected L2/L1 scenario list: "
            f"{SELECTED_L2_L1_20_30_PATH}"
        )
    rows: list[tuple[str, str, str, str]] = []
    for raw in SELECTED_L2_L1_20_30_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 4:
            raise ValueError(f"Malformed selected L2/L1 manifest row: {raw!r}")
        rows.append((parts[0], parts[1], parts[2], parts[3]))
    return rows


def _selected_l2_l1_scenarios() -> list[str]:
    return [scenario_id for _, _, scenario_id, _ in _selected_l2_l1_manifest_rows()]


def _plain_scenario_id_list(path: Path, label: str) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label} scenario list: {path}")
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _l2_skill_scenarios() -> list[str]:
    return _plain_scenario_id_list(L2_SKILL_SCENARIO_IDS_PATH, "L2 skill")


def _l3_mini_20_scenarios() -> list[str]:
    return _plain_scenario_id_list(L3_MINI_20_SCENARIO_IDS_PATH, "L3-mini 20")


def _ensure_selected_l2_l1_scenario_imported(scenario_id: str) -> None:
    if not SELECTED_L2_L1_20_30_PATH.exists():
        return
    for _, _, selected_id, source_path in _selected_l2_l1_manifest_rows():
        if selected_id != scenario_id:
            continue
        module_name = str(Path(source_path).with_suffix("")).replace("/", ".")
        importlib.import_module(module_name)
        return


def _all_default_scenarios() -> list[str]:
    out: list[str] = []
    for group in DEFAULT_SCENARIO_GROUPS.values():
        out.extend(group)
    return out


@dataclass
class BaselineResult:
    scenario_id: str
    biological_yield_g_m2_per_ridge: list[float]
    biological_yield_kg_total: float
    recovered_yield_g_m2_per_ridge: list[float]
    recovered_yield_kg_total: float
    ridges_planted: int
    ridges_r8: int
    ridges_harvested: int
    extrapolation: dict[str, Any]
    duration_s: float
    donothing: dict[str, Any] | None = None
    tool_errors: list[dict[str, str]] | None = None
    crop_backend_provenance: dict[str, Any] = field(
        default_factory=lambda: {"backend": "legacy"}
    )
    ridge_area_m2: float = 268.0 * 1.1


def _require_single_farm_baseline(scenario: Any) -> Any:
    """The FOS cache format identifies a ridge only by its local integer ID.

    Reject a fleet rather than silently publishing the first site's yield as
    the whole scenario. Fleet scenarios use per-farm oracle workflow/state
    validation and Engine.evaluation_report instead of this legacy FOS cache.
    """
    from fairy.apps.farm_world.multi_farm import farm_world_apps

    farms = farm_world_apps(scenario.apps or [])
    if len(farms) > 1:
        raise ValueError(
            f"Scenario {scenario.scenario_id} contains {len(farms)} farms. "
            "The legacy FOS baseline schema has no farm-qualified ridge IDs. "
            "Use the scenario's oracle workflow and per-farm evaluation report; "
            "no single-farm yield baseline will be written."
        )
    return farms[0] if farms else None


def _require_wofost_maturity(
    physics: Any, extrapolation: dict[str, Any], scenario_id: str
) -> None:
    """A failed native season must not be published as a usable baseline."""
    if getattr(physics, "crop_backend_name", "legacy") != "wofost":
        return
    immature = [
        rid for rid, phen in physics.phenology.states.items()
        if getattr(phen, "planted", False)
        and not getattr(physics.yield_recovery.states.get(rid), "r8_reached", False)
    ]
    if extrapolation.get("status") != "error" and not immature:
        return
    reason = extrapolation.get("error") or (
        f"{len(immature)} planted ridge(s) have not reached maturity at the --max-days cap"
    )
    raise RuntimeError(
        f"Cannot build WOFOST baseline for {scenario_id}: {reason}. "
        "Correct the scenario's daily forcing/management and/or increase --max-days, "
        "then rerun with --force. No WOFOST baseline was written."
    )


def _build_donothing_biological_kg(
    scenario_id: str,
    extrapolation_max_days: int,
    crop_backend: str = "legacy",
    crop_backend_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Initialize scenario without any oracle events and extrapolate to R8.

    This gives the "what would the field produce with zero management" lower
    bound. For scenarios that start from bare soil (planting is an oracle
    action) this will be 0 kg, which is the correct answer — nothing was
    planted. For mid-season scenarios that start with a pre-planted field
    (set up in ``init_and_populate_apps``), this represents weather-driven
    yield with no irrigation, fertilization, or pest control.

    Returns a dict with keys:
        biological_yield_kg_total, biological_yield_g_m2_per_ridge,
        recovered_yield_kg_total, recovered_yield_g_m2_per_ridge,
        ridges_planted, ridges_r8, ridges_harvested, extrapolation, duration_s
    """
    from fairy.scenarios.fos.evaluation import (
        _extrapolate_physics_to_maturity,
    )
    from fairy.controllers.engine import Engine
    from fairy.scenarios.registry import registry

    _ensure_selected_l2_l1_scenario_imported(scenario_id)
    cls = registry.get_scenario(scenario_id)
    scenario = cls(
        crop_backend=crop_backend,
        crop_backend_options=crop_backend_options or {},
    )
    scenario.initialize()  # apps + physics init, NO oracle events run
    Engine(agent=None, scenario=scenario)

    farm_world = _require_single_farm_baseline(scenario)
    if farm_world is None:
        return {"error": "no_farm_world"}

    t0 = time.time()
    extrap = _extrapolate_physics_to_maturity(
        farm_world, max_days=extrapolation_max_days
    )

    physics = getattr(farm_world, "_physics", None)
    _require_wofost_maturity(physics, extrap, f"{scenario_id}:donothing")
    if physics is None or not getattr(physics, "engines_active", False):
        # Physics not active: bare-field scenario with no initial ticking.
        return {
            "biological_yield_kg_total": 0.0,
            "biological_yield_g_m2_per_ridge": [],
            "recovered_yield_kg_total": 0.0,
            "recovered_yield_g_m2_per_ridge": [],
            "ridges_planted": 0,
            "ridges_r8": 0,
            "ridges_harvested": 0,
            "extrapolation": extrap,
            "duration_s": round(time.time() - t0, 2),
            "crop_backend_provenance": crop_backend_provenance(physics),
        }

    ridge_area_m2 = farm_world.field_length_m * farm_world.ridge_width_m
    bio_per: list[float] = []
    rec_per: list[float] = []
    n_planted = 0
    n_r8 = 0
    n_harv = 0
    for rid in sorted(physics.yield_recovery.states.keys()):
        yld = physics.yield_recovery.states[rid]
        phen = physics.phenology.states.get(rid)
        bio_per.append(round(float(yld.biological_yield_g_m2), 4))
        rec_per.append(round(float(yld.recovered_yield_g_m2_at_market_moisture), 4))
        if phen is not None and getattr(phen, "planted", False):
            n_planted += 1
        if getattr(yld, "r8_reached", False):
            n_r8 += 1
        if getattr(yld, "harvested", False):
            n_harv += 1

    bio_total_kg = sum(bio_per) * ridge_area_m2 / 1000.0
    rec_total_kg = sum(rec_per) * ridge_area_m2 / 1000.0
    return {
        "biological_yield_kg_total": round(bio_total_kg, 2),
        "biological_yield_g_m2_per_ridge": bio_per,
        "recovered_yield_kg_total": round(rec_total_kg, 2),
        "recovered_yield_g_m2_per_ridge": rec_per,
        "ridges_planted": n_planted,
        "ridges_r8": n_r8,
        "ridges_harvested": n_harv,
        "extrapolation": extrap,
        "duration_s": round(time.time() - t0, 2),
        "crop_backend_provenance": crop_backend_provenance(physics),
    }


def _build_one_baseline(
    scenario_id: str,
    extrapolation_max_days: int,
    include_donothing: bool = False,
    crop_backend: str = "legacy",
    crop_backend_options: dict[str, Any] | None = None,
) -> BaselineResult:
    """Run scenario in oracle mode + extrapolation, return per-ridge yields."""
    from fairy.controllers.engine import Engine
    from fairy.scenarios.fos.evaluation import (
        _extrapolate_physics_to_maturity,
    )
    from fairy.scenarios.registry import registry

    _ensure_selected_l2_l1_scenario_imported(scenario_id)
    cls = registry.get_scenario(scenario_id)
    scenario = cls(
        crop_backend=crop_backend,
        crop_backend_options=crop_backend_options or {},
    )

    t0 = time.time()
    engine = Engine(agent=None, scenario=scenario)
    workflow = engine.run_scenario_oracle(run_oracle=True)
    tool_errors = _workflow_error_returns(workflow)
    if tool_errors:
        logger.warning(
            "Scenario %s returned %d tool-error results; preserving them in baseline metadata",
            scenario_id,
            len(tool_errors),
        )

    farm_world = _require_single_farm_baseline(scenario)
    if farm_world is None:
        raise RuntimeError(
            f"Scenario {scenario_id} has no FarmWorldApp — cannot build baseline"
        )

    extrap = _extrapolate_physics_to_maturity(
        farm_world, max_days=extrapolation_max_days
    )

    # Read per-ridge biological + recovered, compute totals in kg.
    physics = getattr(farm_world, "_physics", None)
    if physics is None or not getattr(physics, "engines_active", False):
        raise RuntimeError(
            f"Scenario {scenario_id} has no active physics engine post-run"
        )
    _require_wofost_maturity(physics, extrap, scenario_id)

    ridge_area_m2 = farm_world.field_length_m * farm_world.ridge_width_m

    bio_per: list[float] = []
    rec_per: list[float] = []
    n_planted = 0
    n_r8 = 0
    n_harv = 0

    for rid in sorted(physics.yield_recovery.states.keys()):
        yld = physics.yield_recovery.states[rid]
        phen = physics.phenology.states.get(rid)
        bio_per.append(round(float(yld.biological_yield_g_m2), 4))
        rec_per.append(round(float(yld.recovered_yield_g_m2_at_market_moisture), 4))
        if phen is not None and getattr(phen, "planted", False):
            n_planted += 1
        if getattr(yld, "r8_reached", False):
            n_r8 += 1
        if getattr(yld, "harvested", False):
            n_harv += 1

    bio_total_kg = sum(bio_per) * ridge_area_m2 / 1000.0
    rec_total_kg = sum(rec_per) * ridge_area_m2 / 1000.0

    duration = time.time() - t0

    # Optional do-nothing sub-baseline (separate initialization).
    donothing: dict[str, Any] | None = None
    if include_donothing:
        try:
            donothing = _build_donothing_biological_kg(
                scenario_id,
                extrapolation_max_days,
                crop_backend=crop_backend,
                crop_backend_options=crop_backend_options,
            )
        except Exception as exc:
            if getattr(physics, "crop_backend_name", "legacy") == "wofost":
                raise RuntimeError(
                    f"Cannot build matching WOFOST do-nothing baseline for {scenario_id}: {exc}"
                ) from exc
            donothing = {"error": str(exc)}

    return BaselineResult(
        scenario_id=scenario_id,
        biological_yield_g_m2_per_ridge=bio_per,
        biological_yield_kg_total=round(bio_total_kg, 2),
        recovered_yield_g_m2_per_ridge=rec_per,
        recovered_yield_kg_total=round(rec_total_kg, 2),
        ridges_planted=n_planted,
        ridges_r8=n_r8,
        ridges_harvested=n_harv,
        extrapolation=extrap,
        duration_s=round(duration, 2),
        donothing=donothing,
        tool_errors=tool_errors,
        crop_backend_provenance=crop_backend_provenance(physics),
        ridge_area_m2=ridge_area_m2,
    )


def _workflow_error_returns(workflow) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for name, step in getattr(workflow, "dag", {}).items():
        parsed = step.content
        if isinstance(parsed, str):
            try:
                parsed = ast.literal_eval(parsed)
            except (SyntaxError, ValueError):
                pass
        if isinstance(parsed, dict) and parsed.get("error"):
            errors.append(
                {
                    "event_id": str(name),
                    "error": str(parsed["error"]),
                }
            )
    return errors


def _baseline_to_dict(b: BaselineResult) -> dict[str, Any]:
    d: dict[str, Any] = {
        "scenario_id": b.scenario_id,
        "schema_version": 3,
        "crop_backend_provenance": b.crop_backend_provenance,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ridge_area_m2": round(b.ridge_area_m2, 4),
        "ridges_total": len(b.biological_yield_g_m2_per_ridge),
        "ridges_planted": b.ridges_planted,
        "ridges_r8": b.ridges_r8,
        "ridges_harvested": b.ridges_harvested,
        "biological_yield_g_m2_per_ridge": b.biological_yield_g_m2_per_ridge,
        "biological_yield_kg_total": b.biological_yield_kg_total,
        "recovered_yield_g_m2_per_ridge": b.recovered_yield_g_m2_per_ridge,
        "recovered_yield_kg_total": b.recovered_yield_kg_total,
        "extrapolation": b.extrapolation,
        "build_duration_s": b.duration_s,
    }
    if b.donothing is not None:
        d["donothing"] = b.donothing
    if b.tool_errors:
        d["tool_errors"] = b.tool_errors
    return d


def _resolve_scenarios(spec: str) -> list[str]:
    spec = spec.strip()
    if spec == "rice":
        from fairy.scenarios.registry import list_scenarios
        return [sid for sid in list_scenarios() if sid.startswith("scenario_rice_")]
    if spec == "all":
        return _all_default_scenarios()
    if spec in {"full", "formal90", "l3_fullseason"}:
        return _formal_fullseason_scenarios()
    if spec in {"selected_l2_l1_20_30", "l2_l1_20_30"}:
        return _selected_l2_l1_scenarios()
    if spec in {"l2_skill_72", "l2_skills", "l2_skill"}:
        return _l2_skill_scenarios()
    if spec in {"l3_mini_20", "l3-mini-20", "l3_mini"}:
        return _l3_mini_20_scenarios()
    if spec in DEFAULT_SCENARIO_GROUPS:
        return list(DEFAULT_SCENARIO_GROUPS[spec])
    return [s.strip() for s in spec.split(",") if s.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--crop-backend",
        choices=("legacy", "wofost"),
        default=None,
        help="Crop model for both baselines (default: legacy; a WOFOST config selects wofost).",
    )
    parser.add_argument(
        "--wofost-config",
        type=Path,
        help="Path to a JSON object of WOFOST backend options; selects wofost unless explicitly legacy.",
    )
    parser.add_argument(
        "--scenarios",
        default="all",
        help=(
            "Comma-separated scenario IDs, or one of: 'all', 'round12', "
            "'round3', 'round4', 'full'/'formal90'/'l3_fullseason', "
            "'selected_l2_l1_20_30', 'l2_skill_72', 'l3_mini_20', 'rice'. "
            "Default: all."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "oracle_baselines_full"),
        help="Where to write <scenario_id>.json files (default: ./oracle_baselines).",
    )
    parser.add_argument(
        "--max-days",
        type=int,
        default=180,
        help="Cap on extrapolation days. 180 covers any soybean season.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-build even if a baseline file already exists.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Log + skip a scenario on failure rather than aborting the whole run.",
    )
    parser.add_argument(
        "--include-donothing",
        action="store_true",
        default=False,
        help=(
            "Also build a do-nothing sub-baseline: initialize the scenario "
            "without running any oracle events, then extrapolate to R8. "
            "Stored as baseline['donothing']['biological_yield_kg_total']. "
            "Enables the normalized yield score in evaluate_fos(): "
            "  (agent_bio - donothing_bio) / (oracle_bio - donothing_bio). "
            "For bare-soil scenarios (planting is an oracle action) this "
            "will be 0 kg; for mid-season pre-planted scenarios it gives "
            "the weather-only yield floor."
        ),
    )
    args = parser.parse_args()

    crop_backend_options: dict[str, Any] = {}
    if args.wofost_config is not None:
        if args.crop_backend == "legacy":
            parser.error("--wofost-config cannot be combined with --crop-backend legacy")
        try:
            crop_backend_options = json.loads(
                args.wofost_config.expanduser().read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"Cannot read --wofost-config: {exc}")
        if not isinstance(crop_backend_options, dict):
            parser.error("--wofost-config must contain a JSON object")
    crop_backend = args.crop_backend or (
        "wofost" if args.wofost_config is not None else "legacy"
    )

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    targets = _resolve_scenarios(args.scenarios)
    if not targets:
        logger.error("No scenarios to build (got --scenarios=%s)", args.scenarios)
        return 2

    logger.info(
        "Building %d oracle baselines into %s (max_days=%d, force=%s)",
        len(targets),
        output_dir,
        args.max_days,
        args.force,
    )

    n_ok = 0
    n_skip = 0
    n_fail = 0
    for sid in targets:
        out_path = output_dir / f"{sid}.json"
        if out_path.exists() and not args.force:
            logger.info("[SKIP] %s — baseline exists at %s", sid, out_path)
            n_skip += 1
            continue
        try:
            logger.info("[BUILD] %s", sid)
            if sid.startswith("scenario_rice_"):
                from fairy.scenarios.rice.evaluation import build_baseline
                if args.crop_backend == "legacy" or crop_backend_options:
                    raise ValueError("Rice baselines require their WOFOST 8.1 profile")
                payload = build_baseline(sid, include_donothing=args.include_donothing, max_days=args.max_days)
                out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.info("  -> rice dry grain=%.1f kg, stored at 14%%=%.1f kg",
                            payload["oracle"]["biological_dry_kg"], payload["oracle"]["stored_kg_at_14pct"])
                n_ok += 1
                continue
            baseline = _build_one_baseline(
                sid,
                extrapolation_max_days=args.max_days,
                include_donothing=args.include_donothing,
                crop_backend=crop_backend,
                crop_backend_options=crop_backend_options,
            )
            payload = _baseline_to_dict(baseline)
            out_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            dn_info = ""
            if baseline.donothing is not None:
                dn_kg = baseline.donothing.get("biological_yield_kg_total", "?")
                dn_rec_kg = baseline.donothing.get("recovered_yield_kg_total", "?")
                dn_info = (
                    f", donothing_bio={dn_kg:.1f}kg, donothing_rec={dn_rec_kg:.1f}kg"
                    if isinstance(dn_kg, float) and isinstance(dn_rec_kg, float)
                    else f", donothing_bio={dn_kg:.1f}kg"
                    if isinstance(dn_kg, float)
                    else f", donothing={dn_kg}"
                )
            logger.info(
                "  -> bio_total=%.1f kg, ridges_planted=%d, R8=%d, "
                "harv=%d, extrap_days=%d%s (%.2fs)",
                baseline.biological_yield_kg_total,
                baseline.ridges_planted,
                baseline.ridges_r8,
                baseline.ridges_harvested,
                baseline.extrapolation.get("days_ticked", 0),
                dn_info,
                baseline.duration_s,
            )
            n_ok += 1
        except Exception as exc:
            logger.exception("[FAIL] %s: %s", sid, exc)
            if crop_backend == "wofost":
                # PCSE may install its own logging configuration on import.
                # Keep a rejected native baseline actionable on the console.
                print(f"[FAIL] {sid}: {exc}", file=sys.stderr)
            n_fail += 1
            if not args.continue_on_error:
                return 1

    logger.info(
        "Done. ok=%d, skip=%d, fail=%d, out=%s", n_ok, n_skip, n_fail, output_dir
    )
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
