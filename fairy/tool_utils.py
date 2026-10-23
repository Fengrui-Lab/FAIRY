from __future__ import annotations

import inspect
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, get_type_hints

from fairy.tool_contracts import OperationContract


class OperationType(Enum):
    READ = "read"
    WRITE = "write"


class ToolAttributeName(Enum):
    APP = "_is_app_tool"
    ENV = "_is_env_tool"
    DATA = "_is_data_tool"
    USER = "_is_user_tool"


class ToolArgumentRejection(dict):
    """JSON-compatible refusal that retains its typed cause for Agent tracing.

    Direct callers receive the normal ``error`` mapping. The Agent boundary
    records this predictable rejection through its existing tool-error path.
    """

    def __init__(self, exception: Exception) -> None:
        super().__init__(error=str(exception))
        self.exception = exception


@dataclass
class AppToolArg:
    name: str
    arg_type: str
    description: str | None = None
    has_default: bool = False
    default: Any | None = None
    choices: list[Any] | None = None
    schema_constraints: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppTool:
    class_name: str
    app_name: str
    name: str
    function_description: str | None
    args: list[AppToolArg]
    function: Callable[..., Any]
    class_instance: Any
    write_operation: bool | None = None

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if getattr(self.class_instance, "validate_tool_arguments", False):
            exception = typed_arguments_exception(self.function, self.class_instance, args, kwargs)
            if exception is not None:
                return ToolArgumentRejection(exception)
        return self.function(self.class_instance, *args, **kwargs)

    def to_open_ai(self) -> dict[str, Any]:
        properties = {
            arg.name: {"type": _json_type(arg.arg_type), "description": arg.description or ""}
            for arg in self.args
        }
        required = [arg.name for arg in self.args if not arg.has_default]
        for arg in self.args:
            properties[arg.name].update(arg.schema_constraints)
            if arg.has_default:
                properties[arg.name]["default"] = arg.default
            if arg.choices is not None:
                properties[arg.name]["enum"] = list(arg.choices)
        return {
            "type": "function",
            "function": {
                "name": f"{self.app_name}__{self.name}",
                "description": self.function_description or "",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
        }


def _json_type(type_name: str) -> str:
    return {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}.get(
        type_name, "string"
    )


def typed_arguments_error(function, instance, args, kwargs, *, check_choices: bool = True) -> str | None:
    """Compatibility text view of the typed argument validation result."""
    exception = typed_arguments_exception(function, instance, args, kwargs, check_choices=check_choices)
    return str(exception) if exception is not None else None


def typed_arguments_exception(function, instance, args, kwargs, *, check_choices: bool = True) -> Exception | None:
    """Validate primitive inputs and the operation contract before effects.

    Apps opt into this independently of source-documentation strictness. Direct
    Python calls and AppTool calls use the same parameter rules.
    """
    try:
        bound = inspect.signature(function).bind(instance, *args, **kwargs)
    except TypeError as exc:
        return TypeError(f"Invalid tool arguments: {exc}")
    bound.apply_defaults()
    hints = get_type_hints(function)
    choices = getattr(instance, "tool_parameter_choices", {})
    for name, value in bound.arguments.items():
        if name == "self":
            continue
        expected = hints.get(name)
        if expected is str:
            valid = isinstance(value, str)
        elif expected is int:
            valid = type(value) is int
        elif expected is float:
            valid = type(value) in (int, float)
            if valid:
                try:
                    valid = math.isfinite(value)
                except OverflowError:
                    valid = False
        elif expected is bool:
            valid = type(value) is bool
        else:
            valid = True
        if not valid:
            return ValueError(f"Invalid {name}: expected finite {getattr(expected, '__name__', expected)}")
        if check_choices and name in choices and value not in choices[name]:
            return ValueError(f"Invalid {name}: choose one of {choices[name]}")
    contract = _operation_contract(instance, function.__name__)
    if contract is not None:
        error = contract.validate({name: value for name, value in bound.arguments.items() if name != "self"})
        if error is not None:
            return ValueError(error)
    return None


def _operation_contract(instance: Any, method_name: str) -> OperationContract | None:
    resolver = getattr(instance, "get_tool_contract", None)
    return resolver(method_name) if resolver is not None else None


def _mark_tool(attr: ToolAttributeName, func: Callable[..., Any] | None = None):
    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        setattr(f, attr.value, True)
        return f

    return decorator if func is None else decorator(func)


def app_tool(func: Callable[..., Any] | None = None, **_: Any):
    return _mark_tool(ToolAttributeName.APP, func)


def data_tool(func: Callable[..., Any] | None = None, **_: Any):
    return _mark_tool(ToolAttributeName.DATA, func)


def env_tool(func: Callable[..., Any] | None = None, **_: Any):
    return _mark_tool(ToolAttributeName.ENV, func)


def user_tool(func: Callable[..., Any] | None = None, **_: Any):
    return _mark_tool(ToolAttributeName.USER, func)


def agent_tool(func: Callable[..., Any] | None = None, *, doc_enabled: bool = True):
    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        setattr(f, "is_agent_tool", True)
        setattr(f, ToolAttributeName.APP.value, True)
        if not doc_enabled:
            f.__doc__ = ""
        return f

    return decorator if func is None else decorator(func)


def _argument_descriptions(func: Callable[..., Any]) -> dict[str, str]:
    """Read parameter descriptions from the actual method's Args section."""
    descriptions: dict[str, str] = {}
    active = False
    current = None
    for line in (inspect.getdoc(func) or "").splitlines():
        if line.strip() in {"Args:", "Arguments:"}:
            active = True
            continue
        if not active or not line.strip():
            continue
        if not line[0].isspace():
            break
        match = re.match(r"\s+(\w+)(?:\s*\([^)]*\))?\s*:\s*(.*)", line)
        if match:
            current = match.group(1)
            descriptions[current] = match.group(2).strip()
        elif current:
            descriptions[current] += " " + line.strip()
    return descriptions


def build_tool(instance: Any, func: Callable[..., Any], failure_probability=None) -> AppTool:
    sig = inspect.signature(func)
    hints = get_type_hints(func)
    descriptions = _argument_descriptions(func)
    contract = _operation_contract(instance, func.__name__)
    if contract is not None:
        unknown = set(contract.parameters) - (set(sig.parameters) - {"self"})
        if unknown:
            raise ValueError(f"Tool {func.__name__} contract refers to unknown arguments: {sorted(unknown)}")
    choices = getattr(instance, "tool_parameter_choices", {})
    # A service can expose several tools; selectors apply only to methods
    # which actually declare them, never add arguments to another method.
    declared_choices = {name: values for name, values in choices.items() if name in sig.parameters}
    args: list[AppToolArg] = []
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        type_obj = hints.get(name, str)
        type_name = getattr(type_obj, "__name__", "str")
        parameter_contract = contract.parameters.get(name) if contract is not None else None
        parameter_choices = (parameter_contract.choices if parameter_contract is not None
                             and parameter_contract.choices is not None else declared_choices.get(name))
        args.append(
            AppToolArg(
                name=name,
                arg_type=type_name,
                description=parameter_contract.description if parameter_contract is not None else descriptions.get(name),
                has_default=param.default is not inspect._empty,
                default=None if param.default is inspect._empty else param.default,
                choices=list(parameter_choices) if parameter_choices is not None else None,
                schema_constraints=(parameter_contract.numeric.json_schema()
                                    if parameter_contract is not None and parameter_contract.numeric is not None else {}),
            )
        )
    description = contract.description if contract is not None else inspect.getdoc(func) or ""
    farm_id = getattr(instance, "bound_farm_id", None)
    if farm_id is not None:
        description += f"\nBound farm: {farm_id}. Ridge and sensor IDs are local to this farm."
    if getattr(instance, "require_explicit_tool_docs", False):
        source = inspect.unwrap(func)
        if "__signature__" in vars(func) or "__signature__" in vars(source):
            raise ValueError(f"Tool {func.__name__} cannot override its source signature")
        expected = set(sig.parameters) - {"self"}
        if expected != set(descriptions):
            raise ValueError(f"Tool {func.__name__} Args must match its explicit parameters")
        if any(p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
               for p in sig.parameters.values()):
            raise ValueError(f"Tool {func.__name__} must declare explicit arguments")
        if any(not text for text in descriptions.values()) or not description:
            raise ValueError(f"Tool {func.__name__} needs nonempty documentation")
        if any(name not in hints for name in expected):
            raise ValueError(f"Tool {func.__name__} needs explicit parameter types")
    return AppTool(
        class_name=instance.__class__.__name__,
        app_name=getattr(instance, "name", instance.__class__.__name__),
        name=func.__name__,
        function_description=description,
        args=args,
        function=func,
        class_instance=instance,
        write_operation=getattr(func, "_event_operation_type", None) == OperationType.WRITE,
    )
