"""Register ordinary typed service declarations for the legacy FarmRuntime.

The public surface is independent of backend app discovery. Configured farm,
asset and probe IDs specialize the declared schema without changing Python
signatures or source documentation.
"""
from __future__ import annotations

import inspect
from copy import deepcopy

from fairy.tool_execution import TOOL_RESULT_SCHEMA, ToolContract


# Workflow routing aliases remain separate from public tool declarations.
ASSET_ONLY = {"get_status", "check_status", "charge", "attach_implement", "detach_implement", "return_supplies"}
ALIASES = {("FieldOps", "irrigate_ridge"): "irrigate", ("FieldOps", "irrigate_range"): "irrigate",
           ("Tractor", "refill_pesticide_tank"): "load_pesticide"}
SINGLE_SENSOR = {"read_soil_sensor", "read_canopy_sensor"}


def make_shared_services(runtime):
    from fairy.apps.farm_world.services import SERVICE_CLASSES
    from fairy.apps.farm_world.services.base import validate_declaration

    available = {cls.service_kind: cls for cls in SERVICE_CLASSES
                 if cls.asset_kind is None or runtime.assets_of_kind(cls.asset_kind)}
    for kind, requested in runtime.tool_allowlists.items():
        declared = available[kind].declared_tools() if kind in available else {}
        if kind not in available or set(requested) - set(declared):
            raise ValueError(f"Unknown shared tools for {kind}: {sorted(set(requested)-set(declared))}")

    services = []
    for cls in available.values():
        app = cls(runtime)
        allowed = runtime.tool_allowlists.get(cls.service_kind)
        for method, function in cls.declared_tools().items():
            if allowed is not None and method not in allowed and method != "return_supplies":
                continue
            schema = validate_declaration(function)
            properties = schema["properties"]
            if "farm_id" in properties:
                properties["farm_id"]["enum"] = sorted(runtime.farms)
            if "asset_id" in properties:
                ids = sorted(runtime.assets if cls.asset_kind is None else
                             [asset.asset_id for asset in runtime.assets_of_kind(cls.asset_kind)])
                parameter = inspect.signature(function).parameters["asset_id"]
                properties["asset_id"]["enum"] = ids + ([None] if parameter.default is None else [])
            if "sensor_id" in properties:
                properties["sensor_id"]["enum"] = runtime.sensor_ids(method)
            source = inspect.unwrap(function)
            declaration = function._service_tool
            contract = ToolContract(
                f"{app.name}__{method}", inspect.getdoc(source) or method, schema,
                operation_type=declaration.operation_type,
                routing_parameters=declaration.routing,
                result_schema=deepcopy(TOOL_RESULT_SCHEMA), response_format="envelope",
                metadata={"service": app.name, "method": method,
                          "source": f"{source.__module__}.{source.__qualname__}",
                          "response_format": "farm_v2"},
            )
            runtime.registry.register(contract, runtime.handler(app.name, method))
            app._contracts[method] = contract
        services.append(app)
    return services
