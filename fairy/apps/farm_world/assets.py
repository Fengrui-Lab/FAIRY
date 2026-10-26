"""Independent equipment identity, payload provenance and serializable state.

An asset is not owned by a tool instance or a farm.  Operation views consume
this one state object; switching a target never recreates its tanks or battery.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import math
import random
import re
from typing import Any


@dataclass(frozen=True)
class AssetSpec:
    asset_id: str
    kind: str
    allowed_farm_ids: tuple[str, ...]
    initial_state: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", self.asset_id):
            raise ValueError("asset_id must start with a letter and contain letters, numbers or underscores")
        if self.kind not in {"tractor", "drone", "robot"}:
            raise ValueError("asset kind must be tractor, drone, or robot")
        if not isinstance(self.allowed_farm_ids, (tuple, list)):
            raise ValueError("allowed_farm_ids must be a list or tuple of farm IDs")
        ids = tuple(self.allowed_farm_ids)
        if not ids or any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError("allowed_farm_ids must contain distinct farm IDs")
        object.__setattr__(self, "allowed_farm_ids", ids)
        object.__setattr__(self, "initial_state", deepcopy(self.initial_state))
        object.__setattr__(self, "parameters", deepcopy(self.parameters))

    def to_dict(self) -> dict[str, Any]:
        return {"asset_id": self.asset_id, "kind": self.kind,
                "allowed_farm_ids": list(self.allowed_farm_ids),
                "initial_state": deepcopy(self.initial_state),
                "parameters": deepcopy(self.parameters)}


def tuple_tree(value: Any) -> Any:
    """Restore random.Random's tuple state after a JSON round trip."""
    return tuple(tuple_tree(item) for item in value) if isinstance(value, (tuple, list)) else value


def _defaults(kind: str) -> dict[str, Any]:
    if kind == "tractor":
        return {"_fuel_tank_l": 100.0, "_pesticide_tank_l": 0.0,
                "_fertilizer_spreader_kg": 0.0, "_fungicide_tank_l": 0.0,
                "_seed_hopper": 0, "seed_type": None, "_grain_bin_kg": 0.0,
                "_operation_log": [], "_attached_implement": None,
                "_harvest_moisture_limit_pct": None}
    data = {"_battery_pct": 100.0, "_charging": False,
            "_charge_started_at": None, "_charge_complete_at": None,
            "_charge_start_battery_pct": None, "description": ""}
    if kind == "drone":
        data.update(_mission_log=[], speed_ms=5.0, effective_ridges_per_pass=7,
                    takeoff_overhead_s=30, min_battery_pct=20.0,
                    battery_pct_per_ridge=1.0)
    else:
        data["_inspection_log"] = []
    return data


_ALIASES = {
    "fuel_tank_l": "_fuel_tank_l", "pesticide_tank_l": "_pesticide_tank_l",
    "fertilizer_spreader_kg": "_fertilizer_spreader_kg", "fungicide_tank_l": "_fungicide_tank_l",
    "seed_hopper": "_seed_hopper", "grain_bin_kg": "_grain_bin_kg",
    "operation_log": "_operation_log", "attached_implement": "_attached_implement",
    "harvest_moisture_limit_pct": "_harvest_moisture_limit_pct",
    "battery_pct": "_battery_pct", "charging": "_charging",
    "charge_started_at": "_charge_started_at", "charge_complete_at": "_charge_complete_at",
    "charge_start_battery_pct": "_charge_start_battery_pct",
    "mission_log": "_mission_log", "inspection_log": "_inspection_log",
}


def _number(value: Any, name: str, low: float = 0.0, high: float = math.inf) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"Invalid asset {name}: expected finite number in [{low}, {high}]")


class AssetState:
    """The single mutable state of a physical tractor, drone, or robot."""

    snapshot_version = 1

    def __init__(self, spec: AssetSpec, seed: int = 0):
        self.spec = spec
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("asset seed must be an integer")
        self.seed = seed
        derived_seed = int.from_bytes(hashlib.sha256(f"{seed}:{spec.asset_id}".encode()).digest()[:8], "big")
        self.rng = random.Random(derived_seed)
        self.data = _defaults(spec.kind)
        self.payload_origin_farm_id: str | None = None
        self.grain_lots: list[dict[str, Any]] = []
        self.last_farm_id: str | None = None
        self.modified = False
        initial = deepcopy(spec.initial_state)
        for key, value in spec.parameters.items():
            name = _ALIASES.get(key, key)
            if name not in self.data:
                raise ValueError(f"Unknown parameter {key!r} for {spec.kind}")
            self.data[name] = deepcopy(value)
        self.payload_origin_farm_id = initial.pop("payload_origin_farm_id", None)
        self.grain_lots = initial.pop("grain_lots", [])
        self.last_farm_id = initial.pop("last_farm_id", None)
        rng_state = initial.pop("rng_state", None)
        for key, value in initial.items():
            name = _ALIASES.get(key, key)
            if name not in self.data:
                raise ValueError(f"Unknown initial asset field {key!r} for {spec.kind}")
            self.data[name] = deepcopy(value)
        self._validate(self.data, self.payload_origin_farm_id, self.grain_lots, self.last_farm_id)
        if rng_state is not None:
            self.rng.setstate(tuple_tree(rng_state))

    @property
    def asset_id(self) -> str:
        return self.spec.asset_id

    @property
    def kind(self) -> str:
        return self.spec.kind

    def has_supplies(self) -> bool:
        return any(float(self.data.get(name, 0)) > 1e-9 for name in
                   ("_seed_hopper", "_fertilizer_spreader_kg", "_pesticide_tank_l", "_fungicide_tank_l"))

    def has_payload(self) -> bool:
        return self.has_supplies() or float(self.data.get("_grain_bin_kg", 0)) > 1e-9

    def reconcile_payload_origin(self, farm_id: str | None = None) -> None:
        if not self.has_payload():
            self.payload_origin_farm_id = None
        elif self.payload_origin_farm_id is None:
            if farm_id is None or farm_id not in self.spec.allowed_farm_ids:
                raise ValueError("Nonempty asset payload requires a valid origin farm")
            self.payload_origin_farm_id = farm_id

    def _validate(self, data: dict[str, Any], origin: Any, lots: Any, last: Any) -> None:
        if set(data) != set(_defaults(self.kind)):
            raise ValueError("Asset snapshot fields do not match the asset kind")
        if origin is not None and origin not in self.spec.allowed_farm_ids:
            raise ValueError("Payload origin is not an allowed farm")
        if last is not None and last not in self.spec.allowed_farm_ids:
            raise ValueError("Last target is not an allowed farm")
        if self.kind == "tractor":
            for key, maximum in (("_fuel_tank_l", 100), ("_pesticide_tank_l", 800),
                                 ("_fungicide_tank_l", 800), ("_fertilizer_spreader_kg", 500),
                                 ("_seed_hopper", 300000), ("_grain_bin_kg", 2000)):
                _number(data[key], key, high=maximum)
            if not isinstance(data["_seed_hopper"], int) or isinstance(data["_seed_hopper"], bool):
                raise ValueError("seed_hopper must be an integer")
            if data["_seed_hopper"] and not isinstance(data["seed_type"], str):
                raise ValueError("Nonempty seed hopper requires seed_type")
            if data["seed_type"] is not None:
                from fairy.apps.farm_world.models import SeedType
                if data["seed_type"] not in {item.value for item in SeedType}:
                    raise ValueError("Unknown asset seed_type")
            if data["_harvest_moisture_limit_pct"] is not None:
                _number(data["_harvest_moisture_limit_pct"], "harvest moisture limit", high=100)
            payload = any(float(data[key]) > 1e-9 for key in
                          ("_seed_hopper", "_fertilizer_spreader_kg", "_pesticide_tank_l", "_fungicide_tank_l", "_grain_bin_kg"))
            if payload and origin is None:
                raise ValueError("Nonempty initial/saved payload must declare payload_origin_farm_id")
            if not isinstance(lots, list):
                raise ValueError("grain_lots must be a list")
            total = 0.0
            seen_ridges: set[int] = set()
            for lot in lots:
                if not isinstance(lot, dict) or lot.get("farm_id") != origin:
                    raise ValueError("Each grain lot must belong to the payload origin")
                if lot.get("crop_type") not in {"soybean", "maize", "rice"}:
                    raise ValueError("Each grain lot needs a known crop")
                ridges = lot.get("ridge_ids")
                if not isinstance(ridges, list) or not ridges or any(isinstance(rid, bool) or not isinstance(rid, int) or rid < 0 for rid in ridges):
                    raise ValueError("Each grain lot needs local ridge IDs")
                if len(set(ridges)) != len(ridges):
                    raise ValueError("A grain lot cannot repeat a ridge")
                if seen_ridges.intersection(ridges):
                    raise ValueError("An asset cannot carry duplicate harvested ridge sources")
                seen_ridges.update(ridges)
                _number(lot.get("grain_kg"), "grain lot kg")
                _number(lot.get("moisture_pct"), "grain lot moisture", high=100)
                _number(lot.get("harvested_at"), "grain lot time")
                if "moistures_pct" in lot:
                    if not isinstance(lot["moistures_pct"], list):
                        raise ValueError("Grain moisture observations must be a list")
                    for moisture in lot["moistures_pct"]:
                        _number(moisture, "grain moisture observation", high=100)
                total += float(lot["grain_kg"])
            if abs(total - float(data["_grain_bin_kg"])) > 0.011:
                raise ValueError("Grain batch mass does not match the asset grain bin")
        else:
            _number(data["_battery_pct"], "battery_pct", high=100)
            if not isinstance(data["_charging"], bool):
                raise ValueError("charging must be boolean")
            session = [data[key] for key in ("_charge_started_at", "_charge_complete_at", "_charge_start_battery_pct")]
            if any(value is not None for value in session):
                if any(value is None for value in session):
                    raise ValueError("Incomplete asset charge session")
                for value in session:
                    _number(value, "charge session")
                if session[1] <= session[0] or session[2] > 100:
                    raise ValueError("Invalid asset charge session")
            if data["_charging"] and any(value is None for value in session):
                raise ValueError("Charging asset must save its charge session")
            if origin is not None or lots:
                raise ValueError("Drone/robot cannot contain tractor payloads")
            if self.kind == "drone":
                for key in ("speed_ms", "effective_ridges_per_pass", "battery_pct_per_ridge"):
                    _number(data[key], key, low=1e-9)
                if not isinstance(data["effective_ridges_per_pass"], int) or isinstance(data["effective_ridges_per_pass"], bool):
                    raise ValueError("effective_ridges_per_pass must be an integer")
                _number(data["takeoff_overhead_s"], "takeoff_overhead_s")
                _number(data["min_battery_pct"], "min_battery_pct", high=100)
        log_key = {"tractor": "_operation_log", "drone": "_mission_log", "robot": "_inspection_log"}[self.kind]
        if not isinstance(data[log_key], list) or any(not isinstance(entry, dict) for entry in data[log_key]):
            raise ValueError("Asset operation log must contain dictionaries")

    def snapshot(self) -> dict[str, Any]:
        return {"version": self.snapshot_version, "spec": self.spec.to_dict(),
                "data": deepcopy(self.data), "seed": self.seed,
                "rng_state": deepcopy(self.rng.getstate()),
                "payload_origin_farm_id": self.payload_origin_farm_id,
                "grain_lots": deepcopy(self.grain_lots), "last_farm_id": self.last_farm_id}

    def load_snapshot(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("version") != self.snapshot_version or snapshot.get("spec") != self.spec.to_dict():
            raise ValueError("Asset snapshot version or identity/configuration mismatch")
        data = deepcopy(snapshot.get("data"))
        if not isinstance(data, dict):
            raise ValueError("Asset snapshot data must be an object")
        origin = snapshot.get("payload_origin_farm_id")
        lots = deepcopy(snapshot.get("grain_lots", []))
        last = snapshot.get("last_farm_id")
        self._validate(data, origin, lots, last)
        rng = random.Random()
        rng.setstate(tuple_tree(snapshot["rng_state"]))
        seed = snapshot.get("seed", self.seed)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("asset snapshot seed must be an integer")
        self.data, self.payload_origin_farm_id, self.grain_lots = data, origin, lots
        self.last_farm_id, self.rng, self.seed = last, rng, seed
        self.modified = False

    get_state = snapshot
    load_state = load_snapshot
