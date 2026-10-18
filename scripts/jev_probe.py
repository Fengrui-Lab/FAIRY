"""Jev probe: can Jev pick the oracle's next tool on scenario_farm_world_field_prep?

Standalone; does not change FAIRY. For each point k in the oracle replay (0..13),
sends Jev the English task plus the first k oracle actions with their real results,
and asks one Choice question over the scenario's 63 tools plus "done".
Tool names only, no arguments.

Usage:
    PYTHONPATH=. python scripts/jev_probe.py \
        --replay validation_runs/jev_mvp/probe_inputs/oracle_replay/scenario_farm_world_field_prep.replay.json \
        --output-dir validation_runs/jev_mvp/probe

Needs TYPESAFE_API_KEY in the environment (read by the SDK; never printed or saved).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from typesafe_sdk import Choice, TypeSafeClient

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.scenarios.registry import get_scenario_class

SCENARIO_ID = "scenario_farm_world_field_prep"
MODEL = "jev-latest"
QUESTION_ID = "next_action"
INSTRUCTIONS = "Which action should the farm agent take next?"
DONE_OPTION = "done"
DONE_DESCRIPTION = "All steps of the task are complete; stop and report."

# English translation of SCENARIO_INPUT_DETAIL in
# fairy/scenarios/baseline_farm_world/scenario_field_prep.py (approved by the user).
TASK_EN = """The farm is entering the pre-planting preparation stage; all field preparation must be finished today. Follow these steps:
1. Check today's weather and confirm there is no rain, so the field can be worked.
2. Check the 3-day forecast (rain the day after tomorrow -> everything must be finished today).
3. Read the soil sensors and confirm soil VWC < 0.35 (the tractor can drive on it).
4. Check the tractor's fuel level and which implement is attached.
5. Check the warehouse inventory and confirm there is enough fertilizer and diesel.
6. Level the ground: first attach the grader, then rotary-till and level the whole field (grader width 3 m, speed 3 km/h); when finished, detach the grader.
7. Apply base fertilizer: load 200 kg of fertilizer from the warehouse into the spreader, then spread it over the whole field (spreader width 6 m, speed 6 km/h).
8. Form ridges: attach the furrower and form the ridges (ridge width 1.1 m, 4 ridges per pass, speed 4 km/h); when finished, detach the furrower.
9. When everything is done, end the task immediately and report to me."""


def first_paragraph(text: str) -> str:
    """Text up to the first blank line, joined into one line."""
    para = (text or "").strip().split("\n\n", 1)[0]
    return " ".join(line.strip() for line in para.splitlines()).strip()


def build_menu() -> dict[str, str]:
    """Scenario tools in the same order the LLM agent sees them, plus 'done'."""
    scenario = get_scenario_class(SCENARIO_ID)()
    scenario.initiate_scenario()
    _, schemas, _ = build_toolset(list(scenario.apps))
    menu = {
        s["function"]["name"]: first_paragraph(s["function"]["description"])
        for s in schemas
    }
    menu[DONE_OPTION] = DONE_DESCRIPTION
    return menu


def load_oracle_actions(replay_path: Path) -> list[dict]:
    workflow = json.loads(replay_path.read_text(encoding="utf-8"))
    nodes = workflow.values() if isinstance(workflow, dict) else workflow
    return [
        {"action": n["tool_name"], "arguments": n["tool_args"] or {}, "result": n["content"]}
        for n in nodes
        if n.get("tool_name")
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    menu = build_menu()
    oracle = load_oracle_actions(args.replay)
    question = Choice(instructions=INSTRUCTIONS, criteria=menu)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    records = []
    with TypeSafeClient(model=MODEL) as client:
        for k in range(len(oracle) + 1):
            expected = oracle[k]["action"] if k < len(oracle) else DONE_OPTION
            state = {"task": TASK_EN, "actions_so_far": oracle[:k]}
            started = time.perf_counter()
            response = client.system_one(state=state, questions={QUESTION_ID: question})
            latency_s = time.perf_counter() - started
            answer = response.choices[QUESTION_ID]
            probabilities = dict(answer.probabilities)
            records.append({
                "call": k + 1,
                "actions_so_far_count": k,
                "expected": expected,
                "pick": answer.choice,
                "correct": answer.choice == expected,
                "p_expected": probabilities.get(expected),
                "confidence": answer.confidence,
                "probabilities": probabilities,
                "latency_s": round(latency_s, 3),
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "model_version": response.model,
                "request_id": response.request_id,
                "state": state,
            })
            r = records[-1]
            print(f"{r['call']:2}  expected={expected:<34} pick={r['pick']:<34} "
                  f"p_expected={r['p_expected']:.2f}  conf={r['confidence']:.2f}")

    out = {
        "scenario_id": SCENARIO_ID,
        "model": MODEL,
        "question": {"id": QUESTION_ID, "instructions": INSTRUCTIONS, "criteria": menu},
        "records": records,
        "totals": {
            "calls": len(records),
            "correct": sum(r["correct"] for r in records),
            "input_tokens": sum(r["input_tokens"] or 0 for r in records),
            "output_tokens": sum(r["output_tokens"] or 0 for r in records),
            "latency_s": round(sum(r["latency_s"] for r in records), 3),
        },
    }
    path = args.output_dir / f"{SCENARIO_ID}.jev_probe.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out["totals"]))
    print(f"saved={path}")


if __name__ == "__main__":
    main()
