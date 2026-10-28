"""Pure visualization projections over FAIRY's original soybean WOFOST tools.

The adapter is intentionally single-scene for v1. Tool execution may mutate the
world; public_state() and audit_state() never call tools, advance a clock, sample
a sensor, or serialize a native checkpoint.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
import hashlib
import importlib.util
import json
import math
import os
from typing import Any
from zoneinfo import ZoneInfo

SOURCE_COMMIT = "5a5dca63ff07cef145b1b42ef6ae27e42f5babf0"
SCENARIO_ID = "scenario_full_season_hb_base_hn84_std_normal_V2"
TITLE = "里尔 2019 大豆正常季"
_CLOSED = "Farm adapter is closed"
_INVENTORY_FIELDS = (
    "seed_stock", "pesticide_liters", "fertilizer_kg", "fuel_liters",
    "harvest_grain_kg", "warehouse_grain_kg", "grain_dried",
)
_MANAGEMENT_FIELDS = (
    "regime", "max_insecticide_applications", "max_fungicide_applications",
    "active_ingredient_cap_kg", "irrigation_quota_mm_total", "fertilizer_quota_kg",
    "max_machine_passes", "max_mechanical_weed_ridges",
    "insecticide_applications_used", "fungicide_applications_used",
    "active_ingredient_used_kg", "irrigation_used_mm_total", "fertilizer_used_kg",
    "machine_passes_used", "mechanical_weed_ridges_treated",
)
_TRACTOR_FIELDS = {
    "fuel_tank_l": "_fuel_tank_l", "pesticide_tank_l": "_pesticide_tank_l",
    "fungicide_tank_l": "_fungicide_tank_l", "fertilizer_spreader_kg": "_fertilizer_spreader_kg",
    "seed_hopper": "_seed_hopper", "grain_bin_kg": "_grain_bin_kg",
    "seed_type": "seed_type", "attached_implement": "_attached_implement",
    "source_farm_id": "source_farm_id", "grain_origin_farm_id": "grain_origin_farm_id",
}
_AUDIT_FIELDS = {
    "dvs": "DVS", "lai": "LAI", "root_vwc": "SM", "available_n_kg_ha": "NAVAIL",
    "aboveground_biomass_kg_ha": "TAGP", "storage_organ_dry_kg_ha": "TWSO",
}
_AUDIT_UNITS = {
    "dvs": "dimensionless", "lai": "m²/m²", "root_vwc": "m³/m³",
    "available_n_kg_ha": "kg N/ha", "aboveground_biomass_kg_ha": "kg dry matter/ha",
    "storage_organ_dry_kg_ha": "kg dry matter/ha",
}
_EXCLUDED_TOOLS = {
    "SystemApp__wait_for_notification",
    "AgentUserInterface__send_message_to_agent",
}


def _json(value: Any) -> Any:
    """Detach JSON-compatible public values; never stringify arbitrary objects."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Enum):
        return _json(value.value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    # Native NumPy scalar results have a numeric item(), not a state serializer.
    if type(value).__module__.startswith("numpy") and hasattr(value, "item"):
        return _json(value.item())
    raise TypeError(f"Unsupported result value: {type(value).__name__}")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(_json(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def catalog() -> dict:
    missing = [name for name in ("pcse", "numpy") if importlib.util.find_spec(name) is None]
    reason = "缺少运行依赖：" + ", ".join(missing) if missing else None
    model = os.getenv("FARM_LLM_MODEL", "").strip()
    key = os.getenv("FARM_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    sdk_available = importlib.util.find_spec("openai") is not None
    configured = bool(model and key and not missing and sdk_available)
    return {
        "schema_version": 1,
        "scenarios": [{
            "id": SCENARIO_ID, "title": TITLE, "backend": "wofost", "crop": "soybean",
            "cultivar": "SOYBEAN_901", "location": "Lille, France", "timezone": "Europe/Paris",
            "available": not missing, "reason": reason, "source_commit": SOURCE_COMMIT,
            "geometry": {"num_ridges": 64, "length_m": 268.0, "ridge_width_m": 1.1, "rows_per_ridge": 2},
        }],
        "agent": {"configured": configured,
                  "reason": None if configured else reason or (
                      "安装 openai SDK 后启用模型接管。" if not sdk_available else
                      "设置 FARM_LLM_MODEL 和 FARM_LLM_API_KEY 后启用模型接管。")},
    }


class FarmAdapter:
    def __init__(self, scenario_id: str = SCENARIO_ID, seed: int = 0):
        if scenario_id != SCENARIO_ID:
            raise ValueError("Unsupported scenario_id")
        if type(seed) is not int or seed != 0:
            raise ValueError("This fixed reference scenario supports only seed=0")
        readiness = catalog()["scenarios"][0]
        if not readiness["available"]:
            raise RuntimeError(readiness["reason"])
        from fairy.scenarios.farm_world_fullseason_v2.scenario_full_season_hb_base_hn84_std_normal_V2 import (
            ScenarioFullSeasonHBBaseHN84StdNormal_V2,
        )
        from fairy.controllers.engine import Engine
        from fairy.agents.agent.toolset_builder import build_toolset
        import pcse

        self._closed = False
        self._observation_sequence = 0
        self._observations: list[dict] = []
        self.scenario = ScenarioFullSeasonHBBaseHN84StdNormal_V2(seed=seed)
        # setup captures the oracle graph; it does NOT execute that graph.
        self.scenario.setup()
        # The pinned scene constructs its own App/Weather seeds. Do not reseed
        # after setup: that can discard randomness consumed by initialization.
        self.engine = Engine(agent=None, scenario=self.scenario)
        self.apps = list(self.scenario.apps)
        self.farm = next(app for app in self.apps if type(app).__name__ == "FarmWorldApp")
        self.sensor = next(app for app in self.apps if type(app).__name__ == "SensorApp")
        self.tractor = next(app for app in self.apps if type(app).__name__ == "TractorApp")
        self.robot = next(app for app in self.apps if type(app).__name__ == "RobotApp")
        self.timezone = ZoneInfo(self.scenario.WORLD.timezone_name)
        _, schemas, tools_map = build_toolset(self.apps)
        self.tools_map = {name: tool for name, tool in tools_map.items() if name not in _EXCLUDED_TOOLS}
        self.tool_schemas = [schema for schema in schemas if schema["function"]["name"] in self.tools_map]
        self.tools = []
        for schema in self.tool_schemas:
            definition = schema["function"]
            tool = self.tools_map[definition["name"]]
            write = getattr(tool, "write_operation", None)
            self.tools.append({
                "name": definition["name"],
                "description": definition.get("description", ""),
                "parameters": deepcopy(definition["parameters"]),
                "operation_type": "write" if write else "read",
            })
        world = asdict(self.scenario.WORLD)
        reference = self.scenario.reference
        self.descriptor = {
            "scenario_id": SCENARIO_ID, "title": TITLE, "source_commit": SOURCE_COMMIT,
            "backend": "wofost", "crop": "soybean", "cultivar": self.scenario.WORLD.seed_type,
            "location": "Lille, France", "timezone": self.scenario.WORLD.timezone_name,
            "seed": seed, "python_hash_seed": os.getenv("PYTHONHASHSEED", "process-randomized"),
            "seed_policy": "fixed upstream scenario; app initialization preserved",
            "config_fingerprint": _fingerprint({"world": world, "native_options": self.scenario.crop_backend_options}),
            "weather_fingerprint": reference["weather_sha256"],
            "cultivar_fingerprint": reference["native_parameters_sha256"],
            "model_version": pcse.__version__,
            "model_name": "Wofost81_NWLP_CWB_CNB",
            "reference": "official model reference; not field-calibrated",
        }

    @property
    def sim_time(self) -> float:
        return float(self.engine.time_manager.time())

    @property
    def sim_datetime(self) -> str:
        return datetime.fromtimestamp(self.sim_time, self.timezone).isoformat()

    def _error(self, code: str, message: str, before: float, *, partial_effects: bool | str = False) -> dict:
        return {"ok": False, "data": None,
                "error": {"code": code, "message": message, "partial_effects": partial_effects},
                "time_before": before, "time_after": self.sim_time}

    def execute(self, tool: str, args: dict) -> dict:
        if self._closed:
            raise RuntimeError(_CLOSED)
        before = self.sim_time
        target = self.tools_map.get(tool)
        if target is None:
            return self._error("unknown_tool", "Tool is not exposed by this scenario", before)
        if not isinstance(args, dict):
            return self._error("invalid_arguments", "Tool arguments must be an object", before)
        from fairy.tool_utils import typed_arguments_exception
        # Validate before effects using the SAME signature/schema/operation contract
        # as the real tool system, including legacy applications.
        exception = typed_arguments_exception(target.function, target.class_instance, (), args)
        if exception is not None:
            return self._error("invalid_arguments", str(exception)[:1000], before)
        try:
            raw = target(**args)
            response = _json(raw)
        except Exception as exc:
            # Tool errors can occur after real effects; do not claim rollback.
            return self._error("tool_exception", f"Tool execution failed ({type(exc).__name__})",
                               before, partial_effects="unknown")
        after = self.sim_time
        if isinstance(response, dict) and isinstance(response.get("ok"), bool):
            result = {
                "ok": response["ok"], "data": response.get("data"),
                "error": response.get("error"),
                "time_before": response.get("time_before", before),
                "time_after": response.get("time_after", after),
            }
        elif isinstance(response, dict) and (
            response.get("error") or response.get("status") in {"error", "failed", "rejected", "failure"}
        ):
            message = response.get("error") or response.get("reason") or response.get("status")
            error = message if isinstance(message, dict) else {
                "code": "business_rejected", "message": str(message)[:1000],
                "partial_effects": "unknown",
            }
            result = {"ok": False, "data": response, "error": error,
                      "time_before": before, "time_after": after}
        else:
            result = {"ok": True, "data": response, "error": None,
                      "time_before": before, "time_after": after}
        if result["ok"] and self._is_observation(tool):
            self._record_observation(tool, args, result["data"], after)
        return _json(result)

    @staticmethod
    def _is_observation(tool: str) -> bool:
        app, _, method = tool.partition("__")
        return ((app == "SensorApp" and method.startswith("read_"))
                or (app.startswith("Robot") and (method.startswith("inspect") or method.startswith("scout")))
                or (app == "WeatherApp" and (method.startswith("get_") or method.startswith("check_"))))

    def _record_observation(self, tool: str, args: dict, data: Any, observed_at: float) -> None:
        self._observation_sequence += 1
        ridge_ids: set[int] = set()
        def collect(value):
            if isinstance(value, dict):
                if type(value.get("ridge_id")) is int:
                    ridge_ids.add(value["ridge_id"])
                if isinstance(value.get("ridge_ids"), list):
                    ridge_ids.update(r for r in value["ridge_ids"] if type(r) is int)
                lo, hi = value.get("ridge_start"), value.get("ridge_end")
                if type(lo) is int and type(hi) is int and 0 <= lo <= hi < self.farm.num_ridges:
                    ridge_ids.update(range(lo, hi + 1))
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
        collect(data)
        # Requested range is NOT assumed observed: a robot can inspect fewer
        # ridges than requested. Only the actual result supplies coverage.
        if tool.startswith("WeatherApp__"):
            ridge_ids.update(range(self.farm.num_ridges))
        coverage = {"farm_id": self.farm.farm_id, "ridge_ids": sorted(ridge_ids)}
        # The manager stores each command-boundary snapshot as history. This
        # live cache retains the latest observation for each tool/coverage pair.
        self._observations = [record for record in self._observations
                              if record["tool"] != tool or record["coverage"] != coverage]
        self._observations.append({
            "observation_id": f"observation-{self._observation_sequence}",
            "tool": tool, "observed_at": observed_at,
            "observed_datetime": datetime.fromtimestamp(observed_at, self.timezone).isoformat(),
            "available_at": observed_at, "revision": self._observation_sequence,
            "coverage": coverage,
            "data": _json(data),
        })

    def _device_states(self) -> list[dict]:
        farm_id = self.farm.farm_id
        t = self.tractor
        tractor = {key: _json(getattr(t, attr, None)) for key, attr in _TRACTOR_FIELDS.items()}
        tractor["available_implements"] = list(t.equipment.implements)
        tractor["grain_bin_max_kg"] = 2000.0
        r = self.robot
        battery, charging = r._battery_pct, r._charging
        start, end, initial = r._charge_started_at, r._charge_complete_at, r._charge_start_battery_pct
        if charging and all(v is not None for v in (start, end, initial)):
            progress = min(max((self.sim_time - start) / max(end - start, 1.0), 0.0), 1.0)
            battery = round(initial + (100.0 - initial) * progress, 1)
            charging = self.sim_time < end
        devices = [
            {"asset_id": t.name, "farm_id": farm_id, "kind": "tractor", "name": "拖拉机",
             "state": tractor},
            {"asset_id": r.name, "farm_id": farm_id, "kind": "robot", "name": "巡检机器人",
             "state": {"battery_pct": battery, "charging": charging,
                       "charge_complete_at": end if charging else None}},
        ]
        for kind, sensors in (("soil_sensor", self.sensor._soil_sensors),
                              ("canopy_sensor", self.sensor._canopy_sensors)):
            for sensor in sensors:
                sid = sensor["sensor_id"]
                devices.append({
                    "asset_id": f"{farm_id}:{sid}", "farm_id": farm_id, "kind": kind,
                    "name": f"{'土壤' if kind == 'soil_sensor' else '冠层'}传感器 {sid}",
                    # Sensor caches contain hidden/noiseless values: copy ONLY
                    # installation metadata, never vwc/temp_c/ndvi_proxy.
                    "state": {k: sensor[k] for k in ("sensor_id", "ridge_id", "ridge_start", "ridge_end")},
                })
        return devices

    def public_state(self) -> dict:
        if self._closed:
            raise RuntimeError(_CLOSED)
        farm = self.farm
        # Use stored public shadows, NOT _agent_ridge_dict/get_farm_overview:
        # those methods refresh pending effects and can mutate world state.
        ridges = [{
            "ridge_id": r.ridge_id, "planted": bool(r.planted), "harvested": bool(r.harvested),
            "growth_stage": r.growth_stage, "grain_moisture_pct": r.grain_moisture_pct,
        } for r in farm._ridges]
        inventory = {k: _json(getattr(farm._inventory, k)) for k in _INVENTORY_FIELDS}
        management = {k: _json(getattr(farm._management_regime, k)) for k in _MANAGEMENT_FIELDS}
        management["completed_field_preparation_ops"] = list(farm.completed_prep_ops)
        management["required_field_preparation_ops"] = list(farm.required_field_preparation_ops)
        return _json({
            "farms": [{"farm_id": farm.farm_id, "name": TITLE,
                       "geometry": asdict(farm.field_geometry),
                       "ridges": ridges, "inventory": inventory, "management": management}],
            "devices": self._device_states(), "observations": self._observations,
        })

    def audit_state(self) -> dict:
        if self._closed:
            raise RuntimeError(_CLOSED)
        # Access _physics directly: the farm.physics property can lazily create it.
        physics = self.farm._physics
        backend = physics.crop_backend if physics is not None else None
        runs = getattr(backend, "_runs", {})
        ridges = []
        for ridge in self.farm._ridges:
            run = runs.get(ridge.ridge_id)
            pcse = run.pcse if run is not None else {}
            values = {name: _number(pcse.get(native)) for name, native in _AUDIT_FIELDS.items()}
            nitrogen_day = None
            if run is not None:
                # Native nitrogen events can update the pool after the last
                # completed forcing day. Read current native state, no stepping.
                nutrient = getattr(getattr(run.model, "soil", None), "nutrientbalance", None)
                if nutrient is not None:
                    values["available_n_kg_ha"] = _number(nutrient.states.NAVAIL)
                days = [d for d in (run.last_day, run.last_soil_nitrogen_event_day) if d is not None]
                nitrogen_day = max(days).isoformat() if days else None
            ridges.append({
                "ridge_id": ridge.ridge_id,
                "model_state_day": run.last_day.isoformat() if run is not None and run.last_day else None,
                "nitrogen_state_day": nitrogen_day, "values": values,
            })
        return _json({
            "farms": [{"farm_id": self.farm.farm_id, "ridges": ridges}],
            "units": _AUDIT_UNITS,
            "mapping_version": "wofost-native-v1",
            "source": "PCSE completed daily state; current native nitrogen pool",
            "notes": [
                "模型诊断值不是田间实测；未启动或未完成计算的原生值保留为空。",
                "WOFOST 按当地已完成日结算；显示时间与原生结算日分别记录。",
                "根区水分为原生平均值；适配器中的表层值不能解释为独立土层测量。",
                "DVS 到大豆阶段的映射为近似；干物质量与标准水分入库量分别解释。",
            ],
        })

    def close(self) -> None:
        self._closed = True
