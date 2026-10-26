"""Lossless maize task checkpoints; JSON contains state, never an Oracle plan."""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path

from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp
from fairy.scenarios.farm_world_fullseason_v2.farm_checkpoint_state import (
    export_farm_checkpoint_state, restore_farm_checkpoint_state,
)
from fairy.time_manager import TimeManager
from .maize_scenario_catalog import SPECS

ROOT = Path(__file__).resolve().parent
# Keep parameter-code provenance separate from a review/staging artifact root.
# Tests and offline verification can select unpublished data without disabling
# source fingerprints or changing the installed scenario package.
ARTIFACT_ROOT = ROOT
REBUILD_COMMAND = "python scripts/build_maize_scenario_artifacts.py"
SCHEMA = 1
# Public device state rounds values for display and omits the loaded seed type.
# Keep this additive checkpoint adapter separate from the public tool schema.
TRACTOR_FIELDS = (
    "seed_type", "_fuel_tank_l", "_pesticide_tank_l", "_fungicide_tank_l",
    "_fertilizer_spreader_kg", "_seed_hopper", "_grain_bin_kg",
    "_operation_log", "_completed_prep_ops", "_attached_implement",
    "_harvest_moisture_limit_pct",
)


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def source_fingerprint(variant):
    payload = {"spec": asdict(SPECS[variant]), "source": {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in ("maize_scenario_catalog.py", "maize_scenario_helpers.py")
    }}
    return hashlib.sha256(json_bytes(payload)).hexdigest()


def checkpoint_path(variant, label):
    if variant not in SPECS or not label or Path(label).name != label or label in {".", ".."}:
        raise ValueError("Invalid maize checkpoint identity")
    return Path("l2_l1_splits") / f"maize_{variant}" / "checkpoints" / f"{label}.json"


def _tuples(value):
    return tuple(_tuples(v) for v in value) if isinstance(value, list) else value


def export_maize_checkpoint(scenario, label):
    farm = scenario.get_typed_app(FarmWorldApp)
    result = {
        "schema_version": SCHEMA,
        "source_l3_scenario_id": scenario.spec.scenario_id,
        "source_fingerprint": source_fingerprint(scenario.spec.variant),
        "variant": scenario.spec.variant,
        "checkpoint_label": label,
        "farm": export_farm_checkpoint_state(
            farm_world=farm, weather_app=scenario.get_typed_app(WeatherApp),
            scenario_id=scenario.spec.scenario_id, checkpoint_label=label,
        ),
        "apps": {},
        "initial_inventory": copy.deepcopy(scenario._maize_initial_inventory),
        "observation_rng": farm.physics.observation_model.rng.getstate(),
        "crop_config_fingerprint": farm.physics.crop_backend.snapshot()["provenance"]["config_fingerprint"],
    }
    for app in scenario.apps:
        if app.name in {"AgentUserInterface", "SystemApp"}:
            continue
        state = {"state": copy.deepcopy(app.get_state()), "seed": app.seed,
                 "rng": app.rng.getstate()}
        if isinstance(app, TractorApp):
            state["exact_state"] = {key: copy.deepcopy(getattr(app, key)) for key in TRACTOR_FIELDS}
        # Other devices expose rounded batteries, which must not lose precision.
        if hasattr(app, "_battery_pct"):
            state["battery_pct"] = app._battery_pct
        result["apps"][app.name] = state
    return result


def load_checkpoint(variant, label, *, root=None):
    root = Path(ARTIFACT_ROOT if root is None else root)
    path = checkpoint_path(variant, label)
    try:
        manifest = json.loads((root / "scenario_artifacts.json").read_text())
        data = (root / path).read_bytes()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Missing maize artifact; rebuild with {REBUILD_COMMAND}") from exc
    if manifest.get("schema_version") != SCHEMA:
        raise ValueError(f"Unsupported maize artifact schema; rebuild with {REBUILD_COMMAND}")
    digest = hashlib.sha256(data).hexdigest()
    if manifest.get("files", {}).get(path.as_posix()) != digest:
        raise ValueError(f"Maize checkpoint checksum mismatch; rebuild with {REBUILD_COMMAND}")
    result = json.loads(data)
    if (result.get("schema_version") != SCHEMA
            or result.get("variant") != variant
            or result.get("checkpoint_label") != label
            or result.get("source_l3_scenario_id") != SPECS[variant].scenario_id
            or result.get("source_fingerprint") != source_fingerprint(variant)):
        raise ValueError(f"Maize checkpoint configuration mismatch; rebuild with {REBUILD_COMMAND}")
    result["sha256"] = digest
    return result


def restore_maize_checkpoint(scenario, saved):
    # A standalone split owns a clock at exactly the captured source instant.
    # Engine subsequently binds all apps to its clock with this same start_time.
    scenario.start_time = float(saved["farm"]["sim_time"])
    clock = TimeManager()
    clock.reset(scenario.start_time)
    clock.real_time_passed = lambda: 0.0
    for app in scenario.apps:
        app.register_time_manager(clock)
    farm = scenario.get_typed_app(FarmWorldApp)
    restore_farm_checkpoint_state(
        farm_world=farm, weather_app=scenario.get_typed_app(WeatherApp),
        checkpoint_state=saved["farm"],
    )
    field_state = saved["farm"]["farm_world_state"]
    modern = ("crop_configuration" in field_state
              and isinstance(field_state.get("physics_state"), Mapping))
    # The legacy codec recomputes public shadows, so its exact visible surface
    # still needs this overlay. Modern snapshots already restored that surface
    # and the complete native journal; loading them twice replays every ridge's
    # entire season a second time.
    if not modern:
        farm.load_state(copy.deepcopy(field_state))
    scenario.get_typed_app(WeatherApp).load_state(copy.deepcopy(saved["farm"]["weather_app_state"]))
    if farm.physics.crop_backend.snapshot()["provenance"]["config_fingerprint"] != saved["crop_config_fingerprint"]:
        raise ValueError("Maize native checkpoint configuration mismatch")
    for app in scenario.apps:
        state = saved["apps"].get(app.name)
        if state is None:
            continue
        # Farm/Weather were already restored with the native and pending state.
        if not isinstance(app, (FarmWorldApp, WeatherApp)) and state["state"] is not None:
            app.load_state(copy.deepcopy(state["state"]))
        for key, value in state.get("exact_state", {}).items():
            if key not in TRACTOR_FIELDS or not isinstance(app, TractorApp):
                raise ValueError("Invalid maize equipment checkpoint field")
            setattr(app, key, copy.deepcopy(value))
        if "battery_pct" in state:
            app._battery_pct = state["battery_pct"]
        app.seed = state["seed"]
        app.rng.setstate(_tuples(state["rng"]))
    farm.physics.observation_model.rng.setstate(_tuples(saved["observation_rng"]))
    scenario._maize_initial_inventory = copy.deepcopy(saved["initial_inventory"])
