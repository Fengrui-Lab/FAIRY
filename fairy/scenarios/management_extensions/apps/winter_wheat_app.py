"""Day-level wheat operations and accounting, not a second crop-growth model."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from functools import wraps
from threading import RLock
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo
from pathlib import Path
import json

from fairy.apps.app import App
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered

from ..china_market_prices import CNY_PER_USD, usd
from ..engines.winter_wheat_inputs import (
    dry_to_moist_mass,
    fingerprint,
    irrigation_m3,
    number,
)

WHEAT_PRICE_BOOK = json.loads(
    (
        Path(__file__).resolve().parents[1] / "data/winter_wheat_prices_2025.json"
    ).read_text()
)


def wheat_price(key):
    return usd(WHEAT_PRICE_BOOK["cny_prices"][key])


@dataclass(frozen=True)
class WheatResources:
    """Whole-field quantities and frozen USD service/input prices; see data price provenance."""

    area_ha: float = 1.0
    seed_kg_ha: float = 180.0  # fixed logistical requirement; not a density response
    seed_stock_kg: float = 180.0
    fertilizer_stock_kg: float = 500.0  # urea PRODUCT, not elemental N
    fertilizer_n_fraction: float = 0.46
    water_stock_m3: float = 2400.0
    warehouse_capacity_kg: float = 15000.0
    budget_usd: float = usd(6000.0)
    seed_usd_kg: float = wheat_price("seed_per_kg")
    fertilizer_usd_kg: float = wheat_price("fertilizer_per_kg")
    water_usd_m3: float = wheat_price("water_per_m3")
    grain_usd_kg: float = wheat_price("grain_per_kg")
    prepare_usd_ha: float = wheat_price("prepare_per_ha")
    sow_usd_ha: float = wheat_price("sow_per_ha")
    fertilize_pass_usd_ha: float = wheat_price("fertilize_pass_per_ha")
    irrigate_pass_usd_ha: float = wheat_price("irrigate_pass_per_ha")
    harvest_usd_ha: float = wheat_price("harvest_per_ha")
    drying_usd_kg: float = wheat_price("drying_per_kg")
    storage_usd_kg: float = wheat_price("storage_per_kg")
    harvest_moisture_fraction: float = 0.20  # logistics assumption, not WOFOST output
    storage_moisture_fraction: float = 0.125

    def __post_init__(self):
        for k, v in asdict(self).items():
            number(v, k, minimum=0)
        if self.area_ha <= 0 or self.seed_kg_ha <= 0:
            raise ValueError("Area and fixed reference seeding rate must be positive")
        if not 0 < self.fertilizer_n_fraction <= 1:
            raise ValueError("Fertilizer N content must be in (0, 1]")
        if not 0 <= self.storage_moisture_fraction < self.harvest_moisture_fraction < 1:
            raise ValueError("Require 0 <= storage moisture < harvest moisture < 1")


def synchronized(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return guarded


class WinterWheatRuntime:
    # Existing FAIRY discovery inspects runtime.domain_apps. This daily world
    # owns its App directly and has no hidden FarmWorld/Tractor instances.
    domain_apps = ()

    def __init__(self, backend: Any, resources: WheatResources):
        self._lock = RLock()
        self.backend = backend
        self.resources = resources
        self.season = backend.bundle.season
        self.tz = ZoneInfo(self.season.timezone)
        self.clock = None
        self.restored_from_snapshot = False
        self.last_timestamp = (
            datetime.combine(self.season.start, datetime.min.time(), tzinfo=self.tz)
            .replace(hour=7)
            .timestamp()
        )
        self.prepared = False
        self.sown = False
        self.harvested = False
        self.dried = False
        self.stored = False
        self.dry_grain_kg = 0.0
        self.grain_moisture = resources.harvest_moisture_fraction
        self.inventory = {
            "seed_kg": resources.seed_stock_kg,
            "fertilizer_product_kg": resources.fertilizer_stock_kg,
            "water_m3": resources.water_stock_m3,
        }
        self.ledger: list[dict] = []
        self.receipts: dict[str, dict] = {}
        self.native_daily: list[dict] = []
        self.failed: str | None = None

    @property
    def cost_usd(self) -> float:
        return sum(row["cost_usd"] for row in self.ledger)

    @property
    def today(self):
        return datetime.fromtimestamp(self.last_timestamp, self.tz).date()

    def bind_clock(self, clock) -> None:
        self.clock = clock

    def _check_time(self, timestamp: float) -> None:
        timestamp = number(timestamp, "timestamp")
        if self.failed:
            raise RuntimeError(f"Episode invalid after native failure: {self.failed}")
        if timestamp < self.last_timestamp - 1e-6:
            raise ValueError("Winter-wheat clock cannot move backwards")
        target = datetime.fromtimestamp(timestamp, self.tz).date()
        if not self.season.start <= target <= self.season.deadline:
            raise ValueError("Time is outside the declared cross-year season")
        if target > self.backend.next_day:
            self.backend.bundle.weather.require(self.backend.next_day, target)

    def before_advance(self, timestamp: float) -> None:
        """Engine supplies the OLD clock time; settle only completed days."""
        self.advance_to(timestamp)

    @synchronized
    def advance_to(self, timestamp: float) -> None:
        self._check_time(timestamp)
        target_day = datetime.fromtimestamp(timestamp, self.tz).date()
        try:
            while self.backend.next_day < target_day:
                snapshot = self.backend.advance_day()
                self.native_daily.append(deepcopy(snapshot))
        except Exception as exc:
            self.failed = f"{type(exc).__name__}: {exc}"
            raise
        self.last_timestamp = timestamp

    def sync(self) -> None:
        if self.clock is not None:
            self.advance_to(self.clock.time())

    @synchronized
    def wait(self, days: int) -> dict:
        if isinstance(days, bool) or not isinstance(days, int) or days < 1:
            raise ValueError(
                "Wait must be a positive integer within the season deadline"
            )
        self.sync()
        target = self.last_timestamp + days * 86400
        self._check_time(target)  # check BEFORE mutating the clock
        if self.clock is None:
            self.advance_to(target)
        else:
            self.clock.add_offset(days * 86400)
            self.advance_to(self.clock.time())  # idempotent if Engine already observed
        return self.observe()

    @synchronized
    def observe(self) -> dict:
        self.sync()
        previous_day = self.today - timedelta(days=1)
        weather = getattr(self.backend.bundle, "weather", None)
        previous_weather = (
            weather[previous_day].as_dict()
            if weather and previous_day in weather.rows
            else None
        )
        return {
            "date": self.today.isoformat(),
            "crop_year": self.season.crop_year,
            "native": self.backend.snapshot(),
            "inventory": deepcopy(self.inventory),
            "prepared": self.prepared,
            "sown": self.sown,
            "harvested": self.harvested,
            "dried": self.dried,
            "stored": self.stored,
            "spent_usd": self.cost_usd,
            "remaining_budget_usd": self.resources.budget_usd - self.cost_usd,
            "weather_visibility": "completed days only; no future realized weather exposed",
            "previous_complete_day_weather": previous_weather,
            "soil_observation_basis": "native model SM/NAVAIL, not independent field measurements",
            "logistics": {
                "dry_grain_kg": self.dry_grain_kg,
                "moisture_fraction": self.grain_moisture,
            },
            "state_timing": "native state at today's start; today's queued inputs settle on next day",
        }

    @synchronized
    def operate(self, operation_id: str, kind: str, amount: float = 0.0) -> dict:
        self.sync()
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("Provide a stable, nonempty operation ID")
        amount = number(amount, "amount", minimum=0)
        request = {"kind": kind, "amount": amount}
        if operation_id in self.receipts:
            old = self.receipts[operation_id]
            if old["request"] != request:
                raise ValueError(
                    "An operation ID cannot be reused with different arguments"
                )
            return deepcopy(old)  # no second charge / application / harvest
        p, area = self.resources, self.resources.area_ha
        cost, changes, flags, native_kind, native_amount = 0.0, {}, {}, None, 0.0
        if self.stored:
            raise ValueError("The full-season workflow has already ended in storage")
        if kind in {"prepare", "sow", "harvest", "dry", "store"} and amount != 0:
            raise ValueError("This operation does not accept an amount")
        if kind == "prepare":
            if self.prepared or self.sown:
                raise ValueError("Preparation is allowed once, before sowing")
            cost, flags = p.prepare_usd_ha * area, {"prepared": True}
        elif kind == "sow":
            self.season.check_sowing(self.today)
            if not self.prepared or self.sown:
                raise ValueError("Prepare the field first; only one sowing per season")
            seed = p.seed_kg_ha * area
            changes = {"seed_kg": -seed}
            cost = seed * p.seed_usd_kg + p.sow_usd_ha * area
            flags, native_kind = {"sown": True}, "sow"
        elif kind in {"fertilize", "irrigate"}:
            if (
                not self.prepared
                or self.harvested
                or self.backend.snapshot()["stage"] == "MATURE"
            ):
                raise ValueError("Prepare first; water/N management ends at maturity")
            if amount <= 0:
                raise ValueError("Water/N dose must be positive")
            native_kind, native_amount = kind, amount
            if kind == "fertilize":
                number(amount, "N per operation kg/ha", maximum=150)
                product_kg = amount * area / p.fertilizer_n_fraction
                changes = {"fertilizer_product_kg": -product_kg}
                cost = product_kg * p.fertilizer_usd_kg + p.fertilize_pass_usd_ha * area
            else:
                number(amount, "irrigation mm per operation", maximum=100)
                m3 = irrigation_m3(amount, area)
                changes = {"water_m3": -m3}
                cost = m3 * p.water_usd_m3 + p.irrigate_pass_usd_ha * area
        elif kind == "harvest":
            snapshot = self.backend.snapshot()
            if self.harvested or snapshot["stage"] != "MATURE":
                raise ValueError(
                    "Harvest requires native DOM maturity; no calendar-forced harvest"
                )
            dry_kg = number(snapshot["values"]["TWSO"], "native TWSO", minimum=0) * area
            if dry_kg <= 0:
                raise ValueError(
                    "Native mature grain mass is zero; no crop may be invented"
                )
            flags = {"harvested": True, "dry_grain_kg": dry_kg}
            cost = p.harvest_usd_ha * area
        elif kind == "dry":
            if not self.harvested or self.dried:
                raise ValueError("Harvest first; drying is allowed once")
            wet = dry_to_moist_mass(self.dry_grain_kg, self.grain_moisture)
            cost = wet * p.drying_usd_kg
            flags = {"dried": True, "grain_moisture": p.storage_moisture_fraction}
        elif kind == "store":
            if not self.dried or self.stored:
                raise ValueError("Dry the harvested grain before storage")
            mass = dry_to_moist_mass(self.dry_grain_kg, self.grain_moisture)
            if mass > p.warehouse_capacity_kg + 1e-9:
                raise ValueError("Insufficient warehouse capacity")
            cost, flags = mass * p.storage_usd_kg, {"stored": True}
        else:
            raise ValueError(f"Unsupported wheat operation: {kind}")
        # All resource guards run before the native queue or any monetary effect.
        for key, delta in changes.items():
            if self.inventory[key] + delta < -1e-8:
                raise ValueError(f"Insufficient {key}")
        if self.cost_usd + cost > p.budget_usd + 1e-8:
            raise ValueError("Operating budget exceeded")
        native_receipt = (
            self.backend.queue(operation_id, native_kind, native_amount)
            if native_kind
            else None
        )
        for key, delta in changes.items():
            self.inventory[key] += delta
        for key, value in flags.items():
            setattr(self, key, value)
        receipt = {
            "operation_id": operation_id,
            "date": self.today.isoformat(),
            "request": request,
            "cost_usd": cost,
            "inventory_delta": changes,
            "native": native_receipt,
        }
        self.ledger.append(deepcopy(receipt))
        self.receipts[operation_id] = receipt
        return deepcopy(receipt)

    @synchronized
    def outcome_summary(self) -> dict:
        self.sync()
        p = self.resources
        stored = (
            dry_to_moist_mass(self.dry_grain_kg, self.grain_moisture)
            if self.stored
            else 0.0
        )
        snapshot = self.backend.snapshot()
        return {
            "crop": "winter_wheat",
            "crop_year": self.season.crop_year,
            "operational_success": bool(self.stored and not self.failed),
            "native": snapshot,
            "currency": "USD",
            "price_book_id": "winter_wheat_china_2025_usd_v1",
            "price_status": "public_benchmarks_and_declared_service_contracts",
            "cny_per_usd": CNY_PER_USD,
            "resources_fingerprint": fingerprint(asdict(p)),
            "area_ha": p.area_ha,
            "area_m2": p.area_ha * 10000,
            "dry_grain_kg": self.dry_grain_kg,
            "stored_grain_kg": stored,
            "stored_kg_by_crop": {"winter_wheat": stored},
            "production_cost": self.cost_usd,
            "cost_components": self.cost_components(),
            "stored_grain_value": stored * p.grain_usd_kg,
            "net_operating_margin": stored * p.grain_usd_kg - self.cost_usd,
            "storage_moisture_fraction": p.storage_moisture_fraction,
            "grain_value_usd": stored * p.grain_usd_kg,
            "operating_cost_usd": self.cost_usd,
            "net_operating_margin_usd": stored * p.grain_usd_kg - self.cost_usd,
            "water_used_m3": p.water_stock_m3 - self.inventory["water_m3"],
            "nitrogen_applied_kg_ha": (
                p.fertilizer_stock_kg - self.inventory["fertilizer_product_kg"]
            )
            * p.fertilizer_n_fraction
            / p.area_ha,
            "comparison_scope": "scenario operating margin; excludes land rent, capital and all omitted costs",
            "not_simulated": [
                "winterkill/snow",
                "pests/diseases/weeds",
                "lodging",
                "density optimization",
                "grain moisture dynamics",
                "tractor passes/durations",
            ],
            "validation_status": "native_reference_not_china_field_calibrated",
            "operation_count": len(self.ledger),
            "native_days": len(self.native_daily),
            "failure": self.failed,
        }

    def cost_components(self) -> dict:
        p = self.resources
        result = dict(
            seed=0.0,
            fertilizer=0.0,
            water=0.0,
            field_services=0.0,
            drying=0.0,
            storage=0.0,
        )
        for row in self.ledger:
            kind, amount = row["request"]["kind"], row["request"]["amount"]
            total = row["cost_usd"]
            if kind == "sow":
                value = p.seed_kg_ha * p.area_ha * p.seed_usd_kg
                result["seed"] += value
                result["field_services"] += total - value
            elif kind == "fertilize":
                value = (
                    amount * p.area_ha / p.fertilizer_n_fraction * p.fertilizer_usd_kg
                )
                result["fertilizer"] += value
                result["field_services"] += total - value
            elif kind == "irrigate":
                value = irrigation_m3(amount, p.area_ha) * p.water_usd_m3
                result["water"] += value
                result["field_services"] += total - value
            else:
                result[
                    {"dry": "drying", "store": "storage"}.get(kind, "field_services")
                ] += total
        return result

    def field_info(self) -> dict:
        p = self.resources
        return {
            "crop_id": "winter_wheat",
            "area_m2": p.area_ha * 10000,
            "field_operations": "whole-field daily services; no ridge/tractor geometry",
            "sowing_window": [
                self.season.sowing_open.isoformat(),
                self.season.sowing_close.isoformat(),
            ],
            "operation_deadline": self.season.deadline.isoformat(),
            "seed_kg_per_ha": p.seed_kg_ha,
            "fertilizer_n_fraction": p.fertilizer_n_fraction,
            "maximum_nitrogen_kg_ha_per_call": 150.0,
            "maximum_irrigation_mm_per_call": 100.0,
            "irrigation_efficiency": self.backend.efficiency,
            "nitrogen_recovery_fraction": self.backend.n_recovery,
            "harvest_requirement": "native DOM reached, positive native TWSO; no fixed-date forced maturity",
            "harvest_moisture_fraction": p.harvest_moisture_fraction,
            "safe_storage_moisture_fraction": p.storage_moisture_fraction,
            "warehouse_capacity_kg": p.warehouse_capacity_kg,
            "cultivar": self.backend.bundle.cultivar,
            "site": deepcopy(self.backend.bundle.manifest["site"]),
            "parameter_status": self.backend.bundle.manifest["parameter_status"],
            "physiology": {
                k: self.backend.parameters[k]
                for k in ("IDSL", "DLO", "DLC", "VERNBASE", "VERNSAT", "VERNDVS")
            },
            "stage_codes": [
                "BARE",
                "SOWN_NOT_EMERGED",
                "VEGETATIVE",
                "POST_ANTHESIS",
                "MATURE",
            ],
            "density_response": "fixed seed logistics; no modeled density optimization",
        }

    def accounts(self) -> dict:
        result = self.outcome_summary()
        p = self.resources
        result.update(
            budget_usd=p.budget_usd,
            remaining_budget_usd=p.budget_usd - self.cost_usd,
            prices={
                "currency": "USD",
                "price_book_id": WHEAT_PRICE_BOOK["price_book_id"],
                "cny_per_usd": CNY_PER_USD,
                **{
                    k: v
                    for k, v in asdict(p).items()
                    if "_usd" in k and k != "budget_usd"
                },
            },
            operation_deadline=self.season.deadline.isoformat(),
            water_budget_m3=p.water_stock_m3,
            fertilizer_product_budget_kg=p.fertilizer_stock_kg,
            price_provenance="management_extensions/data/winter_wheat_prices_2025.json",
            service_accounting="field services include machinery/fuel/operator; no extra fuel charge",
        )
        return result

    @synchronized
    def export_state(self) -> dict:
        self.sync()
        state = {
            "schema": "fairy.winter_wheat.world_checkpoint.v1",
            "resource_fingerprint": fingerprint(asdict(self.resources)),
            "native": self.backend.export_state(),
            "timestamp": self.last_timestamp,
            "ledger": deepcopy(self.ledger),
            "receipts": deepcopy(self.receipts),
            "inventory": deepcopy(self.inventory),
            "daily": deepcopy(self.native_daily),
            "flags": {
                k: getattr(self, k)
                for k in (
                    "prepared",
                    "sown",
                    "harvested",
                    "dried",
                    "stored",
                    "dry_grain_kg",
                    "grain_moisture",
                    "failed",
                )
            },
        }
        state["integrity_sha256"] = fingerprint(state)
        return state

    @synchronized
    def load_state(self, state: dict) -> None:
        from ..engines.winter_wheat_wofost import WinterWheatBackend

        saved = deepcopy(state)
        digest = saved.pop("integrity_sha256")
        if fingerprint(saved) != digest:
            raise ValueError("World checkpoint integrity mismatch")
        if saved["schema"] != "fairy.winter_wheat.world_checkpoint.v1":
            raise ValueError("Unsupported world checkpoint")
        if saved["resource_fingerprint"] != fingerprint(asdict(self.resources)):
            raise ValueError("Resource or price configuration changed since checkpoint")
        restored = WinterWheatBackend.restore(self.backend.bundle, saved["native"])
        target = datetime.fromtimestamp(saved["timestamp"], self.tz).date()
        if target != restored.next_day:
            raise ValueError("Checkpoint world/native date mismatch")
        # Clock restoration belongs to FAIRY; do not mutate a shared clock here.
        self.backend = restored
        self.last_timestamp = saved["timestamp"]
        self.ledger, self.receipts = saved["ledger"], saved["receipts"]
        self.inventory, self.native_daily = saved["inventory"], saved["daily"]
        for k, v in saved["flags"].items():
            setattr(self, k, v)

        # A fresh Engine discovers this restored clock through its existing runtime protocol.
        from fairy.time_manager import SimulationTimeManager

        start = (
            datetime.combine(self.season.start, datetime.min.time(), tzinfo=self.tz)
            .replace(hour=7)
            .timestamp()
        )
        if self.clock is None:
            self.clock = SimulationTimeManager()
        self.clock.reset(start)
        self.clock.set_offset(self.last_timestamp - start)
        self.restored_from_snapshot = True


class WinterWheatApp(App):
    simulation_world = True

    def __init__(self, runtime):
        super().__init__("WinterWheat")
        self.runtime = runtime

    def configure_crop_backend(self, backend: str, **options):
        if backend != "wofost" or options:
            raise ValueError(
                "Winter wheat requires its pinned WOFOST bundle; no legacy fallback or hidden options"
            )

    def get_state(self):
        return self.runtime.export_state()

    def load_state(self, state_dict):
        self.runtime.load_state(state_dict)

    def outcome_summary(self):
        return self.runtime.outcome_summary()

    def crop_backend_provenance(self):
        b = self.runtime.backend
        return {
            "backend": "wofost",
            "model": "Wofost81_NWLP_CWB_CNB",
            "crop_id": "winter_wheat",
            "cultivar": b.bundle.cultivar,
            "pcse_version": b.version,
            "config_fingerprint": fingerprint(
                {
                    "inputs": b.bundle.identity,
                    "resources": asdict(self.runtime.resources),
                }
            ),
            "crop_parameter_sha256": b.bundle.manifest["crop"]["sha256"],
            "weather_sha256": b.bundle.weather.sha256,
            "parameter_status": b.bundle.manifest["parameter_status"],
        }

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_field_info(self) -> dict:
        """Read field geometry, sowing window, dose limits and native harvest conditions.

        Returns:
            Area in m², dates in local ISO format, fixed seed demand and physical/logistics limits.
        """
        return self.runtime.field_info()

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_accounts(self) -> dict:
        """Read frozen USD unit prices, remaining resources and actual operating accounts.

        Returns:
            Prices with units in their keys, consumed-input/service costs, budget and grain value.
        """
        return self.runtime.accounts()

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def observe(self) -> dict:
        """Read native wheat/soil state, pending inputs and resources.

        Returns:
            Native state and completed-day weather; SM is m³/m³, NAVAIL kg N/ha, biomass kg dry matter/ha. Soil values are model estimates."""
        return self.runtime.observe()

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def prepare_field(self, operation_id: str) -> dict:
        """Pay for one field preparation, required before all crop operations.

        Args:
            operation_id: Unique idempotency key; repeat the same request safely.

        Returns:
            Operation receipt with actual USD cost, resource changes and any queued native input.
        """
        return self.runtime.operate(operation_id, "prepare")

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def sow(self, operation_id: str) -> dict:
        """After field preparation, sow once within the queried autumn window at the fixed seed rate.

        Args:
            operation_id: Stable nonempty key; identical retries return the original receipt.

        Returns:
            Operation receipt with actual USD cost, resource changes and any queued native input.
        """
        return self.runtime.operate(operation_id, "sow")

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_nitrogen(self, operation_id: str, nitrogen_kg_ha: float) -> dict:
        """Queue elemental N in kg N/ha. Urea stock and costs use product mass, not N mass.

        Args:
            operation_id: Stable nonempty key; identical retries return the original receipt.
            nitrogen_kg_ha: Positive elemental N dose, at most 150 kg N/ha per operation.

        Returns:
            Operation receipt with actual USD cost, resource changes and any queued native input.
        """
        return self.runtime.operate(operation_id, "fertilize", nitrogen_kg_ha)

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def irrigate(self, operation_id: str, depth_mm: float) -> dict:
        """Queue gross irrigation depth; native efficiency affects infiltration, not water purchased.

        Args:
            operation_id: Stable nonempty key; identical retries return the original receipt.
            depth_mm: Gross depth in millimetres, greater than zero and at most 100.

        Returns:
            Operation receipt with actual USD cost, resource changes and any queued native input.
        """
        return self.runtime.operate(operation_id, "irrigate", depth_mm)

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def wait(self, days: int) -> dict:
        """Advance simulation time and integrate every intervening weather day, including winter and leap day.

        Args:
            days: Positive integer days; must stay within the queried season deadline.

        Returns:
            Updated observation after integrating every intervening native day.
        """
        return self.runtime.wait(days)

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def harvest(self, operation_id: str) -> dict:
        """Harvest native mature grain only (DOM required); no manual yield or forced maturity.

        Args:
            operation_id: Stable nonempty key; identical retries return the original receipt.

        Returns:
            Operation receipt with actual USD cost, resource changes and any queued native input.
        """
        return self.runtime.operate(operation_id, "harvest")

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def dry_grain(self, operation_id: str) -> dict:
        """After harvest, dry once to the queried storage moisture, preserving grain dry matter.

        Args:
            operation_id: Stable nonempty key; identical retries return the original receipt.

        Returns:
            Operation receipt with actual USD cost, resource changes and any queued native input.
        """
        return self.runtime.operate(operation_id, "dry")

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def store_grain(self, operation_id: str) -> dict:
        """After drying, store the whole grain lot within warehouse capacity and finish the season.

        Args:
            operation_id: Stable nonempty key; identical retries return the original receipt.

        Returns:
            Operation receipt with actual USD cost, resource changes and any queued native input.
        """
        return self.runtime.operate(operation_id, "store")
