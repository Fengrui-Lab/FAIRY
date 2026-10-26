"""Infrastructure for explicit, typed farm service methods.

Public methods live in ordinary classes in this package. This module never
creates methods or alters their signatures, names, parameters or docstrings.
"""
from __future__ import annotations

import inspect
from copy import deepcopy
from dataclasses import dataclass
from typing import Annotated, Any, Callable

from fairy.apps.app import App
from fairy.tool_execution import ToolExecutionError
from fairy.tool_utils import AppTool, OperationType, ToolParameter, app_tool, build_tool, parameters_schema
from fairy.types import event_registered


FarmId = Annotated[str, ToolParameter(entity_kind="farm")]
AssetId = Annotated[str, ToolParameter(entity_kind="asset")]
SensorId = Annotated[str, ToolParameter(entity_kind="sensor")]
RidgeId = Annotated[int, ToolParameter(minimum=0)]
Centimeters = Annotated[float, ToolParameter(unit="cm", exclusive_minimum=0)]
Meters = Annotated[float, ToolParameter(unit="m", exclusive_minimum=0)]
Kilograms = Annotated[float, ToolParameter(unit="kg", exclusive_minimum=0)]
Liters = Annotated[float, ToolParameter(unit="L", exclusive_minimum=0)]
Hours = Annotated[float, ToolParameter(unit="hours", exclusive_minimum=0)]
KgPerRidge = Annotated[float, ToolParameter(unit="kg/ridge", exclusive_minimum=0)]
LitersPerRidge = Annotated[float, ToolParameter(unit="L/ridge", exclusive_minimum=0)]


@dataclass(frozen=True)
class ServiceToolSpec:
    operation_type: OperationType
    routing: tuple[str, ...]


def service_tool(operation_type: OperationType, *, routing: tuple[str, ...] = ()):
    """Mark an explicit method and retain ordinary event capture semantics."""
    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        function._service_tool = ServiceToolSpec(operation_type, routing)
        return app_tool(event_registered(operation_type=operation_type)(function))
    return decorate


def argument_documentation(function: Callable[..., Any]) -> dict[str, str]:
    """Read a Google-style Args section, rejecting stale or empty entries."""
    entries: dict[str, str] = {}
    active = False
    for line in (inspect.getdoc(function) or "").splitlines():
        if line.strip() == "Args:":
            active = True
            continue
        if not active or not line.strip():
            continue
        if not line[0].isspace():
            break
        if ":" in line:
            name, description = line.strip().split(":", 1)
            if not name.isidentifier() or name in entries or not description.strip():
                raise ValueError(f"Invalid Args entry on {function.__qualname__}: {line.strip()}")
            entries[name] = description.strip()
    return entries


def validate_declaration(function: Callable[..., Any]) -> dict[str, Any]:
    """Ensure the schema describes the actual source declaration exactly."""
    source = inspect.unwrap(function)
    for candidate in (function, source):
        if "__signature__" in vars(candidate):
            raise ValueError(f"Signature overrides are forbidden: {source.__qualname__}")
    signature = inspect.signature(source)
    names = tuple(signature.parameters)
    actual = source.__code__.co_varnames[:source.__code__.co_argcount + source.__code__.co_kwonlyargcount]
    if names != actual:
        raise ValueError(f"Signature differs from source arguments: {source.__qualname__}")
    expected = set(names) - {"self"}
    documented = set(argument_documentation(source))
    if expected != documented:
        raise ValueError(f"Args differ from signature on {source.__qualname__}: "
                         f"missing={sorted(expected-documented)}, stale={sorted(documented-expected)}")
    if "Returns:" not in (inspect.getdoc(source) or ""):
        raise ValueError(f"Returns documentation required: {source.__qualname__}")
    spec = function._service_tool
    if set(spec.routing) - expected:
        raise ValueError(f"Unknown routing parameters: {source.__qualname__}")
    return parameters_schema(source, require_annotations=True)


class SharedFarmService(App):
    """Base for one public capability service, independent of farm count."""

    service_name: str
    service_kind: str
    asset_kind: str | None = None

    def __init__(self, runtime):
        super().__init__(self.service_name)
        self.runtime = runtime
        self.is_infrastructure = self.service_name == "World"
        self._contracts = {}

    @classmethod
    def declared_tools(cls):
        return {name: function for name, function in vars(cls).items()
                if callable(function) and hasattr(function, "_service_tool")}

    def _execute(self, method: str, **arguments: Any) -> dict[str, Any]:
        self.runtime.freeze()
        return self.runtime.executor.execute(f"{self.name}__{method}", arguments)

    def get_tools(self):
        self.runtime.freeze()
        if self.tool_allowlist is not None and set(self.tool_allowlist) != set(self._contracts):
            raise ValueError("Configure shared tool exposure through FarmFleet.configure_tools before the catalog freezes")
        tools = []
        for method in self._contracts:
            contract = self.runtime.registry.contract(f"{self.name}__{method}")
            tool = SharedAppTool(**vars(build_tool(self, getattr(type(self), method))))
            tool.function_description = contract.description
            tool.parameters_schema = deepcopy(contract.parameters_schema)
            tool.result_schema = deepcopy(contract.result_schema)
            tool.metadata = deepcopy(contract.metadata)
            tools.append(tool)
        return tools


class SharedAppTool(AppTool):
    """JSON-call adapter: reject invalid arguments before Python binding.

    Valid calls still enter the explicit public method, including capture.
    Direct Python callers retain ordinary Python signature error semantics.
    """

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        runtime = self.class_instance.runtime
        runtime.freeze()
        name = f"{self.app_name}__{self.name}"
        arguments = dict(kwargs)
        if args:
            try:
                bound = inspect.signature(self.function).bind(self.class_instance, *args, **kwargs)
                arguments = {key: value for key, value in bound.arguments.items() if key != "self"}
            except TypeError:
                arguments["__invalid_positional_arguments__"] = list(args)
        try:
            runtime.registry.validate_static(name, arguments)
        except ToolExecutionError:
            return runtime.executor.execute(name, arguments)
        return super().__call__(**arguments)
