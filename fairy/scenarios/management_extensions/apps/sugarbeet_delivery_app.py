"""Root delivery composes loading, transport and factory weighing into one operation."""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from fairy.apps.app import App
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered
from ..sugarbeet.contracts import RootLedger, DELIVERY_WEIGHING_TOLERANCE_KG


class SugarBeetDelivery(App):
    def __init__(self, environment, contract, delivery_open, delivery_close):
        super().__init__("RootDelivery")
        self.environment = environment
        self.ledger = RootLedger(contract, delivery_open, delivery_close)
        self.accounts = None

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_delivery_info(self) -> dict:
        """Read factory windows, capacity, batches and the declared quality assumption.
        Returns:
            dict: Clean root and gross-load units are separate; quality is not a sensor.
        """
        return {
            "contract": asdict(self.ledger.contract),
            "delivery_open": self.ledger.delivery_open.isoformat(),
            "delivery_close": self.ledger.delivery_close.isoformat(),
            "batch_state": self.ledger.export(),
            "totals": self.ledger.totals(),
            "delivery_weighing_tolerance_kg": DELIVERY_WEIGHING_TOLERANCE_KG,
            "trip_seconds": 7200,
        }

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def deliver_roots(self, batch_id: str, net_kg: float, operation_id: str) -> dict:
        """Load, haul and sell clean beet roots subject to gross truck/day capacity.
        Args:
            batch_id: Root batch ID returned by harvesting.
            net_kg: Clean roots in kg; gross includes tare and is capacity-limited.
                Upward rounding within 0.01 kg is clipped to the actual remaining
                batch mass; the receipt records the actual accepted weight.
            operation_id: Nonempty retry-safe transaction ID.
        Returns:
            dict: Net/gross/tare mass, transport cost and revenue, or error. Two hours
            of shared simulation time pass; quality/price is an explicit fixed assumption.
        """
        if operation_id in self.ledger.transactions:
            try:
                return self.ledger.deliver(
                    operation_id,
                    batch_id,
                    net_kg,
                    datetime.fromtimestamp(
                        self.time_manager.time(), self.environment.simulation_timezone
                    ).date(),
                )
            except (ValueError, KeyError) as e:
                return {"error": str(e)}
        arrival = datetime.fromtimestamp(
            self.time_manager.time() + 7200, self.environment.simulation_timezone
        ).date()
        probe = deepcopy(self.ledger)
        try:
            receipt = probe.deliver(operation_id, batch_id, net_kg, arrival)
            if (
                self.accounts.compute_accounts()["production_cost"]
                + receipt["transport_usd"]
                > self.accounts.resources.budget_usd + 1e-7
            ):
                raise ValueError("Delivery would exceed budget")
            farm = self.environment.get_farm("arable").world
            if arrival > farm.bundle.season.deadline:
                raise ValueError("Delivery would exceed experiment deadline")
        except (ValueError, KeyError) as e:
            return {"error": str(e)}
        self.environment.advance_time(7200)
        return self.ledger.deliver(operation_id, batch_id, net_kg, arrival)

    def get_state(self):
        return self.ledger.export()

    def load_state(self, state):
        self.ledger.load(state)
