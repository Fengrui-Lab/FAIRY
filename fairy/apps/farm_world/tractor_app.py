"""Single-farm tractor API, retained for existing scenarios.

The agricultural algorithms live in TractorOperations. This App only binds their
explicit farm context to the original single-farm public signatures.
"""
from __future__ import annotations

from typing import Any

from fairy.apps.app import App
from fairy.apps.farm_world.farm_environment import FarmContext
from fairy.apps.farm_world.farm_world_app import FarmWorldApp, PESTICIDE_L_PER_RIDGE
from fairy.apps.farm_world.models import RidgeState
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.farm_world.equipment import TractorEquipment
from fairy.apps.farm_world.tractor_tool_contracts import (
    TractorContractContext, tractor_operation_contract,
)
from fairy.apps.farm_world.tractor_operations import (
    TractorOperations,
    ATTACHMENTS,
    split_pass,
    _full_field_duration,
    _pass_duration,
    _SPEED_TILL_MS,
    _SPEED_FERTILIZE_MS,
    _SPEED_RIDGE_MS,
    _SPEED_PLANT_MS,
    _SPEED_SPRAY_MS,
    _SPEED_HARVEST_MS,
    _WIDTH_FERTILIZE_M,
    _ATTACH_WIDTH_M,
    _HEADLAND_TURN_S,
    _FUEL_PER_PREP_OP,
    _FUEL_PER_PASS,
    _BASE_FERTILIZE_KG,
    _FUEL_TANK_MAX_L,
    _PESTICIDE_TANK_MAX_L,
    _FERTILIZER_SPREADER_MAX_KG,
    _SEED_HOPPER_MAX_PLANTS,
    _GRAIN_BIN_MAX_KG,
    _GRAIN_UNLOAD_DURATION_S,
    _FIELD_PREP_SEQUENCE,
    _base_fertilize_kg,
    _fuel_per_pass,
    _fuel_per_prep_op,
)
from fairy.tool_utils import OperationType, app_tool, data_tool
from fairy.tool_contracts import OperationContract
from fairy.types import event_registered
from fairy.utils.type_utils import type_check


class TractorApp(App, TractorOperations):
    """Tractor bound to one farm for the original single-farm API."""

    require_explicit_tool_docs = True
    validate_tool_arguments = True

    def __init__(
        self,
        farm_world_app: FarmWorldApp,
        weather_app: WeatherApp,
        name: str | None = None,
        *,
        equipment: TractorEquipment | None = None,
    ) -> None:
        super().__init__(name=name)
        self._farm_world_app = farm_world_app
        self._weather_app = weather_app
        farm_world_app.attach_weather_app(weather_app)
        self._farm_context = FarmContext(farm_world_app.name, farm_world_app, weather_app)
        self._initialize_tractor_state(equipment)
        self._harvest_moisture_limit_pct = farm_world_app.default_harvest_moisture_limit_pct
        self._harvest_limit_configured = False
        self._tool_contract_context = TractorContractContext(
            farms=lambda: {self._farm_world_app.farm_id or self._farm_world_app.name: self._farm_world_app},
            equipment=lambda: self.equipment,
            seed_types=lambda: self._farm_world_app.crop_definition.seed_types,
            selected_seed_type=lambda: self.seed_type,
            harvest_moisture_limit=lambda world: (
                self._harvest_moisture_limit_pct if self._harvest_limit_configured
                else world.crop_definition.harvest_rules.max_moisture_pct
            ),
        )

    def _bind_farm_context(self) -> None:
        """Use an explicit scene clock whenever this farm belongs to an environment."""
        environment = self._farm_world_app.farm_environment
        if environment is not None:
            self._farm_context = environment.get_farm(self._farm_world_app.farm_id)
        self._farm_context.legacy_clock = self.time_manager

    def get_tool_contract(self, method_name: str) -> OperationContract | None:
        return tractor_operation_contract(self._tool_contract_context, method_name)

    @property
    def _completed_prep_ops(self) -> list[str]:
        """Compatibility access to prep progress owned by this farm.
        """
        return self._farm_world_app.completed_prep_ops

    @_completed_prep_ops.setter
    def _completed_prep_ops(self, operations: list[str]) -> None:
        self._farm_world_app.completed_prep_ops = list(operations)

    def get_state(self) -> dict[str, Any]:
        state = self._tractor_device_state()
        state["completed_prep_ops"] = list(self._completed_prep_ops)
        state["crop_id"] = self._farm_world_app.crop_id
        state["harvest_moisture_limit_pct"] = self._harvest_moisture_limit_pct
        state["harvest_limit_configured"] = self._harvest_limit_configured
        state["rng_state"] = self.rng.getstate()
        return state

    def load_state(self, state_dict: dict[str, Any]) -> None:
        world = self._farm_world_app
        if state_dict.get("crop_id", "soybean") != world.crop_id:
            raise ValueError("Tractor snapshot crop does not match its bound farm")
        attached = state_dict.get("attached_implement")
        if attached is not None and attached not in self.equipment.implements:
            raise ValueError("Tractor snapshot mounts an implement not owned by this device")
        if (state_dict.get("seed_hopper", 0) > 0
                and state_dict.get("seed_type") not in world.crop_definition.seed_types):
            raise ValueError("Tractor snapshot contains seeds incompatible with its bound farm")
        self._load_tractor_device_state(state_dict)
        self._harvest_moisture_limit_pct = state_dict.get("harvest_moisture_limit_pct", world.default_harvest_moisture_limit_pct)
        self._harvest_limit_configured = state_dict.get("harvest_limit_configured", False)
        if "rng_state" in state_dict:
            from fairy.apps.farm_world.assets import tuple_tree
            self.rng.setstate(tuple_tree(state_dict["rng_state"]))
        self._completed_prep_ops = state_dict.get("completed_prep_ops", [])

    def reset(self) -> None:
        super().reset()
        self._initialize_tractor_state()
        self._harvest_moisture_limit_pct = self._farm_world_app.default_harvest_moisture_limit_pct
        self._harvest_limit_configured = False

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def attach_implement(self, implement: str) -> dict[str, Any]:
        """Mount an implement onto the tractor.

        Args:
            implement: Name of the implement to attach.
        """
        return self._operate_attach_implement(implement=implement)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def detach_implement(self) -> dict[str, Any]:
        """Remove the currently mounted implement from the tractor.
        """
        return self._operate_detach_implement()

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def refuel(self, liters: float) -> dict[str, Any]:
        """Transfer fuel from the farm warehouse to the tractor fuel tank.

        Args:
            liters: Amount to transfer .
        """
        self._bind_farm_context()
        return self._operate_refuel(self._farm_context, liters=liters)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def refill_pesticide_tank(self, liters: float) -> dict[str, Any]:
        """Transfer pesticide from the farm warehouse to the tractor spray tank.

        Args:
            liters: Amount to transfer
        """
        self._bind_farm_context()
        return self._operate_refill_pesticide_tank(self._farm_context, liters=liters)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def load_fertilizer(self, kg: float) -> dict[str, Any]:
        """Transfer fertilizer from the farm warehouse to the tractor spreader.
        Args:
            kg: Amount to transfer.
        """
        self._bind_farm_context()
        return self._operate_load_fertilizer(self._farm_context, kg=kg)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def load_seeds(self, seed_type: str, count: int) -> dict[str, Any]:
        """Transfer one permitted seed identity into this tractor's hopper.

        The bound operation contract publishes the crop's seed choices.

        Args:
            seed_type: Seed identity accepted by this loading point.
            count: Positive number of seeds requested.
        """
        self._bind_farm_context()
        return self._operate_load_seeds(self._farm_context, seed_type=seed_type, count=count)

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_status(self) -> dict[str, Any]:
        """Return tractor resource levels, implement status, and available implements.
        """
        result = self._operate_get_status()
        result["harvest_moisture_limit_pct"] = (self._harvest_moisture_limit_pct
                                                if self._harvest_limit_configured else
                                                self._farm_world_app.default_harvest_moisture_limit_pct
                                                if self._farm_world_app is not None else None)
        return result

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def level(self) -> dict[str, Any]:
        """Level and till the full field surface using the attached implement.
        """
        self._bind_farm_context()
        return self._operate_level(self._farm_context)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def base_fertilize(self, total_kg: float | None = None) -> dict[str, Any]:
        """Apply base fertilizer across the full field using the tractor spreader.

        Args:
            total_kg: Positive total fertilizer product mass; omitted uses the area-scaled field default.
        """
        self._bind_farm_context()
        return self._operate_base_fertilize(self._farm_context, total_kg=total_kg)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def form_ridges(self, ridge_width_m: float) -> dict[str, Any]:
        """Form ridge rows across the full field using a tractor-mounted ridge former.

        Args:
            ridge_width_m: Width of each ridge in metres.
        """
        self._bind_farm_context()
        return self._operate_form_ridges(self._farm_context, ridge_width_m=ridge_width_m)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_fertilizer(
        self,
        start_ridge: int,
        end_ridge: int,
        kg_per_ridge: float,
    ) -> dict[str, Any]:
        """Apply fertilizer across a contiguous block of ridges using the tractor spreader
        (up to 10 ridges per pass).

        Args:
            start_ridge:   First ridge to fertilize.
            end_ridge:     Last ridge to fertilize (max 10-ridge span).
            kg_per_ridge:  Fertilizer amount per ridge in kilograms (must be positive).
        """
        self._bind_farm_context()
        return self._operate_apply_fertilizer(
            self._farm_context,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
            kg_per_ridge=kg_per_ridge,
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def plant_seeds(
        self,
        start_ridge: int,
        end_ridge: int,
        depth_cm: float,
        seed_spacing_cm: float,
    ) -> dict[str, Any]:
        """Sow local ridges according to this field's crop operation rules.

        Args:
            start_ridge: First local ridge to plant, inclusive.
            end_ridge: Last local ridge to plant, inclusive.
            depth_cm:    Sowing depth in centimetres.
            seed_spacing_cm:
                In-row seed spacing in centimetres.
        """
        self._bind_farm_context()
        return self._operate_plant_seeds(
            self._farm_context,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
            depth_cm=depth_cm,
            seed_spacing_cm=seed_spacing_cm,
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_pesticide(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        """Apply insecticide pesticide across a contiguous block of ridges using the tractor
        spray boom (up to 10 ridges per pass).

        Args:
            start_ridge: First ridge to spray (within this farm).
            end_ridge:   Last ridge to spray (within this farm, max 10-ridge span).

        Fields without crop-protection support reject this operation before resource use.
        """
        self._bind_farm_context()
        return self._operate_apply_pesticide(
            self._farm_context,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def load_pesticide(self, liters: float) -> dict[str, Any]:
        """Transfer insecticide from the farm warehouse to the tractor's pesticide tank.

        Args:
            liters: Amount of pesticide (insecticide) to transfer from
                    warehouse to the tractor's onboard pesticide tank.
        """
        self._bind_farm_context()
        return self._operate_load_pesticide(self._farm_context, liters=liters)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def spray_pesticide(
        self,
        start_ridge: int,
        end_ridge: int,
        liters_per_ridge: float = PESTICIDE_L_PER_RIDGE,
    ) -> dict[str, Any]:
        """Spray insecticide over up to 10 contiguous ridges.

        The default dose is 8 L per ridge. Requires sprayable weather,
        trafficable soil, loaded chemical, fuel and permission under the field's
        management rules. Check the treated range and chemical use in the result.
        Fields without crop-protection support reject this operation before resource use.

        Args:
            start_ridge:      First ridge (within this farm).
            end_ridge:        Last ridge (max 10-ridge span).
            liters_per_ridge: Insecticide application rate (>0).

        Fields without crop-protection support reject this operation before resource use.
        """
        self._bind_farm_context()
        return self._operate_spray_pesticide(
            self._farm_context,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
            liters_per_ridge=liters_per_ridge,
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def load_fungicide(self, liters: float) -> dict[str, Any]:
        """Transfer fungicide from the farm warehouse to the tractor's fungicide tank.

        Fungicide is a separate chemical class from insecticide; the agent must
        load fungicide explicitly before calling apply_fungicide. The warehouse
        pesticide pool is shared (`pesticide_liters`).

        Args:
            liters: Amount to transfer.
        """
        self._bind_farm_context()
        return self._operate_load_fungicide(self._farm_context, liters=liters)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_fungicide(
        self,
        start_ridge: int,
        end_ridge: int,
        liters_per_ridge: float,
    ) -> dict[str, Any]:
        """Apply fungicide over up to 10 contiguous ridges.

        Load the fungicide tank first. Requires sprayable weather, trafficable
        soil, a positive rate, sufficient chemical and fuel, and field permission.
        Recheck disease symptoms after treatment. Fields without crop-protection
        support reject this operation before resource use.

        Args:
            start_ridge:      First ridge to spray (within this farm).
            end_ridge:        Last ridge to spray (within this farm, max 10-ridge span).
            liters_per_ridge: Fungicide application rate (>0).

        Fields without crop-protection support reject this operation before resource use.
        """
        self._bind_farm_context()
        return self._operate_apply_fungicide(
            self._farm_context,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
            liters_per_ridge=liters_per_ridge,
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_herbicide(
        self,
        start_ridge: int,
        end_ridge: int,
        liters_per_ridge: float,
    ) -> dict[str, Any]:
        """Apply herbicide over up to 10 contiguous ridges.

        Requires sprayable weather, trafficable soil, loaded chemical, fuel and
        field permission. Recheck weed conditions after treatment. Fields without
        crop-protection support reject this operation before resource use.

        Args:
            start_ridge:      First ridge to treat (within this farm).
            end_ridge:        Last ridge to treat (within this farm, max 10-ridge span).
            liters_per_ridge: Herbicide application rate (>0).

        Fields without crop-protection support reject this operation before resource use.
        """
        self._bind_farm_context()
        return self._operate_apply_herbicide(
            self._farm_context,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
            liters_per_ridge=liters_per_ridge,
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def mechanical_weed_control(
        self,
        start_ridge: int,
        end_ridge: int,
    ) -> dict[str, Any]:
        """Cultivate weeds over up to 10 contiguous ridges.

        Requires trafficable soil, fuel and the applicable machinery-pass and
        mechanical-weeding allowance. Uses no herbicide and does not consume the
        chemical-application count. Fields without crop-protection support reject
        this operation before resource use.

        Args:
            start_ridge: First ridge to cultivate (within this farm).
            end_ridge:   Last ridge to cultivate (within this farm, max 10-ridge span).

        Fields without crop-protection support reject this operation before resource use.
        """
        self._bind_farm_context()
        return self._operate_mechanical_weed_control(
            self._farm_context,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def replant_seeds(
        self,
        start_ridge: int,
        end_ridge: int,
        depth_cm: float,
        spacing_cm: float,
        full_replant: bool = False,
    ) -> dict[str, Any]:
        """Replant local ridges using the modes supported by this crop.

        The operation contract publishes supported modes and agronomic limits.

        Args:
            start_ridge: First local ridge, inclusive.
            end_ridge: Last local ridge, inclusive.
            depth_cm: Sowing depth in centimetres.
            spacing_cm: Positive in-row seed spacing in centimetres.
            full_replant: Whether this pass resets the ridge phenology.
        """
        self._bind_farm_context()
        return self._operate_replant_seeds(
            self._farm_context,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
            depth_cm=depth_cm,
            spacing_cm=spacing_cm,
            full_replant=full_replant,
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def incorporate_residue(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        """Incorporate crop residue over up to 10 contiguous ridges.

        Consumes fuel and working time and records the completed operation.
        This tool does not report a measured increase in soil carbon or fertility.

        Args:
            start_ridge: First ridge (within this farm).
            end_ridge:   Last ridge (within this farm, max 10-ridge span).
        """
        self._bind_farm_context()
        return self._operate_incorporate_residue(
            self._farm_context,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def harvest(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        """Harvest local ridges using their crop's maturity and moisture rules.

        Args:
            start_ridge: First local ridge to harvest, inclusive.
            end_ridge: Last local ridge to harvest, inclusive.
        """
        self._bind_farm_context()
        return self._operate_harvest(
            self._farm_context,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
        )

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def unload_grain(self) -> dict[str, Any]:
        """Unload the machine's grain bin into the farm's pending harvested-grain batch.

        Takes about 8 minutes. This transfer is separate from drying or admission
        to long-term warehouse storage. Check batch moisture before storing.
        """
        self._bind_farm_context()
        return self._operate_unload_grain(self._farm_context)

    def _validate_ridge_window(
        self,
        start_ridge: int,
        end_ridge: int,
        max_width: int,
    ) -> str | None:
        self._bind_farm_context()
        return self._tractor_validate_ridge_window(
            self._farm_context,
            start_ridge=start_ridge,
            end_ridge=end_ridge,
            max_width=max_width,
        )

    def _trafficability_error(self, operation: str) -> str | None:
        self._bind_farm_context()
        return self._tractor_trafficability_error(self._farm_context, operation=operation)

    def _register_planting_with_physics(
        self,
        ridges: list[RidgeState],
        seed_depth_cm: float,
        seed_spacing_cm: float,
        initial_stand_fraction_by_ridge: dict[int, float] | None = None,
    ) -> None:
        self._bind_farm_context()
        return self._tractor_register_planting_with_physics(
            self._farm_context,
            ridges=ridges,
            seed_depth_cm=seed_depth_cm,
            seed_spacing_cm=seed_spacing_cm,
            initial_stand_fraction_by_ridge=initial_stand_fraction_by_ridge,
        )

    def _register_harvest_with_physics(self, ridge_ids: list[int]) -> float:
        """Run a yield-recovery harvest pass and return total kg recovered.

        Uses the YieldRecoveryEngine to compute recovered yield per ridge
        from biological yield potential, grain moisture, machine quality, and
        field/lodging losses. The legacy set_ridge_harvested write is also
        invoked so RidgeState's planted/grain_moisture flags reset. The
        returned grain quantity replaces the fixed GRAIN_KG_PER_RIDGE × yield_potential
        used in the legacy path.
        """
        self._bind_farm_context()
        return self._tractor_register_harvest_with_physics(
            self._farm_context,
            ridge_ids=ridge_ids,
        )

    def _register_base_fertilizer_with_physics(
        self,
        ridge_ids: list[int],
        total_kg: float,
    ) -> None:
        self._bind_farm_context()
        return self._tractor_register_base_fertilizer_with_physics(
            self._farm_context,
            ridge_ids=ridge_ids,
            total_kg=total_kg,
        )

    def _register_fertilizer_with_physics(
        self,
        ridge_ids: list[int],
        kg_per_ridge: float,
        method: str,
    ) -> None:
        self._bind_farm_context()
        return self._tractor_register_fertilizer_with_physics(
            self._farm_context,
            ridge_ids=ridge_ids,
            kg_per_ridge=kg_per_ridge,
            method=method,
        )

    def _register_fungicide_with_physics(
        self,
        ridge_ids: list[int],
        liters_per_ridge: float,
    ) -> None:
        self._bind_farm_context()
        return self._tractor_register_fungicide_with_physics(
            self._farm_context,
            ridge_ids=ridge_ids,
            liters_per_ridge=liters_per_ridge,
        )

    def _register_weed_control_with_physics(
        self,
        ridge_ids: list[int],
        action_type: str,
        method: str,
        efficacy_multiplier: float,
    ) -> None:
        self._bind_farm_context()
        return self._tractor_register_weed_control_with_physics(
            self._farm_context,
            ridge_ids=ridge_ids,
            action_type=action_type,
            method=method,
            efficacy_multiplier=efficacy_multiplier,
        )

    def _register_residue_incorporation_with_physics(
        self,
        ridge_ids: list[int],
    ) -> None:
        self._bind_farm_context()
        return self._tractor_register_residue_incorporation_with_physics(
            self._farm_context,
            ridge_ids=ridge_ids,
        )

    def _register_spray_with_physics(
        self,
        ridge_ids: list[int],
        method: str,
        efficacy_multiplier: float = 1.0,
    ) -> None:
        self._bind_farm_context()
        return self._tractor_register_spray_with_physics(
            self._farm_context,
            ridge_ids=ridge_ids,
            method=method,
            efficacy_multiplier=efficacy_multiplier,
        )

    def configure_harvest(self, *, max_grain_moisture_pct: float = 18.0) -> None:
        """Configure this equipment's wet-harvest capability without changing crop maturity."""
        from math import isfinite
        limit = float(max_grain_moisture_pct)
        maximum = max(25.0, self._farm_world_app.default_harvest_moisture_limit_pct)
        if not isfinite(limit) or not 15.0 <= limit <= maximum:
            raise ValueError(f"Harvest grain moisture capability must be in [15, {maximum:g}] percent")
        self._harvest_moisture_limit_pct = limit
        self._harvest_limit_configured = True


    @property
    def _base_fertilize_kg(self) -> float:
        return _base_fertilize_kg(self._farm_world_app)

    @property
    def _fuel_per_pass(self) -> float:
        return _fuel_per_pass(self._farm_world_app)

    @property
    def _fuel_per_prep_op(self) -> float:
        return _fuel_per_prep_op(self._farm_world_app)

    def _pass_duration(self, speed_ms: float) -> int:
        return _pass_duration(self._farm_world_app, speed_ms)

    def _full_field_duration(self, working_width_m: float, speed_ms: float) -> int:
        return _full_field_duration(self._farm_world_app, working_width_m, speed_ms)
