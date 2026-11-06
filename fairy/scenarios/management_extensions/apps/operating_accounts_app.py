"""Read-only crop valuation and actual-consumption accounting."""

from dataclasses import asdict, dataclass

from fairy.apps.app import App
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered

from .shared_irrigation_app import water_used_m3
from ..china_market_prices import CNY_PER_USD, CNY_PRICES, PRICE_BOOK_ID, usd


@dataclass(frozen=True)
class OperatingPrices:
    crop_per_kg: dict[str, float]
    seed_per_unit: dict[str, float]
    fertilizer_per_kg: float = usd(CNY_PRICES["fertilizer_per_kg"])
    fuel_per_liter: float = usd(CNY_PRICES["fuel_per_liter"])
    water_per_m3: float = usd(CNY_PRICES["water_per_m3"])
    drying_per_kg: float = usd(CNY_PRICES["drying_per_kg"])
    currency: str = "USD"
    price_book_id: str = PRICE_BOOK_ID
    cny_per_usd: float = CNY_PER_USD


class OperatingAccounts(App):
    def __init__(
        self,
        *,
        farms,
        warehouse,
        tractor,
        prices,
        initial_machine_fuel,
        water_capacity_m3,
        operation_deadline: str | None = None,
    ):
        super().__init__("OperatingAccounts")
        self.farms = farms
        self.warehouse = warehouse
        self.tractor = tractor
        self.prices = prices
        self.initial_machine_fuel = initial_machine_fuel
        self.water_capacity_m3 = water_capacity_m3
        self.operation_deadline = operation_deadline

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_accounts(self) -> dict:
        """Read fixed USD prices, actual consumption, stored-grain value and net margin.

        Returns:
            dict: prices per kg, seed, L fuel or m3 water as named; consumption in
            seed counts, fertilizer-product kg, fuel L, water m3 and drying kg.
            stored_kg_by_crop retains crop identity; shared_water_remaining_m3 is the
            common balance. USD margin equals stored value minus consumed-input and
            enabled protection costs. Unused stock remains an asset; rent, ordinary
            labour, depreciation and tax are excluded. operation_deadline is
            the task cutoff as a local ISO timestamp, or null if unconfigured.
        """
        return {
            **self.compute_accounts(),
            "operation_deadline": self.operation_deadline,
        }

    def compute_accounts(self):
        """Pure snapshot used by evaluation; no tool event or state mutation."""
        tractor, warehouse, prices = self.tractor, self.warehouse, self.prices
        initial = warehouse._initial_stock
        seed_used = {}
        for seed, quantity in initial.seed_stock.items():
            hopper = tractor._seed_hopper if tractor.seed_type == seed else 0
            seed_used[seed] = quantity - warehouse.stock.seed_stock[seed] - hopper
        fertilizer = (
            initial.fertilizer_kg
            - warehouse.stock.fertilizer_kg
            - tractor._fertilizer_spreader_kg
        )
        fuel = (
            initial.fuel_liters
            + self.initial_machine_fuel
            - warehouse.stock.fuel_liters
            - tractor._fuel_tank_l
        )
        water = water_used_m3(self.farms)
        yields = {crop: 0.0 for farm in self.farms
                  for crop in getattr(farm, "accounting_crop_ids", (farm.crop_id,))}
        for batch in warehouse.grain_batches.values():
            if batch.status == "stored":
                yields[batch.crop_id] += batch.quantity_kg
        # The warehouse records actual processing throughput, including its skip
        # and rejection rules; a batch flag is not the consumption ledger.
        dried = sum(warehouse._drying_usage_by_date.values())
        costs = {
            "seed": sum(
                quantity * prices.seed_per_unit[seed]
                for seed, quantity in seed_used.items()
            ),
            "fertilizer": fertilizer * prices.fertilizer_per_kg,
            "fuel": fuel * prices.fuel_per_liter,
            "water": water * prices.water_per_m3,
            "drying": dried * prices.drying_per_kg,
        }
        revenue = sum(
            quantity * prices.crop_per_kg[crop] for crop, quantity in yields.items()
        )
        return {
            "currency": prices.currency,
            "price_book_id": prices.price_book_id,
            "cny_per_usd": prices.cny_per_usd,
            "prices": asdict(prices),
            "stored_kg_by_crop": yields,
            "consumed_seeds": seed_used,
            "fertilizer_product_kg": fertilizer,
            "fuel_liters": fuel,
            "water_m3": water,
            "shared_water_capacity_m3": self.water_capacity_m3,
            "shared_water_remaining_m3": self.water_capacity_m3 - water,
            "drying_throughput_kg": dried,
            "cost_components": costs,
            "production_cost": sum(costs.values()),
            "stored_grain_value": revenue,
            "net_operating_margin": revenue - sum(costs.values()),
        }
