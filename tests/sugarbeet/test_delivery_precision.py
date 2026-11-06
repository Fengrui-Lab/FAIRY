from datetime import date
from types import SimpleNamespace

import pytest

from fairy.scenarios.management_extensions.evaluation.sugarbeet import evaluate
from fairy.scenarios.management_extensions.sugarbeet.contracts import (
    RootContract,
    RootLedger,
)


@pytest.mark.parametrize("overshoot", [0.00275, 0.01])
def test_upward_weighing_rounding_settles_only_actual_remaining_mass(overshoot):
    day = date(2021, 10, 1)
    contract = RootContract()
    ledger = RootLedger(contract, day, day)
    batch = ledger.add("b", "beet", 0, day, 1.111)
    actual = batch["recovered_net_kg"]
    requested = actual + overshoot
    receipt = ledger.deliver("t", "b", requested, day)
    assert receipt["net_kg"] == actual
    assert receipt["request"]["net_kg"] == requested
    assert receipt["weighing_adjustment_kg"] == pytest.approx(-overshoot)
    assert receipt["revenue_usd"] == actual * contract.root_price_usd_kg
    assert ledger.totals()["delivered_net_kg"] == actual
    assert ledger.deliver("t", "b", requested, date(2030, 1, 1)) == receipt
    restored = RootLedger(contract, day, day)
    restored.load(ledger.export())
    assert restored.export() == ledger.export()
    with pytest.raises(ValueError, match="changed payload"):
        ledger.deliver("t", "b", requested - 0.001, day)
    with pytest.raises(ValueError, match="fully delivered"):
        ledger.deliver("t2", "b", 0.001, day)


def test_overselling_beyond_weighing_precision_is_rejected_without_mutation():
    day = date(2021, 10, 1)
    ledger = RootLedger(RootContract(), day, day)
    batch = ledger.add("b", "beet", 0, day, 1.111)
    before = ledger.export()
    with pytest.raises(ValueError, match="exceeds remaining"):
        ledger.deliver("t", "b", batch["recovered_net_kg"] + 0.0101, day)
    assert ledger.export() == before


@pytest.mark.parametrize(
    ("shortfalls", "success"),
    [
        ((0.009, 0.009), True),
        ((0.01, 0.01), True),
        ((0.011, 0.0), False),
        ((0.02, 0.0), False),
    ],
)
def test_delivery_weighing_precision_is_checked_per_batch(beet, shortfalls, success):
    harvest_day = date(2021, 10, 1)
    contract = RootContract()
    ledger = RootLedger(contract, beet.harvest_open, beet.harvest_close)
    backends = []
    for block, shortfall in enumerate(shortfalls):
        batch_id = f"root:{block}"
        batch = ledger.add(batch_id, beet.cycle_id, block, harvest_day, 62.5)
        ledger.deliver(
            f"deliver:{block}",
            batch_id,
            batch["recovered_net_kg"] - shortfall,
            harvest_day,
        )
        backends.append(
            SimpleNamespace(
                failed=None,
                receipts={
                    "sow": {
                        "cycle_id": beet.cycle_id,
                        "kind": "sow",
                        "day": beet.sowing_open.isoformat(),
                    }
                },
                harvests={
                    beet.cycle_id: {
                        "crop": "sugarbeet",
                        "day": harvest_day.isoformat(),
                        "last_irrigation": None,
                        "native": {"TWSO": 1000.0},
                    }
                },
                rotation_audit=[],
            )
        )
    resources = SimpleNamespace(
        fertilizer_n_fraction=0.46,
        water_stock_m3=3000.0,
        budget_usd=1800.0,
        area_ha=0.125,
        storage_moisture_pct=12.5,
    )
    farm = SimpleNamespace(
        backends=backends,
        ridge_area_m2=625.0,
        num_ridges=2,
        bundle=SimpleNamespace(cycles=(beet,)),
    )
    accounts = {
        "fertilizer_product_kg": 0.0,
        "water_m3": 0.0,
        "production_cost": 0.0,
        "stored_kg_by_crop": {},
        "net_operating_margin": 0.0,
    }
    scene = SimpleNamespace(
        farm_environment=SimpleNamespace(sync=lambda: None),
        farm=farm,
        resources=resources,
        accounts=SimpleNamespace(compute_accounts=lambda: dict(accounts)),
        delivery=SimpleNamespace(ledger=ledger),
        root_contract=contract,
        tractor=SimpleNamespace(_grain_bin_kg=0.0),
        warehouse=SimpleNamespace(grain_batches={}),
        objective_metric="root_yield",
        ORACLE_REFERENCE=None,
        input_fingerprint=lambda: "delivery-precision-regression",
    )
    result = evaluate(scene)
    assert result.success is success
    assert result.metadata["root_yield"] == pytest.approx(
        ledger.totals()["delivered_net_kg"]
    )
