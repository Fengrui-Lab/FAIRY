from __future__ import annotations

import inspect
from typing import Any, Callable

from fairy.tool_utils import agent_tool, parameters_schema


def agent_toolset(obj: Any) -> list[Callable[..., Any]]:
    if isinstance(obj, type):
        obj = obj()
    if hasattr(obj, "get_tools"):
        return list(obj.get_tools())
    tools: list[Callable[..., Any]] = []
    for attr_name in dir(obj):
        attr = getattr(obj, attr_name)
        if callable(attr) and getattr(attr, "is_agent_tool", False):
            tools.append(attr)
    return tools


def build_tool_schema(tool: Any) -> dict[str, Any]:
    if hasattr(tool, "to_open_ai"):
        return tool.to_open_ai()
    return {
        "type": "function",
        "function": {
            "name": tool.__name__,
            "description": inspect.getdoc(tool) or "",
            "parameters": parameters_schema(tool),
        },
    }


def build_toolset(
    toolsets: list[Any],
    *,
    excluded_tool_names: set[str] | frozenset[str] | None = None,
):
    assert isinstance(toolsets, list)
    excluded_tool_names = excluded_tool_names or set()
    tools: list[Any] = []
    tools_map: dict[str, Callable[..., Any]] = {}
    tool_schemas: list[dict[str, Any]] = []
    for toolset in toolsets:
        for tool in agent_toolset(toolset):
            schema = build_tool_schema(tool)
            name = schema["function"]["name"]
            if name in excluded_tool_names:
                continue
            if name in tools_map:
                raise ValueError(
                    f"Duplicate tool name {name!r}. Give every app a unique name "
                    "when composing multiple farms or devices."
                )
            tool_schemas.append(schema)
            tools_map[name] = tool
            tools.append(tool)
    return tools, tool_schemas, tools_map
