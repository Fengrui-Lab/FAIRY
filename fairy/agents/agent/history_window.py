from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class TurnSpan:
    """A completed LLM turn in the agent's durable message history."""

    turn_index: int
    start: int
    end: int
    tool_call_count: int


@dataclass(frozen=True)
class HistoryWindowSelection:
    """The prompt-only history view and its isolated audit metadata."""

    messages: list[Any]
    audit_record: dict[str, Any]


def select_history_window(
    messages: Sequence[Any],
    *,
    history_window: int,
    pinned_message_indices: Sequence[int],
    completed_turn_spans: Sequence[TurnSpan],
    current_turn_start: int,
) -> HistoryWindowSelection:
    """Select complete recent turns without mutating the durable history."""
    if history_window < 0:
        raise ValueError("history_window must be greater than or equal to 0")
    if not 0 <= current_turn_start <= len(messages):
        raise ValueError("current_turn_start is outside the message history")

    retained_spans = list(completed_turn_spans[-history_window:]) if history_window else []
    selected_indices: list[int] = []
    seen: set[int] = set()

    def retain(index: int) -> None:
        if not 0 <= index < len(messages):
            raise ValueError(f"message index {index} is outside the message history")
        if index not in seen:
            seen.add(index)
            selected_indices.append(index)

    for index in pinned_message_indices:
        retain(index)
    for span in retained_spans:
        if not 0 <= span.start <= span.end <= current_turn_start:
            raise ValueError(f"invalid completed turn span: {span}")
        for index in range(span.start, span.end):
            retain(index)
    for index in range(current_turn_start, len(messages)):
        retain(index)

    completed_count = len(completed_turn_spans)
    return HistoryWindowSelection(
        messages=[messages[index] for index in selected_indices],
        audit_record={
            "schema_version": 1,
            "record_type": "history_window_selection",
            "history_window": history_window,
            "full_message_count": len(messages),
            "prompt_message_count": len(selected_indices),
            "completed_turn_count": completed_count,
            "retained_turn_count": len(retained_spans),
            "dropped_turn_count": completed_count - len(retained_spans),
            "pinned_message_indices": list(pinned_message_indices),
            "current_context_start": current_turn_start,
            "retained_turn_spans": [
                {
                    "turn_index": span.turn_index,
                    "start": span.start,
                    "end": span.end,
                    "tool_call_count": span.tool_call_count,
                }
                for span in retained_spans
            ],
        },
    )
