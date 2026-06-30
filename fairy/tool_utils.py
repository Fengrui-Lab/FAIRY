from __future__ import annotations

import inspect
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Any, Callable, get_type_hints


class OperationType(Enum):
    READ = "read"
    WRITE = "write"


class ToolAttributeName(Enum):
    APP = "_is_app_tool"
    ENV = "_is_env_tool"
    DATA = "_is_data_tool"
    USER = "_is_user_tool"


@dataclass
class AppToolArg:
    name: str
    arg_type: str
    description: str | None = None
    has_default: bool = False
    default: Any | None = None


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
        return self.function(self.class_instance, *args, **kwargs)

    def to_open_ai(self) -> dict[str, Any]:
        properties = {
            arg.name: {"type": _json_type(arg.arg_type), "description": arg.description or ""}
            for arg in self.args
        }
        required = [arg.name for arg in self.args if not arg.has_default]
        return {
            "type": "function",
            "function": {
                "name": f"{self.app_name}__{self.name}",
                "description": self.function_description or "",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


def _json_type(type_name: str) -> str:
    return {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}.get(
        type_name, "string"
    )


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


def build_tool(instance: Any, func: Callable[..., Any], failure_probability=None) -> AppTool:
    sig = inspect.signature(func)
    hints = get_type_hints(func)
    args: list[AppToolArg] = []
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        type_obj = hints.get(name, str)
        type_name = getattr(type_obj, "__name__", "str")
        args.append(
            AppToolArg(
                name=name,
                arg_type=type_name,
                has_default=param.default is not inspect._empty,
                default=None if param.default is inspect._empty else param.default,
            )
        )
    return AppTool(
        class_name=instance.__class__.__name__,
        app_name=getattr(instance, "name", instance.__class__.__name__),
        name=func.__name__,
        function_description=inspect.getdoc(func),
        args=args,
        function=func,
        class_instance=instance,
        write_operation=getattr(func, "_event_operation_type", None) == OperationType.WRITE,
    )
