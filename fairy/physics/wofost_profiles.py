"""Versioned, explicitly scoped soybean parameter transfers for WOFOST.

Profiles document a transfer from published research. They do not certify local
cultivar calibration. Loading a profile needs only the standard library; PCSE
remains optional until the native backend is selected.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .phenology_engine import SeedType


_PROFILE_DIRECTORY = Path(__file__).with_name("data") / "wofost" / "profiles"
_PROFILE_ID = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True)
class SoybeanCultivarProfile:
    """An immutable identity with a copyable source document and native values."""

    profile_id: str
    profile_version: str
    base_variety: str
    supported_seed_types: tuple[str, ...]
    sha256: str
    _document: dict[str, Any]

    def applies_to(self, seed_type: str) -> bool:
        return seed_type in self.supported_seed_types

    @property
    def parameter_overrides(self) -> dict[str, Any]:
        return copy.deepcopy(self._document["parameter_overrides"])

    def provenance(self) -> dict[str, Any]:
        """Include values and research caveats, so either changes the fingerprint."""
        return {**copy.deepcopy(self._document), "sha256": self.sha256}


def load_cultivar_profile(
    profile_id: str, *, directory: Path | None = None
) -> SoybeanCultivarProfile:
    """Load one exact bundled JSON version; never infer a cultivar from its name."""
    if not isinstance(profile_id, str) or not _PROFILE_ID.fullmatch(profile_id):
        raise ValueError("WOFOST cultivar_profile must be an exact bundled profile ID")
    directory = _PROFILE_DIRECTORY if directory is None else Path(directory)
    path = directory / f"{profile_id}.json"
    if not path.is_file():
        available = ", ".join(sorted(candidate.stem for candidate in directory.glob("*.json")))
        raise ValueError(f"Unknown WOFOST cultivar profile {profile_id!r}; "
                         f"available: {available or '(none)'}")
    content = path.read_bytes()
    try:
        document = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid WOFOST cultivar profile JSON: {profile_id}") from exc
    if not isinstance(document, dict):
        raise ValueError("WOFOST cultivar profile must be a JSON object")
    if document.get("schema_version") != 1:
        raise ValueError("Unsupported WOFOST cultivar profile schema_version")
    if document.get("profile_id") != profile_id:
        raise ValueError("WOFOST cultivar profile ID does not match its file name")
    version = document.get("profile_version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("WOFOST cultivar profile requires a non-empty profile_version")
    if document.get("crop_name") != "soybean":
        raise ValueError("WOFOST cultivar profiles currently support soybean only")
    base = document.get("base_variety")
    if not isinstance(base, str) or not base:
        raise ValueError("WOFOST cultivar profile requires base_variety")
    seeds = document.get("supported_seed_types")
    valid_seeds = {seed.value for seed in SeedType}
    if (not isinstance(seeds, list) or not seeds
            or any(not isinstance(seed, str) or seed not in valid_seeds for seed in seeds)
            or len(seeds) != len(set(seeds))):
        raise ValueError("WOFOST cultivar profile requires explicit supported_seed_types; "
                         "wildcard scopes are not supported")
    if document.get("transfer_status") != "literature_transfer":
        raise ValueError("WOFOST cultivar profile must declare transfer_status='literature_transfer'")
    if document.get("validation_status") != "unvalidated":
        raise ValueError("WOFOST cultivar profile must declare validation_status='unvalidated'; "
                         "a literature transfer is not local cultivar calibration")
    overrides = document.get("parameter_overrides")
    if not isinstance(overrides, dict) or not overrides:
        raise ValueError("WOFOST cultivar profile requires native parameter_overrides")
    if document.get("parameter_set_kind") == "complete_native_parameters":
        native_name = document.get("native_variety_name")
        if not isinstance(native_name, str) or not native_name.strip():
            raise ValueError("Complete WOFOST cultivar profile requires native_variety_name")
    sources = document.get("sources")
    if (not isinstance(sources, list) or not sources
            or any(not isinstance(source, dict) or not source.get("title") or not source.get("url")
                   for source in sources)):
        raise ValueError("WOFOST cultivar profile sources require titles and URLs")
    return SoybeanCultivarProfile(
        profile_id=profile_id, profile_version=version, base_variety=base,
        supported_seed_types=tuple(seeds), sha256=hashlib.sha256(content).hexdigest(),
        _document=copy.deepcopy(document),
    )
