"""Explicit scenario assumptions, not Chinese observed prices or calibrated inputs."""

from dataclasses import dataclass
from ..apps.winter_wheat_accounts_app import WheatResources
from ..apps.operating_accounts_app import OperatingPrices


@dataclass(frozen=True)
class BeetResources(WheatResources):
    seed_kg_ha: float = 2.0
    seed_mass_kg: float = 0.00002
    seed_stock_kg: float = 2.0
    fertilizer_stock_kg: float = 500.0
    water_stock_m3: float = 3000.0
    fuel_stock_liters: float = 400.0
    budget_usd: float = 1800.0
    water_usd_m3: float = 0.08

    def operating_prices(self):
        return OperatingPrices(
            crop_per_kg={"winter_wheat": 0.30, "sugarbeet": 0.0},
            seed_per_unit={"WINTER_WHEAT_104": 0.000025, "SUGARBEET_601": 0.002},
            fertilizer_per_kg=0.40,
            fuel_per_liter=1.10,
            water_per_m3=self.water_usd_m3,
            drying_per_kg=0.015,
            currency="USD",
            price_book_id="beet_synthetic_economic_assumptions_v1",
            cny_per_usd=None,
        )  # No currency conversion is performed or asserted.
