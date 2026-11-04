"""Native CWB surface drainage on independently managed winter-wheat blocks."""

from copy import deepcopy
from math import fsum

from .winter_wheat_inputs import json_safe, number
from .winter_wheat_wofost import InputBundle, WinterWheatBackend


class WaterloggingWheatBackend(WinterWheatBackend):
    """Meter only ponded surface water before daily native rate calculation.

    The native total surface outflow includes pumped water for its mass
    balance. The drainage ledger separates pumping from natural runoff.
    """

    def __init__(self, bundle: InputBundle):
        self.drainage_receipts: dict[str, dict] = {}
        self._last_rfos: float | None = None
        self._last_rfos_day: str | None = None
        super().__init__(bundle)

    def queue(self, operation_id: str, kind: str, amount: float = 0.0) -> dict:
        if kind != "drain":
            return super().queue(operation_id, kind, amount)
        if self.failed:
            raise RuntimeError(f"Backend invalid after native error: {self.failed}")
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("A nonempty operation ID is required")
        amount = number(amount, "surface drainage mm", minimum=0)
        if amount <= 0:
            raise ValueError("Surface drainage depth must be positive")
        if operation_id in self.receipts:
            previous = self.receipts[operation_id]
            if previous["kind"] != kind or previous["amount"] != amount:
                raise ValueError("Operation ID reused with different content")
            return deepcopy(previous)
        action = {
            "id": operation_id,
            "kind": kind,
            "amount": amount,
            "day": self.next_day.isoformat(),
        }
        self.pending.append(action)
        self.receipts[operation_id] = action
        return deepcopy(action)

    def _calculate_current_day(self, day, actions):
        water = self.model.soil.waterbalance.states
        for action in actions:
            if action["kind"] != "drain":
                continue
            before_cm = max(0.0, float(water.SS))
            withdrawn_cm = min(before_cm, action["amount"] / 10)
            if withdrawn_cm:
                water.unlock()
                try:
                    water.SS -= withdrawn_cm
                    water.TSR += withdrawn_cm
                finally:
                    water.lock()
            self.drainage_receipts[action["id"]] = {
                "day": day.isoformat(),
                "requested_mm": action["amount"],
                "drained_mm": withdrawn_cm * 10,
                "surface_before_mm": before_cm * 10,
                "surface_after_mm": float(water.SS) * 10,
            }

        crop = self.model.crop
        transpiring = crop is not None and crop.pheno.get_variable("STAGE") != "emerging"
        super()._calculate_current_day(day, actions)
        # PCSE clears rate variables on integration. Sample the actual factor now.
        self._last_rfos = self.model.get_variable("RFOS") if transpiring else None
        self._last_rfos_day = day.isoformat() if self._last_rfos is not None else None

    def _read_values(self):
        return {
            **super()._read_values(),
            **json_safe({
                "SS": self.model.get_variable("SS"),
                "DSOS": self.model.get_variable("DSOS"),
                "RFOS": self._last_rfos,
            }),
        }

    def snapshot(self):
        states = self.model.soil.waterbalance.states
        drained_mm = fsum(row["drained_mm"] for row in self.drainage_receipts.values())
        return {
            **super().snapshot(),
            "rfos_effective_day": self._last_rfos_day,
            "drainage": {
                "total_drained_mm": drained_mm,
                "natural_surface_runoff_mm": max(0.0, states.TSR * 10 - drained_mm),
                "receipts": deepcopy(self.drainage_receipts),
            },
        }
