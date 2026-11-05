"""Additive, unit-explicit receipts for physical resource transfers.

Existing tool-specific onboard fields retain their meaning. This envelope
separates a requested increment from the total already onboard.
"""
VERSION = "resource-transfer-v1"


def transfer_receipt(requested, transferred, onboard, capacity, inventory_remaining, unit):
    return {"transfer_version": VERSION, "requested": requested,
            "transferred": transferred, "onboard": onboard,
            "remaining_capacity": max(0, capacity - onboard),
            "inventory_remaining": inventory_remaining, "unit": unit,
            "transfer_status": "no_op" if transferred == 0 else (
                "partial" if transferred < requested else "completed")}
