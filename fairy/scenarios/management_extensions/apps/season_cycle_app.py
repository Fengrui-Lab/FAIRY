"""Public season lifecycle: close grain ledgers, preserve stocks, advance crop cycles."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, datetime, time

from fairy.apps.app import App
from fairy.apps.farm_world.crop_dynamics import create_crop_dynamics
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered

from ..evaluation.oracle_comparison import biological_grain_kg, recovered_grain_kg


@dataclass(frozen=True)
class AnnualCropSeason:
    sowing_date: date
    harvest_deadline: date
    fertilizer_limit_kg: float = 800.0
    water_limit_mm: float = 300.0

    @property
    def year(self):
        return self.sowing_date.year

    def __post_init__(self):
        if (
            self.harvest_deadline < self.sowing_date
            or self.harvest_deadline.year != self.year
        ):
            raise ValueError("An annual crop must close within its declared year")


class SeasonCycle(App):
    def __init__(
        self,
        farm,
        tractor,
        *,
        seasons: tuple[AnnualCropSeason, ...],
        fertilizer_budget_kg: float,
        water_budget_mm: float,
        prices=None,
    ):
        super().__init__("SeasonCycle")
        self.farm, self.tractor = farm, tractor
        self.prices = deepcopy(prices)
        self.initial_inventory = deepcopy(farm._inventory.to_dict())
        self.initial_machine_fuel = tractor._fuel_tank_l
        if not seasons:
            raise ValueError("At least one annual crop season is required")
        self.seasons = seasons
        self.fertilizer_budget_kg = fertilizer_budget_kg
        self.water_budget_mm = water_budget_mm
        self.current_year = seasons[0].year
        self.closed = []
        self.opened = [self.current_year]

    def get_state(self):
        return {
            "current_year": self.current_year,
            "closed": deepcopy(self.closed),
            "opened": list(self.opened),
        }

    def load_state(self, state):
        self.current_year = int(state["current_year"])
        self.closed = deepcopy(state["closed"])
        self.opened = list(state["opened"])

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_season_ledger(self) -> dict:
        """Read season history, current inventory and operating accounts.

        Returns:
            dict: current_year, opened years, closed-season harvest records and inventory.
            Grain/fertilizer use kg, fuel L, irrigation field-equivalent mm; closed
            input counters are cumulative. Native soil uses cm water and kg N/ha.
            Priced scenes include USD operating_accounts; rotation scenes include
            current_crop and first_crop_locked. seasons lists planned sowing and
            harvest dates, product kg and irrigation mm limits; fertilizer_budget_kg
            and water_budget_mm are whole-horizon caps. Dates are ISO dates.
        """
        result = {
            **self.get_state(),
            "inventory": self.farm.get_inventory(),
            "seasons": [
                {
                    **asdict(season),
                    "sowing_date": season.sowing_date.isoformat(),
                    "harvest_deadline": season.harvest_deadline.isoformat(),
                }
                for season in self.seasons
            ],
            "fertilizer_budget_kg": self.fertilizer_budget_kg,
            "water_budget_mm": self.water_budget_mm,
        }
        for row in result["closed"]:
            row.pop("biological_grain_kg", None)
            row.pop("recovered_grain_kg", None)
        if self.prices:
            result["operating_accounts"] = self.compute_accounts()
        return result

    def yield_seasons(self):
        """Include the current crop even when harvest or storage is unfinished."""
        if self.closed and self.closed[-1]["year"] == self.current_year:
            return self.closed
        season = self.seasons[len(self.closed)]
        deadline = datetime.combine(
            season.harvest_deadline, time.max, self.farm.simulation_timezone
        ).timestamp()
        return [
            *self.closed,
            {
                "year": self.current_year,
                "crop_id": self.farm.crop_id,
                "biological_grain_kg": biological_grain_kg(
                    self.farm, deadline=deadline
                ),
                "recovered_grain_kg": recovered_grain_kg(self.farm),
                "stored_grain_kg": self.farm._inventory.warehouse_grain_kg
                - sum(row["stored_grain_kg"] for row in self.closed),
            },
        ]

    def compute_accounts(self):
        """Actual same-crop USD accounts; rotation scenes override crop-grain attribution."""
        inventory, tractor, p = self.farm._inventory, self.tractor, self.prices
        used = {
            seed: initial
            - inventory.seed_stock.get(seed, 0)
            - (tractor._seed_hopper if tractor.seed_type == seed else 0)
            for seed, initial in self.initial_inventory["seed_stock"].items()
        }
        fertilizer = self.farm._management_regime.fertilizer_used_kg
        fuel = (
            self.initial_inventory["fuel_liters"]
            + self.initial_machine_fuel
            - inventory.fuel_liters
            - tractor._fuel_tank_l
        )
        water = (
            self.farm._management_regime.irrigation_used_mm_total
            * self.farm.field_area_m2
            / 1000
        )
        dried = self.farm.drying_throughput_kg
        costs = {
            "seed": sum(v * p["seed_per_unit"][k] for k, v in used.items()),
            "fertilizer": fertilizer * p["fertilizer_per_kg"],
            "fuel": fuel * p["fuel_per_liter"],
            "water": water * p["water_per_m3"],
            "drying": dried * p["drying_per_kg"],
        }
        stored = inventory.warehouse_grain_kg
        value = stored * p["crop_per_kg"][self.farm.crop_type]
        return {
            "currency": "USD",
            "price_book_id": p["price_book_id"],
            "cny_per_usd": p["cny_per_usd"],
            "prices": deepcopy(p),
            "stored_kg_by_crop": {self.farm.crop_type: stored},
            "grain_value": value,
            "consumed_seeds": used,
            "fertilizer_product_kg": fertilizer,
            "fuel_liters": fuel,
            "water_m3": water,
            "drying_throughput_kg": dried,
            "cost_components": costs,
            "production_cost": sum(costs.values()),
            "net_operating_margin": value - sum(costs.values()),
        }

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def close_season(self, year: int) -> dict:
        """Close the current season after mature grain is safely stored.

        Prerequisites:
            All ridges mature and harvested; tractor and pending grain empty.
            Close once, within that calendar year and by harvest_deadline.

        Args:
            year: Current calendar year from get_season_ledger.current_year.

        Returns:
            dict: Season grain kg, cumulative warehouse kg, dates, inventory and
            harvested ridges. Fertilizer-product kg and irrigation mm are cumulative;
            native_soil_pools uses cm water and kg N/ha.
        """
        if year != self.current_year or any(x["year"] == year for x in self.closed):
            raise ValueError("Season is not open")
        if not all(r.harvested for r in self.farm._ridges):
            raise ValueError("All ridges must actually be harvested")
        if (
            self.tractor._grain_bin_kg > 1e-8
            or self.farm._inventory.harvest_grain_kg > 1e-8
        ):
            raise ValueError("Unload and safely store all harvested grain first")
        today = self.farm.simulation_date(self.time_manager.time())
        season = self.seasons[len(self.closed)]
        if today.year != year or today > season.harvest_deadline:
            raise ValueError("Harvest and close the season by its declared deadline")
        backend = self.farm.physics.crop_backend
        if not all(
            run.maturity_snapshot and run.maturity_snapshot.get("DOM")
            for run in backend._runs.values()
        ):
            raise ValueError("Native physiological maturity must precede harvest")
        if not self.farm._postharvest_market.require_safe_moisture:
            raise ValueError("Strict safe-moisture storage is required")
        inventory = self.farm.get_inventory()
        total = inventory["warehouse_grain_kg"]
        prior = sum(x["stored_grain_kg"] for x in self.closed)
        if total <= prior:
            raise ValueError("This season produced no safely stored grain")
        record = {
            "year": year,
            "stored_grain_kg": total - prior,
            "warehouse_grain_kg_cumulative": total,
            "harvested_ridges": self.farm.num_ridges,
            "inventory": deepcopy(inventory),
            "closed_date": today.isoformat(),
            "planting_dates": sorted(
                {run.specification["planting_date"] for run in backend._runs.values()}
            ),
            "harvest_dates": sorted(
                {
                    state.harvest_date.isoformat()
                    for state in self.farm.physics.yield_recovery.states.values()
                    if state.harvest_date
                }
            ),
            "fertilizer_used_kg_cumulative": self.farm._management_regime.fertilizer_used_kg,
            "irrigation_used_mm_cumulative": self.farm._management_regime.irrigation_used_mm_total,
            "native_soil_pools": {
                str(rid): backend._soil_pools(run.model)
                for rid, run in backend._runs.items()
            },
        }
        self.closed.append(
            {
                **record,
                "biological_grain_kg": biological_grain_kg(self.farm),
                "recovered_grain_kg": recovered_grain_kg(self.farm),
            }
        )
        return deepcopy(record)

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def open_next_season(self, year: int) -> dict:
        """Open the next same-crop season, preserving soil, stocks and consumed-input counters.

        Prerequisites:
            Previous season closed, all ridges harvested and tractor grain empty.
            Advance the native clock through fallow to the next sowing month/year.
            Fallow inputs count toward the next allowance. Opening clears field-work
            records; it does not sow or start a sowing countdown.

        Args:
            year: Next planned calendar year; see get_season_ledger.

        Returns:
            dict: year and preservation flags. For crop changes use open_next_crop.
        """
        next_index = len(self.opened)
        if next_index >= len(self.seasons) or len(self.closed) != next_index:
            raise ValueError(
                "Close the current season before opening the next planned crop"
            )
        season = self.seasons[next_index]
        if year != season.year:
            raise ValueError("Requested year is not the next planned crop season")
        today = self.farm.simulation_date(self.time_manager.time())
        if today.year != year or today.month != season.sowing_date.month:
            raise ValueError("Open the next crop in its declared sowing month")
        if not all(r.harvested for r in self.farm._ridges):
            raise ValueError("Previous crop was not fully harvested")
        if self.tractor._grain_bin_kg:
            raise ValueError("Unload harvested grain before opening the next crop")
        physics = self.farm.physics
        backend = physics.crop_backend
        backend.authorize_next_season(physics, range(self.farm.num_ridges), today)
        soil_before = {
            rid: backend._soil_pools(run.model) for rid, run in backend._runs.items()
        }
        inventory = deepcopy(self.farm._inventory.to_dict())
        fuel = self.tractor._fuel_tank_l
        payloads = (
            self.tractor.seed_type,
            self.tractor._seed_hopper,
            self.tractor._fertilizer_spreader_kg,
        )
        params = physics.yield_recovery.params
        physics.crop = create_crop_dynamics(
            None, physics.num_ridges, crop_type=self.farm.crop_type
        )
        physics.phenology = physics.crop.phenology
        physics.canopy = physics.crop.canopy
        physics.yield_recovery = physics.crop.yield_recovery
        backend.bind_physics(physics)
        physics.yield_recovery.params = params
        for r in self.farm._ridges:
            r.harvested = False
            r.planted = False
            r.growth_stage = "NOT_PLANTED"
            r.yield_potential = 0
        self.farm._field_preparation_ops.clear()
        self.tractor._completed_prep_ops = []
        regime = self.farm._management_regime
        previous_close = self.closed[-1]
        regime.fertilizer_quota_kg = min(
            self.fertilizer_budget_kg,
            previous_close["fertilizer_used_kg_cumulative"]
            + season.fertilizer_limit_kg,
        )
        regime.irrigation_quota_mm_total = min(
            self.water_budget_mm,
            previous_close["irrigation_used_mm_cumulative"] + season.water_limit_mm,
        )
        self.current_year = year
        self.opened.append(year)
        assert (
            inventory == self.farm._inventory.to_dict()
            and fuel == self.tractor._fuel_tank_l
        )
        assert payloads == (
            self.tractor.seed_type,
            self.tractor._seed_hopper,
            self.tractor._fertilizer_spreader_kg,
        )
        assert soil_before == {
            rid: backend._soil_pools(run.model) for rid, run in backend._runs.items()
        }
        return {
            "year": year,
            "soil_preserved": True,
            "stocks_preserved": True,
            "whole_horizon_quotas_preserved": True,
        }
