"""Tool contracts augment actual Python signatures without replacing them."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol


class NumericRule(Protocol):
    def validate(self, value: float, label: str) -> str | None: ...

    def json_schema(self) -> dict[str, float]: ...


@dataclass(frozen=True)
class ParameterContract:
    description: str
    choices: tuple[Any, ...] | None = None
    numeric: NumericRule | None = None

    def validate(self, name: str, value: Any) -> str | None:
        if self.choices is not None and value not in self.choices:
            return f"Invalid {name}: choose one of {list(self.choices)}"
        return self.numeric.validate(value, name) if self.numeric is not None else None


@dataclass(frozen=True)
class OperationContract:
    description: str
    parameters: Mapping[str, ParameterContract] = field(default_factory=dict)
    validator: Callable[[Mapping[str, Any]], str | None] | None = None

    def validate(self, arguments: Mapping[str, Any]) -> str | None:
        for name, parameter in self.parameters.items():
            if name in arguments:
                error = parameter.validate(name, arguments[name])
                if error is not None:
                    return error
        return self.validator(arguments) if self.validator is not None else None
