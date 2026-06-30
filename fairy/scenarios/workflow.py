from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowStep:
    name: str | None = None
    content: Any = None
    op_type: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    depends_on: list[str] = field(default_factory=list)
    time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "content": self.content,
            "op_type": self.op_type,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "depends_on": self.depends_on,
            "time": self.time,
        }


class Workflow:
    def __init__(self) -> None:
        self.dag: dict[str, WorkflowStep] = {}

    def __len__(self) -> int:
        return len(self.dag)

    def add_node(self, node: WorkflowStep) -> None:
        name = node.name if node.name else f"step{len(self.dag)}"
        node.name = name
        self.dag[name] = node

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {name: step.to_dict() for name, step in self.dag.items()}

    def save_workflow(self, filename: str) -> None:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load_workflow(cls, filename: str) -> "Workflow":
        with open(filename, encoding="utf-8") as f:
            data = json.load(f)
        workflow = cls()
        for name, step in data.items():
            workflow.add_node(WorkflowStep(name=name, **{k: v for k, v in step.items() if k != "name"}))
        return workflow

    def __repr__(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

