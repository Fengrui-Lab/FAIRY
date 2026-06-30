from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScenarioValidationResult:
    success: bool = True
    message: str = ""
    rationale: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.rationale and not self.message:
            self.message = self.rationale
        if self.message and not self.rationale:
            self.rationale = self.message

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "rationale": self.rationale,
            "metadata": self.metadata,
        }
