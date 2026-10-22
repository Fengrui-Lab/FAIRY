"""Free check of the Jev agent (no AI): a fake Jev that follows the oracle.

The fake client answers every Jev question with the oracle's next action and its
values, through the real JevAgent loop (snapshot, menus, done check) and a
normal fairy.cli run. It records:
  - oracle actions or values that are not on Jev's menu;
  - "done" refusals (a correct run should get none);
  - the size of each Jev request (characters, and tokens estimated as chars / 4).
Scoring the run bundle against the oracle baseline then shows whether the
snapshot reads change the yield (they should not).

Needs the oracle workflow from:
    python -m fairy.cli -s <id> --build-oracle --run-oracle-tools --output-dir <oracle-dir>/<id>

Usage:
    PYTHONPATH=. python scripts/jev_offline_check.py -s <scenario_id> \
        --oracle-dir validation_runs/jev_l3/oracle_smoke --output-dir <dir> [--max-tool-calls 300]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

from fairy.agents.jev import menu as jev_menu
from fairy.agents.llm import typesafe_client
from fairy.agents.llm.base_llm import BaseLLM

HIDDEN = {"AgentUserInterface__send_message_to_agent"}
_DURATION_KEY = re.compile(r"^(\d+) (second|minute|hour|day)s?$")
_COUNT_KEY = re.compile(r"^\d+ ridges?$")


def oracle_actions(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    steps = data.get("dag", data).values()
    return [
        {"tool": s["tool_name"], "args": s.get("tool_args") or {}}
        for s in steps
        if s.get("tool_name") and s["tool_name"] not in HIDDEN
    ]


def _seconds(args: dict) -> int:
    return sum(int(args.get(u, 0)) * s for u, s in jev_menu.UNIT_SECONDS.items())


def _key_seconds(key: str) -> int | None:
    m = _DURATION_KEY.match(key)
    return int(m.group(1)) * jev_menu.UNIT_SECONDS[m.group(2) + "s"] if m else None


class OracleFollower(BaseLLM):
    llm_class = "OracleFollower"

    def __init__(self, model, temperature, **kwargs):
        super().__init__(model, temperature, **kwargs)
        self.provider = "typesafe"
        self.base_url = None
        self.actions: list[dict] = []
        self.cursor = 0
        self.current: dict | None = None
        self.log = {"missing_tools": [], "missing_values": [], "requests": [], "done_asked": 0}

    def _choose(self, qid: str, criteria: dict) -> str:
        keys = list(criteria)
        if qid == "next_action":
            while self.cursor < len(self.actions):
                self.current = self.actions[self.cursor]
                self.cursor += 1
                if self.current["tool"] in criteria:
                    return self.current["tool"]
                self.log["missing_tools"].append(self.current["tool"])
            self.log["done_asked"] += 1
            return jev_menu.DONE_OPTION
        name = qid.removeprefix("arg__")
        if name.count("__") >= 2:
            # Fan-out question for a likely tool (arg__<App>__<tool>__<arg>): only the picked tool's count.
            tool, name = name.rsplit("__", 1)
            if self.current is None or tool != self.current["tool"]:
                return keys[0]
        args = self.current["args"]
        start = {"end": "start", "end_ridge": "start_ridge"}.get(name)
        if start in args and name in args and all(_COUNT_KEY.match(k) for k in keys):
            want = int(args[name]) - int(args[start]) + 1
            key = f"{want} ridge" if want == 1 else f"{want} ridges"
            if key in criteria:
                return key
            self.log["missing_values"].append({"tool": self.current["tool"], "arg": name, "want": args[name]})
            return keys[-1]
        if name == jev_menu.DURATION_ARG or (name == "timeout" and "timeout" in args):
            want = _seconds(args) if name == jev_menu.DURATION_ARG else int(args["timeout"])
            exact = [k for k in keys if _key_seconds(k) == want]
            if exact:
                return exact[0]
            self.log["missing_values"].append({"tool": self.current["tool"], "arg": name, "want": args})
            timed = [k for k in keys if _key_seconds(k) is not None]
            return min(timed, key=lambda k: abs(_key_seconds(k) - want)) if timed else keys[0]
        if name == "content":
            return jev_menu.REPORT_OPTION
        if name in args:
            value = args[name]
            key = jev_menu._option_key(value, ridge=name in jev_menu.RIDGE_ARGS)
            if key in criteria:
                return key
            self.log["missing_values"].append({"tool": self.current["tool"], "arg": name, "want": value})
            # Like a sensible agent: the smallest option that is at least the wanted amount.
            numbers = {k: float(k.removeprefix("ridge ")) for k in keys if re.fullmatch(r"(ridge )?-?\d+(\.\d+)?", k)}
            if isinstance(value, (int, float)) and numbers:
                above = [k for k, v in numbers.items() if v >= value]
                return min(above, key=numbers.get) if above else max(numbers, key=numbers.get)
        return keys[0]

    def system_one(self, state, questions):
        chars = len(json.dumps({"state": state, "questions": questions}, default=str, ensure_ascii=False))
        self.log["requests"].append({"kind": list(questions)[0], "chars": chars})
        choices = {}
        for qid, q in questions.items():
            pick = self._choose(qid, q["criteria"])
            choices[qid] = SimpleNamespace(choice=pick, confidence=1.0, probabilities={pick: 1.0})
        return SimpleNamespace(
            choices=choices,
            usage=SimpleNamespace(input_tokens=chars // 4, output_tokens=0),
            model="oracle-follower",
            request_id=None,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-s", "--scenario", required=True)
    parser.add_argument("--oracle-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tasks-dir", type=Path, default=Path("docs/jev/tasks_en"))
    parser.add_argument("--max-tool-calls", type=int, default=300)
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument(
        "--no-snapshot", action="store_true",
        help="Skip all farm reads (empty snapshot), to check that the reads leave the simulation unchanged",
    )
    args = parser.parse_args()

    if args.no_snapshot:
        from fairy.agents.jev import jev_agent
        from fairy.agents.jev.snapshot import _tool_steps

        def no_reads(toolsets, workflow, now):
            facts = {"ridges": [], "pending": [], "machines": {}, "inventory": {}, "steps": _tool_steps(workflow)}
            return {"farm_now": {}, "recent_actions": []}, facts

        jev_agent.build_snapshot = no_reads

    follower: dict[str, OracleFollower] = {}
    actions = oracle_actions(args.oracle_dir / args.scenario / f"{args.scenario}.oracle.json")

    def make(model, temperature, **kwargs):
        client = OracleFollower(model, temperature, **kwargs)
        client.actions = actions
        follower["client"] = client
        return client

    typesafe_client.TypeSafeJevClient = make  # picked up by BaseLLM's "typesafe" provider
    task = (args.tasks_dir / f"{args.scenario}.txt").read_text(encoding="utf-8")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    sys.argv = [
        "fairy.cli", "-s", args.scenario, "--agent",
        "--controller", "farm_jev", "--provider", "typesafe", "--model", "oracle-follower",
        "--max-tool-calls", str(args.max_tool_calls),
        "--timeout-seconds", str(args.timeout_seconds),
        "--scenario-kwargs", json.dumps({"agent_task_override": task}),
        "--output-dir", str(args.output_dir),
    ]
    from fairy import cli

    try:
        cli.main()
    finally:
        client = follower.get("client")
        if client is not None:
            sizes = [r["chars"] for r in client.log["requests"]]
            summary = {
                "scenario": args.scenario,
                "oracle_actions": len(actions),
                "oracle_actions_used": client.cursor,
                "missing_tools": client.log["missing_tools"],
                "missing_values": client.log["missing_values"],
                "done_asked": client.log["done_asked"],
                "jev_requests": len(sizes),
                "request_chars_max": max(sizes) if sizes else None,
                "request_chars_avg": round(sum(sizes) / len(sizes)) if sizes else None,
                "est_tokens_total": sum(sizes) // 4,
            }
            (args.output_dir / "offline_check.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
