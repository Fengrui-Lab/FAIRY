"""Public season lifecycle with conserved soil, stocks and equipment state."""

from copy import deepcopy
from datetime import date
from fairy.apps.app import App
from fairy.apps.farm_world import FarmWorldApp
from fairy.apps.farm_world.crop_dynamics import create_crop_dynamics
from fairy.tool_utils import app_tool, OperationType
from fairy.types import event_registered
from .backend import ContinuousSeasonBackend


class ContinuousFarm(FarmWorldApp):
    def load_state(self, state_dict):
        state = deepcopy(state_dict)
        raw = state["physics_state"]["crop_backend_state"]
        backend = ContinuousSeasonBackend.from_state(raw)
        # The shared farm codec owns all other state. Restore it with an empty
        # valid native history, then attach our already-verified local codec.
        placeholder = deepcopy(raw)
        placeholder.update(runs={}, last_day=None, pending={}, preplant_totals={})
        state["physics_state"]["crop_backend_state"] = placeholder
        super().load_state(state)
        params = self.physics.yield_recovery.params
        self.physics.crop_backend = backend
        backend.bind_physics(self.physics)
        self.physics.yield_recovery.params = params


class SeasonCycle(App):
    def __init__(self, farm, tractor):
        super().__init__("SeasonCycle")
        self.farm, self.tractor = farm, tractor
        self.current_year = 2026
        self.closed = []
        self.opened = [2026]

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
        """Read actual completed-season grain and remaining whole-horizon resources."""
        return {**self.get_state(), "inventory": self.farm.get_inventory()}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def close_season(self, year: int) -> dict:
        """Close a truly harvested, unloaded and stored season; never create grain.

        Args:
            year: Calendar year of the crop actually harvested this season.
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
        if today.year != year or today > date(year, 10, 31):
            raise ValueError(
                "Harvest and close the season by October 31 of its stated year"
            )
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
        self.closed.append(record)
        return deepcopy(record)

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def open_next_season(self, year: int) -> dict:
        """Start the next annual crop ledger after real harvest; preserve live soil and stocks.

        All intervening days must already have run. The new sowing window is
        seven days. Whole-horizon consumed counters persist; the newly available seasonal cap
        is bounded by the original 1200 kg / 400 mm horizon limits.

        Args:
            year: Next calendar crop year, fixed to 2027 in this experiment.
        """
        if year != self.current_year + 1 or year != 2027 or len(self.closed) != 1:
            raise ValueError("Close the first season before opening 2027")
        today = self.farm.simulation_date(self.time_manager.time())
        if today.year != year or today.month != 5:
            raise ValueError("This scenario opens its second crop in May 2027")
        if not all(r.harvested for r in self.farm._ridges):
            raise ValueError("Previous crop was not fully harvested")
        if (
            self.tractor._seed_hopper
            or self.tractor._fertilizer_spreader_kg
            or self.tractor._grain_bin_kg
        ):
            raise ValueError("Settle device payload before opening the next crop")
        physics = self.farm.physics
        backend = physics.crop_backend
        backend.authorize_next_season(physics, range(self.farm.num_ridges), today)
        soil_before = {
            rid: backend._soil_pools(run.model) for rid, run in backend._runs.items()
        }
        inventory = deepcopy(self.farm._inventory.to_dict())
        fuel = self.tractor._fuel_tank_l
        params = physics.yield_recovery.params
        physics.crop = create_crop_dynamics(None, physics.num_ridges, crop_type="maize")
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
        regime.fertilizer_quota_kg = min(1200.0, regime.fertilizer_used_kg + 800.0)
        regime.irrigation_quota_mm_total = min(
            400.0, regime.irrigation_used_mm_total + 300.0
        )
        self.current_year = year
        self.opened.append(year)
        assert (
            inventory == self.farm._inventory.to_dict()
            and fuel == self.tractor._fuel_tank_l
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
