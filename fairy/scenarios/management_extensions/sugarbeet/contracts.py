"""Pure contracts: dates, physical units, root batches and finite-search claims.

No growth/yield response is synthesized here. Assumptions are explicitly labelled.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math
from typing import Any


DELIVERY_WEIGHING_TOLERANCE_KG = 0.01


def finite(value: Any, name: str, low: float = 0, high: float = math.inf) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name}: boolean is not a quantity")
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f"{name}: expected finite [{low}, {high}]")
    return result


def digest(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            obj,
            default=lambda x: x.isoformat(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class CropCycle:
    cycle_id: str
    crop: str
    cultivar: str
    prepare_open: date
    sowing_open: date
    sowing_close: date
    harvest_open: date
    harvest_close: date
    nitrogen_close: date
    maximum_n_kg_ha: float
    sowing_depth_cm: float
    seed_count_ha: int
    irrigation_withholding_days: int = 0
    minimum_dry_yield_kg_ha: float = 0.0

    def __post_init__(self):
        if not self.cycle_id or self.crop not in {"winter_wheat", "sugarbeet"}:
            raise ValueError("Explicit unique cycle ID and supported crop required")
        if (
            not self.prepare_open
            <= self.sowing_open
            <= self.sowing_close
            < self.harvest_open
            <= self.harvest_close
        ):
            raise ValueError("Invalid preparation/sowing/harvest order")
        if not self.prepare_open <= self.nitrogen_close < self.harvest_close:
            raise ValueError("Nitrogen cutoff outside cycle")
        if type(self.seed_count_ha) is not int or self.seed_count_ha <= 0:
            raise ValueError("Seed count must be a positive integer")
        if (
            type(self.irrigation_withholding_days) is not int
            or self.irrigation_withholding_days < 0
        ):
            raise ValueError("Invalid withholding interval")
        finite(self.maximum_n_kg_ha, "N cap", 1, 500)
        finite(self.minimum_dry_yield_kg_ha, "minimum crop output")
        finite(self.sowing_depth_cm, "depth", 2, 3 if self.crop == "sugarbeet" else 5)
        if (
            self.crop == "sugarbeet"
            and self.sowing_close.year != self.harvest_close.year
        ):
            raise ValueError(
                "This reference spring-beet cycle is a single growing year"
            )

    @property
    def native_name(self):
        return "wheat" if self.crop == "winter_wheat" else "sugarbeet"

    @property
    def seed(self):
        return self.cultivar.upper()

    def check_sowing(self, day: date):
        if not self.sowing_open <= day <= self.sowing_close:
            raise ValueError("Outside crop-specific sowing window")

    def check_nitrogen(self, day: date, already: float, dose: float):
        finite(dose, "pure N dose", 0.000001)
        finite(already, "previous pure N")
        if not self.prepare_open <= day <= self.nitrogen_close:
            raise ValueError("Outside configured agronomic nitrogen window")
        if already + dose > self.maximum_n_kg_ha + 1e-9:
            raise ValueError("Cycle pure-N ceiling exceeded")

    def check_harvest(self, day: date, last_irrigation: date | None):
        if not self.harvest_open <= day <= self.harvest_close:
            raise ValueError("Outside crop-specific harvest window")
        if (
            last_irrigation is not None
            and (day - last_irrigation).days < self.irrigation_withholding_days
        ):
            raise ValueError("Pre-harvest irrigation withholding interval not met")

    @classmethod
    def from_dict(cls, value):
        names = {
            "prepare_open",
            "sowing_open",
            "sowing_close",
            "harvest_open",
            "harvest_close",
            "nitrogen_close",
        }
        return cls(
            **{k: date.fromisoformat(v) if k in names else v for k, v in value.items()}
        )

    def to_dict(self):
        return {
            k: v.isoformat() if isinstance(v, date) else v
            for k, v in asdict(self).items()
        }


@dataclass(frozen=True)
class Calendar:
    start: date
    deadline: date
    cycles: tuple[CropCycle, ...]
    timezone: str = "Asia/Shanghai"

    def __post_init__(self):
        if not self.cycles or len({c.cycle_id for c in self.cycles}) != len(
            self.cycles
        ):
            raise ValueError("Nonempty cycles with unique IDs required")
        if (
            not self.start <= self.cycles[0].prepare_open
            or self.cycles[-1].harvest_close > self.deadline
        ):
            raise ValueError("Cycle outside experiment calendar")
        for a, b in zip(self.cycles, self.cycles[1:]):
            if a.harvest_close >= b.prepare_open:
                raise ValueError(
                    "Same-land crops cannot overlap; reserve actual fallow time"
                )
        if len(self.cycles) > 1 and tuple(c.crop for c in self.cycles) != (
            "winter_wheat",
            "sugarbeet",
        ):
            raise ValueError("L4 currently supports exactly wheat then beet")


@dataclass(frozen=True)
class RootContract:
    dry_matter_fraction: float = 0.20
    sucrose_fraction_fresh: float = 0.16
    machine_recovery: float = 0.95
    tare_fraction_gross: float = 0.08
    root_price_usd_kg: float = 0.05
    transport_usd_gross_kg: float = 0.004
    truck_gross_capacity_kg: float = 10000
    delivery_daily_gross_kg: float = 100000
    maximum_holding_days: int = 3
    provenance: str = "engineering_assumption_not_observation_or_market_quote"

    def __post_init__(self):
        finite(self.dry_matter_fraction, "root dry matter", 0.05, 0.5)
        finite(self.sucrose_fraction_fresh, "root sucrose", 0, self.dry_matter_fraction)
        finite(self.machine_recovery, "machine recovery", 0.01, 1)
        finite(self.tare_fraction_gross, "tare", 0, 0.5)
        for n in ("root_price_usd_kg", "transport_usd_gross_kg"):
            finite(getattr(self, n), n)
        for n in ("truck_gross_capacity_kg", "delivery_daily_gross_kg"):
            finite(getattr(self, n), n, 1)
        if type(self.maximum_holding_days) is not int or self.maximum_holding_days < 0:
            raise ValueError("Invalid holding interval")
        if not self.provenance:
            raise ValueError("Quality and contract provenance required")

    def recovered_fresh(self, dry_kg: float):
        return (
            finite(dry_kg, "dry kg") * self.machine_recovery / self.dry_matter_fraction
        )

    def gross_for_net(self, net_kg: float):
        return finite(net_kg, "net kg") / (1 - self.tare_fraction_gross)


@dataclass
class RootBatch:
    batch_id: str
    cycle_id: str
    block_id: int
    harvest_day: date
    dry_kg: float
    recovered_net_kg: float
    delivered_net_kg: float = 0.0


class RootLedger:
    """Clean-root mass is never charged twice for tare; delivery is idempotent."""

    def __init__(
        self, contract: RootContract, delivery_open: date, delivery_close: date
    ):
        if delivery_close < delivery_open:
            raise ValueError("Reversed delivery window")
        self.contract, self.delivery_open, self.delivery_close = (
            contract,
            delivery_open,
            delivery_close,
        )
        self.batches: dict[str, RootBatch] = {}
        self.transactions: dict[str, dict] = {}
        self.daily_gross: dict[str, float] = {}

    def add(
        self, batch_id: str, cycle_id: str, block_id: int, day: date, dry_kg: float
    ):
        if not batch_id or batch_id in self.batches:
            raise ValueError("Root batch IDs cannot be reused")
        if type(block_id) is not int or block_id < 0:
            raise ValueError("Invalid block")
        dry_kg = finite(dry_kg, "dry harvest", 0.000001)
        self.batches[batch_id] = RootBatch(
            batch_id,
            cycle_id,
            block_id,
            day,
            dry_kg,
            self.contract.recovered_fresh(dry_kg),
        )
        return deepcopy(asdict(self.batches[batch_id]))

    def deliver(self, operation_id: str, batch_id: str, net_kg: float, day: date):
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("Nonempty operation ID required")
        net_kg = finite(net_kg, "delivered net kg", 0.000001)
        request = {"batch_id": batch_id, "net_kg": net_kg}
        if operation_id in self.transactions:
            old = self.transactions[operation_id]
            if old["request"] != request:
                raise ValueError("Delivery ID reused with changed payload")
            return deepcopy(old)
        b = self.batches[batch_id]
        c = self.contract
        if not self.delivery_open <= day <= self.delivery_close:
            raise ValueError("Factory is outside the declared receiving window")
        if not 0 <= (day - b.harvest_day).days <= c.maximum_holding_days:
            raise ValueError(
                "Batch age violates contract; no synthetic sugar-loss curve is substituted"
            )
        remaining = b.recovered_net_kg - b.delivered_net_kg
        if remaining <= 1e-8:
            raise ValueError("Root batch is already fully delivered")
        if net_kg > remaining + DELIVERY_WEIGHING_TOLERANCE_KG + 1e-8:
            raise ValueError("Delivery exceeds remaining clean roots")
        requested_net_kg = net_kg
        net_kg = min(net_kg, remaining)
        gross = c.gross_for_net(net_kg)
        if gross > c.truck_gross_capacity_kg + 1e-8:
            raise ValueError("Truck gross load exceeded")
        used = self.daily_gross.get(day.isoformat(), 0)
        if used + gross > c.delivery_daily_gross_kg + 1e-8:
            raise ValueError("Daily factory capacity exceeded")
        receipt = {
            "request": request,
            "day": day.isoformat(),
            "gross_kg": gross,
            "net_kg": net_kg,
            "tare_kg": gross - net_kg,
            "revenue_usd": net_kg * c.root_price_usd_kg,
            "transport_usd": gross * c.transport_usd_gross_kg,
            "quality_basis": c.provenance,
        }
        if net_kg != requested_net_kg:
            receipt["weighing_adjustment_kg"] = net_kg - requested_net_kg
        b.delivered_net_kg += net_kg
        self.daily_gross[day.isoformat()] = used + gross
        self.transactions[operation_id] = receipt
        return deepcopy(receipt)

    def totals(self):
        tx = self.transactions.values()
        return {
            "recovered_net_kg": sum(b.recovered_net_kg for b in self.batches.values()),
            "delivered_net_kg": sum(b.delivered_net_kg for b in self.batches.values()),
            "dry_harvest_kg": sum(b.dry_kg for b in self.batches.values()),
            "revenue_usd": sum(t["revenue_usd"] for t in tx),
            "transport_usd": sum(t["transport_usd"] for t in tx),
        }

    def export(self):
        return {
            "batches": [
                {**asdict(b), "harvest_day": b.harvest_day.isoformat()}
                for b in self.batches.values()
            ],
            "transactions": deepcopy(self.transactions),
            "daily_gross": dict(self.daily_gross),
        }

    def load(self, state):
        # Reconstruct from native snapshots and replay receipts; reject forged totals.
        other = type(self)(self.contract, self.delivery_open, self.delivery_close)
        for b in state["batches"]:
            other.add(
                b["batch_id"],
                b["cycle_id"],
                b["block_id"],
                date.fromisoformat(b["harvest_day"]),
                b["dry_kg"],
            )
        for key, t in state["transactions"].items():
            other.deliver(key, **t["request"], day=date.fromisoformat(t["day"]))
        if digest(other.export()) != digest(state):
            raise ValueError("Root ledger checkpoint does not conserve mass/accounting")
        self.batches, self.transactions, self.daily_gross = (
            other.batches,
            other.transactions,
            other.daily_gross,
        )


def select_candidates(rows: list[dict], expected_ids: list[str], objective: str):
    """Only complete enumerations can claim best-in-declared-grid. Never global."""
    if objective not in {"root_yield", "net_operating_margin", "rotation_yield"}:
        raise ValueError("Unknown optimization objective")
    if len(set(expected_ids)) != len(expected_ids):
        raise ValueError("Duplicate candidate IDs")
    if len({r["candidate_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate candidate results")
    if any(r["candidate_id"] not in expected_ids for r in rows):
        raise ValueError("Undeclared candidate result")
    complete = set(expected_ids) == {r["candidate_id"] for r in rows} and all(
        r.get("execution_status", "completed") != "runtime_error" for r in rows
    )
    if not rows:
        return {
            "status": "not_run",
            "complete": False,
            "best": None,
            "global_optimum_proven": False,
        }
    identities = {r["input_fingerprint"] for r in rows}
    if len(identities) != 1:
        raise ValueError("Candidates changed input parameters/resources/prices")
    feasible = [
        r
        for r in rows
        if r["feasible"] and r.get("execution_status", "completed") != "runtime_error"
    ]
    for r in feasible:
        for key in ("root_yield", "wheat_yield", "net_operating_margin"):
            finite(r[key], key, -math.inf if key == "net_operating_margin" else 0)
    if not feasible:
        return {
            "status": "no_feasible_candidate",
            "complete": complete,
            "best": None,
            "global_optimum_proven": False,
        }

    def score(r):
        if objective == "rotation_yield":
            return r["root_yield"], r["wheat_yield"], r["net_operating_margin"]
        return r[objective], r["net_operating_margin"], r["root_yield"]

    feasible.sort(key=lambda r: r["candidate_id"])
    best = max(feasible, key=score)
    pareto = [
        a["candidate_id"]
        for a in feasible
        if not any(
            all(
                b[k] >= a[k]
                for k in ("root_yield", "wheat_yield", "net_operating_margin")
            )
            and any(
                b[k] > a[k]
                for k in ("root_yield", "wheat_yield", "net_operating_margin")
            )
            for b in feasible
        )
    ]
    return {
        "status": "best_in_declared_finite_grid" if complete else "best_tested_only",
        "complete": complete,
        "objective": objective,
        "best": best,
        "candidate_count": len(rows),
        "feasible_count": len(feasible),
        "pareto_candidate_ids": pareto,
        "global_optimum_proven": False,
        "best_root_yield_candidate": max(feasible, key=lambda r: r["root_yield"])[
            "candidate_id"
        ],
        "best_wheat_yield_candidate": max(feasible, key=lambda r: r["wheat_yield"])[
            "candidate_id"
        ],
        "best_margin_candidate": max(feasible, key=lambda r: r["net_operating_margin"])[
            "candidate_id"
        ],
    }
