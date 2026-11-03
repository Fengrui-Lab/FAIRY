"""Product-aware purchases and contracted crop protection for opt-in scenarios.

Manufacturer directions, declared supplier quotes and FAIRY's existing reduced
biotic effect are distinct inputs. No real-product efficacy coefficients are
invented here. Product is measured in g or mL; carrier water is never product.
"""

import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from math import isclose, isfinite

from fairy.apps.app import App
from fairy.physics.biotic_pressure_engine import TreatmentApplication, TreatmentType
from fairy.scenarios.management_extensions.runtime import PlanningTractor
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered

from .operating_accounts_app import OperatingAccounts


class CropProtection(App):
    def __init__(self, farm, weather, catalog, *, purchase_cash):
        super().__init__("CropProtection")
        self.treatment_type = TreatmentType(
            catalog.get("treatment_type", "INSECTICIDE")
        )
        self.farm = farm
        self.weather = weather
        self.catalog = deepcopy(catalog)
        self.catalog_fingerprint = hashlib.sha256(
            json.dumps(self.catalog, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        self.products = {p["product_id"]: p for p in self.catalog["products"]}
        self.quotes = self.catalog["simulation_assumptions"]
        self.initial_cash = float(purchase_cash)
        self.cash = self.initial_cash
        self.stock = {key: 0.0 for key in self.products}
        self.orders = {}
        self.applications = {}

    def get_state(self):
        return {
            "schema": 1,
            "catalog_fingerprint": self.catalog_fingerprint,
            "cash": self.cash,
            "stock": deepcopy(self.stock),
            "orders": deepcopy(self.orders),
            "applications": deepcopy(self.applications),
        }

    def load_state(self, state):
        state = deepcopy(state)
        if (
            state.get("schema") != 1
            or state.get("catalog_fingerprint") != self.catalog_fingerprint
            or set(state["stock"]) != set(self.products)
        ):
            raise ValueError("Crop-protection checkpoint has another product catalogue")
        cash = float(state["cash"])
        if not isfinite(cash) or cash < -1e-8:
            raise ValueError("Invalid crop-protection cash checkpoint")
        payments = sum(row["paid"] for row in state["orders"].values())
        service = sum(row["service_cost"] for row in state["applications"].values())
        if abs(cash + payments + service - self.initial_cash) > 1e-8:
            raise ValueError("Crop-protection cash balance failed")
        for key, amount in state["stock"].items():
            purchased = sum(
                r["quantity"]
                for r in state["orders"].values()
                if r["product_id"] == key
            )
            applied = sum(
                r["product_quantity"]
                for r in state["applications"].values()
                if r["product_id"] == key
            )
            if (
                not isfinite(amount)
                or amount < -1e-8
                or abs(purchased - applied - amount) > 1e-8
            ):
                raise ValueError("Crop-protection product balance failed")
        self.cash = cash
        self.stock = state["stock"]
        self.orders = state["orders"]
        self.applications = state["applications"]

    def _product(self, product_id):
        if product_id not in self.products:
            raise ValueError("Choose a product_id returned by get_products")
        return self.products[product_id]

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_products(self) -> dict:
        """Read available products, dose restrictions and USD quotes before buying or spraying.

        Returns:
            dict: products with product_id, crop, unit (g or mL formulated product),
            dose/season limits (unit/ha), intervals and preharvest days.
            price_per_unit_usd and minimum full-field quantity/cost use field_area_ha;
            cash is USD. simulation_assumptions gives service USD/ha, carrier L/ha,
            minutes/ha and simulated effects. Product directions and price/effect
            assumptions are identified separately.
        """
        area = self.farm.field_area_m2 / 10000
        products = []
        for key, product in self.products.items():
            price = self.quotes["price_per_unit"][key]
            products.append(
                {
                    **deepcopy(product),
                    "price_per_unit_usd": price,
                    "minimum_full_field_quantity": product["min_rate_per_ha"] * area,
                    "minimum_full_field_product_cost_usd": product["min_rate_per_ha"]
                    * area
                    * price,
                }
            )
        return {
            "currency": "USD",
            "price_book_id": self.quotes["price_book_id"],
            "cny_per_usd": self.quotes["cny_per_usd"],
            "products": products,
            "field_area_ha": area,
            "simulation_assumptions": deepcopy(self.quotes),
            "direction_scope": self.catalog["scope"],
            "cash": self.cash,
        }

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def scout(self) -> dict:
        """Inspect planted ridges for current growth stages and pest/disease pressure.

        Returns:
            dict: ISO date and zero-based ridge observations with unitless pressure
            and residual protection days. Insecticide scenes include aphid-equivalents
            per plant and affected fraction (0-1); fungicide scenes include mean
            disease pressure. diagnostic_basis describes the simulated observations.
            No time advance.
        """
        self.farm.advance_physics_time()
        physics = self.farm.physics
        if self.treatment_type == TreatmentType.FUNGICIDE:
            rows = [
                {
                    "ridge_id": rid,
                    "growth_stage": self.farm._ridges[rid].growth_stage,
                    "disease_pressure": state.disease_pressure,
                    "fungicide_residual_days_left": state.fungicide_residual_days_left,
                }
                for rid, state in physics.biotic.states.items()
            ]
            return {
                "date": self.farm.simulation_date(self.time_manager.time()).isoformat(),
                "ridges": rows,
                "mean_disease_pressure": sum(r["disease_pressure"] for r in rows)
                / len(rows),
                "diagnostic_basis": "Reduced disease-severity model, not measured infection counts",
                "scouting_reference": deepcopy(self.catalog["observation_reference"]),
            }
        rows = [
            {
                "ridge_id": rid,
                "growth_stage": self.farm._ridges[rid].growth_stage,
                "insect_pressure": state.insect_pressure,
                "aphid_equivalent_per_plant": physics.biotic._aphid_equivalent(
                    state.insect_pressure
                ),
                "insecticide_residual_days_left": state.insecticide_residual_days_left,
            }
            for rid, state in physics.biotic.states.items()
        ]
        return {
            "date": self.farm.simulation_date(self.time_manager.time()).isoformat(),
            "ridges": rows,
            "mean_aphid_equivalent_per_plant": sum(
                r["aphid_equivalent_per_plant"] for r in rows
            )
            / len(rows),
            "affected_ridge_fraction": sum(r["insect_pressure"] > 0 for r in rows)
            / len(rows),
            "diagnostic_basis": "Reduced pressure model; not measured aphid counts or a plant-level infestation sample",
            "scouting_reference": deepcopy(self.catalog["observation_reference"]),
        }

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def purchase(self, product_id: str, quantity: float, order_id: str) -> dict:
        """Buy formulated product into stock; unused product remains an asset.

        Prerequisites:
            Enough app cash; reserve cash for later spray service.

        Args:
            product_id: Exact product_id from get_products.
            quantity: Finite positive product amount in its catalogue unit (g or mL).
            order_id: Nonempty client-chosen ID; reuse only for identical product
                and quantity to retrieve the receipt without another charge.

        Returns:
            dict: order_id, product_id, quantity, unit, paid (USD) and currency.
        """
        product = self._product(product_id)
        if not isinstance(order_id, str) or not order_id.strip():
            raise ValueError("A nonempty order_id is required")
        if order_id in self.orders:
            old = self.orders[order_id]
            if old["product_id"] != product_id or old["quantity"] != quantity:
                raise ValueError("Cannot change an existing order")
            return deepcopy(old)
        if (
            type(quantity) not in (int, float)
            or not isfinite(quantity)
            or quantity <= 0
        ):
            raise ValueError("Product quantity must be finite and positive")
        price = self.quotes["price_per_unit"][product_id]
        paid = quantity * price
        if paid > self.cash + 1e-9:
            raise ValueError("Insufficient crop-protection purchase cash")
        receipt = {
            "order_id": order_id,
            "product_id": product_id,
            "quantity": quantity,
            "unit": product["unit"],
            "paid": paid,
            "currency": "USD",
        }
        self.cash -= paid
        self.stock[product_id] += quantity
        self.orders[order_id] = receipt
        self.is_state_modified = True
        return deepcopy(receipt)

    def harvest_restriction(self, ridge_ids):
        today = self.farm.simulation_date(self.time_manager.time())
        for row in self.applications.values():
            if (
                set(row["ridge_ids"]).intersection(ridge_ids)
                and today.isoformat() < row["harvest_allowed_from"]
            ):
                return f"Crop-protection preharvest interval: harvest allowed from {row['harvest_allowed_from']}"
        return None

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply(
        self,
        product_id: str,
        start_ridge: int,
        end_ridge: int,
        rate_per_ha: float,
        application_id: str,
    ) -> dict:
        """Apply one ground-spray pass to 1-4 contiguous ridges; advances service time.

        Prerequisites:
            Planted, unharvested target crop; suitable weather, product stock and
            service cash. Follow get_products dose, interval, season, application-count
            and consecutive-use limits, including shared FRAC groups. Check prior
            applications in get_protection_accounts. Service supplies carrier water,
            fuel and labour; harvest only from harvest_allowed_from.

        Args:
            product_id: Exact product_id from get_products.
            start_ridge: First zero-based local ridge ID, inclusive.
            end_ridge: Last ridge ID, inclusive; start_ridge <= end_ridge <= start_ridge+3.
            rate_per_ha: Finite formulated-product dose in g/ha or mL/ha, within
                the product's inclusive min/max range.
            application_id: Nonempty client ID; identical retries do not charge,
                treat or advance time again.

        Returns:
            dict: Applied ridges, area_ha, product_quantity/unit, consumed/service
            costs (USD), carrier water (L), Unix timestamp and harvest_allowed_from
            (inclusive ISO date).
        """
        product = self._product(product_id)
        if not isinstance(application_id, str) or not application_id.strip():
            raise ValueError("A nonempty application_id is required")
        if application_id in self.applications:
            old = self.applications[application_id]
            if (old["product_id"], old["ridge_ids"], old["rate_per_ha"]) != (
                product_id,
                list(range(start_ridge, end_ridge + 1)),
                rate_per_ha,
            ):
                raise ValueError("Cannot change an existing application")
            return {"status": "ok", **deepcopy(old)}
        if (
            type(start_ridge) is not int
            or type(end_ridge) is not int
            or not 0 <= start_ridge <= end_ridge < self.farm.num_ridges
            or end_ridge - start_ridge >= 4
        ):
            raise ValueError("Select1–4 contiguous actual ridges")
        if (
            type(rate_per_ha) not in (int, float)
            or not isfinite(rate_per_ha)
            or not product["min_rate_per_ha"] - 1e-9
            <= rate_per_ha
            <= product["max_rate_per_ha"] + 1e-9
        ):
            raise ValueError(
                f"Rate must be within retained product directions in {product['unit']}/ha"
            )
        self.farm.advance_physics_time()
        ridge_ids = list(range(start_ridge, end_ridge + 1))
        if self.farm.crop_id != product["target_crop"] or any(
            not self.farm._ridges[r].planted or self.farm._ridges[r].harvested
            for r in ridge_ids
        ):
            raise ValueError(
                "Apply only to an actual planted, unharvested soybean crop"
            )
        if not self.weather.is_sprayable:
            raise ValueError("Current rain/wind conditions do not permit spraying")
        today = self.farm.simulation_date(self.time_manager.time())
        for rid in ridge_ids:
            previous_service = sorted(
                (r for r in self.applications.values() if rid in r["ridge_ids"]),
                key=lambda r: r["timestamp"],
            )
            if any(
                (today - self.farm.simulation_date(r["timestamp"])).days
                < self.quotes["minimum_service_interval_days"]
                for r in previous_service
            ):
                raise ValueError(
                    "Contracted ground service allows one product per ridge per seven days"
                )
            prior = [
                r
                for r in self.applications.values()
                if r["product_id"] == product_id and rid in r["ridge_ids"]
            ]
            consecutive = 0
            for previous in reversed(previous_service):
                previous_product = self.products[previous["product_id"]]
                same_product = previous["product_id"] == product_id
                same_frac_group = (
                    product.get("frac_group") is not None
                    and previous_product.get("frac_group") == product["frac_group"]
                )
                if not (same_product or same_frac_group):
                    break
                consecutive += 1
            if consecutive >= product["max_consecutive_applications"]:
                raise ValueError(
                    "Retained consecutive-application limit reached; rotate mode of action"
                )
            if len(prior) >= product["max_applications"]:
                raise ValueError("Retained maximum application count reached")
            if any(
                (today - self.farm.simulation_date(r["timestamp"])).days
                < product["min_interval_days"]
                for r in prior
            ):
                raise ValueError("Retained minimum application interval not reached")
            if (
                sum(r["rate_per_ha"] for r in prior) + rate_per_ha
                > product["max_season_rate_per_ha"] + 1e-8
            ):
                raise ValueError("Retained seasonal product rate exceeded")
        area = len(ridge_ids) * self.farm.ridge_area_m2 / 10000
        quantity = rate_per_ha * area
        service = self.quotes["service_cost_per_ha"] * area
        if quantity > self.stock[product_id] + 1e-9:
            raise ValueError("Insufficient named product stock")
        if service > self.cash + 1e-9:
            raise ValueError("Insufficient contracted application cash")
        receipt = {
            "application_id": application_id,
            "product_id": product_id,
            "ridge_ids": ridge_ids,
            "area_ha": area,
            "rate_per_ha": rate_per_ha,
            "product_quantity": quantity,
            "unit": product["unit"],
            "product_consumed_cost": quantity
            * self.quotes["price_per_unit"][product_id],
            "service_cost": service,
            "carrier_water_liters": area * self.quotes["carrier_water_l_per_ha"],
            "timestamp": self.time_manager.time(),
            "harvest_allowed_from": (
                today + timedelta(days=product["preharvest_interval_days"])
            ).isoformat(),
            "effect_basis": self.quotes["effect_source"],
        }
        self.stock[product_id] = max(0.0, self.stock[product_id] - quantity)
        self.cash = max(0.0, self.cash - service)
        self.applications[application_id] = receipt
        for rid in ridge_ids:
            self.farm.physics.queue_treatment(
                rid,
                TreatmentApplication(
                    self.treatment_type, self.quotes["efficacy_multiplier"]
                ),
            )
        self.farm.advance_physics_time()
        self.farm.farm_environment.advance_time(
            area * self.quotes["service_minutes_per_ha"] * 60
        )
        self.is_state_modified = True
        return {"status": "ok", **deepcopy(receipt)}

    def compute_accounts(self):
        product = sum(r["product_consumed_cost"] for r in self.applications.values())
        service = sum(r["service_cost"] for r in self.applications.values())
        payments = sum(r["paid"] for r in self.orders.values())
        assets = sum(
            q * self.quotes["price_per_unit"][key] for key, q in self.stock.items()
        )
        if not isclose(payments, product + assets, abs_tol=1e-8):
            raise ValueError("Product payment/consumption/asset balance failed")
        return {
            "currency": "USD",
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "purchase_payments": payments,
            "consumed_product_cost": product,
            "service_cost": service,
            "total_consumed_cost": product + service,
            "unused_inventory_book_value": assets,
            "stock": deepcopy(self.stock),
            "applications": deepcopy(self.applications),
        }

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_protection_accounts(self) -> dict:
        """Read product stock, cash, consumed costs and application receipts.

        Returns:
            dict: USD cash, purchase_payments, consumed_product_cost, service_cost,
            total_consumed_cost and unused_inventory_book_value. stock uses product
            g/mL; unused stock is an asset. applications records ridge IDs, hectares,
            product-unit/ha doses, product quantity, carrier L, Unix timestamps and
            inclusive harvest_allowed_from dates for checking use/harvest limits.
        """
        return self.compute_accounts()


class CropProtectionAccounts(OperatingAccounts):
    """Extend the existing operating ledger only for this product-aware scene."""

    def __init__(self, *, protection, **kwargs):
        super().__init__(**kwargs)
        self.protection = protection

    def compute_accounts(self):
        account = super().compute_accounts()
        protection = self.protection.compute_accounts()
        account["crop_protection"] = protection
        account["cost_components"].update(
            **{
                (
                    "insecticide_product"
                    if self.protection.treatment_type == TreatmentType.INSECTICIDE
                    else "fungicide_product"
                ): protection["consumed_product_cost"]
            },
            crop_protection_service=protection["service_cost"],
        )
        account["production_cost"] += protection["total_consumed_cost"]
        account["net_operating_margin"] -= protection["total_consumed_cost"]
        return account


class CropProtectionTractor(PlanningTractor):
    """Apply the scene's product preharvest intervals before the existing harvest operation."""

    protection = None

    def _operate_harvest(self, farm, start_ridge, end_ridge):
        if (
            self.protection is not None
            and 0 <= start_ridge <= end_ridge < farm.world.num_ridges
        ):
            error = self.protection.harvest_restriction(
                range(start_ridge, end_ridge + 1)
            )
            if error:
                return {"error": error}
        return super()._operate_harvest(farm, start_ridge, end_ridge)
