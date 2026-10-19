# Jev agent – progress log

**Goal:** add a second kind of agent to the FAIRY farm simulator. In it, TypeSafe's Jev picks each action from a list of options. Then compare it with the normal LLM agent on 15 small farm scenarios.

Code: branch `jev-agent`. Run outputs: `validation_runs/jev_mvp/` (not in git). Final results: end of this file.

---

## Step 1 – Get FAIRY running (no AI, free)

**Did:** installed FAIRY, ran its self-test, and asked one scenario (`field_prep`) for its reference solution (the "oracle").

**Happened:**
- Windows refused one file whose path is too long, which stopped FAIRY from starting. Fixed by turning on long file paths in Windows. No code changed.
- Self-test: everything passed except one check that needs a search tool not installed on this PC.
- The oracle for `field_prep` has 13 actions: 5 checks (weather, forecast, soil, tractor, warehouse), then level the field, fertilize the whole field, and form ridges, each with its tool attached and removed.

## Step 2 – Normal LLM agent on one scenario

**Did:** ran the normal agent (gpt-4o-mini) on `field_prep` with a 20-action limit, and looked at the two output files every run produces: a report and a list of actions.

**Happened:**
- It did the right steps in the right order, except fertilizing. Instead of the one "whole field" action it used a "10 ridges at a time" action, 8 times. So it hit the 20-action limit.
- Checked in the log: both actions were offered on every turn, and their descriptions are clear. This was the LLM's choice, not something the tool forced. It also matters for later tasks: planting refuses to start unless the "whole field" action was used.
- Cost about $0.014.

## Small test before building – can Jev pick the right next action?

**Did:** gave Jev the task plus the oracle's first *k* actions with their real results, and asked "which action next?", with the 63 actions as options plus "done". 14 questions, no values yet.

**Happened:** 14 of 14 correct. Cost about $0.002. Jev was less sure where a step is easy to skip (for example, removing a tool).

## Step 3 – Build the Jev agent

**Design choices** (agreed one by one):

| Choice | Why |
|---|---|
| Jev only makes the choice; FAIRY runs the action exactly as for the LLM | Same rules, limits and output files, so the existing scoring works unchanged |
| First Jev picks the action, then each value in a separate question | Jev cannot write values. One list of every action-plus-value combination would be far too long (Jev's limit is 255 options per question). |
| Value options come only from the code and the farm: every ridge, named items (tools, seed types, sensors), numbers that appear in the task text, and 10 evenly spaced amounts where the code sets a maximum | Fair: never taken from the oracle, and wrong values are always among the options |
| Wrong combinations are not blocked | The action just fails and is logged, the same as for the LLM |
| Both agents get the same English task (the originals are Chinese) | The Jev docs say Jev works best in English; the same text for both keeps it fair |
| Confidence of an action = the lowest confidence among its questions | One wrong value spoils the action (same as TypeSafe's own example) |
| Scoring: step match, coverage and order versus the oracle | FAIRY's main headline scores turned out to be empty or meaningless for these 15 scenarios; these three work (checked first) |

**Happened (`field_prep`):** Jev did exactly the oracle's 13 actions with the right values, then said "done". Step match 100% (LLM 55%), cost about $0.003 (LLM about $0.014).

## Step 4 – Run all 15 scenarios

**Prepared:**
- Translated the 14 remaining tasks into English. You reviewed them side by side; one cut-off sentence in the original was fixed by you.
- Raised the limit to 60 actions for both agents. Five oracles need more than 20 actions (the longest needs 35), so 20 would have stopped even a perfect agent.

**First round (1 run each):** LLM step match 49, Jev 30. Cause found in Jev's logs: it chose "start ridge" and "end ridge" at the same time without seeing each other. So it often asked for impossible ranges (end before start), up to 52 times in a row.

**Fix (your choice):** Jev now chooses the end ridge in a second question that tells it the start ridge. All 64 ridges are still offered, so mistakes stay possible. This follows the Jev docs.

**Final round:** 3 runs per agent per scenario (90 runs in total). Results below.

## Step 5 – Comparison table and checks

**Did:**
- Built the table (`results/comparison.csv`) and a facts-only summary (`results/summary.md`).
- Added, as you asked:
  - Jev's confidence in runs where it got stuck (the same action 3+ times in a row);
  - cost on the scenarios each agent won.
- Checked that every LLM run used gpt-4o-mini. It is recorded in each run report; the exact dated version is not recorded.
- Looked into why Jev gets stuck (see "Known limits" below).

---

## Results (3 runs per agent per scenario)

| | LLM (gpt-4o-mini) | Jev |
|---|---|---|
| Step match (average) | **53.5** | 47.1 |
| Scenarios where it scored higher | 9 | 6 |
| Coverage of oracle actions | 84.6 | 68.9 |
| Actions per run | 27 | 40 |
| Runs stopped by the 60-action limit | 4 of 45 | 16 of 45 |
| Runs stuck repeating | 3 of 45 | 27 of 45 |
| Cost per run | $0.023 | $0.022 |
| Time per run | 24 s | 24 s |

- **Where Jev scored higher:** field_prep (100 vs 53), harvest (90 vs 44), field_prep_planting (88 vs 65), planting (80 vs 72), fertilizer (78 vs 46), pesticide (73 vs 56). On these, Jev cost $0.016 per run vs the LLM's $0.022.
- **Where the LLM scored higher:** the other 9 scenarios. On these, Jev cost $0.025 per run vs the LLM's $0.023.
- **Waiting:** 8 of the 9 scenarios the LLM won include a waiting step in the oracle (drone charging, waiting for a notification). None of the 6 scenarios Jev won do.
- **Jev's confidence:** 0.54 in stuck runs and 0.81 in the others. It was 0.70 or higher in exactly the 8 scenarios where it scored best.
- **Spread between runs:** Jev's 3 runs per scenario were usually closer to each other than the LLM's.

**Known limits**
- **Why Jev gets stuck:**
  - Partly our design. The right waiting times (in seconds) are not among its options, because the task states waits in minutes and hours.
  - Partly Jev. In one scenario the right option was there and it did not pick it.
  - Why seeing its own repeats does not change its choice is not known.
- **Fixes after seeing results:** one design change (end ridge after start ridge) was made after seeing first results. Before it, Jev averaged 30.
- **Setup:** one LLM and one Jev version; translated tasks; the LLM also gets FAIRY's standard instructions.
- **What the scores mean:** they measure closeness to the oracle, not how well the farm ends up.

Full details: `results/summary.md`. For the professor: `recap.md`.

---

## How to rerun

```
python scripts/jev_run_small15.py --output-root validation_runs/jev_mvp/step4_final --repeats 3
python scripts/rebatch_fos_from_traces.py --root validation_runs/jev_mvp/step4_final --out-root validation_runs/jev_mvp/step4_final_scoring --workers 4
python scripts/jev_compare_table.py --scoring validation_runs/jev_mvp/step4_final_scoring/summary_v2.csv --out docs/jev/results/comparison.csv
```

Needs `OPENAI_API_KEY` and `TYPESAFE_API_KEY` set. Total cost of one full rerun: about $2.
