"""Frozen 2025 Northeast price inputs and transparent CNY -> USD accounting.

Source observations and scenario contract assumptions are recorded separately in
``data/china_market_2025.json``. This module changes economics, never crop biology.
"""

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path

PRICE_BOOK = json.loads(
    (Path(__file__).parent / "data/china_market_2025.json").read_text()
)
PRICE_BOOK_ID = PRICE_BOOK["price_book_id"]
CNY_PER_USD = PRICE_BOOK["exchange_rate"]["cny_per_usd"]
CNY_PRICES = PRICE_BOOK["cny_prices"]
CONTRACTS = PRICE_BOOK["contract_assumptions"]


def usd(cny: float) -> float:
    """Convert once at the frozen FX rate; preserve fractional-cent unit prices."""
    return float(Decimal(str(cny)) / Decimal(str(CNY_PER_USD)))


def usd_cents(cny: float) -> int:
    """Round a complete cash amount to US cents, half up; never round seed unit prices."""
    return int(
        (Decimal(str(cny)) * 100 / Decimal(str(CNY_PER_USD))).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def dollars_to_cents(dollars: float) -> int:
    """Settle an already-USD total to integer cents without another FX conversion."""
    return int(
        (Decimal(str(dollars)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def operating_prices(*, high_water=False) -> dict:
    """One price table shared by extension accounts; each call returns fresh mappings."""
    return {
        "currency": "USD",
        "price_book_id": PRICE_BOOK_ID,
        "cny_per_usd": CNY_PER_USD,
        "crop_per_kg": {k: usd(v) for k, v in CNY_PRICES["crop_per_kg"].items()},
        "seed_per_unit": {k: usd(v) for k, v in CNY_PRICES["seed_per_unit"].items()},
        **{
            k: usd(CNY_PRICES[k])
            for k in ("fertilizer_per_kg", "fuel_per_liter", "drying_per_kg")
        },
        "water_per_m3": usd(
            CNY_PRICES["high_water_per_m3" if high_water else "water_per_m3"]
        ),
    }


def price_provenance() -> dict:
    """Read-only economic provenance included in final reports, not live quotes."""
    return deepcopy(PRICE_BOOK)
