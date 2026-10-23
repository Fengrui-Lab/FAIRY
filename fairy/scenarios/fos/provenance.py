"""Stable crop-backend identity for yield baselines and run reports."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any


def crop_backend_provenance(farm_world_or_physics: Any) -> dict[str, Any]:
    """Return configuration identity, excluding all evolving crop state.

    Accepts either FarmWorldApp or its physics container. Legacy worlds from
    before backend selection retain their historical identity. WOFOST must
    expose the stable ``snapshot()['provenance']`` contract; an incomplete
    identity must never silently become a legacy identity.
    """
    public_provider = getattr(farm_world_or_physics, "crop_backend_provenance", None)
    if callable(public_provider):
        return public_provider()
    physics = getattr(farm_world_or_physics, "_physics", farm_world_or_physics)
    backend_name = str(getattr(physics, "crop_backend_name", "legacy"))
    if backend_name == "legacy":
        return {"backend": "legacy"}
    backend = getattr(physics, "crop_backend", None)
    snapshot = backend.snapshot() if backend is not None else {}
    provenance = snapshot.get("provenance") if isinstance(snapshot, dict) else None
    if (
        not isinstance(provenance, dict)
        or provenance.get("backend") != backend_name
        or not isinstance(provenance.get("config_fingerprint"), str)
        or not provenance["config_fingerprint"]
    ):
        raise ValueError(
            f"Crop backend {backend_name!r} has no stable configuration provenance. "
            "Initialize the backend before evaluating yield or building baselines."
        )
    return copy.deepcopy(provenance)


def validate_baseline_provenance(
    data: dict[str, Any],
    expected: dict[str, Any] | None,
    baseline_path: str | Path,
) -> None:
    """Reject cross-backend/config comparisons; allow old legacy caches."""
    expected = expected or {"backend": "legacy"}
    actual = data.get("crop_backend_provenance")
    expected_backend = expected.get("backend", "legacy")
    if actual is None and expected_backend == "legacy":
        return
    actual_backend = actual.get("backend") if isinstance(actual, dict) else None
    same_backend = actual_backend == expected_backend
    same_config = expected_backend == "legacy" or (
        bool(expected.get("config_fingerprint"))
        and isinstance(actual, dict)
        and actual.get("config_fingerprint") == expected["config_fingerprint"]
    )
    if same_backend and same_config:
        return
    actual_label = actual_backend or "untagged legacy/unknown"
    actual_fingerprint = actual.get("config_fingerprint") if isinstance(actual, dict) else None
    raise ValueError(
        f"Oracle baseline provenance mismatch at {baseline_path}: "
        f"cached backend={actual_label!r}, current backend={expected_backend!r}; "
        f"cached fingerprint={actual_fingerprint!r}, "
        f"current fingerprint={expected.get('config_fingerprint')!r}. "
        "the backend and configuration fingerprints must match. "
        "Regenerate this baseline using scripts/build_oracle_baselines.py "
        "--force with the same crop backend and WOFOST configuration as the run, "
        "and select that baseline directory for FOS evaluation."
    )
