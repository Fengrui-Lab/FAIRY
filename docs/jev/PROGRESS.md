# Jev agent – progress log

Branch: `jev-agent`. Run outputs go to `validation_runs/jev_mvp/` (git-ignored).

## Step 1 – Get FAIRY running (no AI calls)

**Install**
- `uv` was not installed, so used the plan's alternative: `python -m venv .venv` + `pip install -e . pytest` (Python 3.11.9).
- Windows blocked one scenario file whose full path is 268 characters (limit 260). FAIRY loads all scenarios at startup, so every command failed.
  Fix: enabled Windows long paths (`LongPathsEnabled=1`, run once by the user as admin). No code changed.

**Smoke test**
- `python -m fairy.cli --list-controllers` → OK, 11 controllers.
- `pytest tests/test_fairy_migration_smoke.py` → 67 passed, 4 failed. All 4 are environment, not code:
  - 1 needs the `rg` (ripgrep) search tool, which is not installed.
  - 3 need `OPENAI_API_KEY`, which is not set yet.

**Oracle run**

```
python -m fairy.cli -s scenario_farm_world_field_prep --build-oracle \
  --workflow validation_runs/jev_mvp/step1_oracle/scenario_farm_world_field_prep/scenario_farm_world_field_prep.oracle.json \
  --output-dir validation_runs/jev_mvp/step1_oracle/scenario_farm_world_field_prep
```

Status `completed`. Reference steps:

| # | Type | Action |
|---|---|---|
| 1 | read | `WeatherApp__get_current_weather()` |
| 2 | read | `WeatherApp__get_forecast(days=3)` |
| 3 | read | `SensorApp__read_soil_sensors()` |
| 4 | read | `TractorApp__get_status()` |
| 5 | read | `FarmWorldApp__get_inventory()` |
| 6 | write | `TractorApp__attach_implement(implement="grader")` |
| 7 | write | `TractorApp__level()` |
| 8 | write | `TractorApp__detach_implement()` |
| 9 | write | `TractorApp__load_fertilizer(kg=200.0)` |
| 10 | write | `TractorApp__base_fertilize()` |
| 11 | write | `TractorApp__attach_implement(implement="furrower")` |
| 12 | write | `TractorApp__form_ridges(ridge_width_m=1.1)` |
| 13 | write | `TractorApp__detach_implement()` |

**Before Step 2:** `OPENAI_API_KEY` and `TYPESAFE_API_KEY` are not set on this machine. Set both, then restart VS Code.

## Step 2 – Baseline run with the normal LLM agent

First attempt failed: OpenAI said the key had expired (nothing ran, nothing charged). User replaced the key; second attempt ran.

```
python -m fairy.cli -s scenario_farm_world_field_prep --agent --controller farm_baseline_react \
  --provider openai --model gpt-4o-mini --temperature 0.1 --max-tool-calls 20 --timeout-seconds 300 \
  --output-dir validation_runs/jev_mvp/step2_baseline/farm_baseline_react__scenario_farm_world_field_prep__r1
```

**run_report.json summary**

| Field | Value |
|---|---|
| status / stopped_reason | `stopped` / `max_tool_calls` (hit the 20-call limit) |
| tool calls / LLM calls | 20 / 13 |
| wall time | 30.9 s |
| tokens (input / output / cached) | 93,615 / 533 / 84,736 |
| cost | ≈ $0.014 (price table in `scripts/iclr_validation_runner.py`: $0.15 / $0.60 per M tokens) |
| evaluation.validation.success | `true`, message "Scenario validate() returned no result" (this scenario has no check, as the README warns) |
| error | none |

**agent_workflow.json** – a dict `step0 … step20`. Each step has `name`, `content`, `op_type`, `tool_name`, `tool_args`, `depends_on`, `time`.
`step0` is the task prompt (`op_type: USER`; the text is in Chinese). Every other step is one tool call (`op_type: TOOL`) and `content` holds the tool's result.

| Step | Action | Result |
|---|---|---|
| 1–5 | same 5 checks as the oracle (weather, forecast 3 days, soil, tractor, inventory) | ok |
| 6 | `attach_implement(implement="grader")` | ok |
| 7 | `load_fertilizer(kg=200)` | ok |
| 8 | `level()` | ok |
| 9 | `detach_implement()` | ok |
| 10 | `apply_fertilizer(start_ridge=0, end_ridge=63, kg_per_ridge=3.125)` | error: max 10 ridges per pass |
| 11–17 | `apply_fertilizer` in 7 batches of ≤10 ridges | ok |
| 18 | `attach_implement(implement="furrower")` | ok |
| 19 | `form_ridges(ridge_width_m=1.1)` | ok |
| 20 | `detach_implement()` | ok, then stopped by the 20-call limit |

Compared with the oracle: the agent used `apply_fertilizer` per ridge batch instead of `base_fertilize()`, which took 8 calls instead of 1. Otherwise it followed the same order.

## Probe (before Step 3) – can Jev pick the right next tool?

Agreed with the user: a small test before building the agent. It changes nothing in FAIRY.

**Setup**
- Script: `scripts/jev_probe.py`. Uses the official SDK (`pip install typesafe-sdk`, v0.7.5), model `jev-latest`.
- Inputs: the oracle was replayed (`--replay`, no AI) to get real tool results → `validation_runs/jev_mvp/probe_inputs/oracle_replay/`.
- 14 calls. Call *k* sends a state with:
  - `task`: English translation of the task prompt (approved by the user; it is in the script);
  - `actions_so_far`: the oracle's first *k* actions with their real results.
- One Choice question: "Which action should the farm agent take next?"
  - Options: the same 63 tools the LLM agent sees, in the same order. Each option's description is the first paragraph of the tool's existing description.
  - Plus `done`: "All steps of the task are complete; stop and report."
  - Tool names only, no arguments.
- Saved per call: state, menu, pick, all probabilities, confidence, latency, tokens, model version → `validation_runs/jev_mvp/probe/scenario_farm_world_field_prep.jev_probe.json`.

**Result: 14 / 14 correct.** Model that answered: `jev-1.13.0`.

| Call | Expected (oracle) | Jev pick | Confidence | Runner-up |
|---|---|---|---|---|
| 1 | get_current_weather | ✓ | 1.00 | – |
| 2 | get_forecast | ✓ | 1.00 | – |
| 3 | read_soil_sensors | ✓ | 0.99 | read_soil_sensor 0.01 |
| 4 | get_status | ✓ | 0.98 | get_inventory 0.01 |
| 5 | get_inventory | ✓ | 0.96 | attach_implement 0.03 |
| 6 | attach_implement | ✓ | 1.00 | – |
| 7 | level | ✓ | 0.98 | attach_implement 0.02 |
| 8 | detach_implement | ✓ | 0.85 | level 0.08 |
| 9 | load_fertilizer | ✓ | 0.93 | base_fertilize 0.04 |
| 10 | base_fertilize | ✓ | 0.95 | apply_fertilizer 0.04 |
| 11 | attach_implement | ✓ | 0.88 | form_ridges 0.12 |
| 12 | form_ridges | ✓ | 1.00 | – |
| 13 | detach_implement | ✓ | 0.86 | done 0.14 |
| 14 | done | ✓ | 1.00 | – |

Totals: 55,596 input / 12,745 output tokens, about $0.0023 (input only, $0.042 per M). About 0.25 s per call (the first call took 0.8 s). The state grew from about 2.8k to 4.7k tokens.

**What this does and does not show**
- It shows that Jev can follow this written plan step by step, using tool names alone.
- Each call was given the oracle's correct history, so mistakes could not pile up. This is not yet a real run.
- The task text lists the steps almost one by one, so this tests following a plan, not working one out.
- Arguments were not tested. The open question for Step 3 is still how to provide values such as `implement="grader"`, `kg=200` and `ridge_width_m=1.1`.

## Step 3 – rules agreed with the user (before building)

**Menu**
- Built only from what the farm can do: the scenario's tools and their valid argument values, plus `done`.
- The oracle is never used to build or filter the menu. It is used only for scoring afterwards.
- The menu must include wrong and harmful options.
- Each option is a plain-English label. Code keeps a mapping from label to exact tool call.

**Questions** (every question has fewer than 255 options, the Choice limit)
- One question picks the tool (63 tools + `done`).
- Then one separate question per argument. For example, start ridge and end ridge are two questions with 64 options each.
- Invalid combinations (end before start, a range wider than allowed) are not filtered out. The tool's error is logged, the same as for the LLM.

**Preset values for numeric arguments**
1. Task-text numbers: every number in the task text, found by a simple text search, goes on **every** numeric argument's menu. Nobody matches numbers to arguments by hand.
2. Where the tool code has a maximum (for example spreader 500 kg, fuel tank 100 L): 10 evenly spaced values between the code's minimum and maximum, **plus** the task-text numbers.
3. Where the tool code has no maximum (for example `form_ridges(ridge_width_m)` only checks "> 0"): the task-text numbers only.

**Step limit**: counts tool calls (actions), not Jev calls. Identical for both agents.

**Same input for both agents**
- The LLM is rerun on the same English task text as Jev, passed with `--scenario-kwargs '{"scenario_input": "<English text>"}'`. No code change.
- Remaining difference: the LLM also gets its usual system prompt (farm-manager role + function-calling rules); Jev does not.

**Confidence per action**: one action uses several questions, so its confidence is the lowest of them (as in the TypeSafe function-calling cookbook). All individual confidences are also recorded.

## Scoring check (before building)

Ran FAIRY's existing scorer on the Step 2 LLM run (no AI calls):

```
python scripts/rebatch_fos_from_traces.py --root validation_runs/jev_mvp/step2_baseline \
  --out-root validation_runs/jev_mvp/scoring_check --workers 1
```

Output: `validation_runs/jev_mvp/scoring_check/summary_v2.csv`.

**Not meaningful for this scenario. Do not use:**

| Column | Value | Why |
|---|---|---|
| `path_correctness(%)`, `coverage(%)`, `ktc_score(%)`, `combined(%)` | 0.00 | They compare against an oracle built without running it, which has **0 steps** for this scenario, so they are always 0. |
| `fos(%)` | 56.67 | Outcome is 100 by default (no crop in this scenario). Decision counts only 1 oracle action (`base_fertilize`). Efficiency compares 20 calls against "1". |
| `evaluation.validation.success` (run_report) | true | The scenario has no check. |

**Meaningful.** These columns compare against the full 13-step oracle, matching tool **and** exact arguments (`fairy/scenarios/workflow_validation.py::evaluate_workflows`):

| Column | Value | Meaning |
|---|---|---|
| `core_path_correctness(%)` | 55.00 | 1 − (edits needed to turn the agent's sequence into the oracle's) ÷ the longer sequence's length. Here 1 − 9/20. |
| `coverage_v1(%)` | 91.67 | Share of the oracle's distinct actions the agent performed. It did 11 of 12; it missed `base_fertilize()`. |
| `ktc(%)` | 96.36 | How well the agent's order matches the oracle's order, for the actions both did. |
| `bfcl_success(%)` | 91.67 | Another existing column in the same block (definition not checked yet). |

Conclusion: the existing scorer **does** give a meaningful, non-trivial score through `core_path_correctness`, `coverage_v1` and `ktc`. No new scoring is needed, but the headline `path_correctness(%)` / `fos(%)` columns must not be used for these scenarios.

## Step 3 – menu proposal for field_prep (approved by the user, incl. the 3 open decisions: all "yes")

**One action = up to two Jev requests**
1. Tool request: one Choice over 63 tools + `done` (64 options). Same format as the probe, which got 14/14.
2. Argument request, only if the picked tool has arguments: one Choice per argument, all sent in one request. The state is the same as in request 1; the instructions name the picked tool.

Tools with no arguments (22 of 63) need only request 1. The step limit counts tool calls, not requests.

**Where argument values come from** (all read from the code or the farm, never the oracle)

| Argument kind | Values | Example |
|---|---|---|
| Ridge id (start, end, single ridge) | all 64 ridges, 0–63 (`num_ridges`) | 64 options |
| Fixed text list in code | every value in the list | `implement`: grader, furrower, harvester, sprayer, cultivator |
| Text list from the farm | every value the farm has | `sensor_id`: S1–S6 (soil), C1–C6 (canopy); `seed_type`: 10 types in inventory |
| Yes/no | true, false | `full_replant` |
| Number, code has a max | 10 evenly spaced values from max/10 to max, + task numbers | `load_fertilizer(kg)`: 50…500 + task numbers = 21 options |
| Small whole-number range in code | every whole number in the range, + task numbers | `get_forecast(days)`, range 1–7 |
| Number, code has no max | task numbers only | `form_ridges(ridge_width_m)`: 12 options |

Task numbers (simple text search of the English task): 0.35, 1, 1.1, 2, 3, 4, 5, 6, 7, 8, 9, 200. This includes the step numbers 1–9.

**Code maxima found**

| Argument | Max | Kind |
|---|---|---|
| fuel tank (`refuel`) | 100 L | amount above it is cut to fit |
| spreader (`load_fertilizer`) | 500 kg | amount above it is cut to fit |
| pesticide / fungicide tank | 800 L | amount above it is cut to fit |
| seed hopper (`load_seeds`) | 300,000 | amount above it is cut to fit |
| `get_forecast(days)` | 1–7 | clamped |
| `dry_grain(target_moisture_pct)` | 11–16 | rejected outside |
| `plant_seeds` / `replant_seeds(depth_cm)` | 3–5 | rejected outside |
| `apply_pesticide_manual(ridge_count)` | 1–2 | rejected outside |

No max (task numbers only): `ridge_width_m`, `kg_per_ridge`, `liters_per_ridge`, `seed_spacing_cm`/`spacing_cm`, irrigation `hours`/`duration_hours`, `nutrient_amount`, `water_mm`, `advance_time` amounts, `wait_for_notification(timeout)`.

**Sizes**: the largest question has 64 options (tool, or ridge id). Every question is under 255.

**Open decisions for the user**
1. Do tank capacities (amount above max is cut to fit) count as "a maximum in the code"? Proposed: yes.
2. Whole-number arguments: drop task numbers that are not whole (0.35, 1.1)? Proposed: yes, because the tool would reject them on type.
3. Arguments with a default (e.g. `days=7`, `liters_per_ridge=8`): add the default value as one more option? Proposed: yes; the LLM can also leave them out.

## Step 3 – Jev agent built and tested on field_prep

**What was added** (existing agents unchanged; existing files only got additions)

| File | What |
|---|---|
| `fairy/agents/jev/menu.py` (new) | The agreed argument-value rules. Builds one menu per tool. Refuses to build a question with more than 255 options, or an argument with no rule. |
| `fairy/agents/jev/jev_agent.py` (new) | `JevAgent`. Replaces only the "LLM decides" step. FAIRY's normal loop still runs the tool, enforces the limits and records workflow, runtime log and report. |
| `fairy/agents/llm/typesafe_client.py` (new) | Thin wrapper around the official SDK. The key is read by the SDK from `TYPESAFE_API_KEY`. |
| `fairy/controllers/agent_builder.py` | Added controller `farm_jev` (requires `--provider typesafe`). |
| `fairy/agents/llm/base_llm.py` | Added provider `typesafe`. |
| `pyproject.toml` | Optional extra `jev = ["typesafe-sdk>=0.7.5"]`. |
| `docs/jev/tasks_en/scenario_farm_world_field_prep.txt` (new) | The approved English task, used by **both** agents. |
| `tests/test_jev_agent.py` (new) | 4 offline tests with a fake Jev. They cover: typed arguments, the step limit, invalid ridge ranges being executed (not filtered), and token totals. |

**What gets recorded**
- `runtime_log.jsonl`:
  - `jev_menu`: the full menu once, with every option and where it came from.
  - `jev_request_start` / `jev_request_end`, per request: the questions, the state, option counts, pick, all probabilities, confidence, latency, tokens, model version, request id.
  - `jev_action`, per action: the action, its arguments, its confidence (the lowest of its questions) and every question's confidence.
- `run_report.json`:
  - token totals: Jev input → `prompt_tokens`, output → `completion_tokens`;
  - `llm_call_count` = Jev requests;
  - `controller_telemetry.avg_action_confidence` / `min_action_confidence`.

**Tests**: `tests/test_jev_agent.py` 4/4 passed. Smoke test 70 passed, 1 failed (the `rg` tool is not installed, same as before).

**Commands** (same limits for both agents: 20 tool calls, 300 s, same English task)

```
KW=$(python -c "import json,sys;print(json.dumps({'scenario_input':open(sys.argv[1],encoding='utf-8').read()}))" docs/jev/tasks_en/scenario_farm_world_field_prep.txt)

python -m fairy.cli -s scenario_farm_world_field_prep --agent --controller farm_jev --provider typesafe --model jev-latest \
  --max-tool-calls 20 --timeout-seconds 300 --scenario-kwargs "$KW" \
  --output-dir validation_runs/jev_mvp/step3_jev/farm_jev__scenario_farm_world_field_prep__r1

python -m fairy.cli -s scenario_farm_world_field_prep --agent --controller farm_baseline_react --provider openai --model gpt-4o-mini \
  --temperature 0.1 --max-tool-calls 20 --timeout-seconds 300 --scenario-kwargs "$KW" \
  --output-dir validation_runs/jev_mvp/step3_llm_en/farm_baseline_react__scenario_farm_world_field_prep__r1

python scripts/rebatch_fos_from_traces.py --root validation_runs/jev_mvp/step3_jev validation_runs/jev_mvp/step3_llm_en \
  validation_runs/jev_mvp/step2_baseline --out-root validation_runs/jev_mvp/step3_scoring --workers 1
```

**Result on field_prep**

| | Jev (`farm_jev`) | LLM, English task | LLM, Chinese task (Step 2) |
|---|---|---|---|
| status | completed (picked `done`) | stopped at 20 calls | stopped at 20 calls |
| tool calls | 13 | 20 | 20 |
| core_path_correctness | **100%** | 55% | 55% |
| coverage_v1 | **100%** | 91.67% | 91.67% |
| ktc | **100%** | 96.36% | 96.36% |
| wall time | 9.0 s | 22.5 s | 30.9 s |
| tokens in / out | 65,651 / 13,266 (19 Jev requests) | 93,563 / 533 | 93,615 / 533 |
| cost | ≈ $0.0028 | ≈ $0.014 | ≈ $0.014 |
| avg / min action confidence | 0.94 / 0.66 | – | – |

Jev ran exactly the oracle's 13 steps with the oracle's arguments (`days=3`, `implement="grader"`, `kg=200.0`, `implement="furrower"`, `ridge_width_m=1.1`), then picked `done`.
- Its lowest confidence (0.66) was `furrower` vs `grader` (0.73 / 0.27).
- Every other argument was picked with confidence ≥ 0.98.

The LLM did the same steps, except it fertilized with 8 `apply_fertilizer` calls instead of one `base_fertilize`, and so hit the 20-call limit.

`fos(%)` was 56.67 for all three runs, including Jev's exact oracle match. This confirms it is not meaningful for this scenario.

**Caveat**: the task text lists every step and every value (3 days, 200 kg, 1.1 m). Because task-text numbers are on every numeric menu, this scenario is close to the easiest case for Jev. It shows the agent works end to end; it does not show Jev can plan when the task is less explicit.

## Commit and push

- Committed on `jev-agent` as `735ab8c`.
- Checked before committing: no `.env` files, no API key values and no key-shaped strings in the commit.
- Added remote `fairy-jev` → https://github.com/Synkrasis-Labs/fairy-jev and pushed `jev-agent` there.
- Nothing was pushed to `origin` (quaoq/FAIRY).

## Why did the LLM fertilize in 8 calls instead of 1? (evidence from the Step 2 log)

**Answer: an LLM mistake (wrong tool choice). The 10-ridge limit then made the mistake cost 8 calls.**

1. **Both tools were offered on every turn.** All 13 LLM calls listed both `TractorApp__base_fertilize` and `TractorApp__apply_fertilizer`.
2. **The descriptions are clear.**
   - `base_fertilize()`: "Apply base fertilizer across the full field using the tractor spreader." No arguments; one call covers all 64 ridges.
   - `apply_fertilizer(start_ridge, end_ridge, kg_per_ridge)`: "Apply fertilizer across a contiguous block of ridges using the tractor spreader (up to 10 ridges per pass)."
   - The task asks to "apply base fertilizer … spread it over the whole field".
3. **What the LLM did** (log, turns 9–10):
   - Turn 9: `apply_fertilizer(0, 63, 3.125)` → error "Range cannot exceed 10 ridges per pass".
   - Turn 10: it kept the same tool and split the field into 7 blocks of up to 10 ridges. It never tried `base_fertilize`.
   - It wrote no explanation text on any turn, so its reasoning is not visible.
4. **It is not just slower; the farm ends up different.**
   - Only `base_fertilize` records the field-prep step (`_completed_prep_ops`). Planting checks it: "Field preparation incomplete: must finish level -> base_fertilize -> form_ridges before planting".
   - So in a scenario that continues to planting, this choice would block planting.
5. **Same behaviour with the English task** (Step 3 run).

Jev, with the same tool descriptions, picked `base_fertilize` (0.95 in the probe, 0.96 in the real run).

## Step 4 prep – English task texts (APPROVED by the user)

- I translated the 14 remaining task texts into `docs/jev/tasks_en/<scenario_id>.txt`.
- Side-by-side review with the Chinese originals and flags: `docs/jev/tasks_en/REVIEW.md`.
- Automatic check: the numbers found in each English text match the Chinese, except "30万" (= 300,000), written as `300000` in 3 files.
- Defects in the original texts are flagged in REVIEW.md, not silently fixed:
  - field_prep_plus has a cut-off sentence;
  - drone_survey and pesticide_outbreak_plus have missing words;
  - survey_pesticide_irrigation has a typo.

- User approved all translations, with one fix: field_prep_plus step 3 now reads "please wait for the soil sensor notification."

## Step 4 – decisions before running

- **Step limit 60 tool calls**, the same for both agents and every scenario. The longest oracle needs 35 actions; 5 scenarios need more than 20, so the old limit of 20 would have stopped even a perfect agent.
- Time limit 600 s per run, the same for both.
- One run per agent per scenario. Both agents get the approved English task text.
- Old commit `68fa710` keeps its Claude co-author line (user's choice). Nothing pushed since.

## Step 4 – results (15 scenarios × 2 agents, 1 run each)

Run: `python scripts/jev_run_small15.py --output-root validation_runs/jev_mvp/step4` (60 actions, 600 s, English tasks). All 30 runs finished without errors; no keys in the outputs.
Scored: `python scripts/rebatch_fos_from_traces.py --root validation_runs/jev_mvp/step4 --out-root validation_runs/jev_mvp/step4_scoring --workers 4`. Combined numbers: `validation_runs/jev_mvp/step4_scoring/combined.json`.

| Scenario | LLM step match / coverage / order | LLM actions | Jev step match / coverage / order | Jev actions | Jev avg confidence |
|---|---|---|---|---|---|
| drone_survey | 11.7 / 75.0 / 100 | 60 (limit) | 5.0 / 37.5 / 100 | 60 (limit) | 0.60 |
| drone_survey_plus | 33.3 / 90.0 / 100 | 33 | 8.7 / 30.0 / 100 | 60 (limit) | 0.43 |
| fertilizer | 53.3 / 88.9 / 100 | 15 | **77.8** / 77.8 / 100 | 9 | 0.78 |
| field_prep | 52.4 / 91.7 / 96.4 | 21 | **100 / 100 / 100** | 13 | 0.93 |
| field_prep_planting | 69.0 / 100 / 97.7 | 42 | 26.7 / 56.7 / 100 | 60 (limit) | 0.65 |
| field_prep_plus | 36.0 / 78.6 / 96.4 | 25 | 8.3 / 35.7 / 100 | 60 (limit) | 0.42 |
| harvest | 33.3 / 89.3 / 95.0 | 60 (limit) | 13.3 / 32.1 / 100 | 60 (limit) | 0.71 |
| irrigation | 83.3 / 80.0 / 100 | 6 | 8.7 / 60.0 / 100 | 46 | 0.51 |
| pesticide | 22.7 / 77.8 / 95.2 | 22 | **72.7 / 88.9** / 100 | 11 | 0.74 |
| pesticide_outbreak | 52.9 / 64.7 / 100 | 16 | 18.3 / 64.7 / 100 | 60 (limit) | 0.62 |
| pesticide_outbreak_plus | 40.7 / 40.7 / 100 | 18 | 6.7 / 18.5 / 100 | 60 (limit) | 0.52 |
| planting | 68.0 / 100 / 100 | 25 | 11.7 / 33.3 / 100 | 60 (limit) | 0.62 |
| planting_plus | 45.2 / 95.7 / 100 | 42 | 14.0 / 34.8 / 100 | 60 (limit) | 0.44 |
| survey_fertilizer_irrigation | 73.7 / 88.2 / 98.1 | 19 | 57.1 / 88.2 / 100 | 28 | 0.70 |
| survey_pesticide_irrigation | 63.2 / 88.9 / 95.0 | 19 | 21.7 / 72.2 / 100 | 60 (limit) | 0.52 |
| **Average** | **49.3 / 83.3 / 98.3** | 28.2 | **30.0 / 55.4 / 100** | 47.1 | |

Totals: LLM about $0.40, average 24.9 s per run. Jev about $0.39, average 23.8 s per run.
Note: "order" is 100 for Jev mostly because it matched few actions; with few matches, order is easy.

**Why Jev did badly (from the Jev workflows)**
1. **Start and end ridge are picked separately, and Jev picks them independently** (the docs say questions in one request cannot see each other's answers). Example, planting: `plant_seeds(start=8, end=7)` → error, repeated **52 times**. drone_survey shows the same pattern. This comes from our agreed design (one question per argument).
2. **It repeats the same action without making progress.** drone_survey: `check_status` ×42. irrigation: `wait_for_notification` ×23 and `irrigate_ridge(25)` ×6.
3. **Task numbers land in unrelated arguments.** For example `wait_for_notification(timeout=22)`, where 22 comes from "22 days after sowing". This follows the agreed rule (task numbers go on every numeric menu).

Jev did better than the LLM where each action needs few or no ridge ranges: field_prep, fertilizer, pesticide.

**LLM run-to-run difference**: on field_prep, the LLM finished in 21 actions this time (52.4%). In Step 3 it hit the limit (55%). We use 1 run per agent, so single-scenario numbers carry noise.

## Step 4b – fix: end ridge asked after start ridge (user's choice B)

**Change** (`fairy/agents/jev/jev_agent.py`)
- For tools with a ridge range (`start_ridge`/`end_ridge` or `start`/`end`), the end ridge is now asked in its own, later request.
- That request says which start ridge was already chosen.
- The end-ridge menu still has all 64 ridges, so invalid picks are still possible and still logged.
- This follows the TypeSafe docs: use a second request when an earlier answer is needed.

**Tests**: `tests/test_jev_agent.py` 5/5 passed. The new test checks that the end question comes second, names the chosen start, and keeps all 64 options.

**Reruns** (user: 3 runs per agent per scenario). All in `validation_runs/jev_mvp/step4_final/`:
- LLM: r1 is copied from Step 4 (the LLM agent did not change); r2 and r3 are new.
- Jev: r1–r3 are all new, with the fix.
- The pre-fix Jev runs stay in `validation_runs/jev_mvp/step4/` for the record.

Command: `python scripts/jev_run_small15.py --output-root validation_runs/jev_mvp/step4_final --repeats 3`

## Step 4b – results (3 runs per agent per scenario, after the fix)

Scored: `python scripts/rebatch_fos_from_traces.py --root validation_runs/jev_mvp/step4_final --out-root validation_runs/jev_mvp/step4_final_scoring --workers 4`.
All 90 runs scored OK; no keys in the outputs. Per-run numbers: `validation_runs/jev_mvp/step4_final_scoring/combined.json`.

Step match = `core_path_correctness`, mean of 3 runs (lowest–highest).

| Scenario | LLM step match | LLM actions | Jev step match | Jev actions | Jev hit limit | Jev confidence |
|---|---|---|---|---|---|---|
| drone_survey | 36.7 (12–75) | 35 | 5.0 (5–5) | 60 | 3/3 | 0.58 |
| drone_survey_plus | 27.8 (20–33) | 44 | 7.0 (7–8) | 60 | 3/3 | 0.42 |
| fertilizer | 45.8 (31–53) | 19 | **77.8** (78–78) | 9 | 0/3 | 0.84 |
| field_prep | 52.5 (50–55) | 21 | **100** (100–100) | 13 | 0/3 | 0.95 |
| field_prep_planting | 65.4 (60–69) | 46 | **87.8** (86–89) | 35 | 0/3 | 0.84 |
| field_prep_plus | 36.2 (33–39) | 25 | 13.7 (8–25) | 58 | 2/3 | 0.46 |
| harvest | 43.6 (33–64) | 57 | **89.8** (86–91) | 36 | 0/3 | 0.77 |
| irrigation | 83.3 (83–83) | 6 | 8.2 (7–9) | 49 | 0/3 | 0.53 |
| pesticide | 56.1 (23–73) | 15 | **72.7** (73–73) | 11 | 0/3 | 0.74 |
| pesticide_outbreak | 56.9 (53–59) | 15 | 46.8 (23–59) | 29 | 0/3 | 0.71 |
| pesticide_outbreak_plus | 43.2 (41–48) | 19 | 13.8 (7–28) | 55 | 2/3 | 0.54 |
| planting | 72.0 (68–80) | 25 | **79.9** (51–96) | 34 | 0/3 | 0.76 |
| planting_plus | 55.5 (45–68) | 40 | 19.5 (18–21) | 60 | 3/3 | 0.33 |
| survey_fertilizer_irrigation | 72.9 (70–75) | 20 | 62.4 (62–64) | 26 | 0/3 | 0.70 |
| survey_pesticide_irrigation | 54.4 (42–63) | 19 | 22.2 (22–23) | 60 | 3/3 | 0.58 |
| **Average (45 runs each)** | **53.5** | 27.0 | **47.1** | 39.7 | 16/45 | 0.65 |

Other averages:
- Coverage: LLM 84.6, Jev 68.9.
- Order: LLM 98.4, Jev 100.
- Hit the 60-action limit: LLM 4 of 45 runs, Jev 16 of 45.
- Cost: LLM $1.02 total ($0.023 per run), Jev $0.97 total ($0.022 per run).
- Time: LLM 23.6 s per run, Jev 24.2 s per run.

**Effect of the fix**: Jev's average step match went from 30.0 to 47.1. Jev now scores higher in 6 of 15 scenarios (before: 3), with big gains on harvest (13 → 90), field_prep_planting (27 → 88) and planting (12 → 80).

**What still goes wrong for Jev** (run 1 of each):
- It repeats one action instead of moving on:
  - drone_survey: `check_status` ×54 in a row;
  - irrigation: `wait_for_notification` 34 times;
  - planting_plus: `advance_time` 35 times.
- survey_pesticide_irrigation: `spray_pesticide` 41 times, 28 of them errors.
- These are the scenarios where the task says "wait for a notification" / "wait until …", or where a step depends on an earlier result.

Jev's runs vary much less than the LLM's (narrower lowest–highest ranges).

## Step 5 – comparison table

- `docs/jev/results/comparison.csv`: one row per scenario plus AVERAGE, built from the 3-run results.
  - Columns per agent: step match (mean, min, max), coverage, order, actions, runs that hit the limit, cost per run, time per run.
  - Also: Jev's average confidence, and empty `are_*` columns for the ARE results.
- `docs/jev/results/summary.md`: short factual summary (setup, how measured, results, per-scenario counts, log observations, setup facts).
  - The log observations were checked the same way for both agents (run 1 of each agent's 5 lowest-scoring scenarios).
- Rebuild the CSV: `python scripts/jev_compare_table.py --scoring validation_runs/jev_mvp/step4_final_scoring/summary_v2.csv --out docs/jev/results/comparison.csv`
