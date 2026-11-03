"""Single-field rotation world with crop-identifiable storage and actual drying ledger."""

from copy import deepcopy
from inspect import unwrap

from fairy.apps.farm_world import FarmWorldApp
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered

from ..engines.crop_rotation_wofost import CropRotationBackend


class CropRotationFarm(FarmWorldApp):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stored_batches = []
        self.drying_throughput_kg = 0.0
        self._rotation_geometry = (
            self.num_ridges,
            self.field_length_m,
            self.ridge_width_m,
            self.field_area_m2,
        )

    def _check_rotation_geometry(self):
        if (
            self.num_ridges,
            self.field_length_m,
            self.ridge_width_m,
            self.field_area_m2,
        ) != self._rotation_geometry:
            raise ValueError(
                "Crop rotation cannot change the field geometry or land area"
            )

    def advance_physics_time(self, target_sim_time=None):
        self._check_rotation_geometry()
        return super().advance_physics_time(target_sim_time)

    def get_state(self):
        self._check_rotation_geometry()
        return {
            **super().get_state(),
            "rotation_geometry": list(self._rotation_geometry),
            "rotation_storage": {
                "schema": 1,
                "batches": deepcopy(self.stored_batches),
                "drying_throughput_kg": self.drying_throughput_kg,
            },
        }

    def _restore_crop_backend(self, payload):
        return CropRotationBackend.from_state(payload)

    def load_state(self, state_dict):
        state = deepcopy(state_dict)
        self._rotation_geometry = tuple(state["rotation_geometry"])
        raw = state["physics_state"]["crop_backend_state"]
        backend = self._restore_crop_backend(raw)
        placeholder = deepcopy(raw)
        placeholder.update(runs={}, last_day=None, pending={}, preplant_totals={})
        state["physics_state"]["crop_backend_state"] = placeholder
        super().load_state(state)
        params = self.physics.yield_recovery.params
        self.physics.crop_backend = backend
        backend.bind_physics(self.physics)
        self.physics.yield_recovery.params = params
        storage = state["rotation_storage"]
        if storage.get("schema") != 1:
            raise ValueError("Rotation storage checkpoint marker is required")
        self._check_rotation_geometry()
        self.stored_batches = deepcopy(storage["batches"])
        self.drying_throughput_kg = float(storage["drying_throughput_kg"])
        if (
            abs(
                sum(b["quantity_kg"] for b in self.stored_batches)
                - self._inventory.warehouse_grain_kg
            )
            > 1e-7
        ):
            raise ValueError(
                "Crop-specific storage ledger disagrees with real warehouse"
            )

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_inventory(self) -> dict:
        """Read stocks, limits and stored grain by original crop/season.

        Returns:
            dict: seed counts, fertilizer-product kg, fuel L, pending/stored grain kg,
            cumulative management use and storage/drying limits (kg, moisture %).
            Null capacity means unconfigured. grain_batches preserves batch, crop,
            variety, season, ridge IDs, kg and moisture %. actual_drying_throughput_kg
            is cumulative processed kg; changing crops does not relabel prior grain.
        """
        result = unwrap(FarmWorldApp.get_inventory)(self)
        result["grain_batches"] = deepcopy(self.stored_batches)
        result["actual_drying_throughput_kg"] = self.drying_throughput_kg
        return result

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def dry_grain(self, target_moisture_pct: float = 13.0) -> dict:
        """Dry unloaded grain; already-safe batches are skipped without drying cost.

        Prerequisites:
            Harvested grain unloaded to farm; pending batch fits drying capacity.

        Args:
            target_moisture_pct: Moisture percent, default 13.0; inclusive [11, 16]
                and no higher than postharvest_market.max_storage_moisture_pct.

        Returns:
            dict: status, batch/ridge IDs, grain kg and target moisture, or
            drying_skipped with reason. actual_drying_throughput_kg is cumulative;
            skipped/rejected requests do not increase it. Refusals return error.
        """
        result = unwrap(FarmWorldApp.dry_grain)(self, target_moisture_pct)
        if result.get("status") == "ok" and not result.get("drying_skipped"):
            self.drying_throughput_kg += result["trailer_grain_kg"]
        return {**result, "actual_drying_throughput_kg": self.drying_throughput_kg}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def store_grain(self) -> dict:
        """Store the unloaded safe batch, preserving crop, variety and season identity.

        Prerequisites:
            Known moisture within storage limit and enough warehouse capacity;
            dry_grain first if needed.

        Returns:
            dict: status, moved_kg, pending/warehouse kg, ridge IDs and moisture %;
            refusals return error. Empty repeats move zero and add no batch.
            Read get_inventory.grain_batches for stored-batch identity.
        """
        crop = self.crop_type
        year = self.simulation_date(self.time_manager.time()).year
        variety = self.physics.crop_backend.config.variety_name
        basis = self._postharvest_market.market_moisture_pct
        result = unwrap(FarmWorldApp.store_grain)(self)
        if result.get("status") == "ok" and result["moved_kg"] > 0:
            self.stored_batches.append(
                {
                    "batch_id": f"{self.farm_id}-{year}-{crop}-{len(self.stored_batches)}",
                    "origin_farm_id": self.farm_id,
                    "crop_id": crop,
                    "variety_name": variety,
                    "season": year,
                    "ridge_ids": list(result["batch_ridge_ids"]),
                    "quantity_kg": result["moved_kg"],
                    "market_moisture_pct": basis,
                    "moisture_pct": result["storage_grain_moisture_pct"],
                    "status": "stored",
                }
            )
        return result
