"""Provider-independent Choice results; absent usage is unknown, never zero."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from collections.abc import Mapping
from typing import Any


class DecisionProtocolError(ValueError):
    """The service did not satisfy the requested decision contract."""


def read_field(obj: Any, name: str, default: Any = None) -> Any:
    return obj.get(name, default) if isinstance(obj, Mapping) else getattr(obj, name, default)


@dataclass
class DecisionAnswer:
    choice: str
    probabilities: dict[str, float]
    confidence: float | None
    deterministic: bool = False


@dataclass
class DecisionUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None

    def tokens(self) -> dict[str, int | None]:
        return {
            "prompt_tokens": self.input_tokens,
            "completion_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "total_tokens": (
                self.input_tokens + self.output_tokens
                if self.input_tokens is not None and self.output_tokens is not None else None
            ),
        }


@dataclass
class DecisionBatch:
    question_ids: list[str]
    usage: DecisionUsage
    model: str | None = None
    request_id: str | None = None
    wall_time_seconds: float = 0.0
    status: str = "ok"


@dataclass
class DecisionResponse:
    choices: dict[str, DecisionAnswer]
    usage: DecisionUsage
    model: str | None = None
    request_id: str | None = None
    batches: list[DecisionBatch] = field(default_factory=list)


def validate_questions(questions: Any) -> None:
    if not isinstance(questions, dict) or not questions:
        raise DecisionProtocolError("questions must be a nonempty object")
    for qid, question in questions.items():
        if not isinstance(qid, str) or not qid or not isinstance(question, dict):
            raise DecisionProtocolError("question IDs must be nonempty strings with object values")
        if question.get("type") != "choice":
            raise DecisionProtocolError("FAIRY currently supports Choice questions only")
        options = question.get("criteria")
        if not isinstance(options, dict) or not 1 <= len(options) <= 255:
            raise DecisionProtocolError("Choice requires between 1 and 255 options")
        if any(not isinstance(k, str) or not k for k in options):
            raise DecisionProtocolError("option IDs must be nonempty strings")


def _probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionProtocolError("probabilities and confidence must be numeric")
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise DecisionProtocolError("probabilities and confidence must be finite and in [0, 1]")
    return value


def _count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DecisionProtocolError("token usage must be nonnegative integers or null")
    return value


def _metadata_string(value: Any) -> str | None:
    if value is not None and not isinstance(value, str):
        raise DecisionProtocolError("model and request identifiers must be strings or null")
    return value


def normalize_response(raw: Any, questions: dict[str, Any]) -> DecisionResponse:
    """Accept TypeSafe SDK objects or System One JSON, without fabricating fields."""
    validate_questions(questions)
    if isinstance(raw, DecisionResponse):
        return raw  # Constructed and validated by the compatible client.
    answers = read_field(raw, "answers")
    if answers is None:
        answers = read_field(raw, "choices")
    if not isinstance(answers, Mapping) or set(answers) != set(questions):
        raise DecisionProtocolError("response question IDs must exactly match the request")
    normalized: dict[str, DecisionAnswer] = {}
    for qid, question in questions.items():
        answer = answers[qid]
        choice = read_field(answer, "choice")
        options = question["criteria"]
        probabilities = read_field(answer, "probabilities")
        if not isinstance(choice, str) or choice not in options:
            raise DecisionProtocolError("response selected an unknown option")
        if not isinstance(probabilities, Mapping) or set(probabilities) != set(options):
            raise DecisionProtocolError("response must include a probability for every option, and no others")
        probs = {k: _probability(v) for k, v in probabilities.items()}
        confidence = read_field(answer, "confidence")
        normalized[qid] = DecisionAnswer(
            choice, probs, _probability(confidence) if confidence is not None else None
        )
    usage = read_field(raw, "usage")
    return DecisionResponse(
        choices=normalized,
        usage=DecisionUsage(
            _count(read_field(usage, "input_tokens")),
            _count(read_field(usage, "output_tokens")),
            _count(read_field(usage, "cached_tokens")),
        ),
        model=_metadata_string(read_field(raw, "model")),
        request_id=_metadata_string(read_field(raw, "request_id") or read_field(raw, "id")),
    )


def aggregate_usage(batches: list[DecisionBatch]) -> DecisionUsage:
    def total(key: str) -> int | None:
        values = [getattr(b.usage, key) for b in batches]
        return sum(values) if all(v is not None for v in values) else None
    return DecisionUsage(*(total(k) for k in ("input_tokens", "output_tokens", "cached_tokens")))
