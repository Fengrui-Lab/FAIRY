"""Explicitly convert legacy app-scoped workflows to shared farm tools.

This is an opt-in structural migration, never a re-signing shortcut for shared
workflows. Every old app name must have a caller-supplied identity binding.
Successful conversion proves static compatibility only: changed geometry,
initial equipment, weather or crop conditions may still make the old strategy
fail. Always replay from a fresh target initial state and evaluate the result.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any

from fairy.scenarios.workflow import Workflow
from fairy.tool_execution import WorkflowBundle, fingerprint
from fairy.tool_utils import parameters_schema, validate_schema


_FIELD_SERVICES = {"Farm": "farm", "Weather": "weather", "Sensor": "sensor", "FieldOps": "field_ops"}
_DEVICE_SERVICES = {"Tractor": "tractor", "Drone": "drone", "Robot": "robot"}
_SHARED_SERVICES = {"World", *_FIELD_SERVICES, *_DEVICE_SERVICES}


def _shared_names(runtime):
    return (_SHARED_SERVICES | {app.name for app in runtime.apps}
            | {name.split("__", 1)[0] for name in runtime.registry.names})


def _legacy_wire(value):
    # Match the legacy Workflow JSON representation (including integer map
    # keys), while refusing nonfinite values or colliding JSON object keys.
    def unique_object(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"Legacy JSON has colliding object key {key!r}")
            result[key] = item
        return result
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False), object_pairs_hook=unique_object)


@dataclass(frozen=True)
class LegacyAppBinding:
    """Explicit identity of the complete old app prefix before ``__``.

    Field/device bindings require a farm. Devices additionally require one
    asset. Platform services require an explicitly supplied platform app and
    cannot carry farm or asset IDs.
    """

    service: str
    farm_id: str | None = None
    asset_id: str | None = None


def _check_bindings(runtime, app_bindings, platform_apps):
    if not isinstance(app_bindings, Mapping) or not app_bindings:
        raise ValueError("Explicit legacy app bindings are required")
    platform = {}
    shared_names = _shared_names(runtime)
    for app in platform_apps:
        if app.name in platform:
            raise ValueError(f"Duplicate platform app {app.name!r}")
        if app.name in shared_names:
            raise ValueError("Shared agricultural services are not legacy platform apps")
        platform[app.name] = app
    bindings = {}
    used_assets = {}
    for prefix, value in app_bindings.items():
        if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", prefix) or "__" in prefix:
            raise ValueError(f"Invalid legacy app prefix {prefix!r}")
        if prefix in shared_names:
            raise ValueError(f"Already-shared app prefix {prefix!r} cannot be migrated")
        binding = LegacyAppBinding(**dict(value)) if isinstance(value, Mapping) else value
        if not isinstance(binding, LegacyAppBinding):
            raise TypeError(f"Binding for {prefix!r} must be LegacyAppBinding or an explicit mapping")
        if binding.service in _FIELD_SERVICES or binding.service in _DEVICE_SERVICES:
            if not isinstance(binding.farm_id, str) or binding.farm_id not in runtime.farms:
                raise ValueError(f"Binding {prefix!r} references unknown farm {binding.farm_id!r}")
            if binding.service in _DEVICE_SERVICES:
                asset = runtime.assets.get(binding.asset_id)
                if asset is None:
                    raise ValueError(f"Binding {prefix!r} references unknown asset {binding.asset_id!r}")
                if asset.kind != _DEVICE_SERVICES[binding.service]:
                    raise ValueError(f"Asset {binding.asset_id!r} does not match {binding.service}")
                if binding.farm_id not in asset.spec.allowed_farm_ids:
                    raise ValueError(f"Asset {binding.asset_id!r} cannot serve farm {binding.farm_id!r}")
                if binding.asset_id in used_assets:
                    raise ValueError(
                        f"Legacy device apps {used_assets[binding.asset_id]!r} and {prefix!r} map to "
                        f"the same asset {binding.asset_id!r}; rebuild the Oracle with explicit shared payload handling"
                    )
                used_assets[binding.asset_id] = prefix
            elif binding.asset_id is not None:
                raise ValueError(f"Field service binding {prefix!r} must not contain an asset_id")
        else:
            if binding.service not in platform:
                raise ValueError(f"Unknown service {binding.service!r}; platform instances must be supplied explicitly")
            if binding.farm_id is not None or binding.asset_id is not None:
                raise ValueError(f"Platform binding {prefix!r} must not contain target IDs")
        bindings[prefix] = binding
    return bindings, platform


def _source_app(runtime, binding, platform):
    if binding.service in _FIELD_SERVICES:
        return getattr(runtime.farms[binding.farm_id], _FIELD_SERVICES[binding.service])
    if binding.service in _DEVICE_SERVICES:
        from fairy.apps.farm_world.operations import operation_view
        return operation_view(runtime.context(binding.farm_id, runtime.assets[binding.asset_id]))
    return platform[binding.service]


def _manual_spray_arguments(arguments):
    values = dict(arguments)
    if not values.pop("advance_time"):
        raise ValueError("Legacy manual spray with advance_time=False has no equivalent shared tool; rebuild the Oracle")
    start = values.pop("ridge_id")
    count = values.pop("ridge_count")
    values.update(start_ridge=start, end_ridge=start + count - 1)
    return values


def migrate_legacy_workflow(
    source: Workflow,
    runtime,
    app_bindings: Mapping[str, LegacyAppBinding | Mapping[str, Any]],
    *,
    platform_apps: Sequence[Any] = (),
) -> WorkflowBundle:
    """Migrate only explicitly mapped legacy names, without executing any step.

    The caller must choose this operation explicitly. New shared prefixes are
    refused even if a binding is provided. Collapsing multiple legacy device
    instances onto one asset is refused because the source lacks the required
    return/unload semantics. The source workflow is never modified.
    """
    if not isinstance(source, Workflow):
        raise TypeError("source must be an unbundled legacy Workflow")
    wire_source = _legacy_wire(source.to_dict())
    bindings, platform = _check_bindings(runtime, app_bindings, platform_apps)
    runtime.freeze()
    converted = deepcopy(source)
    shared_names = _shared_names(runtime)
    legacy_operations = 0
    for name, step in converted.dag.items():
        step.content = deepcopy(wire_source[name]["content"])
        if not step.tool_name:
            continue
        if not isinstance(step.tool_name, str):
            raise ValueError(f"Invalid tool name at step {name!r}")
        prefix, separator, method = step.tool_name.partition("__")
        if prefix in shared_names:
            raise ValueError(f"Step {name!r} already uses shared service {prefix!r}; conversion cannot re-sign it")
        if not separator or not method or prefix not in bindings:
            raise ValueError(f"Step {name!r} has unmapped legacy app prefix {prefix!r}")
        binding = bindings[prefix]
        backend = _source_app(runtime, binding, platform)
        function = getattr(type(backend), method, None)
        if method.startswith("_") or not callable(function) or not getattr(function, "_is_app_tool", False):
            raise ValueError(f"Unknown legacy public method {prefix}__{method}")
        if step.tool_args is not None and not isinstance(step.tool_args, Mapping):
            raise ValueError(f"Step {name!r} arguments must be an object")
        # Validate the old signature too: routing fields must not be silently
        # overwritten and aliases must not discard unknown source arguments.
        values = validate_schema(parameters_schema(function), step.tool_args or {}, apply_defaults=True)
        if binding.service == "FieldOps" and method == "apply_pesticide_manual":
            values = _manual_spray_arguments(values)
        target, canonical, values = runtime.route(backend, method, values)
        if binding.service in _FIELD_SERVICES or binding.service in _DEVICE_SERVICES:
            legacy_operations += 1
            if target.name != binding.service:
                raise ValueError(f"Cannot route legacy tool {step.tool_name!r} to its explicitly declared service")
            if "farm_id" in values and values["farm_id"] != binding.farm_id:
                raise ValueError(f"Legacy tool {step.tool_name!r} resolved a different farm")
            if binding.asset_id is not None and values.get("asset_id") != binding.asset_id:
                raise ValueError(f"Legacy tool {step.tool_name!r} resolved a different asset")
        step.tool_name = f"{target.name}__{canonical}"
        step.tool_args = deepcopy(values)
    if not legacy_operations:
        raise ValueError("No legacy agricultural operations to migrate; shared or platform-only workflows cannot be re-signed")
    manifest = runtime.registry.manifest
    manifest["migration"] = {
        "kind": "explicit_legacy_app_mapping",
        "source_workflow_fingerprint": fingerprint(wire_source),
        "app_bindings": {prefix: asdict(binding) for prefix, binding in bindings.items()},
        "dynamic_success_verified": False,
    }
    bundle = WorkflowBundle(converted, manifest)
    extra_tools = {f"{app.name}__{tool.name}": tool for app in platform.values() for tool in app.get_tools()}
    bundle.validate(runtime.registry, extra_tools=extra_tools)
    converted.manifest = deepcopy(manifest)
    return bundle
