# Part 2 review: Jev + LLM hybrid for full-season (L3) scenarios

State on 2026-10-22. Branch `jev-agent`, commits `0286c9f` … `2bbc4d8` (not pushed). Step-by-step details and every run: `PROGRESS.md`, Part 2.

## 1. Goal (from the brief)

Run full-season (L3) scenarios end to end with a yield similar to the LLM agent (gpt-6-luna), at lower token cost. Likely a hybrid: Jev for most decisions, LLM for some. Measure yield loss, recovered-grain loss, coverage, tokens, cost, runtime. Target: paper, 2026-11-05.

## 2. Known problems from the brief, and their status

| # | Problem | What we did | Status |
|---|---|---|---|
| 1 | Jev's input grows too long (full history) | Short snapshot + one-line list of all steps + last 5 actions (results cut at 1,500 characters) | Solved: 3–5k tokens per request on L1/L2, up to ~6k on L3 |
| 2 | Jev does not see the farm state | Snapshot built by code: crop stage per ridge range, inventory, machines, pending effects, notifications | Solved. Weather and sensor readings left out on purpose (see 4.2) |
| 3 | Jev says "done" too early | "Done" refused (max 2 times, reason shown) if visible facts say work is left | Works (refusals seen in runs) |
| 4 | LLM-written summaries were wrong | The LLM never writes the state; the snapshot is code-built | Avoided by design |
| 5 | Wait loops; task times in minutes/hours, simulator in seconds | One wait question in plain units (30 min … 14 days) + "until <pending effect> is ready" | Works (Jev used day steps and "until ready") |

## 3. What was built

| Part | File | What it does |
|---|---|---|
| Snapshot | `fairy/agents/jev/snapshot.py` | Builds Jev's view of the farm from stored values only. Never writes to the simulation (checked: identical results with and without it) |
| Agent | `fairy/agents/jev/jev_agent.py` | Jev decision loop; per-turn options; done check; LLM fallback; report text written by code |
| Menus | `fairy/agents/jev/menu.py` | Wait question; per-pass ridge limits from the code; report option |
| English tasks | `docs/jev/tasks_en/` (8 files), `agent_task_override` in `fairy/scenarios/scenario.py`, used in `fairy/controllers/engine.py` | Both agents get the same English task |
| LLM | `fairy/agents/llm/openai_llm.py` | gpt-6-luna added (reasoning "none": the only way it accepts tools on FAIRY's API route) |
| Options | `fairy/cli.py` | `--fallback-model`, `--fallback-confidence`, `--jev-state history` (Part 1 input, for comparison) |
| Free test | `scripts/jev_offline_check.py` | A fake Jev follows the oracle through the real agent; reports missing menu values, done refusals, request sizes |
| Tests | `tests/test_jev_agent.py` | 10 tests, all pass |
| Fix | `scripts/build_oracle_baselines.py` | Windows path bug (L1/L2 baselines failed) |

## 4. Key decisions (details in PROGRESS.md)

1. **Fairness:** the snapshot shows only what the agent's own tools would show; the done check uses visible facts, never FAIRY's evaluator.
2. **No weather/sensors in the snapshot:** with them, Jev skipped the "check weather / read sensors" steps and then repeated a later step (shown with single-question tests).
3. **Value questions list earlier calls of the same action** and ask for the value of the next undone step: otherwise Jev repeated the task's first ridge range.
4. **No report straight after a report:** Jev sent up to 5 in a row.
5. **LLM fallback** (gpt-6-luna) when Jev's confidence < **0.4**, when Jev repeats a call that changed nothing, or after 2 refused "done". 0.4 instead of 0.6: same quality on L2 at a quarter of the cost.
6. **Limits for both agents:** L1 60 actions / 10 min, L2 100 / 15 min, L3 300 / 60 min. Runs with `PYTHONHASHSEED=0` (FAIRY's sensor noise is otherwise different every run).

## 5. Results

One run each. Yield loss vs the oracle baseline (recovered grain for harvest tasks). Hybrid = Jev + gpt-6-luna fallback.

| Scenario | Jev only | Hybrid (threshold) | gpt-6-luna | LLM share of hybrid decisions | Hybrid cost | gpt-6-luna cost |
|---|---|---|---|---|---|---|
| L1 herbicide | 0.0% | 0.0% (0.6) | 0.0% | 3 / 12 | $0.007 | $0.003 |
| L1 harvest + store | 0.0% | 0.0% (0.6) | 0.0% | 4 / 37 | $0.011 | $0.010 |
| L1 planting | 82% | −2.8% (0.6) | 0.0% | 26 / 50 | $0.034 | $0.004 |
| L2 harvest drydown | 18.7%* | 0.0% (0.4) | 0.0% | 4 / 71 | $0.028 | $0.012 |
| L2 replant | 0.9% | 1.7% (0.4) | −0.15% | 25 / 42 | $0.028 | $0.006 |
| **L3 hn58** (run 2) | – | recovered 100%, no harvest (0.4) | recovered 100%, stopped after planting | 264 / ~300 | $0.41 | $0.03 |

\* hit the old 60-action limit.

- **L1/L2:** the hybrid reaches the LLM's yield. Jev alone fails where it lacks a value (e.g. seed spacing not in the task) or loses its place.
- **L3:** neither finishes a season.
  - gpt-6-luna (reasoning off) plants and then stops, saying the season cannot be completed; it never advances the clock.
  - The hybrid advances (to 29 July) but runs out of its 300 actions, because the fallback LLM has no memory between calls and keeps re-reading sensors.
- **Cost:** the hybrid costs more dollars than gpt-6-luna everywhere. gpt-6-luna's repeated input is ~97% cached ($0.01 per million); Jev's requests are never cached ($0.042 per million) and repeat the state for every question (2–3 per action). Jev often uses fewer tokens.
- Total spent in Part 2: about $1.6.

## 6. Where we stand

- Infrastructure is done and tested: snapshot, menus, done check, fallback, English tasks, oracle baselines, free test, scoring.
- Jev alone can do short, step-by-step tasks; the hybrid fixes its failures on L1/L2.
- Not yet: any agent completing an L3 season; the 3 L3-mini test scenarios; a cost advantage in dollars.

## 7. Next high-level goals

1. **A baseline that can finish L3:** gpt-6-luna with reasoning on (needs OpenAI's Responses API in FAIRY, ~half a day). Without it, "yield similar to the LLM agent" has nothing to compare against.
2. **A hybrid that finishes L3 with Jev doing most decisions:** give the fallback LLM memory of its own earlier calls (cached, cheap); then look at why Jev's confidence is low on L3.
3. **Test set:** the 3 L3-mini scenarios, hybrid vs gpt-6-luna, all metrics.
4. **Cost claim for the paper:** decide with the supervisor whether to report tokens, dollars, or both; with caching, dollars favour the LLM.
5. **Report** by ~2026-10-28 (a week before the deadline).

## 8. For you to check

- gpt-6-luna runs with reasoning "none"; the paper must say so (or we switch, goal 1).
- All runs are single runs; no repeats yet.

## 9. Update (2026-10-22, later): both agents now finish L3

Commits `c92328b`, `ea9bf7f` (not pushed). Details: `PROGRESS.md`, Steps 10–11.

### 9.1 What changed

| # | Change | File |
|---|---|---|
| 1 | gpt-6-luna with reasoning on, through OpenAI's Responses API. New option `--reasoning-effort` (we use "medium"). Other models and the old setting (reasoning "none") work as before | `fairy/agents/llm/openai_llm.py`, `fairy/cli.py` |
| 2 | The hybrid's fallback LLM keeps its own earlier calls and their results, plus Jev's actions in between (window of 20 calls, cut back to 10) | `fairy/agents/jev/jev_agent.py` |

Same agents, tools, English tasks and action/time limits as before. One setting differs for the reasoning baseline: output limit 8,192 tokens per call (was 2,048), because reasoning tokens count toward it.

### 9.2 Results on L3 hn58 (one run each)

| | gpt-6-luna, reasoning on | Hybrid before | Hybrid with memory |
|---|---|---|---|
| Season | finished | ran out of actions on 29 July | finished |
| Yield loss (crop) | 1.7% | 1.8% | 1.8% |
| Recovered-grain loss | **4.2%** | 100% | 6.3% |
| Actions (limit 300) | 134 | 300 | 189 |
| Decisions Jev / LLM | – | 36 / 264 | 94 / 96 |
| Tokens | 6.2M (99% cached) | 8.9M | 7.1M (Jev 2.7M, LLM 4.4M) |
| Cost | **$0.07** | $0.41 | $0.20 |
| Time | 5.5 min | 26 min | 5 min |

- With reasoning on, gpt-6-luna waits in big steps (14–40 days) and completes the season: planting → harvest → drying → storage.
- The hybrid also completes it, with half the decisions made by Jev. It loses a bit more grain (6.3% vs 4.2%) and costs about 3× more.
- Jev's part alone ($0.11) costs more than the whole reasoning baseline: the baseline's input is 99% cached at $0.01 per million, Jev's input is never cached.

### 9.3 Findings

1. **Reasoning on, L2 harvest drydown:** the baseline waited one day at a time and read all 64 ridges every day. It cost $0.13 (reasoning off: $0.012) and ran out of actions with 8 ridges unharvested. On L3 it did the opposite (few, long waits). The model's waiting behaviour varies by task.
2. **OpenAI caching:** gpt-6-luna only caches a request that starts with a whole earlier request. A request that shares only part of an earlier one gets nothing cached (tested directly). So the fallback's memory must only grow at the end, like the LLM agent's history.
3. **Why Jev's confidence is low on L3** (96 hand-offs to the LLM):
   - 77 of 96 are about which action to take, not which value. Jev's top choice gets 0.2–0.4, the rest is spread over 2–3 other reasonable actions.
   - **Mid-season is almost all LLM** (June–August: 53 of 62 decisions). The task gives no fixed order for crop checks (inspect, fly survey, read sensors, wait). Planting (May: 15 of 54 to the LLM) and harvest (Sept: 28 of 74) are step by step and mostly Jev's.
   - **Robot/drone batteries:** "check status", "charge" and "wait 65 min" score close.
   - **Two drones, same action:** "fly survey" exists for both drones; in 12 hand-offs Jev split its confidence between them (e.g. 0.26 vs 0.24).
   - **How long to wait:** no number in the task, so 1/7/10/14 days score about the same.
   - **When to harvest:** in September "harvest" leads at 0.2–0.4 with "check weather" and "wait" close behind.
   - In 31 of 96 hand-offs the LLM chose the same action as Jev.

### 9.4 For review

- **Baseline for the paper:** gpt-6-luna with reasoning "medium" now finishes L3. Do we use it as the reference (instead of reasoning "none")?
- **Cost claim:** on hn58 the hybrid costs about 3× the reasoning baseline in dollars and uses about the same number of tokens. As things stand, there is no cost advantage to report.
- **Possible next steps for Jev's share** (not started, need your OK): treat the two drones' surveys as one option; give Jev a default wait length per crop stage; check whether a lower threshold is safe in step-by-step phases, since the LLM picked Jev's top action in 31 of 96 hand-offs.
- **Single runs only:** the 4.2% vs 6.3% difference may be partly chance; repeats are needed before the paper.
- Spent in Part 2 so far: about $2.05.

## 10. Repeats and two more L3-mini scenarios (2026-10-22)

Commit `b540644` (not pushed). Details: `PROGRESS.md`, Step 12. Same settings as section 9; seed 0 in every run (same farm and weather), so repeats differ only through the models. Scenarios: hn58 (3 runs per agent), staggered wetjune canopy disease and dryer capacity batch harvest storage (1 run per agent).

### 10.1 Results

| Scenario | Agent | Season | Yield loss (crop) | Recovered-grain loss | Actions | Decisions Jev / LLM | Tokens | Cost | Time |
|---|---|---|---|---|---|---|---|---|---|
| hn58 | Baseline, runs 1 / 2 / 3 | finished ×3 | 1.7 / 1.8 / 1.8% | 4.2 / 1.9 / 6.7% | 134 / 179 / 157 | – | 6.2 / 9.6 / 5.4M | $0.07 / $0.11 / $0.06 | 5.5 / 7.6 / 5.8 min |
| hn58 | Hybrid, runs 1 / 2 / 3 | finished ×3 | 1.8 / 1.8 / 1.5% | 6.3 / 8.1 / 3.3% | 189 / 108 / 141 | 94/96, 62/47, 85/57 | 7.0 / 2.8 / 4.0M | $0.20 / $0.09 / $0.12 | 5.0 / 2.6 / 3.2 min |
| hn58 | **Baseline, average** | | 1.8% | **4.3%** | 157 | – | 7.1M | **$0.08** | 6.3 min |
| hn58 | **Hybrid, average** | | 1.7% | **5.9%** | 146 | 55% / 45% | 4.6M | **$0.14** | 3.6 min |
| Wetjune disease | Baseline | finished | 7.4% | 7.5% | 144 | – | 5.2M | $0.06 | 6.3 min |
| Wetjune disease | Hybrid | finished | 5.4% | 6.8% | 279 | 106 / 174 | 15.2M | $0.41 | 8.5 min |
| Dryer capacity | Baseline | finished | 0.1% | 0.5% | 155 | – | 6.1M | $0.07 | 6.7 min |
| Dryer capacity | Hybrid | finished late (7 Nov) | 0.0% | **21.5%** | 126 | 86 / 41 | 2.6M | $0.08 | 2.3 min |

### 10.2 Findings

1. **Both agents finish every L3 run** (8 of 8 here, 10 of 10 counting section 9).
2. **hn58, 3 runs each:** the hybrid loses a little more grain on average (5.9% vs 4.3%), but runs of the same agent spread just as widely (1.9–6.7% and 3.3–8.1%), so 3 runs cannot tell them apart. The hybrid uses fewer tokens (4.6M vs 7.1M) but costs more ($0.14 vs $0.08), because the baseline's input is 99% cached. Jev made 55% of the hybrid's decisions.
3. **Wetjune disease:** the hybrid got slightly more grain than the baseline, but used 279 of its 300 actions; the LLM made 62% of decisions, and the run cost 7× more.
4. **Dryer capacity, hybrid much worse (21.5% vs 0.5%), mostly through Jev's own decisions:**
   - Jev started trying to harvest on 8 August and kept failing (not mature, then rain, then grain too wet), waiting a full week between tries. It harvested only from 10 October to 7 November, getting less grain per ridge the later it went (440 → 361 kg per 4 ridges; the baseline got 510 kg, all harvested on 7 September).
   - It stored 7 batches at 13.7% moisture without drying them first (the task says batches above 13.5% must be dried before storing); the late batches were at 8% and needed no drying.
   - These were mostly Jev's choices (17 of 23 harvests, 15 of 16 stores). Jev also tried "done" too early 15 times.

### 10.3 For review

- **Paper claim:** as things stand, the hybrid matches the baseline's yield on 2 of 3 scenarios, does not save money, and fails on harvest timing in the dryer scenario.
- **Possible fixes** (not started, need your OK): shorter waits once the crop is near maturity (the task gives no wait length; Jev waited 7 days between tries); a "done"-style check that grain above 13.5% moisture is dried before it is stored (the task states this rule).
- **More repeats** are needed for wetjune and dryer capacity (1 run each so far).
- Spent in Part 2 so far: about $3.05.
