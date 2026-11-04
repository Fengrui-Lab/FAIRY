"""Public annual crop choice, native soil continuity and crop-specific grain ledgers."""

from copy import deepcopy
from dataclasses import asdict, replace
from inspect import unwrap

from fairy.apps.farm_world.crop_dynamics import create_crop_dynamics
from fairy.apps.farm_world.crop_profiles import get_crop_profile
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered

from .season_cycle_app import SeasonCycle


class CropRotationApp(SeasonCycle):
    def __init__(
        self,
        farm,
        tractor,
        *,
        seasons,
        fertilizer_budget_kg,
        water_budget_mm,
        crop_configurations,
        prices,
        initial_inventory,
        first_crop_locked=True,
    ):
        super().__init__(
            farm,
            tractor,
            seasons=seasons,
            fertilizer_budget_kg=fertilizer_budget_kg,
            water_budget_mm=water_budget_mm,
        )
        self.name = "CropRotation"
        self.crop_configurations = deepcopy(crop_configurations)
        self.prices = deepcopy(prices)
        self.initial_inventory = deepcopy(initial_inventory)
        # Both seasons are captured before tools execute. Publish the declared
        # seed catalogue; native loading still validates the current field crop.
        declared_seeds = tuple(
            seed
            for config in self.crop_configurations.values()
            for seed in config["cultivar_map"]
        )
        self.tractor._tool_contract_context = replace(
            self.tractor._tool_contract_context, seed_types=lambda: declared_seeds
        )
        self.fertilizer_cost_reader = None
        self.current_crop = farm.crop_type
        self.initial_crop = farm.crop_type
        self.first_crop_locked = first_crop_locked

    def get_state(self):
        return {
            **super().get_state(),
            "current_crop": self.current_crop,
            "initial_crop": self.initial_crop,
            "first_crop_locked": self.first_crop_locked,
        }

    def load_state(self, state):
        super().load_state(state)
        self.current_crop = state["current_crop"]
        if (
            state.get("initial_crop") != self.initial_crop
            or state.get("first_crop_locked") != self.first_crop_locked
        ):
            raise ValueError(
                "Checkpoint changes the declared first-season crop obligation"
            )

    def _set_crop_views(self, crop_id):
        farm = self.farm
        physics = farm.physics
        backend = physics.crop_backend
        farm.crop_name = crop_id
        farm.variety_name = backend.config.variety_name
        farm._cultivar_id = "MAIZE_201" if crop_id == "maize" else "SOYBEAN_901"
        farm._rows_per_ridge_override = None
        physics.crop_type = crop_id
        physics.crop_profile = get_crop_profile(crop_id)
        physics.crop = create_crop_dynamics(None, physics.num_ridges, crop_type=crop_id)
        physics.phenology = physics.crop.phenology
        physics.canopy = physics.crop.canopy
        physics.yield_recovery = physics.crop.yield_recovery
        backend.bind_physics(physics)
        if crop_id == "soybean":
            physics.yield_recovery.params.grain_moisture_mode = "soybean_equilibrium"
        farm.configure_postharvest_market(
            market_moisture_pct=14.0 if crop_id == "maize" else 13.0,
            max_storage_moisture_pct=14.0 if crop_id == "maize" else 13.0,
        )
        farm._postharvest_market.require_safe_moisture = True
        self.tractor.configure_harvest(
            max_grain_moisture_pct=25.0 if crop_id == "maize" else 18.0
        )

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def select_first_crop(self, crop_id: str) -> dict:
        """Choose the first crop without changing soil or planting seed.

        Prerequisites:
            First season only, before growth or field work. If first_crop_locked,
            only first_crop is allowed; see get_crop_options.

        Args:
            crop_id: Key in get_crop_options.options, e.g. maize or soybean;
                use a crop ID, not a seed ID.

        Returns:
            dict: crop_id, official_variety and field_area_m2 (m2).
        """
        if self.first_crop_locked and crop_id != self.initial_crop:
            raise ValueError("First-season crop is a fixed planting obligation")
        if (
            self.closed
            or len(self.opened) != 1
            or self.farm.physics.crop_backend.has_started
            or self.farm._field_preparation_ops
            or any(r.planted for r in self.farm._ridges)
        ):
            raise ValueError(
                "Choose the first crop before native growth or field work begins"
            )
        if crop_id not in self.crop_configurations:
            raise ValueError("Choose a declared official crop")
        self.farm.physics.crop_backend._activate_configuration(
            self.crop_configurations[crop_id]
        )
        self._set_crop_views(crop_id)
        self.current_crop = crop_id
        return {
            "crop_id": crop_id,
            "official_variety": self.farm.physics.crop_backend.config.variety_name,
            "field_area_m2": self.farm.field_area_m2,
        }

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_crop_options(self) -> dict:
        """Read crop choices, prices, first-crop obligations and season limits.

        Returns:
            dict: options maps crop IDs to official configurations and cultivar_map
            seed IDs. prices are USD per kg, seed, L fuel or m3 water as named.
            first_crop_locked restricts the first crop. seasons gives ISO sowing/
            harvest dates, fertilizer-product kg and field-equivalent irrigation mm;
            opening requires the planned sowing month. land_area_m2 is actual area.
        """
        return {
            "options": deepcopy(self.crop_configurations),
            "prices": deepcopy(self.prices),
            "first_crop": self.initial_crop,
            "first_crop_locked": self.first_crop_locked,
            "land_area_m2": self.farm.field_area_m2,
            "seasons": [
                {
                    **asdict(s),
                    "sowing_date": s.sowing_date.isoformat(),
                    "harvest_deadline": s.harvest_deadline.isoformat(),
                }
                for s in self.seasons
            ],
        }

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def unload_unused_seeds(self) -> dict:
        """Return unused hopper seeds to this farm before changing crops.

        Returns:
            dict: seed_type, returned_count and remaining seed_hopper (seed counts).
            An empty hopper returns zero; inventory is conserved.
        """
        count = self.tractor._seed_hopper
        seed = self.tractor.seed_type
        if count and not seed:
            raise ValueError("Loaded seed must have an identity")
        if count:
            self.farm._inventory.seed_stock[seed] = (
                self.farm._inventory.seed_stock.get(seed, 0) + count
            )
            self.tractor._seed_hopper = 0
        return {
            "seed_type": seed,
            "returned_count": count,
            "seed_hopper": self.tractor._seed_hopper,
        }

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def close_season(self, year: int) -> dict:
        """Close the current crop season and record its safely stored grain batches.

        Prerequisites:
            All ridges mature, harvested, unloaded and safely stored; no pending grain.
            Close once in the crop's calendar year by harvest_deadline.

        Args:
            year: Current calendar year from get_season_ledger.current_year.

        Returns:
            dict: crop_id, seasonal/cumulative stored kg, dates, inventory and batches.
            Fertilizer-product kg and irrigation mm are cumulative; soil pools use
            cm water and kg N/ha. Batches identify the same grain, not extra yield.
        """
        record = unwrap(SeasonCycle.close_season)(self, year)
        batch = {
            "batch_id": f"{self.farm.farm_id}-{year}-{self.current_crop}",
            "origin_farm_id": self.farm.farm_id,
            "crop_id": self.current_crop,
            "variety_name": self.farm.physics.crop_backend.config.variety_name,
            "season": year,
            "quantity_kg": record["stored_grain_kg"],
            "market_moisture_pct": self.farm._postharvest_market.market_moisture_pct,
            "storage_limit_pct": self.farm._postharvest_market.max_storage_moisture_pct,
            "status": "stored",
        }
        self.closed[-1]["crop_id"] = self.current_crop
        self.closed[-1]["grain_batch"] = batch
        batches = [deepcopy(b) for b in self.farm.stored_batches if b["season"] == year]
        if (
            abs(sum(b["quantity_kg"] for b in batches) - record["stored_grain_kg"])
            > 1e-7
        ):
            raise ValueError(
                "Closed-season grain does not match crop-specific warehouse batches"
            )
        self.closed[-1]["grain_batches"] = batches
        record = deepcopy(self.closed[-1])
        record.pop("biological_grain_kg")
        record.pop("recovered_grain_kg")
        return record

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def open_next_crop(self, year: int, crop_id: str) -> dict:
        """Open the next crop season, preserving soil, land, stocks and input counters.

        Prerequisites:
            Previous season closed and grain unloaded; native clock advanced through
            fallow to the next sowing month/year. Return other-crop hopper seeds via
            unload_unused_seeds first. Opening clears field-work records; it does not
            sow or start a sowing countdown.

        Args:
            year: Next calendar year in get_crop_options.seasons.
            crop_id: Crop key in get_crop_options.options, e.g. maize or soybean.

        Returns:
            dict: year, crop_id, soil_and_area_preserved and inventory_preserved.
        """
        index = len(self.opened)
        if index >= len(self.seasons) or len(self.closed) != index:
            raise ValueError("Close the current safely stored season first")
        season = self.seasons[index]
        today = self.farm.simulation_date(self.time_manager.time())
        if (
            year != season.year
            or today.year != year
            or today.month != season.sowing_date.month
        ):
            raise ValueError("Open the next crop in its declared sowing month")
        if crop_id not in self.crop_configurations:
            raise ValueError("Choose a declared official crop")
        if (
            not all(r.harvested for r in self.farm._ridges)
            or self.tractor._grain_bin_kg
            or self.farm._inventory.harvest_grain_kg
        ):
            raise ValueError("Harvest, unload and store the previous crop first")
        if self.tractor._seed_hopper and self.current_crop != crop_id:
            raise ValueError("Return unused seed before changing crops")
        farm = self.farm
        physics = farm.physics
        backend = physics.crop_backend
        area = farm.field_area_m2
        inventory = deepcopy(farm._inventory.to_dict())
        soil_before = {
            rid: backend._soil_pools(run.model) for rid, run in backend._runs.items()
        }
        backend.authorize_next_crop(
            physics, range(farm.num_ridges), today, self.crop_configurations[crop_id]
        )
        self._set_crop_views(crop_id)
        for ridge in farm._ridges:
            ridge.harvested = False
            ridge.planted = False
            ridge.growth_stage = "NOT_PLANTED"
            ridge.yield_potential = 0
            ridge.seed_type = None
        farm._field_preparation_ops.clear()
        self.tractor._completed_prep_ops = []
        previous = self.closed[-1]
        regime = farm._management_regime
        regime.fertilizer_quota_kg = min(
            self.fertilizer_budget_kg,
            previous["fertilizer_used_kg_cumulative"] + season.fertilizer_limit_kg,
        )
        regime.irrigation_quota_mm_total = min(
            self.water_budget_mm,
            previous["irrigation_used_mm_cumulative"] + season.water_limit_mm,
        )
        self.current_year = year
        self.current_crop = crop_id
        self.opened.append(year)
        assert farm.field_area_m2 == area and inventory == farm._inventory.to_dict()
        assert soil_before == {
            rid: backend._soil_pools(run.model) for rid, run in backend._runs.items()
        }
        return {
            "year": year,
            "crop_id": crop_id,
            "soil_and_area_preserved": True,
            "inventory_preserved": True,
        }

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def open_next_season(self, year: int) -> dict:
        """Use open_next_crop(year, crop_id) in rotation scenes.

        Args:
            year: Proposed next calendar year.

        Returns:
            No receipt; always raises ValueError directing you to open_next_crop.
        """
        raise ValueError("Use CropRotation.open_next_crop(year, crop_id)")

    def compute_accounts(self):
        inventory = self.farm._inventory
        regime = self.farm._management_regime
        stored = {crop: 0.0 for crop in self.crop_configurations}
        for batch in self.farm.stored_batches:
            stored[batch["crop_id"]] += batch["quantity_kg"]
        seed_used = {}
        for seed, initial in self.initial_inventory["seed_stock"].items():
            hopper = self.tractor._seed_hopper if self.tractor.seed_type == seed else 0
            seed_used[seed] = initial - inventory.seed_stock.get(seed, 0) - hopper
        fertilizer = regime.fertilizer_used_kg
        fuel = (
            self.initial_inventory["fuel_liters"]
            + self.initial_inventory["machine_fuel_liters"]
            - inventory.fuel_liters
            - self.tractor._fuel_tank_l
        )
        water = regime.irrigation_used_mm_total * self.farm.field_area_m2 / 1000
        fertilizer_cost = (
            self.fertilizer_cost_reader()
            if self.fertilizer_cost_reader
            else fertilizer * self.prices["fertilizer_per_kg"]
        )
        costs = {
            "seed": sum(
                seed_used[k] * self.prices["seed_per_unit"][k] for k in seed_used
            ),
            "fertilizer": fertilizer_cost,
            "fuel": fuel * self.prices["fuel_per_liter"],
            "water": water * self.prices["water_per_m3"],
            "drying": self.farm.drying_throughput_kg * self.prices["drying_per_kg"],
        }
        value = sum(stored[c] * self.prices["crop_per_kg"][c] for c in stored)
        return {
            "currency": self.prices["currency"],
            "price_book_id": self.prices.get("price_book_id"),
            "cny_per_usd": self.prices.get("cny_per_usd"),
            "prices": deepcopy(self.prices),
            "stored_kg_by_crop": stored,
            "grain_batches": deepcopy(self.farm.stored_batches),
            "drying_throughput_kg": self.farm.drying_throughput_kg,
            "grain_value": value,
            "consumed_seeds": seed_used,
            "fertilizer_product_kg": fertilizer,
            "fuel_liters": fuel,
            "water_m3": water,
            "cost_components": costs,
            "production_cost": sum(costs.values()),
            "net_operating_margin": value - sum(costs.values()),
        }

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_accounts(self) -> dict:
        """Read multi-season consumption, crop-specific stored grain and USD margin.

        Returns:
            dict: USD prices/cost_components, production_cost, grain_value and
            net_operating_margin (value minus consumed costs, excluding subsidies).
            Quantities use seed counts, fertilizer-product kg, fuel L, water m3 and
            drying kg. grain_batches preserves crop/season identity. Unused fertilizer
            remains inventory; see FertilizerMarket accounts. Paid subsidies are
            reported separately by CropSubsidy.
        """
        return self.compute_accounts()
