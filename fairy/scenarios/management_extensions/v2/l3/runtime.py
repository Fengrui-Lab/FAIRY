"""Local shared-water enforcement and auditable operating accounts.

No shared platform defaults are modified. Read-only accounts derive consumption
from material balances, so loading a machine is never charged as consumption.
Prices are synthetic DEMO assumptions, frozen before candidate exploration.
"""

from dataclasses import dataclass, asdict
from math import isfinite

from fairy.apps.app import App
from fairy.apps.farm_world.irrigation_app import IrrigationApp
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered


@dataclass(frozen=True)
class Prices:
    maize_per_kg: float = 0.25
    soybean_per_kg: float = 0.45
    maize_seed_per_unit: float = 0.002
    soybean_seed_per_unit: float = 0.0003
    fertilizer_per_kg: float = 0.8
    fuel_per_liter: float = 1.5
    water_per_m3: float = 0.20
    drying_per_kg: float = 0.03


def water_used_m3(farms):
    return sum(
        farm._management_regime.irrigation_used_mm_total * farm.field_area_m2 / 1000
        for farm in farms
    )


class PooledIrrigation(IrrigationApp):
    """Each stationary controller checks the same remaining physical supply."""

    def __init__(self, farm, weather, farms, capacity_m3, name):
        super().__init__(farm, weather, name=name)
        self._pool_farms = farms
        self._pool_capacity_m3 = capacity_m3

    def _start_irrigation(self, ridge_ids, duration_hours):
        requested = (
            duration_hours
            * 5
            * len(ridge_ids)
            * self._farm_world_app.ridge_area_m2
            / 1000
        )
        if not isfinite(requested) or requested < 0:
            return {"error": "Water request must be finite and nonnegative"}
        remaining = self._pool_capacity_m3 - water_used_m3(self._pool_farms)
        if requested > remaining + 1e-8:
            return {
                "error": "Shared seasonal water supply exceeded",
                "requested_m3": requested,
                "remaining_m3": remaining,
            }
        # Base operation owns the sole quota update; refusal never debits a second ledger.
        return super()._start_irrigation(ridge_ids, duration_hours)


class OperatingAccounts(App):
    def __init__(self, scene):
        super().__init__("OperatingAccounts")
        self.scene = scene

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_accounts(self) -> dict:
        """Read public prices, actual material consumption, crop revenue and net operating margin.

        Stored grain is valued at fixed crop-specific prices; no sale or cash
        receipt is implied. Unused warehouse/machine inputs remain assets.
        Costs exclude land rent, labour, equipment depreciation and taxes.
        """
        return self.compute_accounts()

    def compute_accounts(self):
        """Pure snapshot used by evaluation; no tool event or state mutation."""
        scene = self.scene
        tractor, warehouse, prices = scene.tractor, scene.warehouse, scene.prices
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
            + scene.initial_machine_fuel
            - warehouse.stock.fuel_liters
            - tractor._fuel_tank_l
        )
        water = water_used_m3(scene.farms)
        yields = {farm.crop_id: 0.0 for farm in scene.farms}
        for batch in warehouse.grain_batches.values():
            if batch.status == "stored":
                yields[batch.crop_id] += batch.quantity_kg
        # The warehouse records actual processing throughput, including its skip
        # and rejection rules; a batch flag is not the consumption ledger.
        dried = sum(warehouse._drying_usage_by_date.values())
        costs = {
            "seed": seed_used["MAIZE_201"] * prices.maize_seed_per_unit
            + seed_used["SOYBEAN_901"] * prices.soybean_seed_per_unit,
            "fertilizer": fertilizer * prices.fertilizer_per_kg,
            "fuel": fuel * prices.fuel_per_liter,
            "water": water * prices.water_per_m3,
            "drying": dried * prices.drying_per_kg,
        }
        revenue = (
            yields["maize"] * prices.maize_per_kg
            + yields["soybean"] * prices.soybean_per_kg
        )
        return {
            "currency": "DEMO",
            "prices": asdict(prices),
            "stored_kg_by_crop": yields,
            "consumed_seeds": seed_used,
            "fertilizer_product_kg": fertilizer,
            "fuel_liters": fuel,
            "water_m3": water,
            "shared_water_capacity_m3": scene.water_capacity_m3,
            "shared_water_remaining_m3": scene.water_capacity_m3 - water,
            "drying_throughput_kg": dried,
            "cost_components": costs,
            "production_cost": sum(costs.values()),
            "stored_grain_value": revenue,
            "net_operating_margin": revenue - sum(costs.values()),
        }
