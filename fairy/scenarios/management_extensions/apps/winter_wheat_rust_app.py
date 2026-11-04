"""Wheat-only stripe rust observation, application and accounting."""

from copy import deepcopy
from datetime import datetime, timedelta
from math import isfinite

from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered

from ..china_market_prices import CNY_PER_USD
from ..engines.winter_wheat_stripe_rust import StripeRust
from ..engines.winter_wheat_wofost import WinterWheatBackend
from .crop_protection_app import CropProtection
from .winter_wheat_accounts_app import WinterWheatAccounts
from .winter_wheat_farm_app import WinterWheatFarm
from .winter_wheat_scouting_apps import WheatScoutRobot
from .winter_wheat_tractor_app import WinterWheatTractor

PRODUCT_ID = "tebuconazole_pd20180278"
CATALOG = {
    "treatment_type": "FUNGICIDE",
    "scope": "Domestic wheat rust label; daily sprayability is a rain/wind proxy. Price and effect are simulation assumptions.",
    "products": [
        {
            "product_id": PRODUCT_ID,
            "name": "戊唑醇 430 g/L 悬浮剂",
            "registration": "PD20180278",
            "source_url": "https://www.icama.cn/BasicdataSystem/pesticideRegistration/tagview.do?pdno=PD20180278",
            "target_crop": "winter_wheat",
            "target_pest": "wheat_rust",
            "frac_group": "3",
            "unit": "mL",
            "min_rate_per_ha": 180.0,
            "max_rate_per_ha": 270.0,
            "min_interval_days": 7,
            "max_applications": 2,
            "max_season_rate_per_ha": 540.0,
            "preharvest_interval_days": 35,
        }
    ],
    "simulation_assumptions": {
        "price_book_id": "winter_wheat_rust_simulated_usd_v1",
        "price_per_unit": {PRODUCT_ID: 0.024},
        "price_source": "Fixed USD benchmark quote, not an observed market price.",
        "cny_per_usd": CNY_PER_USD,
        "service_cost_per_ha": 32.0,
        "service_minutes_per_ha": 90,
        "carrier_water_l_per_ha": 675.0,
        "effect_source": "Declared equal suppression of new infection across the allowed rates. Existing lesions remain.",
    },
}


class StripeRustWheatFarm(WinterWheatFarm):
    def __init__(self, bundle, resources):
        self.rust = StripeRust(resources.block_count)
        super().__init__(bundle, resources)

    def advance_physics_time(self, target_sim_time=None):
        target = float(
            self.time_manager.time() if target_sim_time is None else target_sim_time
        )
        if self.farm_environment is not None and not self.farm_environment._syncing:
            return self.farm_environment.sync(target)
        old = self._physics.last_physics_sim_time
        if old is not None and target < old:
            raise ValueError("Cannot move wheat clock backwards")
        day = datetime.fromtimestamp(target, self.simulation_timezone).date()
        if day > self.bundle.season.deadline:
            raise ValueError("Winter-wheat season deadline exceeded")
        current = self.backends[0].next_day
        ticks = 0
        while current < day:
            self._advance_native_day(self.backends, self.rust, current)
            ticks += len(self.backends)
            current = self.backends[0].next_day
        self._sim_date = day.isoformat()
        self._physics.last_physics_sim_time = target
        self._sync_blocks()
        self._publish_weather(day)
        return {
            "status": "advanced",
            "block_day_ticks": ticks,
            "last_physics_sim_time": target,
        }

    def _advance_native_day(self, backends, rust, day):
        active = [
            b.values.get("DOE") is not None and b.maturity is None for b in backends
        ]
        factors = rust.advance_day(day, self.bundle.weather[day], active)
        for backend, factor in zip(backends, factors):
            backend.advance_day(assimilation_factor=factor)

    def project_biological_grain_kg(self, max_days):
        """Advance a clone of the entire field so continuing spread is represented."""

        def growing(backend):
            planted = backend.sown or any(
                action["kind"] == "sow" for action in backend.pending
            )
            return planted and backend.maturity is None

        backends = self.backends
        if any(growing(b) for b in backends) and not any(b.failed for b in backends):
            backends = [
                WinterWheatBackend.restore(b.bundle, b.export_state()) for b in backends
            ]
            rust = deepcopy(self.rust)
            current = backends[0].next_day
            end = min(
                current + timedelta(days=max_days),
                self.bundle.season.deadline + timedelta(days=1),
            )
            while current < end and any(growing(b) for b in backends):
                self._advance_native_day(backends, rust, current)
                current = backends[0].next_day
        return sum(
            (b.values.get("TWSO") or 0) * self.ridge_area_m2 / 10000 for b in backends
        )

    def _sync_blocks(self):
        super()._sync_blocks()
        for index, lesions in enumerate(self.rust.blocks):
            canopy = self._physics.canopy.states[index]
            if canopy.initialized:
                canopy.ndvi_proxy *= 1.0 - 0.9 * lesions.symptomatic

    def crop_backend_provenance(self):
        return {
            **super().crop_backend_provenance(),
            "stripe_rust": {
                "model": "fairy.wheat.stripe_rust.v1",
                "forcing": "daily rain, relative humidity and temperature wetness proxy",
                "assimilation": "native gross assimilation factor from symptomatic fraction",
                "parameters": "experimental and uncalibrated",
            },
        }

    def get_state(self):
        return {**super().get_state(), "stripe_rust": self.rust.get_state()}

    def load_state(self, state):
        rust = deepcopy(self.rust)
        rust.load_state(state["stripe_rust"])
        super().load_state(state)
        self.rust = rust
        self._sync_blocks()


class StripeRustRobot(WheatScoutRobot):
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def inspect_blocks(self, start_block: int, end_block: int) -> dict:
        """Sample wheat leaves and check visible stripe-like symptoms.

        Args:
            start_block: First block to visit, inclusive.
            end_block: Last block to visit, inclusive. Each visit uses 20% battery.

        Returns:
            Covered blocks, crop stage, SPAD proxy and sampled leaf counts.
            A leaf sample reports visible pustules only. Check neighboring
            blocks and repeat if coverage or evidence is insufficient.
        """
        return super().inspect_blocks(start_block, end_block)

    def _observe_generic_ridge(self, farm, ridge_id, traits):
        row = super()._observe_generic_ridge(farm, ridge_id, traits)
        if not row["emerged"]:
            return row
        leaves = 30
        fraction = farm.world.rust.blocks[ridge_id].symptomatic
        affected = sum(self.rng.random() < fraction for _ in range(leaves))
        return {
            **row,
            "disease_detected": affected > 0,
            "leaf_sample": {
                "leaves_examined": leaves,
                "leaves_with_yellow_stripe_pustules": affected,
                "visible_sign": "yellow pustules in rows along the leaf veins"
                if affected
                else None,
            },
        }


class WheatRustProtection(CropProtection):
    def __init__(self, farm, weather):
        super().__init__(farm, weather, CATALOG, purchase_cash=100.0)
        self.tool_allowlist = {
            "get_products",
            "purchase",
            "spray_blocks",
            "get_protection_accounts",
        }

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def spray_blocks(
        self,
        product_id: str,
        start_block: int,
        end_block: int,
        rate_per_ha: float,
        application_id: str,
    ) -> dict:
        """Apply a contracted wheat-rust spray to adjacent blocks in dry, low-wind weather.

        Args:
            product_id: Exact catalogue ID. Check crop, rate, interval and stock.
            start_block: First emerged, unharvested block ID, inclusive.
            end_block: Last block ID, inclusive, at most four blocks per pass.
            rate_per_ha: Formulated product in mL/ha within the catalogue range.
            application_id: Unique ID. Identical retries return the previous receipt.

        Returns:
            Treated block IDs, product mL, service cost in USD and first legal
            harvest date. Allow native days to advance before checking new symptoms.
        """
        product = self._product(product_id)
        if not isinstance(application_id, str) or not application_id.strip():
            raise ValueError("Application ID is required")
        if (
            type(start_block) is not int
            or type(end_block) is not int
            or not (
                0 <= start_block <= end_block < self.farm.num_ridges
                and end_block - start_block < 4
            )
        ):
            raise ValueError("Select one to four contiguous wheat blocks")
        if (
            type(rate_per_ha) not in (int, float)
            or not isfinite(rate_per_ha)
            or not (
                product["min_rate_per_ha"] <= rate_per_ha <= product["max_rate_per_ha"]
            )
        ):
            raise ValueError("Use the catalogue rate in formulated product mL/ha")
        blocks = list(range(start_block, end_block + 1))
        old = self.applications.get(application_id)
        if old:
            if (old["product_id"], old["ridge_ids"], old["rate_per_ha"]) != (
                product_id,
                blocks,
                rate_per_ha,
            ):
                raise ValueError("Application ID reused with different inputs")
            return self._public_receipt(old)
        self.farm.advance_physics_time()
        if not self.weather.is_sprayable:
            raise ValueError("Current rain or wind prevents the spray service")
        if any(
            not self.farm._ridges[i].planted
            or self.farm._ridges[i].harvested
            or self.farm.backends[i].maturity is not None
            or self.farm.backends[i].values.get("DOE") is None
            for i in blocks
        ):
            raise ValueError(
                "Spraying requires emerged, unharvested wheat before maturity"
            )
        timestamp = self.time_manager.time()
        today = self.farm.simulation_date(timestamp)
        for index in blocks:
            prior = [r for r in self.applications.values() if index in r["ridge_ids"]]
            if len(prior) >= product["max_applications"]:
                raise ValueError("Wheat maximum application count reached")
            if any(
                (today - self.farm.simulation_date(r["timestamp"])).days
                < product["min_interval_days"]
                for r in prior
            ):
                raise ValueError("Wheat application interval has not elapsed")
        area = len(blocks) * self.farm.ridge_area_m2 / 10000
        quantity = area * rate_per_ha
        service = area * self.quotes["service_cost_per_ha"]
        if quantity > self.stock[product_id] + 1e-9 or service > self.cash + 1e-9:
            raise ValueError("Insufficient product stock or service cash")
        duration = area * self.quotes["service_minutes_per_ha"] * 60
        if self.farm.simulation_date(timestamp + duration) != today:
            raise ValueError("The spray pass must finish on the current day")
        receipt = {
            "application_id": application_id,
            "product_id": product_id,
            "ridge_ids": blocks,  # Existing ledger and harvest guard consume this key.
            "rate_per_ha": rate_per_ha,
            "area_ha": area,
            "product_quantity": quantity,
            "unit": product["unit"],
            "product_consumed_cost": quantity
            * self.quotes["price_per_unit"][product_id],
            "service_cost": service,
            "carrier_water_liters": area * self.quotes["carrier_water_l_per_ha"],
            "timestamp": timestamp,
            "harvest_allowed_from": (
                today + timedelta(days=product["preharvest_interval_days"])
            ).isoformat(),
        }
        self.farm.farm_environment.advance_time(duration)
        self.farm.rust.apply(blocks, today)
        self.stock[product_id] = max(0.0, self.stock[product_id] - quantity)
        self.cash = max(0.0, self.cash - service)
        self.applications[application_id] = receipt
        self.is_state_modified = True
        return self._public_receipt(receipt)

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_protection_accounts(self) -> dict:
        """Read USD cash, product stock in mL and the spray-service ledger.

        Returns:
            Cash, payments, consumed product and service costs, unused product
            value, and receipts keyed by application ID. Receipts list treated
            blocks, product dose in mL/ha and the first legal harvest date.
        """
        accounts = self.compute_accounts()
        accounts["applications"] = {
            key: self._public_receipt(row)
            for key, row in accounts["applications"].items()
        }
        return accounts

    @staticmethod
    def _public_receipt(receipt):
        result = deepcopy(receipt)
        result["block_ids"] = result.pop("ridge_ids")
        return {"status": "ok", **result}


class StripeRustWheatTractor(WinterWheatTractor):
    protection = None

    def _operate_harvest(self, farm, start_ridge, end_ridge):
        restriction = self.protection.harvest_restriction(
            range(start_ridge, end_ridge + 1)
        )
        if restriction:
            return {"error": restriction}
        return super()._operate_harvest(farm, start_ridge, end_ridge)


class StripeRustAccounts(WinterWheatAccounts):
    protection = None

    def compute_accounts(self):
        account = super().compute_accounts()
        protection = self.protection.compute_accounts()
        account["crop_protection"] = protection
        account["cost_components"]["fungicide_product"] = protection[
            "consumed_product_cost"
        ]
        account["cost_components"]["crop_protection_service"] = protection[
            "service_cost"
        ]
        account["production_cost"] += protection["total_consumed_cost"]
        account["net_operating_margin"] -= protection["total_consumed_cost"]
        return account
