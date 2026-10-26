"""Equipment operations with explicit per-call dependencies.

Named operation classes reuse existing agricultural rules through ordinary
inheritance. Their properties show which farm or asset owns every field. They
never initialize a legacy App or keep a second copy of equipment state.
Only shared services are public Agent tools. Compatibility site equipment
handles also enter the same assignment and payload-provenance gate.
"""
from __future__ import annotations

from collections.abc import Callable, MutableSequence
from copy import deepcopy
from dataclasses import dataclass
import inspect
from random import Random
from typing import Any, Protocol, TYPE_CHECKING

from fairy.apps.farm_world.assets import AssetState
from fairy.apps.farm_world.equipment import TractorEquipment
from fairy.apps.farm_world.farm_environment import FarmContext
from fairy.apps.farm_world.tractor_tool_contracts import TractorContractContext
from fairy.apps.farm_world.drone_app import DroneApp
from fairy.apps.farm_world.robot_app import RobotApp
from fairy.apps.farm_world.tractor_app import PESTICIDE_L_PER_RIDGE, TractorApp
from fairy.tool_execution import private_tool_execution
from fairy.tool_utils import app_tool

if TYPE_CHECKING:
    from fairy.apps.farm_world.farm_world_app import FarmWorldApp
    from fairy.time_manager import TimeManager


class OperationWeather(Protocol):
    """Weather facts consumed by equipment operation rules."""

    @property
    def rainfall_mm(self) -> float: ...

    @property
    def is_flyable(self) -> bool: ...

    @property
    def is_sprayable(self) -> bool: ...

    def get_current_weather_snapshot(self) -> dict[str, Any]: ...


class OperationRecorder(Protocol):
    def record_tool_result(self, result: dict[str, Any]) -> None: ...


@dataclass(frozen=True)
class OperationContext:
    farm: FarmWorldApp | None
    weather: OperationWeather | None
    asset: AssetState | None
    clock: TimeManager
    recorder: Callable[[dict[str, Any]], None] | OperationRecorder | None = None

    @property
    def farm_id(self) -> str | None:
        return None if self.farm is None else self.farm.farm_id

    @property
    def asset_id(self) -> str | None:
        return None if self.asset is None else self.asset.asset_id


class _ScopedLog(MutableSequence):
    """Append directly to the asset log, attaching the operation identity."""

    def __init__(self, entries: list, context: OperationContext):
        self._entries, self._context = entries, context

    def __len__(self):
        return len(self._entries)

    def __getitem__(self, index):
        return self._entries[index]

    def __setitem__(self, index, value):
        self._entries[index] = value

    def __delitem__(self, index):
        del self._entries[index]

    def insert(self, index, value):
        item = dict(value)
        item.update(farm_id=self._context.farm_id, asset_id=self._context.asset_id)
        item.setdefault("timestamp", float(self._context.clock.time()))
        self._entries.insert(index, item)


class EquipmentOperations:
    """Fixed dependencies and common asset-backed state.

    No legacy App constructor is called. The only stored field is the frozen
    OperationContext; mutable equipment fields below write to its AssetState.
    """

    def __init__(self, context: OperationContext) -> None:
        if context.asset is None:
            raise ValueError("An equipment operation requires an asset")
        self.__context = context

    @property
    def _operation_context(self) -> OperationContext:
        return self.__context

    @property
    def _shared_asset_state(self) -> AssetState:
        return self.__context.asset

    @property
    def farm_id(self) -> str | None:
        return self.__context.farm_id

    @property
    def _site_farm_id(self) -> str | None:
        return self.farm_id

    @property
    def asset_id(self) -> str:
        return self._shared_asset_state.asset_id

    @property
    def name(self) -> str:
        return self.asset_id

    @name.setter
    def name(self, value) -> None:
        raise AttributeError("Operation asset identity cannot be rebound")

    @property
    def _farm_world_app(self) -> FarmWorldApp | None:
        return self.__context.farm

    @_farm_world_app.setter
    def _farm_world_app(self, value) -> None:
        raise AttributeError("An operation's farm target cannot be rebound")

    @property
    def _weather_app(self) -> OperationWeather | None:
        return self.__context.weather

    @_weather_app.setter
    def _weather_app(self, value) -> None:
        raise AttributeError("An operation's weather dependency cannot be rebound")

    @property
    def time_manager(self) -> TimeManager:
        return self.__context.clock

    @time_manager.setter
    def time_manager(self, value) -> None:
        raise AttributeError("An operation's clock cannot be rebound")

    @property
    def rng(self) -> Random:
        return self._shared_asset_state.rng

    @rng.setter
    def rng(self, value: Random) -> None:
        self._shared_asset_state.rng = value

    @property
    def seed(self) -> int:
        return self._shared_asset_state.seed

    @seed.setter
    def seed(self, value: int) -> None:
        self._shared_asset_state.seed = value

    @property
    def is_state_modified(self) -> bool:
        return self._shared_asset_state.modified

    @is_state_modified.setter
    def is_state_modified(self, value: bool) -> None:
        self._shared_asset_state.modified = value

    @property
    def tool_allowlist(self) -> None:
        return None

    @property
    def failure_probability(self) -> None:
        return None

    def get_tools(self) -> list:
        """A bound compatibility handle is not a shared public tool service."""
        raise ValueError("Register shared public services from fleet.apps, not an internal operation handle")

    def _invoke(self, method: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        from fairy.types import EventRegisterer
        if EventRegisterer.is_capturing():
            raise RuntimeError("Capture the shared public service, not an internal operation handle")
        return invoke_operation(self._operation_context, method, arguments)


class TractorOperations(EquipmentOperations, TractorApp):
    """Tractor rules backed by one asset and one fixed farm context."""

    @property
    def equipment(self) -> TractorEquipment:
        # Historical runtime AssetSpec owns the fixed standard tractor fleet;
        # no crop rule or compatibility view creates additional implements.
        return TractorEquipment()

    @property
    def _tool_contract_context(self) -> TractorContractContext:
        world = self._farm_world_app
        return TractorContractContext(
            farms=lambda: {} if world is None else {world.farm_id: world},
            equipment=lambda: self.equipment,
            seed_types=lambda: () if world is None else world.crop_definition.seed_types,
            selected_seed_type=lambda: self.seed_type,
        )

    @property
    def _farm_context(self) -> FarmContext:
        world = self._farm_world_app
        if world is None:
            raise ValueError("Field work requires an explicit farm context")
        environment = world.farm_environment
        if environment is not None:
            return environment.get_farm(world.farm_id)
        return FarmContext(world.farm_id, world, self._weather_app,
                           legacy_clock=self.time_manager)

    def _bind_farm_context(self) -> None:
        # Dependencies are already frozen in OperationContext; never initialize
        # a new App or retain a second mutable target/equipment state.
        pass

    @property
    def source_farm_id(self) -> str | None:
        return self._shared_asset_state.payload_origin_farm_id

    @source_farm_id.setter
    def source_farm_id(self, value: str | None) -> None:
        self._shared_asset_state.payload_origin_farm_id = value

    @property
    def grain_origin_farm_id(self) -> str | None:
        return self._shared_asset_state.payload_origin_farm_id if self._grain_bin_kg > 0 else None

    @grain_origin_farm_id.setter
    def grain_origin_farm_id(self, value: str | None) -> None:
        self._shared_asset_state.payload_origin_farm_id = value

    @property
    def _harvest_limit_configured(self) -> bool:
        return self._shared_asset_state.data["_harvest_moisture_limit_pct"] is not None

    @property
    def _fuel_tank_l(self) -> float:
        return self._shared_asset_state.data["_fuel_tank_l"]

    @_fuel_tank_l.setter
    def _fuel_tank_l(self, value: float) -> None:
        self._shared_asset_state.data["_fuel_tank_l"] = value

    @property
    def _pesticide_tank_l(self) -> float:
        return self._shared_asset_state.data["_pesticide_tank_l"]

    @_pesticide_tank_l.setter
    def _pesticide_tank_l(self, value: float) -> None:
        self._shared_asset_state.data["_pesticide_tank_l"] = value

    @property
    def _fertilizer_spreader_kg(self) -> float:
        return self._shared_asset_state.data["_fertilizer_spreader_kg"]

    @_fertilizer_spreader_kg.setter
    def _fertilizer_spreader_kg(self, value: float) -> None:
        self._shared_asset_state.data["_fertilizer_spreader_kg"] = value

    @property
    def _fungicide_tank_l(self) -> float:
        return self._shared_asset_state.data["_fungicide_tank_l"]

    @_fungicide_tank_l.setter
    def _fungicide_tank_l(self, value: float) -> None:
        self._shared_asset_state.data["_fungicide_tank_l"] = value

    @property
    def _seed_hopper(self) -> int:
        return self._shared_asset_state.data["_seed_hopper"]

    @_seed_hopper.setter
    def _seed_hopper(self, value: int) -> None:
        self._shared_asset_state.data["_seed_hopper"] = value

    @property
    def seed_type(self) -> str | None:
        return self._shared_asset_state.data["seed_type"]

    @seed_type.setter
    def seed_type(self, value: str | None) -> None:
        self._shared_asset_state.data["seed_type"] = value

    @property
    def _grain_bin_kg(self) -> float:
        return self._shared_asset_state.data["_grain_bin_kg"]

    @_grain_bin_kg.setter
    def _grain_bin_kg(self, value: float) -> None:
        self._shared_asset_state.data["_grain_bin_kg"] = value

    @property
    def _attached_implement(self) -> str | None:
        return self._shared_asset_state.data["_attached_implement"]

    @_attached_implement.setter
    def _attached_implement(self, value: str | None) -> None:
        self._shared_asset_state.data["_attached_implement"] = value

    @property
    def _operation_log(self) -> _ScopedLog:
        return _ScopedLog(self._shared_asset_state.data["_operation_log"], self._operation_context)

    @_operation_log.setter
    def _operation_log(self, value: list[dict[str, Any]]) -> None:
        self._shared_asset_state.data["_operation_log"] = value

    @property
    def _completed_prep_ops(self) -> list[str]:
        farm = self._farm_world_app
        return [] if farm is None else farm._field_preparation_ops

    @_completed_prep_ops.setter
    def _completed_prep_ops(self, value: list[str]) -> None:
        if self._farm_world_app is None:
            raise ValueError("Field preparation requires a farm context")
        self._farm_world_app._field_preparation_ops = list(value)

    @property
    def _harvest_moisture_limit_pct(self) -> float | None:
        override = self._shared_asset_state.data["_harvest_moisture_limit_pct"]
        if self._farm_world_app is None:
            return override
        crop_limit = self._farm_world_app.default_harvest_moisture_limit_pct
        return crop_limit if override is None else min(crop_limit, float(override))

    @_harvest_moisture_limit_pct.setter
    def _harvest_moisture_limit_pct(self, value: float | None) -> None:
        self._shared_asset_state.data["_harvest_moisture_limit_pct"] = value

    @app_tool()
    def attach_implement(self, implement: str) -> dict[str, Any]:
        return self._invoke("attach_implement", {"implement": implement})

    @app_tool()
    def detach_implement(self) -> dict[str, Any]:
        return self._invoke("detach_implement")

    @app_tool()
    def refuel(self, liters: float) -> dict[str, Any]:
        return self._invoke("refuel", {"liters": liters})

    @app_tool()
    def refill_pesticide_tank(self, liters: float) -> dict[str, Any]:
        return self._invoke("refill_pesticide_tank", {"liters": liters})

    @app_tool()
    def load_fertilizer(self, kg: float) -> dict[str, Any]:
        return self._invoke("load_fertilizer", {"kg": kg})

    @app_tool()
    def load_seeds(self, seed_type: str, count: int) -> dict[str, Any]:
        return self._invoke("load_seeds", {"seed_type": seed_type, "count": count})

    @app_tool()
    def get_status(self) -> dict[str, Any]:
        return self._invoke("get_status")

    @app_tool()
    def level(self) -> dict[str, Any]:
        return self._invoke("level")

    @app_tool()
    def base_fertilize(self) -> dict[str, Any]:
        return self._invoke("base_fertilize")

    @app_tool()
    def form_ridges(self, ridge_width_m: float) -> dict[str, Any]:
        return self._invoke("form_ridges", {"ridge_width_m": ridge_width_m})

    @app_tool()
    def apply_fertilizer(self, start_ridge: int, end_ridge: int, kg_per_ridge: float) -> dict[str, Any]:
        return self._invoke("apply_fertilizer", {"start_ridge": start_ridge, "end_ridge": end_ridge,
                                                "kg_per_ridge": kg_per_ridge})

    @app_tool()
    def plant_seeds(self, start_ridge: int, end_ridge: int, depth_cm: float,
                   seed_spacing_cm: float) -> dict[str, Any]:
        return self._invoke("plant_seeds", {"start_ridge": start_ridge, "end_ridge": end_ridge,
                                          "depth_cm": depth_cm, "seed_spacing_cm": seed_spacing_cm})

    @app_tool()
    def apply_pesticide(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        return self._invoke("apply_pesticide", {"start_ridge": start_ridge, "end_ridge": end_ridge})

    @app_tool()
    def load_pesticide(self, liters: float) -> dict[str, Any]:
        return self._invoke("load_pesticide", {"liters": liters})

    @app_tool()
    def spray_pesticide(self, start_ridge: int, end_ridge: int,
                       liters_per_ridge: float = PESTICIDE_L_PER_RIDGE) -> dict[str, Any]:
        return self._invoke("spray_pesticide", {"start_ridge": start_ridge, "end_ridge": end_ridge,
                                              "liters_per_ridge": liters_per_ridge})

    @app_tool()
    def load_fungicide(self, liters: float) -> dict[str, Any]:
        return self._invoke("load_fungicide", {"liters": liters})

    @app_tool()
    def apply_fungicide(self, start_ridge: int, end_ridge: int, liters_per_ridge: float) -> dict[str, Any]:
        return self._invoke("apply_fungicide", {"start_ridge": start_ridge, "end_ridge": end_ridge,
                                              "liters_per_ridge": liters_per_ridge})

    @app_tool()
    def apply_herbicide(self, start_ridge: int, end_ridge: int, liters_per_ridge: float) -> dict[str, Any]:
        return self._invoke("apply_herbicide", {"start_ridge": start_ridge, "end_ridge": end_ridge,
                                              "liters_per_ridge": liters_per_ridge})

    @app_tool()
    def mechanical_weed_control(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        return self._invoke("mechanical_weed_control", {"start_ridge": start_ridge, "end_ridge": end_ridge})

    @app_tool()
    def replant_seeds(self, start_ridge: int, end_ridge: int, depth_cm: float,
                     spacing_cm: float, full_replant: bool = False) -> dict[str, Any]:
        return self._invoke("replant_seeds", {"start_ridge": start_ridge, "end_ridge": end_ridge,
                                            "depth_cm": depth_cm, "spacing_cm": spacing_cm,
                                            "full_replant": full_replant})

    @app_tool()
    def incorporate_residue(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        return self._invoke("incorporate_residue", {"start_ridge": start_ridge, "end_ridge": end_ridge})

    @app_tool()
    def harvest(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        return self._invoke("harvest", {"start_ridge": start_ridge, "end_ridge": end_ridge})

    @app_tool()
    def unload_grain(self) -> dict[str, Any]:
        return self._invoke("unload_grain")


class BatteryEquipmentOperations(EquipmentOperations):
    """Battery and charging state shared by drone and robot rules."""

    @property
    def description(self) -> str:
        return self._shared_asset_state.data["description"]

    @description.setter
    def description(self, value: str) -> None:
        self._shared_asset_state.data["description"] = value

    @property
    def _battery_pct(self) -> float:
        return self._shared_asset_state.data["_battery_pct"]

    @_battery_pct.setter
    def _battery_pct(self, value: float) -> None:
        self._shared_asset_state.data["_battery_pct"] = value

    @property
    def _charging(self) -> bool:
        return self._shared_asset_state.data["_charging"]

    @_charging.setter
    def _charging(self, value: bool) -> None:
        self._shared_asset_state.data["_charging"] = value

    @property
    def _charge_started_at(self) -> float | None:
        return self._shared_asset_state.data["_charge_started_at"]

    @_charge_started_at.setter
    def _charge_started_at(self, value: float | None) -> None:
        self._shared_asset_state.data["_charge_started_at"] = value

    @property
    def _charge_complete_at(self) -> float | None:
        return self._shared_asset_state.data["_charge_complete_at"]

    @_charge_complete_at.setter
    def _charge_complete_at(self, value: float | None) -> None:
        self._shared_asset_state.data["_charge_complete_at"] = value

    @property
    def _charge_start_battery_pct(self) -> float | None:
        return self._shared_asset_state.data["_charge_start_battery_pct"]

    @_charge_start_battery_pct.setter
    def _charge_start_battery_pct(self, value: float | None) -> None:
        self._shared_asset_state.data["_charge_start_battery_pct"] = value


class DroneOperations(BatteryEquipmentOperations, DroneApp):
    """Drone rules with explicit survey configuration and asset-backed battery."""

    @property
    def speed_ms(self) -> float:
        return self._shared_asset_state.data["speed_ms"]

    @speed_ms.setter
    def speed_ms(self, value: float) -> None:
        self._shared_asset_state.data["speed_ms"] = value

    @property
    def effective_ridges_per_pass(self) -> int:
        return self._shared_asset_state.data["effective_ridges_per_pass"]

    @effective_ridges_per_pass.setter
    def effective_ridges_per_pass(self, value: int) -> None:
        self._shared_asset_state.data["effective_ridges_per_pass"] = value

    @property
    def takeoff_overhead_s(self) -> int:
        return self._shared_asset_state.data["takeoff_overhead_s"]

    @takeoff_overhead_s.setter
    def takeoff_overhead_s(self, value: int) -> None:
        self._shared_asset_state.data["takeoff_overhead_s"] = value

    @property
    def min_battery_pct(self) -> float:
        return self._shared_asset_state.data["min_battery_pct"]

    @min_battery_pct.setter
    def min_battery_pct(self, value: float) -> None:
        self._shared_asset_state.data["min_battery_pct"] = value

    @property
    def battery_pct_per_ridge(self) -> float:
        return self._shared_asset_state.data["battery_pct_per_ridge"]

    @battery_pct_per_ridge.setter
    def battery_pct_per_ridge(self, value: float) -> None:
        self._shared_asset_state.data["battery_pct_per_ridge"] = value

    @property
    def _mission_log(self) -> _ScopedLog:
        return _ScopedLog(self._shared_asset_state.data["_mission_log"], self._operation_context)

    @_mission_log.setter
    def _mission_log(self, value: list[dict[str, Any]]) -> None:
        self._shared_asset_state.data["_mission_log"] = value

    @app_tool()
    def fly_survey(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        return self._invoke("fly_survey", {"start_ridge": start_ridge, "end_ridge": end_ridge})

    @app_tool()
    def check_status(self) -> dict[str, Any]:
        return self._invoke("check_status")

    @app_tool()
    def charge(self) -> dict[str, Any]:
        return self._invoke("charge")


class RobotOperations(BatteryEquipmentOperations, RobotApp):
    """Ground inspection rules backed by the selected robot's state."""

    @property
    def _inspection_log(self) -> _ScopedLog:
        return _ScopedLog(self._shared_asset_state.data["_inspection_log"], self._operation_context)

    @_inspection_log.setter
    def _inspection_log(self, value: list[dict[str, Any]]) -> None:
        self._shared_asset_state.data["_inspection_log"] = value

    @app_tool()
    def inspect_ridge(self, ridge_id: int) -> dict[str, Any]:
        return self._invoke("inspect_ridge", {"ridge_id": ridge_id})

    @app_tool()
    def inspect_pests(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        return self._invoke("inspect_pests", {"start_ridge": start_ridge, "end_ridge": end_ridge})

    @app_tool()
    def inspect_crop_health(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        return self._invoke("inspect_crop_health", {"start_ridge": start_ridge, "end_ridge": end_ridge})

    @app_tool()
    def inspect_emergence(self, start_ridge: int, end_ridge: int) -> dict[str, Any]:
        return self._invoke("inspect_emergence", {"start_ridge": start_ridge, "end_ridge": end_ridge})

    @app_tool()
    def check_status(self) -> dict[str, Any]:
        return self._invoke("check_status")

    @app_tool()
    def charge(self) -> dict[str, Any]:
        return self._invoke("charge")


def operation_view(context: OperationContext) -> TractorOperations | DroneOperations | RobotOperations:
    """Create a named operation class, without initializing a legacy App."""
    if context.asset is None:
        raise ValueError("An equipment operation requires an asset")
    if context.asset.kind == "tractor":
        return TractorOperations(context)
    if context.asset.kind == "drone":
        return DroneOperations(context)
    if context.asset.kind == "robot":
        return RobotOperations(context)
    raise ValueError(f"Unsupported asset kind {context.asset.kind!r}")


# Fixed references to existing methods, with no dynamic getattr dispatch.
_TRACTOR_OPERATIONS = {
    "attach_implement": TractorApp.attach_implement,
    "detach_implement": TractorApp.detach_implement,
    "refuel": TractorApp.refuel,
    "refill_pesticide_tank": TractorApp.refill_pesticide_tank,
    "load_fertilizer": TractorApp.load_fertilizer,
    "load_seeds": TractorApp.load_seeds,
    "get_status": TractorApp.get_status,
    "level": TractorApp.level,
    "base_fertilize": TractorApp.base_fertilize,
    "form_ridges": TractorApp.form_ridges,
    "apply_fertilizer": TractorApp.apply_fertilizer,
    "plant_seeds": TractorApp.plant_seeds,
    "apply_pesticide": TractorApp.apply_pesticide,
    "load_pesticide": TractorApp.load_pesticide,
    "spray_pesticide": TractorApp.spray_pesticide,
    "load_fungicide": TractorApp.load_fungicide,
    "apply_fungicide": TractorApp.apply_fungicide,
    "apply_herbicide": TractorApp.apply_herbicide,
    "mechanical_weed_control": TractorApp.mechanical_weed_control,
    "replant_seeds": TractorApp.replant_seeds,
    "incorporate_residue": TractorApp.incorporate_residue,
    "harvest": TractorApp.harvest,
    "unload_grain": TractorApp.unload_grain,
}
_DRONE_OPERATIONS = {
    "fly_survey": DroneApp.fly_survey,
    "check_status": DroneApp.check_status,
    "charge": DroneApp.charge,
}
_ROBOT_OPERATIONS = {
    "inspect_ridge": RobotApp.inspect_ridge,
    "inspect_pests": RobotApp.inspect_pests,
    "inspect_crop_health": RobotApp.inspect_crop_health,
    "inspect_emergence": RobotApp.inspect_emergence,
    "check_status": RobotApp.check_status,
    "charge": RobotApp.charge,
}
_OPERATIONS = {"tractor": _TRACTOR_OPERATIONS, "drone": _DRONE_OPERATIONS,
               "robot": _ROBOT_OPERATIONS}
_ASSET_ONLY = {"get_status", "check_status", "charge", "attach_implement", "detach_implement"}


def _error(code: str, reason: str, **details):
    return {"error": reason, "error_code": code, **details}


def return_supplies(context: OperationContext) -> dict[str, Any]:
    asset = context.asset
    if asset.kind != "tractor":
        return _error("wrong_asset_kind", "Only a tractor has seed/fertilizer/chemical supplies")
    if not asset.has_supplies():
        return {"status": "ok", "returned": {}, "asset_id": asset.asset_id}
    origin = asset.payload_origin_farm_id
    if context.farm is None or context.farm_id != origin:
        return _error("payload_origin_mismatch", "Return supplies to their recorded origin farm", origin_farm_id=origin)
    data, inventory = asset.data, context.farm._inventory
    seeds = int(data["_seed_hopper"])
    fertilizer = float(data["_fertilizer_spreader_kg"])
    pesticide = float(data["_pesticide_tank_l"])
    fungicide = float(data["_fungicide_tank_l"])
    if seeds:
        seed_type = data["seed_type"]
        if seed_type not in inventory.seed_stock:
            return _error("unknown_payload_material", "Source inventory does not recognize the loaded seed type")
        inventory.seed_stock[seed_type] += seeds
    inventory.fertilizer_kg = round(inventory.fertilizer_kg + fertilizer, 6)
    inventory.pesticide_liters = round(inventory.pesticide_liters + pesticide + fungicide, 6)
    returned = {"seed_type": data["seed_type"], "seeds": seeds,
                "fertilizer_kg": fertilizer, "pesticide_liters": pesticide,
                "fungicide_liters": fungicide}
    for key in ("_seed_hopper", "_fertilizer_spreader_kg", "_pesticide_tank_l", "_fungicide_tank_l"):
        data[key] = 0
    data["seed_type"] = None
    asset.reconcile_payload_origin()
    asset.modified = context.farm.is_state_modified = True
    _ScopedLog(data["_operation_log"], context).append({"operation": "return_supplies", "returned": deepcopy(returned)})
    return {"status": "ok", "returned": returned, "origin_farm_id": origin, "asset_id": asset.asset_id}


def invoke_operation(context: OperationContext, method: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute one real operation against explicit state; return its legacy result.

    Public tool services perform their schema checks before calling this private
    boundary.  This boundary additionally enforces asset/farm/provenance identity.
    The fixed method registry runs inside a private execution scope, so existing
    decorators do not open a second tool gate or capture an internal handle.
    """
    arguments = dict(args or {})
    asset = context.asset
    if asset is None:
        return _error("missing_asset_context", "An equipment operation requires an explicit asset")
    if context.farm_id is not None and context.farm_id not in asset.spec.allowed_farm_ids:
        return _error("asset_farm_not_allowed", "Asset is not allowed to serve this farm", allowed_farm_ids=list(asset.spec.allowed_farm_ids))
    if method == "return_supplies":
        if arguments:
            return _error("unexpected_arguments", "return_supplies has no operation arguments")
        return return_supplies(context)
    if context.farm is None and method not in _ASSET_ONLY:
        return _error("missing_farm_context", "This operation requires an explicit farm target")
    if (context.farm is not None and method not in _ASSET_ONLY
            and asset.has_payload() and asset.payload_origin_farm_id != context.farm_id):
        return _error("payload_origin_mismatch", "Finish, unload or return this asset's payload before serving another farm",
                      origin_farm_id=asset.payload_origin_farm_id)
    implementation = _OPERATIONS[asset.kind].get(method)
    if implementation is None:
        return _error("unknown_operation", f"No public {asset.kind} operation {method!r}")
    view = operation_view(context)
    try:
        inspect.signature(implementation).bind(view, **arguments)
    except TypeError as error:
        return _error("invalid_arguments", str(error))
    try:
        with private_tool_execution():
            result = implementation(view, **arguments)
    finally:
        # Preserve provenance even when an internal failure follows a mutation.
        asset.reconcile_payload_origin(context.farm_id)
    if not isinstance(result, dict):
        result = {"result": result}
    if "error" not in result and context.farm_id is not None and method not in _ASSET_ONLY:
        asset.last_farm_id = context.farm_id
    return result
