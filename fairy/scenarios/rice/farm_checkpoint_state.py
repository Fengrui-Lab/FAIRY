"""Load reviewed rice artifacts; never generate a season during scenario setup."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fairy.scenarios.rice.rice_scenario_catalog import VARIANTS

ARTIFACT_ROOT = Path(__file__).resolve().parent
MANIFEST_NAME = "scenario_artifacts.json"
ARTIFACT_SCHEMA = 1
REBUILD_COMMAND = "python scripts/build_rice_scenario_artifacts.py"


def checkpoint_relative_path(variant, label):
    if variant not in VARIANTS or not label or Path(label).name != label or label in {".", ".."}:
        raise ValueError("Invalid rice checkpoint variant or label")
    return Path("l2_l1_splits") / f"rice_{variant}" / "checkpoints" / f"{label}.json"


def plan_relative_path(scenario_id):
    from fairy.scenarios.rice.rice_scenario_catalog import get_spec
    get_spec(scenario_id)
    return Path("oracle_plans") / f"{scenario_id}.json"


def load_artifact(relative_path):
    relative_path = Path(relative_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("Rice artifact paths must stay inside the scenario package")
    try:
        manifest = json.loads((ARTIFACT_ROOT / MANIFEST_NAME).read_text(encoding="utf-8"))
        data = (ARTIFACT_ROOT / relative_path).read_bytes()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Missing rice scenario artifact; rebuild with {REBUILD_COMMAND}") from exc
    if manifest.get("schema_version") != ARTIFACT_SCHEMA:
        raise ValueError(f"Unsupported rice artifact manifest; rebuild with {REBUILD_COMMAND}")
    expected = manifest.get("files", {}).get(relative_path.as_posix())
    if not expected or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Rice artifact checksum mismatch: {relative_path}; rebuild with {REBUILD_COMMAND}")
    return json.loads(data)


def load_checkpoint(variant, label):
    return load_artifact(checkpoint_relative_path(variant, label))


def load_oracle_plan(scenario_id):
    return load_artifact(plan_relative_path(scenario_id))


def checkpoint_labels(variant):
    """Return only checkpoints listed in the reviewed manifest."""
    if variant not in VARIANTS:
        raise ValueError(f"Unknown rice variant {variant}")
    manifest = json.loads((ARTIFACT_ROOT / MANIFEST_NAME).read_text(encoding="utf-8"))
    prefix = Path("l2_l1_splits") / f"rice_{variant}" / "checkpoints"
    return sorted(Path(name).stem for name in manifest["files"] if Path(name).parent == prefix)
