from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class GateSpec:
    name: str
    intent: str = ""
    window_days: tuple[float, float] | None = None
    eligible_tools: list[tuple[str, str]] | None = None
    requires: Callable[..., bool] | None = None
    predicate: Callable[..., bool] | None = None
    metadata: dict[str, Any] | None = None
