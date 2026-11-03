"""Dated fertilizer offers, actual cash purchases and conserved material-cost lots."""

from copy import deepcopy
from math import isfinite

from fairy.apps.app import App
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered
from ..china_market_prices import PRICE_BOOK_ID, CNY_PER_USD


class FertilizerMarket(App):
    def __init__(
        self, farm, tractor, *, cash, initial_fertilizer_kg, initial_unit_cost, offers
    ):
        super().__init__("FertilizerMarket")
        self.farm = farm
        self.tractor = tractor
        self.initial_cash = float(cash)
        self.cash = float(cash)
        self.offers = deepcopy(offers)
        self.orders = {}
        self.initial_lot = {
            "kg": float(initial_fertilizer_kg),
            "unit_cost": float(initial_unit_cost),
        }

    def get_state(self):
        return {"cash": self.cash, "orders": deepcopy(self.orders)}

    def load_state(self, state):
        self.cash = float(state["cash"])
        self.orders = deepcopy(state["orders"])
        if (
            self.cash < 0
            or abs(
                self.cash
                + sum(o["paid"] for o in self.orders.values())
                - self.initial_cash
            )
            > 1e-7
        ):
            raise ValueError("Invalid fertilizer cash checkpoint")

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_offers(self) -> dict:
        """Read announced fertilizer quotes and remaining purchase cash.

        Returns:
            dict: ISO date, USD cash and offers with offer_id, announced_on,
            valid_from/valid_until and unit_price (USD/kg fertilizer product).
            Announced offers may be expired or not yet valid; check dates.
            Includes price_book_id, source and fixed cny_per_usd conversion.
        """
        today = self.farm.simulation_date(self.time_manager.time()).isoformat()
        return {
            "currency": "USD",
            "price_book_id": PRICE_BOOK_ID,
            "cny_per_usd": CNY_PER_USD,
            "date": today,
            "cash": self.cash,
            "offers": [deepcopy(o) for o in self.offers if o["announced_on"] <= today],
            "quote_source": "Supplier contracts anchored to the 2025 Jilin urea benchmark; advance discount is a declared contract assumption, not an observed historical rise",
        }

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def purchase_fertilizer(self, offer_id: str, kg: float, order_id: str) -> dict:
        """Buy fertilizer into warehouse stock; apply it separately.

        Prerequisites:
            Announced offer valid today (inclusive dates) and enough purchase cash.
            Buying does not increase field-use allowances.

        Args:
            offer_id: Exact offer_id from get_offers.
            kg: Finite positive product kg, not kg nitrogen.
            order_id: Client-chosen order ID; identical offer/kg retries return the
                original receipt without charging again, including after expiry.

        Returns:
            dict: IDs, product kg, unit_cost (USD/kg), paid (USD) and ISO purchase date.
        """
        if order_id in self.orders:
            old = self.orders[order_id]
            if old["offer_id"] != offer_id or old["kg"] != kg:
                raise ValueError("Cannot change an existing order")
            return deepcopy(old)
        if (
            not isinstance(kg, (int, float))
            or isinstance(kg, bool)
            or not isfinite(kg)
            or kg <= 0
        ):
            raise ValueError("Purchase quantity must be finite and positive")
        today = self.farm.simulation_date(self.time_manager.time()).isoformat()
        offer = next((o for o in self.offers if o["offer_id"] == offer_id), None)
        if (
            offer is None
            or today < offer["announced_on"]
            or not offer["valid_from"] <= today <= offer["valid_until"]
        ):
            raise ValueError("Offer is unavailable on the current simulated date")
        total = float(kg) * offer["unit_price"]
        if total > self.cash + 1e-8:
            raise ValueError("Insufficient fertilizer purchase cash")
        receipt = {
            "currency": "USD",
            "offer_id": offer_id,
            "order_id": order_id,
            "kg": float(kg),
            "unit_cost": offer["unit_price"],
            "paid": total,
            "date": today,
        }
        # Decimal-derived USD unit prices can leave a negative floating-point
        # residue after an exactly affordable order; keep checkpoints nonnegative.
        self.cash = max(0.0, self.cash - total)
        self.farm._inventory.fertilizer_kg += float(kg)
        self.orders[order_id] = receipt
        return deepcopy(receipt)

    def consumed_cost(self):
        """FIFO cost of physically applied product; unloaded/unused lots remain inventory assets."""
        used = self.farm._management_regime.fertilizer_used_kg
        cost = 0.0
        lots = [self.initial_lot] + [
            {"kg": o["kg"], "unit_cost": o["unit_cost"]} for o in self.orders.values()
        ]
        for lot in lots:
            amount = min(used, lot["kg"])
            cost += amount * lot["unit_cost"]
            used -= amount
        if used > 1e-7:
            raise ValueError("Applied fertilizer exceeds accounted stock and purchases")
        return cost

    def compute_purchase_accounts(self) -> dict:
        """Separate purchase cash expenditure, actual consumed cost and unused inventory book value."""
        purchased = sum(o["kg"] for o in self.orders.values())
        used = self.farm._management_regime.fertilizer_used_kg
        real_unused = (
            self.farm._inventory.fertilizer_kg + self.tractor._fertilizer_spreader_kg
        )
        if abs(self.initial_lot["kg"] + purchased - used - real_unused) > 1e-6:
            raise ValueError("Fertilizer material balance failed")
        asset_total = self.initial_lot["kg"] * self.initial_lot["unit_cost"] + sum(
            o["paid"] for o in self.orders.values()
        )
        return {
            "currency": "USD",
            "price_book_id": PRICE_BOOK_ID,
            "cny_per_usd": CNY_PER_USD,
            "cash": self.cash,
            "purchase_payments": sum(o["paid"] for o in self.orders.values()),
            "consumed_cost": self.consumed_cost(),
            "unused_product_kg": real_unused,
            "unused_inventory_book_value": asset_total - self.consumed_cost(),
            "orders": deepcopy(self.orders),
        }

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_purchase_accounts(self) -> dict:
        """Read fertilizer cash, consumption cost and unused inventory separately.

        Returns:
            dict: USD cash, purchase_payments, consumed_cost (FIFO) and
            unused_inventory_book_value; unused_product_kg includes warehouse and
            spreader stock. orders holds product kg, USD/kg price, USD payment and
            ISO purchase dates. Unused purchases are assets, not consumed cost.
        """
        return self.compute_purchase_accounts()
