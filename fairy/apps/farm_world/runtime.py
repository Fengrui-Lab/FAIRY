"""Domain lifetime and explicit identity behind the shared farm tools."""
from __future__ import annotations

from copy import copy, deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import random
from types import SimpleNamespace
from typing import Any

from fairy.apps.farm_world.assets import AssetSpec, AssetState, tuple_tree
from fairy.apps.farm_world.operations import OperationContext, invoke_operation, operation_view
from fairy.apps.farm_world.shared_apps import make_shared_services, ASSET_ONLY, ALIASES, SINGLE_SENSOR
from fairy.time_manager import TimeManager
from fairy.tool_execution import ToolRegistry, ToolExecutor, ToolExecutionError


class FarmWeatherView:
    """Immutable target context; station meteorology never owns field moisture."""
    def __init__(self, station, farm, runtime=None, station_id=None):
        self.station, self.farm = station, farm
        self.runtime, self.station_id = runtime, station_id

    def daily_inputs(self, day):
        if self.runtime is None:
            raise ValueError("A managed weather context requires its runtime")
        return self.runtime.weather_inputs(self.station_id, day)

    def __getattr__(self, key):
        return getattr(self.station, key)

    @property
    def is_trafficable(self):
        from fairy.apps.farm_world.weather_app import _MAX_VWC_TRAFFIC
        return self.farm.get_avg_vwc() < _MAX_VWC_TRAFFIC

    def set_avg_soil_vwc(self, value):
        return {"status": "field_context", "farm_id": self.farm.farm_id}

    def set_weather(self, **kwargs):
        # Only the runtime advances shared station state. Physics can still
        # derive its daily inputs without writing another field's station.
        return {"status": "station_managed_by_runtime"}


class FarmRuntime:
    snapshot_version = 1

    def __init__(self, fleet, assets, *, seed=0, bindings=None):
        self.fleet = fleet
        self.seed = seed
        self.farms = {site.spec.farm_id: site for site in fleet.sites}
        self.assets = {}
        for spec in assets:
            if isinstance(spec, dict):
                spec = AssetSpec(**spec)
            if spec.asset_id in self.assets:
                raise ValueError(f"Duplicate asset ID {spec.asset_id!r}")
            unknown = set(spec.allowed_farm_ids) - set(self.farms)
            if unknown:
                raise ValueError(f"Asset {spec.asset_id} references unknown farms {sorted(unknown)}")
            self.assets[spec.asset_id] = AssetState(spec, seed=seed)
        for asset in self.assets.values():
            origin = asset.payload_origin_farm_id
            if origin is None:
                continue
            farm = self.farms[origin].farm
            if asset.data.get("_seed_hopper", 0):
                from fairy.apps.farm_world.crop_profiles import seed_crop_type
                if seed_crop_type(asset.data["seed_type"]) != farm.crop_type:
                    raise ValueError("Initial seed payload does not match its origin farm's crop")
            for lot in asset.grain_lots:
                if lot["crop_type"] != farm.crop_type or any(rid >= farm.num_ridges for rid in lot["ridge_ids"]):
                    raise ValueError("Initial grain batch does not match its origin crop or local ridge bounds")
        self.bindings = deepcopy(bindings or {})
        self.clock = TimeManager()
        self._last_advance = None
        self._frozen = False
        self._active = False
        self.definition_metadata = {}
        self.tool_allowlists = {}
        self.stations = {}
        self.station_farms = {}
        self._station_forcing = {}
        self._station_daily_inputs = {}
        for site in fleet.sites:
            if site.station_id in self.stations and self.stations[site.station_id] is not site.weather:
                first = {key: value for key, value in self.stations[site.station_id].get_state().items()
                         if key not in {"app_name", "avg_soil_vwc"}}
                second = {key: value for key, value in site.weather.get_state().items()
                          if key not in {"app_name", "avg_soil_vwc"}}
                if first != second:
                    raise ValueError(f"Conflicting weather data for station {site.station_id}")
                site.weather = self.stations[site.station_id]
                site.field_ops._weather_app = site.weather
            self.stations[site.station_id] = site.weather
            self.station_farms.setdefault(site.station_id, []).append(site.spec.farm_id)
            site.weather._runtime_managed_station = True
            site.farm.attach_weather_app(FarmWeatherView(site.weather, site.farm, self, site.station_id))
        self._seed_private_apps()
        self.registry = ToolRegistry()
        self.registry.set_static_validator(self.validate_static_targets)
        self.executor = ToolExecutor(self.registry, self.resolve, clock=self.clock)
        self.apps = make_shared_services(self)

    @property
    def domain_apps(self):
        result, seen = [], set()
        for site in self.fleet.sites:
            for app in site.private_apps:
                if id(app) not in seen:
                    result.append(app)
                    seen.add(id(app))
        return result

    def assets_of_kind(self, kind):
        return [asset for asset in self.assets.values() if asset.kind == kind]

    def asset_for(self, farm_id, kind):
        explicit = self.bindings.get(farm_id, {}).get(kind)
        options = [asset for asset in self.assets_of_kind(kind) if farm_id in asset.spec.allowed_farm_ids]
        if explicit is not None:
            options = [asset for asset in options if asset.asset_id == explicit]
        if len(options) != 1:
            raise ValueError(f"Farm {farm_id} needs an explicit {kind} binding; choices: {[a.asset_id for a in options]}")
        return options[0]

    def context(self, farm_id=None, asset=None):
        site = self.farms.get(farm_id) if farm_id is not None else None
        return OperationContext(None if site is None else site.farm,
                                None if site is None else FarmWeatherView(site.weather, site.farm, self, site.station_id),
                                asset, self.clock)

    def _seed_private_apps(self):
        """Shared worlds use stable streams; legacy App.set_seed stays intact."""
        for app in self.domain_apps:
            seed = int.from_bytes(hashlib.sha256(f"{self.seed}:{app.name}".encode()).digest()[:8], "big")
            app.seed, app.rng = seed, random.Random(seed)

    def _prepare_station_forcing(self):
        from fairy.apps.farm_world.runtime_state import encode_state
        for station_id, farm_ids in self.station_farms.items():
            definitions = []
            for farm_id in farm_ids:
                physics = self.farms[farm_id].farm._physics
                generator = getattr(physics, "weather_generator", None)
                profile = getattr(physics, "profile", None)
                events = getattr(profile, "weather_events", None) or []
                definitions.append({"generator": generator, "events": events})
            signatures = [json.dumps(encode_state(value), sort_keys=True, separators=(",", ":"),
                                     allow_nan=False) for value in definitions]
            if len(set(signatures)) != 1:
                raise ValueError(f"Conflicting weather forcing for station {station_id}: farms {farm_ids}")
            # One station owns its actual RNG, forecast cache and daily inputs.
            # Per-farm generators are declarations, never the managed forcing.
            self._station_forcing[station_id] = deepcopy(definitions[0])
            self._station_daily_inputs[station_id] = {}

    def weather_inputs(self, station_id, day):
        """Return one full-precision station forcing shared by every consumer."""
        from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs
        self.freeze()
        cache = self._station_daily_inputs[station_id]
        if day not in cache:
            source = self._station_forcing[station_id]
            physics = SimpleNamespace(weather_generator=source["generator"],
                                      profile=SimpleNamespace(weather_events=source["events"]))
            station = self.stations[station_id]
            displayed = station.get_current_weather_snapshot()["date"]
            today = datetime.fromtimestamp(self.clock.time(), timezone.utc).date()
            # A late-starting farm may request an uncached past day. Future
            # lookups may also populate the canonical cache. Neither may roll
            # the public station backward or publish tomorrow's observations.
            sink = station if displayed <= day.isoformat() and day <= today else copy(station)
            advance = displayed != day.isoformat()
            cache[day] = _build_weather_inputs(sink, day, physics=physics, advance_weather=advance)
        return deepcopy(cache[day])

    def device_view(self, farm_id, kind):
        return operation_view(self.context(farm_id, self.asset_for(farm_id, kind)))

    def configure_tools(self, allowlists):
        if self._frozen:
            if {k: set(v) for k, v in allowlists.items()} != self.tool_allowlists:
                raise ValueError("Tool catalog is frozen for this season")
            return
        self.tool_allowlists = {("farm" if k == "farm" else k): set(v) for k, v in allowlists.items()}
        self.registry = ToolRegistry()
        self.registry.set_static_validator(self.validate_static_targets)
        self.executor = ToolExecutor(self.registry, self.resolve, clock=self.clock)
        self.apps = make_shared_services(self)

    def freeze(self):
        if self._frozen:
            return
        from fairy.apps.farm_world.runtime_state import encode_state
        self._seed_private_apps()
        self._prepare_station_forcing()
        # Freeze after scenario soil, weather and quota initialization, before
        # any agent or reference operation. Do not hash mutable observations.
        initial = {"seed": self.seed, "farms": {fid: site.farm.get_state() for fid, site in self.farms.items()},
                   "stations": {sid: {key: value for key, value in station.get_state().items() if key != "avg_soil_vwc"}
                                for sid, station in self.stations.items()},
                   "assets": [asset.spec.to_dict() for asset in self.assets.values()], "bindings": self.bindings,
                   "scenario": deepcopy(self.definition_metadata)}
        initial["physics"] = {fid: encode_state(site.farm._physics) for fid, site in self.farms.items()}
        initial["sensors"] = {fid: encode_state({"zones": site.sensor._sensor_zones,
                                               "state": site.sensor.get_state(),
                                               "seed": site.sensor.seed, "rng": site.sensor.rng})
                              for fid, site in self.farms.items()}
        initial["actual_assets"] = {aid: encode_state(asset.snapshot()) for aid, asset in self.assets.items()}
        initial["station_forcing"] = encode_state(self._station_forcing)
        fingerprint = hashlib.sha256(json.dumps(initial, sort_keys=True, allow_nan=False).encode()).hexdigest()
        self._initial_definition = deepcopy(initial)
        self.registry.freeze(self._environment_structure(), scenario_config_fingerprint=fingerprint)
        self._frozen = True

    def _environment_structure(self):
        return {"farms": [{"farm_id": fid, "crop_type": site.farm.crop_type,
                            "layout": site.farm.configuration(),
                            "ridge_range": [0, site.farm.num_ridges - 1],
                            "crop_profile": site.farm.crop_profile.to_dict(),
                            "planting_windows": deepcopy(site.farm._planting_windows),
                            "station_id": site.station_id,
                            "sensor_ids": self.sensor_ids(farm_id=fid)}
                           for fid, site in self.farms.items()],
                "assets": [{"asset_id": a.asset_id, "kind": a.kind,
                            "allowed_farm_ids": list(a.spec.allowed_farm_ids),
                            "parameters": deepcopy(a.spec.parameters)} for a in self.assets.values()],
                "weather_stations": [{"station_id": sid, "farm_ids": list(ids)} for sid, ids in self.station_farms.items()],
                "bindings": deepcopy(self.bindings), "clock": "shared; serial operations; inter-farm travel is not modeled"}

    def describe_environment(self):
        self.freeze()
        return {**self._environment_structure(), "tool_manifest": deepcopy(self.registry.manifest),
                "response_contract": {
                    "applies_to": list(self.registry.names),
                    "services": [app.name for app in self.apps],
                    "fields": {"ok": "boolean success flag", "tool": "executed public tool name",
                               "data": "business result on success; read fields inside data",
                               "error": "null on success; structured error on failure",
                               "time_before": "simulation timestamp in seconds",
                               "time_after": "simulation timestamp in seconds"},
                    "identities": "Applicable farm_id, asset_id, station_id or sensor_id accompany the receipt",
                    "errors": {"fields": ["code", "message", "field", "stage", "partial_effects", "details"],
                               "partial_effects": "false only when no effect is established; 'unknown' means effects may have occurred; inspect state before retrying"},
                    "legacy_exceptions": ["SystemApp", "AgentUserInterface"],
                    "delegation": "A2A expert_agent calls return plain text and may modify state; the receipt applies to their inner agricultural calls.",
                }}

    def capabilities(self, context):
        from fairy.apps.farm_world.crop_profiles import seed_crop_type
        from fairy.apps.farm_world.models import SeedType
        farm = context.farm
        result = {"farm_id": context.farm_id, "crop_type": farm.crop_type,
                  "ridge_range": [0, farm.num_ridges - 1], "crop_profile": farm.crop_profile.to_dict(),
                  "planting": {"max_ridges_per_pass": 4,
                               "required_field_preparation_ops": list(farm.required_field_preparation_ops),
                               "depth_cm_range": list(farm.crop_profile.planting_depth_range_cm),
                               "seed_spacing_cm_range": farm.crop_profile.to_dict()["seed_spacing_range_cm"],
                               "compatible_seed_types": [seed.value for seed in SeedType
                                                         if seed_crop_type(seed.value) == farm.crop_type]},
                  "harvest": {"max_ridges_per_pass": 4,
                              "max_grain_moisture_pct": farm.crop_profile.harvest_moisture_max_pct}}
        if context.asset is not None:
            result["asset_id"] = context.asset_id
            result["asset_kind"] = context.asset.kind
            result["allowed_farm_ids"] = list(context.asset.spec.allowed_farm_ids)
            if context.asset.kind == "tractor":
                from fairy.apps.farm_world import tractor_app
                limits = {"fuel_tank_l": tractor_app._FUEL_TANK_MAX_L,
                          "fertilizer_spreader_kg": tractor_app._FERTILIZER_SPREADER_MAX_KG,
                          "seed_hopper_count": tractor_app._SEED_HOPPER_MAX_PLANTS,
                          "grain_bin_kg": tractor_app._GRAIN_BIN_MAX_KG,
                          "pesticide_tank_l": tractor_app._PESTICIDE_TANK_MAX_L}
                result["asset_capacities"] = limits
                override = context.asset.data.get("_harvest_moisture_limit_pct")
                if override is not None:
                    result["harvest"]["max_grain_moisture_pct"] = min(result["harvest"]["max_grain_moisture_pct"], override)
            elif context.asset.kind == "robot":
                result["inspection"] = {"max_covered_ridges_per_call": 8, "may_return_partial_coverage": True}
            elif context.asset.kind == "drone":
                result["survey"] = {"ridges_per_flight_pass": context.asset.data["effective_ridges_per_pass"],
                                    "may_return_partial_coverage": True,
                                    "speed_m_s": context.asset.data["speed_ms"]}
        return result

    def sensor_ids(self, method=None, farm_id=None):
        result = []
        for fid, site in self.farms.items():
            if farm_id is not None and fid != farm_id:
                continue
            for group in ("soil_sensors", "canopy_sensors"):
                if method and method.startswith("read_soil") and group != "soil_sensors":
                    continue
                if method and method.startswith("read_canopy") and group != "canopy_sensors":
                    continue
                for probe in site.sensor.get_state()[group]:
                    result.append(f"{fid}:{probe['sensor_id']}")
        return sorted(result)

    def validate_static_targets(self, contract, arguments):
        service, method = contract.name.split("__", 1)
        farm_id = arguments.get("farm_id")
        if service == "Sensor" and method in SINGLE_SENSOR:
            farm_id = arguments["sensor_id"].split(":", 1)[0]
        asset = self.assets.get(arguments.get("asset_id"))
        if farm_id is not None and farm_id not in self.farms:
            raise ToolExecutionError("UNKNOWN_FARM", f"Unknown farm {farm_id}", details={"valid_ids": sorted(self.farms)})
        if asset is not None and farm_id is not None and farm_id not in asset.spec.allowed_farm_ids:
            raise ToolExecutionError("ASSET_NOT_ASSIGNED", f"{asset.asset_id} cannot serve {farm_id}")
        if service in {"Tractor", "Drone", "Robot"}:
            if asset is None or asset.kind != service.lower():
                raise ToolExecutionError("WRONG_ASSET_KIND", f"{service} requires a registered {service.lower()} asset")
        if method == "form_ridges" and arguments["ridge_width_m"] != self.farms[farm_id].farm.ridge_width_m:
            raise ToolExecutionError("LAYOUT_IS_FIXED", "Use the ridge width declared in this scenario")
        if farm_id is None:
            return
        farm = self.farms[farm_id].farm
        if "ridge_id" in arguments and not 0 <= arguments["ridge_id"] < farm.num_ridges:
            raise ToolExecutionError("RIDGE_OUT_OF_BOUNDS", "ridge_id is outside this farm's local range", field="ridge_id")
        span = None
        for low_key, high_key in (("start", "end"), ("start_ridge", "end_ridge")):
            if low_key in arguments and high_key in arguments:
                low, high = arguments[low_key], arguments[high_key]
                if not 0 <= low <= high < farm.num_ridges:
                    raise ToolExecutionError("RIDGE_OUT_OF_BOUNDS", "Inclusive ridge range is outside this farm's local range",
                                             field=low_key, details={"valid_range": [0, farm.num_ridges - 1]})
                span = high - low + 1
        if span is not None:
            max_width = None
            if service == "Tractor":
                max_width = 4 if method in {"plant_seeds", "replant_seeds", "harvest"} else 10
            elif service == "FieldOps" and method == "apply_pesticide_manual":
                max_width = 2
            # Drone surveys split into passes; Robot ranges deliberately allow
            # a larger request and report partial coverage. Neither is a hard
            # request-width limit, so do not invent a new rejection here.
            if max_width is not None and span > max_width:
                raise ToolExecutionError("PASS_TOO_WIDE", f"This operation accepts at most {max_width} ridges per call",
                                         details={"max_ridges_per_call": max_width})
        if service == "Tractor" and method in {"plant_seeds", "replant_seeds"}:
            depth = arguments.get("depth_cm")
            spacing = arguments.get("seed_spacing_cm")
            if depth is not None and not farm.crop_profile.planting_depth_range_cm[0] <= depth <= farm.crop_profile.planting_depth_range_cm[1]:
                raise ToolExecutionError("CROP_PARAMETER_MISMATCH", "depth_cm is outside this crop's range", field="depth_cm")
            if spacing is not None and not farm.crop_profile.seed_spacing_range_cm[0] <= spacing <= farm.crop_profile.seed_spacing_range_cm[1]:
                raise ToolExecutionError("CROP_PARAMETER_MISMATCH", "seed_spacing_cm is outside this crop's range", field="seed_spacing_cm")
        if service == "Tractor" and "seed_type" in arguments:
            from fairy.apps.farm_world.crop_profiles import seed_crop_type
            if seed_crop_type(arguments["seed_type"]) != farm.crop_type:
                raise ToolExecutionError("CROP_PARAMETER_MISMATCH", "seed_type does not match the target crop", field="seed_type")

    def resolve(self, contract, arguments):
        self.freeze()
        self.validate_static_targets(contract, arguments)
        service, method = contract.name.split("__", 1)
        farm_id = arguments.get("farm_id")
        if service == "Sensor" and method in SINGLE_SENSOR:
            farm_id = arguments["sensor_id"].split(":", 1)[0]
        asset = self.assets.get(arguments.get("asset_id"))
        if method == "return_supplies" and asset is not None:
            farm_id = asset.payload_origin_farm_id
        context = self.context(farm_id, asset)
        return context

    def handler(self, service, method):
        """Bind one declared service method to its domain adapter."""
        adapters = {
            "World": self._world_operation,
            "Farm": self._farm_operation,
            "Weather": self._weather_operation,
            "Sensor": self._sensor_operation,
            "FieldOps": self._field_operation,
            "Tractor": self._device_operation,
            "Drone": self._device_operation,
            "Robot": self._device_operation,
        }
        if service not in adapters:
            raise ValueError(f"Unknown tool service {service!r}")
        operation = adapters[service]

        def execute(context, **arguments):
            if self._active:
                raise ToolExecutionError("RUNTIME_BUSY", "A domain operation is already running")
            self._active = True
            try:
                result = operation(context, method, arguments)
                if isinstance(result, dict) and "error" in result:
                    raise ToolExecutionError(
                        result.get("error_code", "OPERATION_REJECTED"), str(result["error"]),
                        details={"domain_result": result}, stage="execution", partial_effects="unknown",
                    )
                return _response_value(result)
            finally:
                self._active = False
        return execute

    def _world_operation(self, context: OperationContext, method: str, arguments: dict[str, Any]):
        if method == "describe_environment":
            return self.describe_environment()
        if method == "get_capabilities":
            return self.capabilities(context)
        raise ValueError(f"Unknown World operation {method!r}")

    def _farm_operation(self, context: OperationContext, method: str, arguments: dict[str, Any]):
        """Project domain truth into the farm's permitted public observations."""
        return _public_projection(getattr(context.farm, method)(**arguments))

    def _weather_operation(self, context: OperationContext, method: str, arguments: dict[str, Any]):
        site = self.farms[context.farm_id]
        today = datetime.fromtimestamp(context.clock.time(), timezone.utc).date()
        self.weather_inputs(site.station_id, today)
        result = getattr(site.weather, method)(**arguments)
        return {**result, "station_id": site.station_id}

    def _sensor_operation(self, context: OperationContext, method: str, arguments: dict[str, Any]):
        site = self.farms[context.farm_id]
        if method in SINGLE_SENSOR:
            arguments = {**arguments, "sensor_id": arguments["sensor_id"].split(":", 1)[1]}
        return getattr(site.sensor, method)(**arguments)

    def _field_operation(self, context: OperationContext, method: str, arguments: dict[str, Any]):
        site = self.farms[context.farm_id]
        if method == "apply_pesticide_manual":
            first = arguments["start_ridge"]
            arguments = {"ridge_id": first, "ridge_count": arguments["end_ridge"] - first + 1,
                         "liters_per_ridge": arguments["liters_per_ridge"], "advance_time": True}
        return getattr(site.field_ops, method)(**arguments)

    def _device_operation(self, context: OperationContext, method: str, arguments: dict[str, Any]):
        if method == "replant_seeds":
            arguments = {**arguments, "spacing_cm": arguments["seed_spacing_cm"]}
            arguments.pop("seed_spacing_cm")
        result = invoke_operation(context, method, arguments)
        if method in {"get_status", "check_status"} and "error" not in result:
            result.update(asset_id=context.asset_id,
                          payload_origin_farm_id=context.asset.payload_origin_farm_id,
                          last_farm_id=context.asset.last_farm_id)
        return result

    def route(self, app, method, arguments):
        if app in self.apps:
            return app, method, dict(arguments)
        site, service = None, None
        for item in self.fleet.sites:
            for kind in ("farm", "weather", "sensor", "field_ops"):
                if app is getattr(item, kind):
                    site, service = item, {"farm": "Farm", "weather": "Weather", "sensor": "Sensor", "field_ops": "FieldOps"}[kind]
                    break
            if site is not None:
                break
        asset = getattr(app, "_shared_asset_state", None)
        if asset is not None:
            service = asset.kind.title()
            site = self.farms.get(getattr(app, "farm_id", None))
        if service is None:
            return app, method, dict(arguments)
        values = dict(arguments)
        canonical = ALIASES.get((service, method), method)
        if service == "FieldOps" and method == "irrigate_ridge":
            values = {"start": values["ridge_id"], "end": values["ridge_id"], "hours": values["duration_hours"]}
        elif service == "FieldOps" and method == "irrigate_range":
            values["hours"] = values.pop("duration_hours")
        if service == "Tractor" and method == "replant_seeds" and "spacing_cm" in values:
            values["seed_spacing_cm"] = values.pop("spacing_cm")
        if service == "Sensor" and method in SINGLE_SENSOR:
            values["sensor_id"] = f"{site.spec.farm_id}:{values['sensor_id']}"
        elif service not in {"Tractor", "Drone", "Robot"} or method not in ASSET_ONLY:
            values["farm_id"] = site.spec.farm_id
        if asset is not None:
            values["asset_id"] = asset.asset_id
        target = next((item for item in self.apps if item.name == service), None)
        if target is None or canonical not in target._contracts:
            raise ValueError(f"Tool {service}__{canonical} is not exposed")
        return target, canonical, values

    def project_workflow_steps(self, steps):
        result = []
        for original in steps:
            step = copy(original)
            step.tool_args = deepcopy(original.tool_args or {})
            content = original.content
            farm_id = step.tool_args.get("farm_id")
            if isinstance(content, dict) and isinstance(content.get("ok"), bool):
                farm_id = farm_id or content.get("farm_id")
                data = deepcopy(content.get("data") or {})
                if not isinstance(data, dict):
                    data = {"result": data}
                if not content["ok"]:
                    data["error"] = deepcopy(content.get("error"))
                data.update({key: deepcopy(content[key]) for key in ("phase", "oracle_reason") if key in content})
                step.content = data
            service, _, method = str(step.tool_name).partition("__")
            if farm_id in self.farms:
                step.tool_args.setdefault("farm_id", farm_id)
                site = self.farms[farm_id]
                if service in {"Farm", "Weather", "Sensor", "FieldOps", "Tractor", "Drone", "Robot"}:
                    suffix = {"Farm": "Farm", "FieldOps": "FieldOps"}.get(service, service)
                    step.tool_name = f"{site.spec.name}{suffix}__{method}"
            else:
                for fid, site in self.farms.items():
                    if service.startswith(site.spec.name) and service != "SystemApp":
                        step.tool_args.setdefault("farm_id", fid)
                        break
            result.append(step)
        return result

    def operation_log(self, farm_id, kind="tractor"):
        key = {"tractor": "_operation_log", "drone": "_mission_log", "robot": "_inspection_log"}[kind]
        return [row for asset in self.assets_of_kind(kind) for row in asset.data[key] if row.get("farm_id") == farm_id]

    def bind_clock(self, clock):
        self.clock = clock
        self.executor.clock = clock
        for app in [*self.domain_apps, *self.apps]:
            app.register_time_manager(clock)
        self._last_advance = float(clock.time())

    def before_advance(self, timestamp):
        self._last_advance = timestamp
        for site in self.fleet.sites:
            site.farm.prepare_for_time_advance(timestamp)

    def advance_to(self, timestamp):
        previous = self._last_advance if self._last_advance is not None else timestamp
        day = datetime.fromtimestamp(previous, timezone.utc).date()
        end_day = datetime.fromtimestamp(timestamp, timezone.utc).date()
        marks = []
        while day < end_day:
            day += timedelta(days=1)
            marks.append(datetime.combine(day, datetime.min.time(), timezone.utc).timestamp())
        marks.append(timestamp)
        for mark in marks:
            current = datetime.fromtimestamp(mark, timezone.utc).date()
            for station_id in self.stations:
                self.weather_inputs(station_id, current)
            for site in self.fleet.sites:
                site.farm.advance_physics_time(mark)
        self._last_advance = timestamp

    def outcome(self):
        # Used by Engine for the asset-dependent part; physics remains the
        # domain's existing measured yield calculation.
        return {fid: {"combine_bin_grain_kg": round(sum(float(lot["grain_kg"]) for asset in self.assets.values()
                                                      for lot in asset.grain_lots if lot["farm_id"] == fid), 6)}
                for fid in self.farms}

    def snapshot(self):
        from fairy.apps.farm_world.runtime_state import snapshot_runtime
        return snapshot_runtime(self)

    @classmethod
    def load_snapshot(cls, state):
        from fairy.apps.farm_world.runtime_state import restore_runtime
        return restore_runtime(state)


def _public_projection(value):
    hidden = {"nutrient_index", "stand_fraction", "ndvi_proxy"}
    if isinstance(value, dict):
        return {key: _public_projection(item) for key, item in value.items() if key not in hidden}
    if isinstance(value, list):
        return [_public_projection(item) for item in value]
    return value


def _response_value(value):
    """Public JSON maps use string ridge IDs, never lossy ambiguous keys."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if isinstance(key, bool) or not isinstance(key, (str, int)):
                raise ValueError("Public response map keys must be strings or integer ridge IDs")
            normalized = str(key)
            if normalized in result:
                raise ValueError("Ambiguous public response map key")
            result[normalized] = _response_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_response_value(item) for item in value]
    return value
