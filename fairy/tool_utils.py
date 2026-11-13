from __future__ import annotations

import inspect
import re
import textwrap
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


@dataclass(frozen=True)
class ToolDocstring:
    description: str | None
    arg_descriptions: dict[str, str]
    relation_description: str | None = None


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
    relation_description: str | None = None

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.function(self.class_instance, *args, **kwargs)

    def to_open_ai(self, *, include_tool_relations: bool = True) -> dict[str, Any]:
        description = self.function_description or ""
        if include_tool_relations and self.relation_description:
            relation = f"Relation:\n{self.relation_description}"
            description = f"{description}\n\n{relation}" if description else relation
        properties = {
            arg.name: {"type": _json_type(arg.arg_type), "description": arg.description or ""}
            for arg in self.args
        }
        required = [arg.name for arg in self.args if not arg.has_default]
        return {
            "type": "function",
            "function": {
                "name": f"{self.app_name}__{self.name}",
                "description": description,
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


def parse_tool_docstring(doc: str | None) -> ToolDocstring:
    """Separate Description, Relation and Google-style Args.

    Opening prose is the description; an explicit Description heading is also
    accepted. Relation (or Relations) is kept separately for optional export.
    Parameter entries use a common indentation level; deeper lines belong to
    the preceding parameter. Legacy sections such as Returns and Notes stay
    in the description until the tool docs are migrated. Unrecognized Args
    blocks are preserved verbatim rather than silently dropping documentation.
    """
    if doc is None:
        return ToolDocstring(None, {})

    lines = inspect.cleandoc(doc).splitlines()
    description: list[str] = []
    arg_descriptions: dict[str, str] = {}
    relations: list[str] = []
    index = 0
    while index < len(lines):
        heading = lines[index].rstrip()
        if heading in {"Description:", "Relation:", "Relations:"}:
            end = index + 1
            while end < len(lines) and not re.fullmatch(r"[A-Za-z][\w /-]*:\s*", lines[end]):
                end += 1
            body = textwrap.dedent("\n".join(lines[index + 1 : end])).strip()
            if heading == "Description:":
                description.extend(body.splitlines())
            elif body:
                relations.append(body)
            if description and description[-1].strip():
                description.append("")
            index = end
            continue
        if heading != "Args:":
            description.append(lines[index])
            index += 1
            continue

        end = index + 1
        while end < len(lines) and (
            not lines[end].strip() or lines[end][0].isspace()
        ):
            end += 1
        parsed_args = _parse_args_block(lines[index + 1 : end])
        if parsed_args is None:
            description.extend(lines[index:end])
        else:
            arg_descriptions.update(parsed_args)
            if description and description[-1].strip():
                description.append("")
        index = end

    return ToolDocstring(
        description="\n".join(description).strip(),
        arg_descriptions=arg_descriptions,
        relation_description="\n\n".join(relations) or None,
    )


def _parse_args_block(lines: list[str]) -> dict[str, str] | None:
    nonempty = [line for line in lines if line.strip()]
    if not nonempty:
        return None
    entry_indent = min(len(line) - len(line.lstrip()) for line in nonempty)
    entries: dict[str, list[str]] = {}
    current_name: str | None = None
    for line in lines:
        indent = len(line) - len(line.lstrip())
        match = (
            re.fullmatch(r"(\*{0,2}[A-Za-z_]\w*)(?:\s+\([^)]*\))?:\s*(.*)", line.strip())
            if line.strip() and indent == entry_indent
            else None
        )
        if match:
            current_name = match.group(1).lstrip("*")
            if current_name in entries:
                return None
            entries[current_name] = [match.group(2)]
        elif current_name is not None:
            entries[current_name].append(line)
        elif line.strip():
            return None
    return {
        name: inspect.cleandoc("\n".join(parts))
        for name, parts in entries.items()
    }


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
    documentation = parse_tool_docstring(inspect.getdoc(func))
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
                description=documentation.arg_descriptions.get(name),
                has_default=param.default is not inspect._empty,
                default=None if param.default is inspect._empty else param.default,
            )
        )
    return AppTool(
        class_name=instance.__class__.__name__,
        app_name=getattr(instance, "name", instance.__class__.__name__),
        name=func.__name__,
        function_description=documentation.description,
        args=args,
        function=func,
        class_instance=instance,
        write_operation=getattr(func, "_event_operation_type", None) == OperationType.WRITE,
        relation_description=documentation.relation_description,
    )
