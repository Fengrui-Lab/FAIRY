"""Scene-owned supplies and grain batches, independent of any field or machine.

Loading transfers stock into a machine; applying it changes the target field.
Grain is owned here as well, with origin retained solely for traceability.
Legacy single-farm scenarios retain their original InventoryState adapter.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import TYPE_CHECKING, Any

from fairy.apps.app import App
from fairy.tool_utils import OperationType, app_tool, data_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check

if TYPE_CHECKING:
    from fairy.apps.farm_world.farm_environment import FarmEnvironment


@dataclass
class WarehouseStock:
    """Remaining consumables in the one warehouse; no implicit per-farm defaults."""

    seed_stock: dict[str, int]
    pesticide_liters: float
    fertilizer_kg: float
    fuel_liters: float

    def __post_init__(self) -> None:
        if any(not isinstance(key, str) or not key or type(value) is not int or value < 0
               for key, value in self.seed_stock.items()):
            raise ValueError("Seed stock requires named varieties and non-negative integer counts")
        for name in ("pesticide_liters", "fertilizer_kg", "fuel_liters"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        self.seed_stock = dict(self.seed_stock)


@dataclass
class GrainBatch:
    """One unloaded bin; kg use the origin crop model's market-moisture basis."""

    batch_id: str
    origin_farm_id: str
    crop_id: str
    cultivar_id: str | None
    ridge_ids: list[int]
    quantity_kg: float
    moisture_pct: float | None
    status: str = "pending"
    dried: bool = False
    cultivar_ids: list[str] = field(default_factory=list)


class WarehouseApp(App):
    """One common warehouse registered once in a scenario's App list."""

    require_explicit_tool_docs = True
    validate_tool_arguments = True

    def __init__(
        self, stock: WarehouseStock, name: str = "Warehouse", *,
        storage_capacity_kg: float | None = None,
        drying_capacity_kg_per_day: float | None = None,
        max_storage_moisture_pct: float = 14.0,
    ) -> None:
        super().__init__(name=name)
        for value in (storage_capacity_kg, drying_capacity_kg_per_day):
            if value is not None and (not isfinite(value) or value <= 0):
                raise ValueError("Warehouse capacities must be finite and positive")
        if not isfinite(max_storage_moisture_pct) or not 11 <= max_storage_moisture_pct <= 16:
            raise ValueError("Storage moisture limit must be in [11, 16]")
        self.stock = deepcopy(stock)
        self._initial_stock = deepcopy(stock)
        self.storage_capacity_kg = storage_capacity_kg
        self.drying_capacity_kg_per_day = drying_capacity_kg_per_day
        self.max_storage_moisture_pct = float(max_storage_moisture_pct)
        self.grain_batches: dict[str, GrainBatch] = {}
        self._drying_usage_by_date: dict[str, float] = {}
        self.environment: FarmEnvironment | None = None

    @property
    def warehouse_id(self) -> str:
        return self.name

    def bind_environment(self, environment: FarmEnvironment) -> None:
        if self.environment is not None and self.environment is not environment:
            raise ValueError("Warehouse already belongs to another scene")
        self.environment = environment
        self.register_time_manager(environment.time_manager)

    def _before_tool(self) -> None:
        if self.environment is not None:
            self.environment.before_tool()

    def _facility_state(self) -> dict[str, Any]:
        return {"storage_capacity_kg": self.storage_capacity_kg,
                "drying_capacity_kg_per_day": self.drying_capacity_kg_per_day,
                "max_storage_moisture_pct": self.max_storage_moisture_pct}

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_inventory(self) -> dict[str, Any]:
        """Read the scene's common seed, chemical, fertilizer, fuel and grain stock.

        All farms draw from these same quantities. Machine tanks and hoppers
        are reported by the machine, and each farm reports its own water quota
        and applied-material limits through get_management_status.

        Returns:
            Warehouse identity, remaining consumables, pending/stored grain kg
            and common storage/drying limits. Grain kg use each crop's model basis.
        """
        self._before_tool()
        return {"warehouse_id": self.warehouse_id, "inventory_scope": "scene",
                **asdict(self.stock),
                "harvest_grain_kg": self._grain_total("pending"),
                "warehouse_grain_kg": self._grain_total("stored"),
                "facilities": self._facility_state()}

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_grain_batches(self) -> dict[str, Any]:
        """Read every common-warehouse grain batch and its origin and moisture.

        Returns:
            Batches with batch_id, origin_farm_id, crop, cultivar, ridge IDs,
            quantity_kg, moisture_pct, pending/stored status and dried flag.
            Pass the batch_id to dry_grain or store_grain.
        """
        self._before_tool()
        return {"warehouse_id": self.warehouse_id,
                "batches": [asdict(batch) for batch in self.grain_batches.values()]}

    def _grain_total(self, status: str) -> float:
        return sum(batch.quantity_kg for batch in self.grain_batches.values()
                   if batch.status == status)

    def _consume(self, name: str, amount: float) -> bool:
        if type(amount) not in (int, float) or not isfinite(amount) or amount <= 0:
            return False
        available = getattr(self.stock, name)
        if available < amount:
            return False
        # Keep full precision internally: rounding a small withdrawal to zero
        # would create free material. Formatting is not inventory arithmetic.
        setattr(self.stock, name, available - amount)
        self.is_state_modified = True
        return True

    def consume_seeds(self, seed_type: str, count: int) -> bool:
        if type(count) is not int or count <= 0:
            return False
        available = self.stock.seed_stock.get(seed_type, 0)
        if available < count:
            return False
        self.stock.seed_stock[seed_type] = available - count
        self.is_state_modified = True
        return True

    def consume_pesticide(self, liters: float) -> bool:
        return self._consume("pesticide_liters", liters)

    def consume_fertilizer(self, kg: float) -> bool:
        return self._consume("fertilizer_kg", kg)

    def consume_fuel(self, liters: float) -> bool:
        return self._consume("fuel_liters", liters)

    def return_supplies(
        self, seed_type: str | None, seeds: int, fertilizer_kg: float,
        pesticide_liters: float, fungicide_liters: float,
    ) -> None:
        if type(seeds) is not int or seeds < 0 or (seeds and not seed_type):
            raise ValueError("Invalid returned seed payload")
        amounts = (fertilizer_kg, pesticide_liters, fungicide_liters)
        if any(not isfinite(value) or value < 0 for value in amounts):
            raise ValueError("Returned supplies must be finite and non-negative")
        if seeds:
            self.stock.seed_stock[seed_type] = self.stock.seed_stock.get(seed_type, 0) + seeds
        self.stock.fertilizer_kg += fertilizer_kg
        self.stock.pesticide_liters += pesticide_liters + fungicide_liters
        self.is_state_modified = True

    def has_batch(self, batch_id: str) -> bool:
        return batch_id in self.grain_batches

    def receive_grain(
        self, batch_id: str, origin_farm_id: str, kg: float,
        ridge_ids: list[int], moistures_pct: list[float],
        cultivar_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Receive one bin; the caller validates before consuming unload time."""
        error = self.validate_receive_grain(batch_id, origin_farm_id, kg, ridge_ids, moistures_pct, cultivar_ids)
        if error:
            raise ValueError(error)
        world = self.environment.get_farm(origin_farm_id).world
        cultivars = sorted(set(cultivar_ids or ([world.cultivar_id] if world.cultivar_id else [])))
        batch = GrainBatch(batch_id, origin_farm_id, world.crop_id,
                           cultivars[0] if len(cultivars) == 1 else None,
                           list(ridge_ids), float(kg),
                           max(moistures_pct) if moistures_pct else None,
                           cultivar_ids=cultivars)
        self.grain_batches[batch_id] = batch
        self.is_state_modified = True
        return {"status": "ok", "warehouse_id": self.warehouse_id, "batch": asdict(batch)}

    def validate_receive_grain(
        self, batch_id: str, origin_farm_id: str, kg: float,
        ridge_ids: list[int], moistures_pct: list[float],
        cultivar_ids: list[str] | None = None,
    ) -> str | None:
        """Validate a prospective bin transfer before the machine spends unload time."""
        if not isinstance(batch_id, str) or not batch_id.strip() or self.has_batch(batch_id):
            return "Grain batch_id must be nonempty and unique"
        if self.environment is None:
            return "Bind the warehouse to a scene before receiving grain"
        try:
            world = self.environment.get_farm(origin_farm_id).world
        except ValueError as exc:
            return str(exc)
        if not isfinite(kg) or kg <= 0:
            return "Grain kg must be finite and positive"
        if (not ridge_ids or len(set(ridge_ids)) != len(ridge_ids)
                or any(type(rid) is not int or not 0 <= rid < world.num_ridges for rid in ridge_ids)):
            return "Grain ridge IDs must belong to the origin farm and be nonempty and unique"
        if len(moistures_pct) != len(ridge_ids):
            return "Each source ridge requires a grain moisture measurement"
        if any(not isfinite(value) or not 0 <= value < 100 for value in moistures_pct):
            return "Invalid grain moisture"
        if cultivar_ids is not None and any(
                cultivar not in world.crop_definition.seed_types for cultivar in cultivar_ids):
            return "Grain cultivar does not belong to its origin crop"
        return None

    def _batch_error(self, batch_id: str) -> str | None:
        batch = self.grain_batches.get(batch_id)
        if batch is None:
            return f"Unknown grain batch_id: {batch_id}"
        if batch.status != "pending":
            return f"Batch {batch_id} is already stored"
        return None

    def _storage_limit(self, batch: GrainBatch) -> float:
        world = self.environment.get_farm(batch.origin_farm_id).world
        return min(self.max_storage_moisture_pct,
                   world._postharvest_market.max_storage_moisture_pct)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def dry_grain(self, batch_id: str, target_moisture_pct: float = 13.0) -> dict[str, Any]:
        """Dry one pending grain batch to a safe moisture without advancing time.

        Already safe batches are left unchanged. Drying capacity is shared by
        all farms and counted cumulatively per scene calendar day. Stored or
        unknown batches fail. Kg retain the crop model's market-moisture basis.

        Args:
            batch_id: Exact pending batch ID returned by get_grain_batches.
            target_moisture_pct: Target percentage in [11,16], no greater than
                the common facility and origin crop's storage moisture limits.

        Returns:
            Updated batch or an error with no batch or capacity changes.
        """
        if not isfinite(target_moisture_pct) or not 11 <= target_moisture_pct <= 16:
            return {"error": "target_moisture_pct must be in [11, 16]"}
        self._before_tool()
        error = self._batch_error(batch_id)
        if error:
            return {"error": error}
        batch = self.grain_batches[batch_id]
        limit = self._storage_limit(batch)
        if target_moisture_pct > limit:
            return {"error": f"Target moisture exceeds storage limit {limit}%"}
        if batch.moisture_pct is not None and batch.moisture_pct <= limit:
            return {"status": "ok", "drying_skipped": True, "batch": asdict(batch)}
        day = self.environment.get_farm(batch.origin_farm_id).world.simulation_date().isoformat()
        used = self._drying_usage_by_date.get(day, 0.0)
        if (self.drying_capacity_kg_per_day is not None
                and used + batch.quantity_kg > self.drying_capacity_kg_per_day + 1e-9):
            return {"error": "Common warehouse daily drying capacity exceeded"}
        self._drying_usage_by_date[day] = used + batch.quantity_kg
        batch.moisture_pct = float(target_moisture_pct)
        batch.dried = True
        self.is_state_modified = True
        return {"status": "ok", "batch": asdict(batch)}

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def store_grain(self, batch_id: str) -> dict[str, Any]:
        """Admit one pending batch into common long-term grain storage.

        Requires known moisture at or below the facility and origin crop's
        storage limit, and sufficient remaining common storage capacity.
        No time advances; repeated admission is rejected without changing kg.

        Args:
            batch_id: Exact pending batch ID returned by get_grain_batches.

        Returns:
            Stored batch and total common warehouse grain kg, or an error.
        """
        self._before_tool()
        error = self._batch_error(batch_id)
        if error:
            return {"error": error}
        batch = self.grain_batches[batch_id]
        if batch.moisture_pct is None or batch.moisture_pct > self._storage_limit(batch) + 1e-9:
            return {"error": "Batch requires known, safe moisture before storage"}
        if (self.storage_capacity_kg is not None
                and self._grain_total("stored") + batch.quantity_kg > self.storage_capacity_kg + 1e-9):
            return {"error": "Common warehouse storage capacity exceeded"}
        batch.status = "stored"
        self.is_state_modified = True
        return {"status": "ok", "batch": asdict(batch),
                "warehouse_grain_kg": self._grain_total("stored")}

    def get_state(self) -> dict[str, Any]:
        return {"app_name": self.name, "warehouse_id": self.warehouse_id,
                "resource_schema_version": 2, "stock": asdict(self.stock),
                "grain_batches": [asdict(batch) for batch in self.grain_batches.values()],
                "facilities": self._facility_state(),
                "drying_usage_by_date": dict(self._drying_usage_by_date)}

    def load_state(self, state_dict: dict[str, Any]) -> None:
        if (state_dict.get("warehouse_id") != self.warehouse_id
                or state_dict.get("resource_schema_version") != 2
                or state_dict.get("facilities") != self._facility_state()):
            raise ValueError("Warehouse snapshot identity, version or facility configuration mismatch")
        stock = WarehouseStock(**deepcopy(state_dict["stock"]))
        batches: dict[str, GrainBatch] = {}
        for data in state_dict["grain_batches"]:
            batch = GrainBatch(**deepcopy(data))
            if (not batch.batch_id.strip() or batch.batch_id in batches
                    or not isfinite(batch.quantity_kg) or batch.quantity_kg <= 0
                    or batch.status not in ("pending", "stored")
                    or type(batch.dried) is not bool
                    or (batch.moisture_pct is not None
                        and (not isfinite(batch.moisture_pct) or not 0 <= batch.moisture_pct < 100))):
                raise ValueError("Invalid grain batch snapshot")
            if self.environment is None:
                raise ValueError("Bind warehouse before restoring grain batches")
            world = self.environment.get_farm(batch.origin_farm_id).world
            if (batch.crop_id != world.crop_id
                    or not batch.ridge_ids or len(set(batch.ridge_ids)) != len(batch.ridge_ids)
                    or any(type(rid) is not int or not 0 <= rid < world.num_ridges
                           for rid in batch.ridge_ids)):
                raise ValueError("Grain batch origin does not match the scene")
            if (batch.cultivar_ids != sorted(set(batch.cultivar_ids))
                    or any(cultivar not in world.crop_definition.seed_types for cultivar in batch.cultivar_ids)
                    or batch.cultivar_id != (batch.cultivar_ids[0] if len(batch.cultivar_ids) == 1 else None)):
                raise ValueError("Grain batch cultivar metadata is inconsistent")
            if batch.status == "stored" and (batch.moisture_pct is None
                    or batch.moisture_pct > self._storage_limit(batch) + 1e-9):
                raise ValueError("Stored batch has unsafe moisture")
            batches[batch.batch_id] = batch
        usage = dict(state_dict.get("drying_usage_by_date", {}))
        from datetime import date
        for day, amount in usage.items():
            date.fromisoformat(day)
            if not isfinite(amount) or amount < 0:
                raise ValueError("Invalid drying usage")
        stored_kg = sum(batch.quantity_kg for batch in batches.values() if batch.status == "stored")
        if self.storage_capacity_kg is not None and stored_kg > self.storage_capacity_kg + 1e-9:
            raise ValueError("Snapshot exceeds common storage capacity")
        if self.drying_capacity_kg_per_day is not None and any(
                amount > self.drying_capacity_kg_per_day + 1e-9 for amount in usage.values()):
            raise ValueError("Snapshot exceeds daily drying capacity")
        self.stock = stock
        self.grain_batches = batches
        self._drying_usage_by_date = usage

    def reset(self) -> None:
        super().reset()
        self.stock = deepcopy(self._initial_stock)
        self.grain_batches = {}
        self._drying_usage_by_date = {}
