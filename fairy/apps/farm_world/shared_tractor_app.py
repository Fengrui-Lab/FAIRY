"""One physical tractor shared by the farms in a FarmEnvironment.

Public tool signatures declare their real target parameters. Fixed field state is
provided by FarmContext; fuel, implements, supplies and grain stay on this App.
"""
from __future__ import annotations

from math import isfinite
from typing import Any

from fairy.apps.app import App
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import PESTICIDE_L_PER_RIDGE
from fairy.apps.farm_world.equipment import TractorEquipment
from fairy.apps.farm_world.tractor_tool_contracts import (
    TractorContractContext, tractor_operation_contract,
)
from fairy.apps.farm_world.tractor_operations import (
    TractorOperations,
    _FERTILIZER_SPREADER_MAX_KG,
    _FUEL_TANK_MAX_L,
    _GRAIN_BIN_MAX_KG,
    _GRAIN_UNLOAD_DURATION_S,
    _PESTICIDE_TANK_MAX_L,
    _SEED_HOPPER_MAX_PLANTS,
)
from fairy.time_manager import TimeManager
from fairy.tool_utils import OperationType, app_tool, data_tool
from fairy.tool_contracts import OperationContract
from fairy.types import event_registered
from fairy.utils.type_utils import type_check


class SharedTractorApp(App, TractorOperations):
    """Shared tractor with explicit farm targets and one equipment state."""

    require_explicit_tool_docs = True
    validate_tool_arguments = True

    def __init__(
        self,
        farm_environment: FarmEnvironment,
        name: str = 'Tractor',
        *,
        equipment: TractorEquipment | None = None,
    ) -> None:
        super().__init__(name=name)
        self.farm_environment = farm_environment
        if farm_environment.warehouse is None:
            raise ValueError("SharedTractorApp requires the environment's shared warehouse")
        self.tool_parameter_choices = {
            "farm_id": list(farm_environment.farms),
        }
        self._initialize_tractor_state(equipment)
        self._tool_contract_context = TractorContractContext(
            farms=lambda: {name: farm.world for name, farm in self.farm_environment.farms.items()},
            equipment=lambda: self.equipment,
            seed_types=lambda: tuple(self.farm_environment.warehouse.stock.seed_stock),
            selected_seed_type=lambda: self.seed_type,
            has_farm_selector=True,
            harvest_moisture_limit=lambda world: (
                self._harvest_moisture_limit_pct
                if getattr(self, "_harvest_limit_configured", False)
                else world.crop_definition.harvest_rules.max_moisture_pct
            ),
        )
        self._grain_cultivar_ids: list[str] = []
        self._grain_ridge_ids: list[int] = []
        self._grain_moistures_pct: list[float] = []
        self.register_time_manager(farm_environment.time_manager)

    def get_tool_contract(self, method_name: str) -> OperationContract | None:
        return tractor_operation_contract(self._tool_contract_context, method_name)

    def register_time_manager(self, time_manager: TimeManager) -> None:
        super().register_time_manager(time_manager)
        self.farm_environment.register_time_manager(time_manager)

    def get_state(self) -> dict[str, Any]:
        state = self._tractor_device_state()
        state.pop("source_farm_id")
        state["warehouse_id"] = self.farm_environment.warehouse.warehouse_id
        state["grain_cultivar_ids"] = list(self._grain_cultivar_ids)
        state["grain_ridge_ids"] = list(self._grain_ridge_ids)
        state["grain_moistures_pct"] = list(self._grain_moistures_pct)
        return state

    def load_state(self, state_dict: dict[str, Any]) -> None:
        self._validate_origin_state(state_dict)
        self._load_tractor_device_state(state_dict)
        self._grain_cultivar_ids = sorted(state_dict.get("grain_cultivar_ids", []))
        self._grain_ridge_ids = list(state_dict.get("grain_ridge_ids", []))
        self._grain_moistures_pct = list(state_dict.get("grain_moistures_pct", []))

    def reset(self) -> None:
        super().reset()
        self._initialize_tractor_state()
        self._grain_cultivar_ids = []
        self._grain_ridge_ids = []
        self._grain_moistures_pct = []

    def _validate_origin_state(self, state: dict[str, Any]) -> None:
        attached = state.get("attached_implement")
        if attached is not None and attached not in self.equipment.implements:
            raise ValueError("Tractor snapshot mounts an implement not owned by this device")
        if "source_farm_id" in state:
            raise ValueError("Historical farm-owned payload snapshots require migration")
        if state.get("warehouse_id") != self.farm_environment.warehouse.warehouse_id:
            raise ValueError("Snapshot belongs to a different shared warehouse")
        capacities = {
            "fuel_tank_l": _FUEL_TANK_MAX_L,
            "pesticide_tank_l": _PESTICIDE_TANK_MAX_L,
            "fungicide_tank_l": _PESTICIDE_TANK_MAX_L,
            "fertilizer_spreader_kg": _FERTILIZER_SPREADER_MAX_KG,
            "grain_bin_kg": _GRAIN_BIN_MAX_KG,
        }
        for name, capacity in capacities.items():
            value = state.get(name, 0)
            if (type(value) not in (int, float) or not isfinite(value)
                    or not 0 <= value <= capacity):
                raise ValueError(f"Invalid shared tractor snapshot {name}")
        seeds = state.get("seed_hopper", 0)
        if type(seeds) is not int or not 0 <= seeds <= _SEED_HOPPER_MAX_PLANTS:
            raise ValueError("Invalid shared tractor snapshot seed_hopper")
        farm_id = state.get("grain_origin_farm_id")
        if farm_id is not None:
            farm = self.farm_environment.get_farm(farm_id)
        cultivars = state.get("grain_cultivar_ids", [])
        if (not isinstance(cultivars, list)
                or any(not isinstance(value, str) or not value for value in cultivars)
                or len(set(cultivars)) != len(cultivars)):
            raise ValueError("Invalid shared tractor snapshot grain_cultivar_ids")
        if cultivars and (farm_id is None or state.get("grain_bin_kg", 0) <= 0):
            raise ValueError("Grain cultivar provenance requires a nonempty origin bin")
        if farm_id is not None and any(
            value not in farm.world.crop_definition.seed_types for value in cultivars
        ):
            raise ValueError("Grain cultivars do not belong to the origin farm's crop")
        if state.get("grain_bin_kg", 0) > 0 and state.get("grain_origin_farm_id") is None:
            raise ValueError("Nonempty shared tractor grain bin requires grain_origin_farm_id")
        ridge_ids = state.get("grain_ridge_ids", [])
        moistures = state.get("grain_moistures_pct", [])
        if (not isinstance(ridge_ids, list) or not isinstance(moistures, list)
                or len(ridge_ids) != len(moistures)
                or any(type(rid) is not int for rid in ridge_ids)
                or len(set(ridge_ids)) != len(ridge_ids)
                or any(type(value) not in (int, float) or not isfinite(value)
                       or not 0 <= value < 100 for value in moistures)):
            raise ValueError("Invalid shared tractor grain ridge/moisture provenance")
        if state.get("grain_bin_kg", 0) > 0:
            if not ridge_ids or any(not 0 <= rid < farm.world.num_ridges for rid in ridge_ids):
                raise ValueError("Nonempty shared tractor grain bin requires origin ridge/moisture provenance")
        elif ridge_ids or moistures:
            raise ValueError("Empty grain bin cannot contain ridge/moisture provenance")
        if (seeds > 0
                and state.get("seed_type") not in self.farm_environment.warehouse.stock.seed_stock):
            raise ValueError("Nonempty shared tractor seed hopper requires a valid seed_type")

    def _prepare(self, farm_id: str) -> FarmContext:
        farm = self.farm_environment.get_farm(farm_id)
        self.farm_environment.before_tool()
        return farm

    def _target_error(self, farm_id: str) -> dict[str, Any] | None:
        """Protect a harvest batch's provenance without restricting other field work."""
        if self._grain_bin_kg > 0 and self.grain_origin_farm_id is None:
            return {"farm_id": farm_id, "error": "Grain origin is unknown"}
        return None

    def _finish(self, farm: FarmContext, result: dict[str, Any]) -> dict[str, Any]:
        if self._grain_bin_kg <= 0:
            self.grain_origin_farm_id = None
            self._grain_cultivar_ids = []
            self._grain_ridge_ids = []
            self._grain_moistures_pct = []
        self.farm_environment.sync()
        return {**result, "farm_id": farm.farm_id}

    def _load_material(
        self, *, amount: float, payload_attribute: str, capacity: float,
        warehouse_resource: str, output_key: str,
    ) -> dict[str, Any]:
        """Transfer one resource from the common stock to an onboard container."""
        self.farm_environment.before_tool()
        if not isfinite(amount) or amount <= 0:
            return {"error": "amount must be finite and positive"}
        current = getattr(self, payload_attribute)
        space = capacity - current
        if space <= 0:
            return {"msg": f"{output_key} is already full"}
        transferred = min(amount, space)
        warehouse = self.farm_environment.warehouse
        consume = getattr(warehouse, f"consume_{warehouse_resource}")
        if not consume(transferred):
            return {"error": f"Insufficient {warehouse_resource} in shared warehouse"}
        setattr(self, payload_attribute, current + transferred)
        self.is_state_modified = True
        return {"status": "ok", "warehouse_id": warehouse.warehouse_id,
                output_key: getattr(self, payload_attribute)}

    def _finish_harvest(
        self,
        farm: FarmContext,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if "error" not in result and self._grain_bin_kg > 0:
            self.grain_origin_farm_id = farm.farm_id
            self._grain_ridge_ids.extend(farm.world._pending_bin_grain_ridge_ids)
            self._grain_moistures_pct.extend(farm.world._pending_bin_grain_moistures_pct)
            farm.world._pending_bin_grain_ridge_ids = []
            farm.world._pending_bin_grain_moistures_pct = []
            farm.world.is_state_modified = True
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def attach_implement(self, implement: str) -> dict[str, Any]:
        """Mount one implement on this shared tractor.

        Only one implement can be mounted. Detach the current implement before changing it.
        No farm parameter is required because the implement belongs to this tractor.

        Args:
            implement: Owned implement name from this tractor's equipment configuration.

        Returns:
            Status and mounted implement, or an error.
        """
        self.farm_environment.before_tool()
        return self._operate_attach_implement(implement=implement)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def detach_implement(self) -> dict[str, Any]:
        """Remove the currently mounted implement from this shared tractor.

        Fails if there is no mounted implement. No farm parameter is required;
        the mounted implement belongs to this tractor.

        Returns:
            Status and detached implement, or an error.
        """
        self.farm_environment.before_tool()
        return self._operate_detach_implement()

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def refuel(self, liters: float) -> dict[str, Any]:
        """Transfer fuel from the shared warehouse into this tractor's fuel tank.

        Requires positive liters and sufficient warehouse fuel; transfer is capped by the 100 L
        tank capacity. Fuel remains available to subsequent work on any registered farm.

        Args:
            liters: Requested transfer volume in liters; must be positive.

        Returns:
            Warehouse ID and fuel level, or an error.
        """
        return self._load_material(
            amount=float(liters), payload_attribute="_fuel_tank_l",
            capacity=_FUEL_TANK_MAX_L, warehouse_resource="fuel", output_key="fuel_tank_l",
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def refill_pesticide_tank(self, liters: float) -> dict[str, Any]:
        """Transfer pesticide from the shared warehouse into the shared spray tank.

        Requires positive liters and sufficient stock; transfer is capped by the 800 L tank
        capacity. Loaded pesticide can be used on any registered farm.

        Args:
            liters: Requested transfer volume in liters; must be positive.

        Returns:
            Warehouse ID and spray tank level, or an error.
        """
        return self._load_material(
            amount=float(liters), payload_attribute="_pesticide_tank_l",
            capacity=_PESTICIDE_TANK_MAX_L, warehouse_resource="pesticide",
            output_key="pesticide_tank_l",
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def load_fertilizer(self, kg: float) -> dict[str, Any]:
        """Load fertilizer from the shared warehouse into the shared spreader.

        Requires positive kilograms and sufficient stock; transfer is capped by the 500 kg
        spreader capacity. Loading does not consume a farm's fertilizer quota;
        actual application counts against the selected target farm.

        Args:
            kg: Requested fertilizer mass in kilograms; must be positive.

        Returns:
            Warehouse ID and spreader level, or an error.
        """
        return self._load_material(
            amount=float(kg), payload_attribute="_fertilizer_spreader_kg",
            capacity=_FERTILIZER_SPREADER_MAX_KG, warehouse_resource="fertilizer",
            output_key="fertilizer_spreader_kg",
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def load_seeds(self, seed_type: str, count: int) -> dict[str, Any]:
        """Load one seed variety from the shared warehouse into the shared hopper.

        Requires a supported seed variety, positive count and sufficient stock. Hopper capacity
        is 300000 seeds. Different varieties cannot be mixed. Field planting checks
        whether the loaded variety is supported by the selected target farm.

        Args:
            seed_type: Exact variety key reported by Warehouse.get_inventory.
            count: Requested number of seeds to load; positive integer.

        Returns:
            Warehouse ID, loaded seed variety and hopper level, or an error.
        """
        self.farm_environment.before_tool()
        warehouse = self.farm_environment.warehouse
        if seed_type not in warehouse.stock.seed_stock:
            return {"error": f"Unknown warehouse seed_type '{seed_type}'"}
        if count <= 0:
            return {"error": "count must be positive"}
        if self._seed_hopper > 0 and self.seed_type != seed_type:
            return {"error": "Seed hopper contains another variety; return it first"}
        space = _SEED_HOPPER_MAX_PLANTS - self._seed_hopper
        if space <= 0:
            return {"msg": f"Seed hopper already full for {seed_type}"}
        transferred = min(count, space)
        if not warehouse.consume_seeds(seed_type, transferred):
            return {"error": f"Insufficient {seed_type} seeds in shared warehouse: need {transferred}"}
        self.seed_type = seed_type
        self._seed_hopper += transferred
        self.is_state_modified = True
        return {"status": "ok", "warehouse_id": warehouse.warehouse_id,
                "seed_type": seed_type, "seed_hopper": self._seed_hopper}

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_status(self) -> dict[str, Any]:
        """Read this shared tractor's fuel, payload, implement and grain batch origin.

        Loaded supplies can be used on any registered farm. Grain from different
        farms must be unloaded into separate batches before harvesting another farm.

        Returns:
            Device resource levels, shared warehouse ID and current grain origin.
        """
        self.farm_environment.before_tool()
        status = self._operate_get_status()
        status.pop("source_farm_id")
        status["warehouse_id"] = self.farm_environment.warehouse.warehouse_id
        status["grain_cultivar_ids"] = list(self._grain_cultivar_ids)
        status["grain_ridge_ids"] = list(self._grain_ridge_ids)
        status["grain_moisture_pct"] = (
            max(self._grain_moistures_pct) if self._grain_moistures_pct else None
        )
        return status

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def level(self, farm_id: str) -> dict[str, Any]:
        """Level and till the selected farm with the shared tractor.

        Requires the grader implement, trafficable soil and fuel proportional to field area (8 L on the reference 64-ridge field). Advances all registered farms by
        the full-field operation duration and records preparation only on the selected farm.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_level(farm)
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def base_fertilize(self, farm_id: str, total_kg: float | None = None) -> dict[str, Any]:
        """Spread base fertilizer over the selected farm with the shared tractor.

        Fertilizer and fuel scale with target field area: the reference 64-ridge
        field (268 m length, 1.1 m ridge width) needs 200 kg and 8 L. Requires
        trafficable soil. Advances all registered farms by the operation duration
        and records preparation only on the selected farm.

        Args:
            total_kg: Positive total fertilizer product mass; omitted uses the selected field's area-scaled default.
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_base_fertilize(farm, total_kg=total_kg)
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def form_ridges(self, farm_id: str, ridge_width_m: float) -> dict[str, Any]:
        """Form ridge rows across the selected farm with the shared tractor.

        Requires positive ridge width, trafficable soil and fuel proportional to field area (8 L on the reference 64-ridge field). Keeps the farm’s
        existing ridge IDs and resets their crop state; advances all registered farms and records
        preparation on this farm.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            ridge_width_m: Operating ridge width in meters; must be positive. Does not change
                the number of indexed ridges.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_form_ridges(farm, ridge_width_m=ridge_width_m)
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_fertilizer(
        self,
        farm_id: str,
        start_ridge: int,
        end_ridge: int,
        kg_per_ridge: float,
    ) -> dict[str, Any]:
        """Fertilize an inclusive ridge range on the selected farm.

        Covers at most 10 ridges per pass. Requires positive dose, enough loaded fertilizer, length-scaled fuel (2 L per 268 m pass) and trafficable soil. Advances all registered farms; fertilizer effects belong to the
        selected ridges.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            start_ridge: First local ridge ID, inclusive, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be inside the target farm and within
                the per-pass limit.
            kg_per_ridge: Fertilizer dose per ridge in kilograms; must be positive.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_apply_fertilizer(
            farm,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
            kg_per_ridge=kg_per_ridge,
        )
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def plant_seeds(
        self,
        farm_id: str,
        start_ridge: int,
        end_ridge: int,
        depth_cm: float,
        seed_spacing_cm: float,
    ) -> dict[str, Any]:
        """Plant an inclusive ridge range on the selected farm.

        The bound operation contract publishes each farm's crop limits and the configured
        device's pass limit. Requires the target farm's declared
        required_field_preparation_ops (as listed by the field capabilities), bare ridges, suitable
        soil and sufficient resources. Advances all registered farms.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            start_ridge: First local ridge ID, inclusive, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be inside the target farm and within
                the per-pass limit.
            depth_cm: Sowing depth in centimeters; use the selected farm's crop limits.
            seed_spacing_cm: Within-row seed spacing in centimeters; must be positive.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        if self.seed_type not in farm.world.crop_definition.seed_types:
            return {"farm_id": farm_id, "error": (
                f"Loaded seed variety {self.seed_type!r} is not supported by "
                f"target crop {farm.world.crop_id}"
            )}
        result = self._operate_plant_seeds(
            farm,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
            depth_cm=depth_cm,
            seed_spacing_cm=seed_spacing_cm,
        )
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_pesticide(
        self,
        farm_id: str,
        start_ridge: int,
        end_ridge: int,
    ) -> dict[str, Any]:
        """Spray pesticide at the standard dose over selected farm ridges.

        Covers at most 10 ridges. Requires sprayable weather, trafficable soil, an allowed
        chemical regime, enough loaded pesticide and length-scaled fuel (2 L per 268 m pass). Advances all registered farms and
        applies effects only to the selected ridges.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            start_ridge: First local ridge ID, inclusive, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be inside the target farm and within
                the per-pass limit.

        Returns:
            Operation result or error; farm operations include the target farm_id.

        Fields without crop-protection support reject this operation before resource use.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_apply_pesticide(
            farm,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
        )
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def load_pesticide(self, liters: float) -> dict[str, Any]:
        """Load pesticide from the shared warehouse into the shared spray tank.

        Requires positive liters and sufficient stock; transfer is capped by the 800 L tank
        capacity. Loaded pesticide can be used on any registered farm.

        Args:
            liters: Requested transfer volume in liters; must be positive.

        Returns:
            Warehouse ID and spray tank level, or an error.
        """
        return self._load_material(
            amount=float(liters), payload_attribute="_pesticide_tank_l",
            capacity=_PESTICIDE_TANK_MAX_L, warehouse_resource="pesticide",
            output_key="pesticide_tank_l",
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def spray_pesticide(
        self,
        farm_id: str,
        start_ridge: int,
        end_ridge: int,
        liters_per_ridge: float = PESTICIDE_L_PER_RIDGE,
    ) -> dict[str, Any]:
        """Spray pesticide at an explicit per-ridge dose on the selected farm.

        Covers at most 10 ridges. Requires a positive dose, sprayable weather, trafficable soil,
        an allowed chemical regime, enough loaded pesticide and length-scaled fuel (2 L per 268 m pass). Advances all
        registered farms.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            start_ridge: First local ridge ID, inclusive, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be inside the target farm and within
                the per-pass limit.
            liters_per_ridge: Positive working-fluid liters per ridge; lower dose reduces efficacy.

        Returns:
            Operation result or error; farm operations include the target farm_id.

        Fields without crop-protection support reject this operation before resource use.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_spray_pesticide(
            farm,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
            liters_per_ridge=liters_per_ridge,
        )
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def load_fungicide(self, liters: float) -> dict[str, Any]:
        """Load the fungicide tank from the shared warehouse's chemical stock.

        Requires positive liters and sufficient stock; transfer is capped by the separate 800 L
        fungicide tank capacity. Loaded fungicide can be used on any registered farm.
        Pesticide and fungicide currently draw from the same warehouse chemical pool.

        Args:
            liters: Requested transfer volume in liters; must be positive.

        Returns:
            Warehouse ID and fungicide tank level, or an error.
        """
        return self._load_material(
            amount=float(liters), payload_attribute="_fungicide_tank_l",
            capacity=_PESTICIDE_TANK_MAX_L, warehouse_resource="pesticide",
            output_key="fungicide_tank_l",
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_fungicide(
        self,
        farm_id: str,
        start_ridge: int,
        end_ridge: int,
        liters_per_ridge: float,
    ) -> dict[str, Any]:
        """Apply fungicide over selected farm ridges from the shared fungicide tank.

        Covers at most 10 ridges. Requires a positive dose, sprayable weather, trafficable soil,
        an allowed chemical regime, enough loaded fungicide and length-scaled fuel (2 L per 268 m pass). Advances all
        registered farms.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            start_ridge: First local ridge ID, inclusive, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be inside the target farm and within
                the per-pass limit.
            liters_per_ridge: Positive working-fluid liters per ridge; lower dose reduces efficacy.

        Returns:
            Operation result or error; farm operations include the target farm_id.

        Fields without crop-protection support reject this operation before resource use.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_apply_fungicide(
            farm,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
            liters_per_ridge=liters_per_ridge,
        )
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_herbicide(
        self,
        farm_id: str,
        start_ridge: int,
        end_ridge: int,
        liters_per_ridge: float,
    ) -> dict[str, Any]:
        """Apply herbicide over selected farm ridges from the shared pesticide tank.

        Covers at most 10 ridges. Requires a positive dose, sprayable weather, trafficable soil,
        an allowed herbicide regime, enough loaded pesticide and length-scaled fuel (2 L per 268 m pass). Advances all
        registered farms.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            start_ridge: First local ridge ID, inclusive, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be inside the target farm and within
                the per-pass limit.
            liters_per_ridge: Positive working-fluid liters per ridge; lower dose reduces efficacy.

        Returns:
            Operation result or error; farm operations include the target farm_id.

        Fields without crop-protection support reject this operation before resource use.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_apply_herbicide(
            farm,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
            liters_per_ridge=liters_per_ridge,
        )
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def mechanical_weed_control(
        self,
        farm_id: str,
        start_ridge: int,
        end_ridge: int,
    ) -> dict[str, Any]:
        """Perform mechanical weeding over selected farm ridges.

        Covers at most 10 ridges. Requires trafficable soil, an allowed machine pass and
        mechanical-weeding quota, plus length-scaled fuel (2 L per 268 m pass). Advances all registered farms; records usage on the
        selected farm.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            start_ridge: First local ridge ID, inclusive, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be inside the target farm and within
                the per-pass limit.

        Returns:
            Operation result or error; farm operations include the target farm_id.

        Fields without crop-protection support reject this operation before resource use.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_mechanical_weed_control(
            farm,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
        )
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def replant_seeds(
        self,
        farm_id: str,
        start_ridge: int,
        end_ridge: int,
        depth_cm: float,
        spacing_cm: float,
        full_replant: bool = False,
    ) -> dict[str, Any]:
        """Replant an inclusive ridge range on the selected farm.

        The selected crop's operation rules determine whether gap filling or full replanting
        is supported. Requires suitable soil and sufficient loaded resources. Advances all
        registered farms.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            start_ridge: First local ridge ID, inclusive, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be inside the target farm and within
                the per-pass limit.
            depth_cm: Sowing depth in centimeters; use the selected farm's crop limits.
            spacing_cm: Within-row replacement seed spacing in centimeters; must be positive.
            full_replant: Whether to restart each target ridge's season; false uses a partial
                mode only when supported by the crop.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        if self.seed_type not in farm.world.crop_definition.seed_types:
            return {"farm_id": farm_id, "error": (
                f"Loaded seed variety {self.seed_type!r} is not supported by "
                f"target crop {farm.world.crop_id}"
            )}
        result = self._operate_replant_seeds(
            farm,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
            depth_cm=depth_cm,
            spacing_cm=spacing_cm,
            full_replant=full_replant,
        )
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def incorporate_residue(
        self,
        farm_id: str,
        start_ridge: int,
        end_ridge: int,
    ) -> dict[str, Any]:
        """Incorporate crop residue over selected farm ridges.

        Covers at most 10 ridges. Requires length-scaled fuel (2 L per 268 m pass). Advances all registered farms and queues residue
        incorporation for the selected farm.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            start_ridge: First local ridge ID, inclusive, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be inside the target farm and within
                the per-pass limit.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_incorporate_residue(
            farm,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
        )
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def harvest(self, farm_id: str, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        """Harvest selected farm ridges into this shared tractor’s grain bin.

        The operation contract publishes the selected farm's mature stages, moisture limit
        and this tractor's pass limit. Requires planted crop, dry weather, trafficable soil,
        fuel and grain-bin room. Grain from different farms cannot mix. Advances all farms.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            start_ridge: First local ridge ID, inclusive, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be inside the target farm and within
                the per-pass limit.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        if self._grain_bin_kg > 0 and self.grain_origin_farm_id != farm_id:
            return {"farm_id": farm_id, "error": (
                f"Grain bin contains grain from {self.grain_origin_farm_id}; "
                "unload it as a separate warehouse batch before harvesting another farm"
            )}
        cultivars = {
            ridge.seed_type
            for ridge in farm.world._ridges[max(0, start_ridge):end_ridge + 1]
            if ridge.seed_type is not None
        }
        result = self._operate_harvest(farm, start_ridge=start_ridge, end_ridge=end_ridge)
        if "error" not in result and result.get("grain_kg_added", 0) > 0:
            self._grain_cultivar_ids = sorted(set(self._grain_cultivar_ids) | cultivars)
        return self._finish_harvest(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def unload_grain(self, batch_id: str) -> dict[str, Any]:
        """Unload this tractor's grain bin into a new shared warehouse batch.

        Transfers the entire bin, preserves its farm and ridge provenance, clears
        the bin's origin and advances all farms by 480 seconds. No farm selection
        is needed: the harvest records already identify the grain's origin.

        Args:
            batch_id: Unique nonempty ID for the new grain batch. Existing IDs are rejected.

        Returns:
            Warehouse batch details and emptied grain bin, or an error.
        """
        self.farm_environment.before_tool()
        warehouse = self.farm_environment.warehouse
        if self._grain_bin_kg <= 0:
            return {"error": "Grain bin is already empty"}
        if self.grain_origin_farm_id is None:
            return {"error": "Grain origin is unknown"}
        farm = self.farm_environment.get_farm(self.grain_origin_farm_id)
        ridge_ids = list(self._grain_ridge_ids)
        moistures = list(self._grain_moistures_pct)
        unloaded = round(self._grain_bin_kg, 2)
        validation_error = warehouse.validate_receive_grain(
            batch_id=batch_id, origin_farm_id=farm.farm_id, kg=unloaded,
            ridge_ids=ridge_ids, moistures_pct=moistures,
            cultivar_ids=list(self._grain_cultivar_ids),
        )
        if validation_error:
            return {"error": validation_error}
        farm.advance_time(_GRAIN_UNLOAD_DURATION_S)
        result = warehouse.receive_grain(
            batch_id=batch_id, origin_farm_id=farm.farm_id, kg=unloaded,
            ridge_ids=ridge_ids, moistures_pct=moistures,
            cultivar_ids=list(self._grain_cultivar_ids),
        )
        self._grain_bin_kg = 0.0
        self.grain_origin_farm_id = None
        self._grain_cultivar_ids = []
        self._grain_ridge_ids = []
        self._grain_moistures_pct = []
        self._operation_log.append({
            "operation": "unload_grain", "batch_id": batch_id,
            "origin_farm_id": farm.farm_id, "grain_kg_unloaded": unloaded,
            "duration_s": _GRAIN_UNLOAD_DURATION_S,
        })
        self.is_state_modified = True
        return {**result, "grain_kg_unloaded": unloaded, "grain_bin_kg": 0.0,
                "duration_minutes": _GRAIN_UNLOAD_DURATION_S / 60}

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def return_supplies(self) -> dict[str, Any]:
        """Return all remaining seeds, fertilizer and chemicals to the shared warehouse.

        Fuel stays in the shared tank. Pesticide and fungicide both return to the
        warehouse chemical pool. Loading and returning supplies do not consume
        any farm's application quota. No time passes during this transfer.

        Returns:
            Warehouse ID and returned quantities.
        """
        self.farm_environment.before_tool()
        returned = {
            "seeds": self._seed_hopper,
            "seed_type": self.seed_type,
            "fertilizer_kg": self._fertilizer_spreader_kg,
            "pesticide_liters": self._pesticide_tank_l,
            "fungicide_liters": self._fungicide_tank_l,
        }
        warehouse = self.farm_environment.warehouse
        warehouse.return_supplies(
            seed_type=self.seed_type, seeds=self._seed_hopper,
            fertilizer_kg=self._fertilizer_spreader_kg,
            pesticide_liters=self._pesticide_tank_l,
            fungicide_liters=self._fungicide_tank_l,
        )
        self._seed_hopper = 0
        self.seed_type = None
        self._fertilizer_spreader_kg = 0.0
        self._pesticide_tank_l = 0.0
        self._fungicide_tank_l = 0.0
        self.is_state_modified = True
        self._operation_log.append({"operation": "return_supplies", **returned})
        return {"status": "ok", "warehouse_id": warehouse.warehouse_id,
                "returned": returned}
