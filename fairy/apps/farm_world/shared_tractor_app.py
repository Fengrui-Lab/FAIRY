"""One physical tractor shared by the farms in a FarmEnvironment.

Public tool signatures declare their real target parameters. Fixed field state is
provided by FarmContext; fuel, implements, supplies and grain stay on this App.
"""
from __future__ import annotations

from typing import Any

from fairy.apps.app import App
from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.farm_world_app import PESTICIDE_L_PER_RIDGE
from fairy.apps.farm_world.models import SeedType
from fairy.apps.farm_world.tractor_operations import TractorOperations
from fairy.time_manager import TimeManager
from fairy.tool_utils import OperationType, app_tool, data_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check


class SharedTractorApp(App, TractorOperations):
    """Shared tractor with explicit farm targets and one equipment state."""

    require_explicit_tool_docs = True

    def __init__(
        self,
        farm_environment: FarmEnvironment,
        name: str = 'Tractor',
    ) -> None:
        super().__init__(name=name)
        self.farm_environment = farm_environment
        self.tool_parameter_choices = {"farm_id": list(farm_environment.farms)}
        self._initialize_tractor_state()
        self.register_time_manager(farm_environment.time_manager)

    def register_time_manager(self, time_manager: TimeManager) -> None:
        super().register_time_manager(time_manager)
        self.farm_environment.register_time_manager(time_manager)

    def get_state(self) -> dict[str, Any]:
        return self._tractor_device_state()

    def load_state(self, state_dict: dict[str, Any]) -> None:
        self._validate_origin_state(state_dict)
        self._load_tractor_device_state(state_dict)

    def reset(self) -> None:
        super().reset()
        self._initialize_tractor_state()

    def _validate_origin_state(self, state: dict[str, Any]) -> None:
        for name in ("source_farm_id", "grain_origin_farm_id"):
            farm_id = state.get(name)
            if farm_id is not None:
                self.farm_environment.get_farm(farm_id)
        material_present = any(float(state.get(key, 0)) > 0 for key in (
            "seed_hopper", "fertilizer_spreader_kg", "pesticide_tank_l", "fungicide_tank_l"
        ))
        if material_present and state.get("source_farm_id") is None:
            raise ValueError("Nonempty shared tractor payload requires source_farm_id")
        if float(state.get("grain_bin_kg", 0)) > 0 and state.get("grain_origin_farm_id") is None:
            raise ValueError("Nonempty shared tractor grain bin requires grain_origin_farm_id")
        if int(state.get("seed_hopper", 0)) > 0 and state.get("seed_type") not in {
            seed.value for seed in SeedType
        }:
            raise ValueError("Nonempty shared tractor seed hopper requires a valid seed_type")

    def _prepare(self, farm_id: str) -> FarmContext:
        farm = self.farm_environment.get_farm(farm_id)
        self.farm_environment.before_tool()
        return farm

    def _target_error(self, farm_id: str) -> dict[str, Any] | None:
        if self._has_supplies() and self.source_farm_id is None:
            return {"farm_id": farm_id, "error": "Payload origin is unknown"}
        if self._grain_bin_kg > 0 and self.grain_origin_farm_id is None:
            return {"farm_id": farm_id, "error": "Grain origin is unknown"}
        if self.source_farm_id is not None and self.source_farm_id != farm_id:
            return {"farm_id": farm_id, "error": (
                f"Payload belongs to {self.source_farm_id}; call return_supplies for that farm before switching farms"
            )}
        if self.grain_origin_farm_id is not None and self.grain_origin_farm_id != farm_id:
            return {"farm_id": farm_id, "error": (
                f"Grain belongs to {self.grain_origin_farm_id}; unload it there before switching farms"
            )}
        return None

    def _has_supplies(self) -> bool:
        return (self._seed_hopper > 0 or self._fertilizer_spreader_kg > 0
                or self._pesticide_tank_l > 0 or self._fungicide_tank_l > 0)

    def _finish(self, farm: FarmContext, result: dict[str, Any]) -> dict[str, Any]:
        if not self._has_supplies():
            self.source_farm_id = None
        if self._grain_bin_kg <= 0:
            self.grain_origin_farm_id = None
        self.farm_environment.sync()
        return {**result, "farm_id": farm.farm_id}

    def _finish_load(self, farm: FarmContext, result: dict[str, Any]) -> dict[str, Any]:
        if "error" not in result and self._has_supplies():
            self.source_farm_id = farm.farm_id
        return self._finish(farm, result)

    def _finish_harvest(
        self,
        farm: FarmContext,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if "error" not in result and self._grain_bin_kg > 0:
            self.grain_origin_farm_id = farm.farm_id
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def attach_implement(self, implement: str) -> dict[str, Any]:
        """Mount one implement on this shared tractor.

        Only one implement can be mounted. Detach the current implement before changing it.
        No farm parameter is required because the implement belongs to this tractor.

        Args:
            implement: Implement name: grader, furrower, harvester, sprayer or cultivator.

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
    def refuel(self, farm_id: str, liters: float) -> dict[str, Any]:
        """Transfer fuel from the selected farm warehouse into the shared fuel tank.

        Requires positive liters and sufficient warehouse fuel; transfer is capped by the 100 L
        tank capacity. Fuel remains available to subsequent work on any registered farm.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            liters: Requested transfer volume in liters; must be positive.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_refuel(farm, liters=liters)
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def refill_pesticide_tank(self, farm_id: str, liters: float) -> dict[str, Any]:
        """Transfer pesticide from the selected farm warehouse into the shared spray tank.

        Requires positive liters and sufficient stock; transfer is capped by the 800 L tank
        capacity. Existing payload must belong to this farm.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            liters: Requested transfer volume in liters; must be positive.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_refill_pesticide_tank(farm, liters=liters)
        return self._finish_load(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def load_fertilizer(self, farm_id: str, kg: float) -> dict[str, Any]:
        """Load fertilizer from the selected farm warehouse into the shared spreader.

        Requires positive kilograms and sufficient stock; transfer is capped by the 500 kg
        spreader capacity. Existing payload must belong to this farm.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            kg: Requested fertilizer mass in kilograms; must be positive.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_load_fertilizer(farm, kg=kg)
        return self._finish_load(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def load_seeds(self, farm_id: str, seed_type: str, count: int) -> dict[str, Any]:
        """Load one seed variety from the selected farm warehouse into the shared hopper.

        Requires a supported seed variety, positive count and sufficient stock. Hopper capacity
        is 300000 seeds. Different varieties cannot be mixed; remaining payload belongs to this
        farm.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            seed_type: Warehouse seed variety: STANDARD, EARLY_COLD, HIGH_DENSITY,
                STRESS_TOLERANT, HEIHE43, HEIHE50, HEINONG58, HEINONG60, HEINONG84 or HEIKE71.
            count: Requested number of seeds to load; positive integer.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_load_seeds(farm, seed_type=seed_type, count=count)
        return self._finish_load(farm, result)

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_status(self) -> dict[str, Any]:
        """Read this shared tractor’s fuel, payload, implement, grain bin and farm origins.

        The same resource levels are used for all registered farms. A nonempty payload must be returned to
        its source before switching farms. No farm parameter is required to read
        this tractor's resource levels.

        Returns:
            Device resource levels and current farm origins.
        """
        self.farm_environment.before_tool()
        return self._operate_get_status()

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def level(self, farm_id: str) -> dict[str, Any]:
        """Level and till the selected farm with the shared tractor.

        Requires the grader implement, trafficable soil and 8 L of fuel. Advances all registered farms by
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
    def base_fertilize(self, farm_id: str) -> dict[str, Any]:
        """Spread base fertilizer over the selected farm with the shared tractor.

        Requires 200 kg of loaded fertilizer, 8 L of fuel and trafficable soil. Advances all
        registered farms by the operation duration and records preparation only on the selected farm.

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
        result = self._operate_base_fertilize(farm)
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def form_ridges(self, farm_id: str, ridge_width_m: float) -> dict[str, Any]:
        """Form ridge rows across the selected farm with the shared tractor.

        Requires positive ridge width, trafficable soil and 8 L of fuel. Keeps the farm’s
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

        Covers at most 10 ridges per pass. Requires positive dose, enough loaded fertilizer, 2 L
        of fuel and trafficable soil. Advances all registered farms; fertilizer effects belong to the
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

        Covers at most 4 ridges per pass. Requires completed local field preparation, bare
        ridges, a valid planting window, suitable soil, enough loaded seeds and 2 L of fuel.
        Depth must be 3–5 cm. Advances all registered farms.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            start_ridge: First local ridge ID, inclusive, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be inside the target farm and within
                the per-pass limit.
            depth_cm: Sowing depth in centimeters; allowed range 3–5.
            seed_spacing_cm: Within-row seed spacing in centimeters; must be positive.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
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
        chemical regime, enough loaded pesticide and 2 L of fuel. Advances all registered farms and
        applies effects only to the selected ridges.

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
        result = self._operate_apply_pesticide(
            farm,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
        )
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def load_pesticide(self, farm_id: str, liters: float) -> dict[str, Any]:
        """Load pesticide from the selected farm warehouse into the shared spray tank.

        Requires positive liters and sufficient stock; transfer is capped by the 800 L tank
        capacity. Existing payload must belong to this farm.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            liters: Requested transfer volume in liters; must be positive.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_load_pesticide(farm, liters=liters)
        return self._finish_load(farm, result)

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
        an allowed chemical regime, enough loaded pesticide and 2 L of fuel. Advances all
        registered farms.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            start_ridge: First local ridge ID, inclusive, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be inside the target farm and within
                the per-pass limit.
            liters_per_ridge: Spray volume in liters per ridge; must be positive.

        Returns:
            Operation result or error; farm operations include the target farm_id.
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
    def load_fungicide(self, farm_id: str, liters: float) -> dict[str, Any]:
        """Load the shared fungicide tank from the selected farm pesticide inventory.

        Requires positive liters and sufficient stock; transfer is capped by the separate 800 L
        fungicide tank capacity. Existing payload must belong to this farm.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            liters: Requested transfer volume in liters; must be positive.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
        result = self._operate_load_fungicide(farm, liters=liters)
        return self._finish_load(farm, result)

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
        an allowed chemical regime, enough loaded fungicide and 2 L of fuel. Advances all
        registered farms.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            start_ridge: First local ridge ID, inclusive, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be inside the target farm and within
                the per-pass limit.
            liters_per_ridge: Spray volume in liters per ridge; must be positive.

        Returns:
            Operation result or error; farm operations include the target farm_id.
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
        an allowed herbicide regime, enough loaded pesticide and 2 L of fuel. Advances all
        registered farms.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            start_ridge: First local ridge ID, inclusive, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be inside the target farm and within
                the per-pass limit.
            liters_per_ridge: Spray volume in liters per ridge; must be positive.

        Returns:
            Operation result or error; farm operations include the target farm_id.
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
        mechanical-weeding quota, plus 2 L of fuel. Advances all registered farms; records usage on the
        selected farm.

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

        Covers at most 4 ridges. Requires positive spacing, depth 3–5 cm, enough loaded seeds
        and 2 L of fuel. With full_replant false, existing live plants remain; true replaces the
        full stand. Advances all registered farms.

        Args:
            farm_id: Target farm ID from the environment farm directory; ridge IDs are local to
                this farm.
            start_ridge: First local ridge ID, inclusive, starting at 0.
            end_ridge: Last local ridge ID, inclusive; must be inside the target farm and within
                the per-pass limit.
            depth_cm: Sowing depth in centimeters; allowed range 3–5.
            spacing_cm: Within-row replacement seed spacing in centimeters; must be positive.
            full_replant: If true, replace all plants in each target ridge; if false, fill the
                missing stand.

        Returns:
            Operation result or error; farm operations include the target farm_id.
        """
        farm = self._prepare(farm_id)
        error = self._target_error(farm_id)
        if error:
            return error
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

        Covers at most 10 ridges. Requires 2 L of fuel. Advances all registered farms and queues residue
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

        Covers at most 4 ridges. Requires mature planted ridges, grain moisture at most 18%, no
        rain, trafficable soil, 2 L of fuel and enough room in the 2000 kg grain bin. Grain from
        different farms cannot mix. Advances all registered farms.

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
        result = self._operate_harvest(farm, start_ridge=start_ridge, end_ridge=end_ridge)
        return self._finish_harvest(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def unload_grain(self, farm_id: str) -> dict[str, Any]:
        """Unload this shared tractor’s grain bin into its origin farm warehouse.

        farm_id must match grain_origin_farm_id. Transfers the whole bin, clears its origin and
        advances all registered farms by 480 seconds. Fails when the bin is empty.

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
        result = self._operate_unload_grain(farm)
        return self._finish(farm, result)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def return_supplies(self, farm_id: str) -> dict[str, Any]:
        """Return every remaining seed, fertilizer and chemical payload to its source farm.

        Fuel stays in the shared tank. Pesticide and fungicide both return to the
        warehouse pesticide inventory. Releases the returned fertilizer's quota
        reservation. This frees the tractor for another farm.

        Args:
            farm_id: Actual source farm ID, matching source_farm_id when supplies remain.

        Returns:
            Returned quantities and farm_id, or an error without inventory changes.
        """
        farm = self._prepare(farm_id)
        if self.source_farm_id is not None and self.source_farm_id != farm_id:
            return {"farm_id": farm_id, "error": f"Supplies belong to {self.source_farm_id}"}
        if self._has_supplies() and self.source_farm_id is None:
            return {"farm_id": farm_id, "error": "Payload origin is unknown"}
        returned = {
            "seeds": self._seed_hopper,
            "seed_type": self.seed_type,
            "fertilizer_kg": self._fertilizer_spreader_kg,
            "pesticide_liters": self._pesticide_tank_l,
            "fungicide_liters": self._fungicide_tank_l,
        }
        inventory = farm.world._inventory
        if self._seed_hopper > 0:
            inventory.seed_stock[self.seed_type] = inventory.seed_stock.get(self.seed_type, 0) + self._seed_hopper
        inventory.fertilizer_kg = round(inventory.fertilizer_kg + self._fertilizer_spreader_kg, 2)
        # Warehouse withdrawal reserves fertilizer quota at loading time.
        # Release only the unused amount now returned, leaving applied fertilizer counted.
        regime = farm.world._management_regime
        regime.fertilizer_used_kg = round(
            max(0.0, regime.fertilizer_used_kg - self._fertilizer_spreader_kg), 4
        )
        inventory.pesticide_liters = round(inventory.pesticide_liters + self._pesticide_tank_l + self._fungicide_tank_l, 2)
        self._seed_hopper = 0
        self.seed_type = None
        self._fertilizer_spreader_kg = 0.0
        self._pesticide_tank_l = 0.0
        self._fungicide_tank_l = 0.0
        self.source_farm_id = None
        farm.world.is_state_modified = True
        self.is_state_modified = True
        self._operation_log.append({"operation": "return_supplies", "farm_id": farm_id, **returned})
        return self._finish(farm, {"status": "ok", "returned": returned})
