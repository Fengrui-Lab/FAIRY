"""Shared tool contracts, one execution gate, and versioned workflow bundles.

Domain state and operation preconditions belong to the runtime resolver and
private handlers. This module never guesses a farm from an app name.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Mapping
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fairy.tool_utils import (
    SchemaValidationError, ToolContract, canonical_json, json_value, validate_schema,
)


MANIFEST_FORMAT_VERSION = 1
_PRIVATE_EXECUTION_DEPTH: ContextVar[int] = ContextVar("fairy_private_tool_execution_depth", default=0)


def inside_tool_execution() -> bool:
    """Legacy adapters called by a private handler must not open a second gate."""
    return _PRIVATE_EXECUTION_DEPTH.get() > 0


@contextmanager
def private_tool_execution():
    """Run a registered domain operation without opening nested legacy gates."""
    token = _PRIVATE_EXECUTION_DEPTH.set(_PRIVATE_EXECUTION_DEPTH.get() + 1)
    try:
        yield
    finally:
        _PRIVATE_EXECUTION_DEPTH.reset(token)


TOOL_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"}, "tool": {"type": "string"},
        "time_before": {"type": ["number", "null"]},
        "time_after": {"type": ["number", "null"]},
        "farm_id": {"type": "string"}, "asset_id": {"type": "string"},
        "station_id": {"type": "string"}, "sensor_id": {"type": "string"},
        "storage_id": {"type": "string"}, "data": {},
        "error": {"anyOf": [{"type": "null"}, {
            "type": "object", "properties": {
                "code": {"type": "string"}, "message": {"type": "string"},
                "field": {"type": ["string", "null"]}, "stage": {"type": "string"},
                "partial_effects": {"anyOf": [{"type": "boolean"}, {"const": "unknown"}]},
                "details": {},
            }, "required": ["code", "message", "field", "stage", "partial_effects"],
            "additionalProperties": False,
        }]},
    },
    "required": ["ok", "tool", "time_before", "time_after", "data", "error"],
    "additionalProperties": False,
}


def fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class ToolExecutionError(ValueError):
    """An explicit domain rejection, distinguishable from an internal failure."""

    def __init__(self, code: str, message: str, *, field: str | None = None,
                 details: Any = None, stage: str = "precondition",
                 partial_effects: bool | str = False) -> None:
        self.code = code
        self.message = message
        self.field = field
        self.details = details
        self.stage = stage
        self.partial_effects = partial_effects
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        result = {"code": self.code, "message": self.message, "field": self.field,
                  "stage": self.stage, "partial_effects": self.partial_effects}
        if self.details is not None:
            result["details"] = json_value(self.details)
        return result


class ToolResult(dict):
    """JSON-compatible receipt; successful results always have error=null."""

    def __init__(self, *, ok: bool, tool: str, data: Any = None,
                 error: ToolExecutionError | Mapping[str, Any] | None = None,
                 time_before: float | None = None, time_after: float | None = None,
                 **identities: Any) -> None:
        super().__init__(ok=bool(ok), tool=tool, time_before=time_before,
                         time_after=time_after, data=json_value(data),
                         error=error.to_dict() if isinstance(error, ToolExecutionError)
                         else json_value(error))
        self.update({key: json_value(value) for key, value in identities.items() if value is not None})

    @property
    def ok(self) -> bool:
        return self["ok"]

    @property
    def data(self) -> Any:
        return self["data"]

    @property
    def error(self) -> dict[str, Any] | None:
        return self["error"]

    def legacy(self) -> Any:
        if self.ok:
            return deepcopy(self.data)
        return {"error": self.error["message"], "error_code": self.error["code"],
                "error_details": deepcopy(self.error)}


class ToolRegistry:
    """A run's frozen public contracts and their unique private handlers."""

    def __init__(self, *, static_validator: Callable[[ToolContract, dict[str, Any]], None] | None = None) -> None:
        self._contracts: dict[str, ToolContract] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._world_manifest: dict[str, Any] | None = None
        self._manifest: dict[str, Any] | None = None
        self._static_validator = static_validator

    def set_static_validator(self, validator: Callable[[ToolContract, dict[str, Any]], None]) -> None:
        if self.frozen:
            raise RuntimeError("Cannot change static routing validation after freezing")
        self._static_validator = validator

    @property
    def static_validator(self):
        return self._static_validator

    @static_validator.setter
    def static_validator(self, validator):
        self.set_static_validator(validator)

    def register(self, contract: ToolContract, handler: Callable[..., Any]) -> None:
        if self.frozen:
            raise RuntimeError("Cannot register tools after the catalog is frozen")
        if contract.name in self._contracts:
            raise ValueError(f"Duplicate tool contract {contract.name!r}")
        if not callable(handler):
            raise TypeError("A tool handler must be callable")
        if getattr(handler, "_is_app_tool", False):
            raise ValueError("Register a private handler, not the public delegating method")
        self._check_handler(contract, handler)
        self._contracts[contract.name] = deepcopy(contract)
        self._handlers[contract.name] = handler

    @staticmethod
    def _check_handler(contract: ToolContract, handler: Callable[..., Any]) -> None:
        parameters = list(inspect.signature(handler).parameters.values())
        if not parameters or parameters[0].kind in (
            inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL,
        ):
            raise TypeError("A private handler must declare its context parameter first")
        payload = set(contract.parameters_schema.get("properties", {})) - set(contract.routing_parameters)
        remaining = parameters[1:]
        if any(item.kind is inspect.Parameter.VAR_POSITIONAL for item in remaining):
            raise TypeError("A private tool handler cannot accept positional varargs")
        named = {item.name for item in remaining if item.kind is not inspect.Parameter.VAR_KEYWORD}
        required = {item.name for item in remaining
                    if item.default is inspect.Parameter.empty
                    and item.kind is not inspect.Parameter.VAR_KEYWORD}
        variadic = any(item.kind is inspect.Parameter.VAR_KEYWORD for item in remaining)
        if required - payload or (not variadic and named != payload):
            raise ValueError(f"Handler payload {sorted(named)} disagrees with contract payload {sorted(payload)}")
        if any(item.kind is inspect.Parameter.POSITIONAL_ONLY for item in remaining):
            raise TypeError("Handler payload must accept keyword arguments")

    @property
    def frozen(self) -> bool:
        return self._manifest is not None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._contracts)

    @property
    def tool_names(self) -> tuple[str, ...]:
        return self.names

    def __contains__(self, name: str) -> bool:
        return name in self._contracts

    def __len__(self) -> int:
        return len(self._contracts)

    def contract(self, name: str) -> ToolContract:
        if name not in self._contracts:
            raise ToolExecutionError("UNKNOWN_TOOL", f"Unknown tool {name!r}", field="tool",
                                     details={"valid_options": list(self.names)}, stage="arguments")
        return deepcopy(self._contracts[name])

    get = contract

    def handler(self, name: str) -> Callable[..., Any]:
        self.contract(name)
        return self._handlers[name]

    def validate_static(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        contract = self.contract(name)
        try:
            normalized = contract.validate(arguments)
        except SchemaValidationError as error:
            raise ToolExecutionError("INVALID_ARGUMENT", str(error), field=error.field,
                                     stage="arguments") from error
        if self._static_validator is not None:
            self._static_validator(contract, deepcopy(normalized))
        return normalized

    def freeze(self, world_manifest: Mapping[str, Any], *,
               scenario_config_fingerprint: str | None = None) -> str:
        world = json_value(world_manifest)
        if not isinstance(world, dict):
            raise TypeError("world_manifest must be an object")
        supplied_fingerprint = world.pop("scenario_config_fingerprint", None)
        config_fingerprint = scenario_config_fingerprint or supplied_fingerprint or fingerprint(world)
        if not isinstance(config_fingerprint, str) or not config_fingerprint:
            raise ValueError("scenario_config_fingerprint must be a nonempty string")
        catalog = {"tools": [self._contracts[name].to_dict() for name in sorted(self._contracts)],
                   "world": world}
        manifest = {"format_version": MANIFEST_FORMAT_VERSION,
                    "catalog_version": fingerprint(catalog),
                    "scenario_config_fingerprint": config_fingerprint}
        if self.frozen:
            if manifest != self._manifest:
                raise RuntimeError("Cannot refreeze a changed tool catalog or world")
            return self.catalog_version
        self._world_manifest = deepcopy(world)
        self._manifest = manifest
        return self.catalog_version

    @property
    def catalog_version(self) -> str:
        if not self.frozen:
            raise RuntimeError("Freeze the tool catalog before accessing its version")
        return self._manifest["catalog_version"]

    @property
    def manifest(self) -> dict[str, Any]:
        if not self.frozen:
            raise RuntimeError("Freeze the tool catalog before creating a manifest")
        return deepcopy(self._manifest)

    def describe(self) -> dict[str, Any]:
        return {**self.manifest, "environment": deepcopy(self._world_manifest),
                "tools": [self._contracts[name].to_dict() for name in self.names]}


class ToolExecutor:
    """The shared gate used by Agent, Oracle, captured events and replay."""

    def __init__(self, registry: ToolRegistry, resolver: Callable[..., Any], *,
                 clock: Any = None, recorder: Any = None) -> None:
        self.registry = registry
        self.resolver = resolver
        owner = getattr(resolver, "__self__", None)
        self.clock = clock or getattr(owner, "clock", None) or getattr(owner, "time_manager", None)
        self.recorder = recorder
        self.history: list[ToolResult] = []

    @staticmethod
    def _time(clock: Any) -> float | None:
        if clock is None:
            return None
        read = getattr(clock, "time", None)
        return float(read()) if callable(read) else None

    @staticmethod
    def _identities(arguments: Mapping[str, Any], context: Any = None) -> dict[str, Any]:
        result = {key: value for key, value in arguments.items()
                  if key in {"farm_id", "asset_id", "station_id", "sensor_id", "storage_id"}}
        if context is not None:
            for key in ("farm_id", "asset_id", "station_id", "sensor_id", "storage_id"):
                value = getattr(context, key, None)
                if value is not None:
                    result[key] = value
        return result

    def execute(self, name: str, arguments: Mapping[str, Any], *, response_format: str = "envelope") -> Any:
        if response_format not in {"envelope", "result", "data", "legacy"}:
            raise ValueError("response_format must be envelope, result, data, or legacy")
        if not self.registry.frozen:
            raise RuntimeError("Freeze the tool catalog before executing public tools")
        context = None
        normalized: dict[str, Any] = {}
        before = self._time(self.clock)
        clock = self.clock
        stage = "arguments"
        try:
            normalized = self.registry.validate_static(name, arguments)
            contract = self.registry.contract(name)
            stage = "resolution"
            context = self.resolver(contract, deepcopy(normalized))
            clock = getattr(context, "clock", None) or self.clock
            if before is None:
                before = self._time(clock)
            payload = {key: value for key, value in normalized.items()
                       if key not in contract.routing_parameters}
            stage = "execution"
            with private_tool_execution():
                data = self.registry.handler(name)(context, **payload)
            if isinstance(data, ToolResult):
                if not data.ok:
                    error = data.error
                    raise ToolExecutionError(error["code"], error["message"], field=error.get("field"),
                                             details=error.get("details"), stage=error.get("stage", "execution"),
                                             partial_effects=error.get("partial_effects", "unknown"))
                data = data.data
            if contract.result_schema is not None and contract.response_format == "data":
                stage = "result"
                data = validate_schema(contract.result_schema, data, path="result")
            result = ToolResult(ok=True, tool=name, data=data, time_before=before,
                                time_after=self._time(clock), **self._identities(normalized, context))
            if contract.result_schema is not None and contract.response_format == "envelope":
                stage = "result"
                validate_schema(contract.result_schema, result, path="result")
        except ToolExecutionError as error:
            result = ToolResult(ok=False, tool=name, error=error, time_before=before,
                                time_after=self._time(clock), **self._identities(normalized, context))
        except Exception as error:
            # Once the handler has started we cannot promise that nothing changed.
            result = ToolResult(ok=False, tool=name, time_before=before, time_after=self._time(clock),
                                error=ToolExecutionError("INTERNAL_ERROR", f"{type(error).__name__}: {error}",
                                                         stage=stage,
                                                         partial_effects="unknown" if stage in {"execution", "result"} else False),
                                **self._identities(normalized, context))
        recorder = self.recorder or getattr(context, "recorder", None)
        record = getattr(recorder, "record_tool_result", None)
        try:
            if callable(record):
                record(deepcopy(result))
            elif callable(recorder):
                recorder(deepcopy(result))
        except Exception as error:
            result = ToolResult(ok=False, tool=name, data=result.data, time_before=before,
                                time_after=self._time(clock),
                                error=ToolExecutionError("INTERNAL_ERROR", f"Result recording failed: {error}",
                                                         stage="recording", partial_effects="unknown"),
                                **self._identities(normalized, context))
        self.history.append(deepcopy(result))
        if response_format in {"data", "legacy"}:
            return result.legacy()
        return result


@dataclass
class WorkflowBundle:
    """Keep Workflow's step dictionary intact and attach a required run manifest."""

    workflow: Any
    manifest: dict[str, Any]

    def __post_init__(self) -> None:
        self.manifest = json_value(self.manifest)
        self._validate_manifest(self.manifest)

    @staticmethod
    def _validate_manifest(manifest: Mapping[str, Any]) -> None:
        if type(manifest.get("format_version")) is not int or manifest.get("format_version") != MANIFEST_FORMAT_VERSION:
            raise ValueError("Unsupported or missing workflow manifest format_version")
        for key in ("catalog_version", "scenario_config_fingerprint"):
            if not isinstance(manifest.get(key), str) or not manifest[key]:
                raise ValueError(f"Workflow manifest requires {key}")

    @staticmethod
    def manifest_path(path: str | Path) -> Path:
        return Path(path).with_suffix(".manifest.json")

    def save(self, path: str | Path) -> None:
        path = Path(path)
        data = self.workflow.to_dict()
        manifest = {**self.manifest, "workflow_fingerprint": fingerprint(data)}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(json_value(data), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        self.manifest_path(path).write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "WorkflowBundle":
        from fairy.scenarios.workflow import Workflow
        path = Path(path)
        sidecar = cls.manifest_path(path)
        if not sidecar.is_file():
            raise ValueError(f"Missing workflow manifest: {sidecar}")
        manifest = json.loads(sidecar.read_text(encoding="utf-8"))
        cls._validate_manifest(manifest)
        workflow = Workflow.load_workflow(str(path))
        if manifest.get("workflow_fingerprint") != fingerprint(workflow.to_dict()):
            raise ValueError("Workflow and manifest fingerprint do not match")
        return cls(workflow, manifest)

    def validate(self, registry: ToolRegistry, *, extra_tools: Mapping[str, Any] | None = None) -> None:
        self._validate_manifest(self.manifest)
        if "workflow_fingerprint" in self.manifest and self.manifest["workflow_fingerprint"] != fingerprint(self.workflow.to_dict()):
            raise ValueError("Workflow and manifest fingerprint do not match")
        expected = registry.manifest
        for key in ("catalog_version", "scenario_config_fingerprint"):
            if self.manifest[key] != expected[key]:
                raise ValueError(f"Workflow {key} does not match the target runtime")
        extra_tools = extra_tools or {}
        from fairy.agents.agent.toolset_builder import build_tool_schema
        visited: set[str] = set()
        for name, step in self.workflow.dag.items():
            if set(step.depends_on or []) - visited:
                raise ValueError(f"Workflow step {name!r} has missing or forward dependencies")
            tool_name = step.tool_name
            arguments = step.tool_args or {}
            if tool_name:
                if tool_name in registry:
                    registry.validate_static(tool_name, arguments)
                elif tool_name in extra_tools:
                    schema = build_tool_schema(extra_tools[tool_name])["function"]["parameters"]
                    validate_schema(schema, arguments, apply_defaults=True)
                else:
                    raise ValueError(f"Unknown workflow tool {tool_name!r}")
            visited.add(name)

    preflight = validate
