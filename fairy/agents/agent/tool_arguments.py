"""Shared argument parsing for live tool calls and workflow replay."""
from __future__ import annotations

import json
from typing import Any


def parse_tool_arguments(raw_arguments: str | None) -> dict[str, Any]:
    arguments = json.loads(raw_arguments or "{}")
    if not isinstance(arguments, dict):
        # Python's ** TypeError embeds the callable repr (including memory
        # addresses). Reject earlier with a stable, replayable observation.
        raise TypeError("Tool arguments must decode to a JSON object")
    return arguments
