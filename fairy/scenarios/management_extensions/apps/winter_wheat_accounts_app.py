"""Wheat configuration and the existing consumed-input operating ledger."""

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
from ..china_market_prices import CNY_PER_USD, usd
from ..engines.winter_wheat_inputs import number
from .operating_accounts_app import OperatingAccounts, OperatingPrices
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered

SEED = "WINTER_WHEAT_104"
PRICE_BOOK = json.loads(
    (
        Path(__file__).resolve().parents[1] / "data/winter_wheat_prices_2025.json"
    ).read_text()
)


def wheat_price(key):
    return usd(PRICE_BOOK["cny_prices"][key])


@dataclass(frozen=True)
class WheatResources:
    block_count: int = 16
    block_length_m: float = 100.0
    block_width_m: float = 6.25
    seed_kg_ha: float = 180.0
    seed_mass_kg: float = 0.000045  # Logistics assumption: 45 g / 1000 seeds.
    seed_stock_kg: float = 180.0
    fertilizer_stock_kg: float = 500.0
    fertilizer_n_fraction: float = 0.46
    water_stock_m3: float = 2400.0
    warehouse_capacity_kg: float = 15000.0
    fuel_stock_liters: float = 100.0
    budget_usd: float = usd(6000.0)
    water_usd_m3: float = wheat_price("water_per_m3")
    storage_moisture_pct: float = 12.5
    harvest_moisture_pct: float = 20.0

    def __post_init__(self):
        for key, value in asdict(self).items():
            number(value, key, minimum=0)
        if type(self.block_count) is not int or self.block_count <= 0:
            raise ValueError("block_count must be a positive integer")
        if (
            min(
                self.block_length_m,
                self.block_width_m,
                self.seed_mass_kg,
                self.seed_kg_ha,
            )
            <= 0
        ):
            raise ValueError("Geometry and reference seed rate/mass must be positive")
        if not 0 < self.fertilizer_n_fraction <= 1:
            raise ValueError("Fertilizer nitrogen fraction must be in (0, 1]")
        if not 11 <= self.storage_moisture_pct < self.harvest_moisture_pct < 100:
            raise ValueError("Invalid harvest/storage moisture")

    @property
    def area_ha(self):
        return self.block_count * self.block_length_m * self.block_width_m / 10000

    @property
    def seeds_per_block(self):
        return round(
            self.seed_kg_ha * self.area_ha / self.block_count / self.seed_mass_kg
        )

    def operating_prices(self):
        return OperatingPrices(
            crop_per_kg={"winter_wheat": wheat_price("grain_per_kg")},
            seed_per_unit={SEED: wheat_price("seed_per_kg") * self.seed_mass_kg},
            fertilizer_per_kg=wheat_price("fertilizer_per_kg"),
            fuel_per_liter=wheat_price("fuel_per_liter"),
            water_per_m3=self.water_usd_m3,
            drying_per_kg=wheat_price("drying_per_kg"),
            currency="USD",
            price_book_id=PRICE_BOOK["price_book_id"],
            cny_per_usd=CNY_PER_USD,
        )


class WinterWheatAccounts(OperatingAccounts):
    """Reuse the soybean/maize ledger, with wheat mass/count conversions."""

    def __init__(self, *, resources, **kwargs):
        self.resources = resources
        prices = resources.operating_prices()
        seed_stock = kwargs["warehouse"].stock.seed_stock
        if seed_stock.keys() - prices.seed_per_unit.keys():
            seed_price = prices.seed_per_unit[SEED]
            prices = replace(
                prices,
                seed_per_unit={
                    seed: prices.seed_per_unit.get(seed, seed_price) for seed in seed_stock
                },
            )
        super().__init__(prices=prices, **kwargs)

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_accounts(self) -> dict:
        """Query USD prices, stocks, actual costs and grain revenue.

        Returns:
            dict: Prices per kg product, seed, L fuel and m3 water; seed count/kg,
            urea kg, pure-N fraction, remaining water and budget. Loaded supplies
            are assets until applied. Costs include consumed fuel and actual drying;
            owned machinery has no additional service fee. Rent/depreciation excluded.
        """
        result = super().get_accounts()
        r = self.resources
        result.update(
            seed_mass_kg=r.seed_mass_kg,
            seed_usd_per_kg=wheat_price("seed_per_kg"),
            consumed_seed_kg=sum(result["consumed_seeds"].values()) * r.seed_mass_kg,
            fertilizer_n_fraction=r.fertilizer_n_fraction,
            operating_cost_limit_usd=r.budget_usd,
            operating_cost_remaining_usd=r.budget_usd - result["production_cost"],
            inventory=self.warehouse.get_inventory(),
            price_sources=PRICE_BOOK["sources"],
        )
        return result
