"""Extend existing consumed-input accounts with separately delivered root revenue."""

from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered
from .operating_accounts_app import OperatingAccounts


class SugarBeetAccounts(OperatingAccounts):
    def __init__(self, *, resources, delivery, **kwargs):
        self.resources, self.delivery = resources, delivery
        super().__init__(prices=resources.operating_prices(), **kwargs)

    def compute_accounts(self):
        result = super().compute_accounts()
        root = self.delivery.ledger.totals()
        result["cost_components"]["root_transport"] = root["transport_usd"]
        result["production_cost"] += root["transport_usd"]
        result["delivered_root_value"] = root["revenue_usd"]
        result["delivered_root_net_kg"] = root["delivered_net_kg"]
        result["native_root_dry_kg"] = root["dry_harvest_kg"]
        result["net_operating_margin"] = (
            result["stored_grain_value"]
            + root["revenue_usd"]
            - result["production_cost"]
        )
        result["operating_budget_usd"] = self.resources.budget_usd
        result["economic_status"] = "assumed_prices_not_a_real_farm_profit_estimate"
        result["cny_per_usd"] = (
            None  # Prices are independently assumed in USD; no FX assertion.
        )
        return result

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_accounts(self) -> dict:
        """Read actual consumed inputs, stored wheat, sold roots and net operating margin.
        Returns:
            dict: USD assumptions; excludes land, ordinary labour, depreciation, tax,
            P/K and pest management. Fresh root value comes only from accepted delivery.
        """
        return {**self.compute_accounts(), "operation_deadline": self.operation_deadline}
