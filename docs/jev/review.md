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

## 11. Asking Jev fewer times per action (branch `jev-fewer-requests`, 2026-10-23)

Details: `PROGRESS.md`, Steps 13–14.

### 11.1 The idea

Every time we ask Jev something, we pay for the whole farm description again. Before this change, each farm action took 2–3 asks:
1. "Which action?" (for example: harvest)
2. "Which settings?" (for example: start at ridge 8)
3. "Up to which ridge?" (for example: ridge 11). This was asked separately because the list of possible answers depended on the start ridge.

We changed this so that most actions take one ask:
- **Settings are asked together with "which action?"**, for the few actions Jev is likely to pick (the ones it rated highest last time, and the last 3 actions). If Jev picks a different action, we ask for its settings in a second ask, as before.
- **"Up to which ridge?" was replaced by "how many ridges?"**, so it no longer depends on the start ridge and can go in the same ask.

### 11.2 Results (one run each, hybrid = Jev + LLM help)

| Scenario | Version | Season | Grain loss (crop / recovered) | Asks per action | Jev tokens per action | Decisions Jev / LLM | Jev cost | Total cost |
|---|---|---|---|---|---|---|---|---|
| L1 herbicide | before | finished | 0.0% / – | 2.08 | 7.8k | 13 / 0 | $0.004 | $0.004 |
| | after | finished | 0.0% / – | **1.38** | **6.9k** | 12 / 1 | $0.004 | $0.004 |
| L1 planting | before | finished | −2.8% / – | 2.22 | 8.8k | 32 / 4 | $0.013 | $0.015 |
| | after | finished | −2.8% / – | **1.16** | **7.5k** | 35 / 3 | $0.012 | $0.013 |
| L2 harvest drydown | before | finished | 0.0% / 4.7% | 2.21 | 9.2k | 65 / 12 | $0.030 | $0.033 |
| | after | finished | 0.0% / 0.0% | **1.03** | **6.2k** | 41 / 19 | $0.016 | $0.020 |
| L2 replant | before | finished | 0.65% / – | 2.21 | 9.5k | 11 / 3 | $0.006 | $0.006 |
| | after | finished | 0.46% / – | **1.40** | **9.1k** | 9 / 6 | $0.006 | $0.007 |
| L3 hn58 | before (average of 3 runs) | finished | 1.7% / 5.9% | 2.24 | 13.1k | 55% / 45% | $0.080 | $0.135 |
| | after | finished | 1.4% / 5.1% | **1.06** | **9.5k** | 45% / 55% | $0.065 | $0.144 |
| L3 wetjune disease | before | finished | 5.4% / 6.8% | 2.35 | 17.1k | 38% / 62% | $0.201 | $0.411 |
| | after | **ran out of actions, no harvest** | 15.5% / 100% | **1.09** | **12.3k** | 16% / 84% | $0.155 | $0.472 |
| L3 dryer capacity | before | finished | 0.0% / 21.5% | 1.98 | 10.1k | 68% / 32% | $0.054 | $0.079 |
| | after | finished | −1.9% / 0.1% | **1.19** | **9.9k** | 52% / 48% | $0.079 | $0.148 |

### 11.3 What we found

1. **Asks per action roughly halved**, and Jev's cost per action went down on every scenario.
2. **But total cost on L3 did not go down**, because Jev handed more decisions to the LLM, which costs more.
3. **The reason is the "how many ridges?" question.** Jev is often unsure about it, so it hands the decision to the LLM. It seems to read "how many" as "up to which ridge": starting at ridge 12, it answered "63 ridges" when it meant "up to ridge 63".
4. **A fairness problem we found afterwards.** When Jev's answer did not fit the field, the code replaced it with one that fits, instead of sending Jev's answer. Example: Jev said "start at ridge 12, cover 63 ridges"; the field ends at ridge 63, so the code sent "ridges 12 to 63". The LLM agent never gets this kind of help: if it sends an impossible action, the farm refuses it. This happened in 8 of 151 ridge choices (wetjune 6, L1 herbicide 2, the others 0). This code is still in the branch.

### 11.4 Proposed next steps (not done, need your OK)

1. **Remove the replacing.** Send Jev's answer as it is; if it does not fit, the farm refuses it, the same as for the LLM.
2. **Ask "up to which ridge?" again instead of "how many ridges?"**, in the same ask as the start ridge, with all ridges as possible answers. Jev handled this question well before. If its answer does not fit, the farm refuses it (point 1).
3. Run the free check, then L1/L2, then the 3 L3 scenarios again, to see whether the saving reaches total cost.

Spent in Part 2 so far: about $3.9.

### 11.5 After the fixes (2026-10-23)

Fixes: Jev's ridge answer is now sent unchanged (the farm refuses it if it does not fit). "How many ridges?" kept, with clearer wording; earlier calls shown as "ridges 12-15 (4 ridges)".

| | hn58 before (3 runs) | hn58 now | wetjune before | wetjune now |
|---|---|---|---|---|
| Season | finished ×3 | finished | finished | finished |
| Recovered-grain loss | 3.3–8.1% | 5.4% | 6.8% | 7.3% |
| Asks per action | 2.16–2.29 | **1.05** | 2.35 | **1.15** |
| Jev tokens per action | 11.6–14.1k | **9.1k** | 17.1k | **8.9k** |
| Jev's share of decisions | 49–60% | **47%** | 38% | **56%** |
| Total cost | $0.09–0.20 | $0.12 | $0.41 | $0.08 |

Merge test: (1) fewer asks and Jev tokens per action: yes on both. (2) Jev's share not lower: yes on wetjune, **no on hn58** (47% vs 49–60%). (3) season finishes, hn58 loss within 3–8%, wetjune harvests: yes.

Extra hn58 run: finished, recovered-grain loss 1.9% (better than the 3–8% range), 1.08 asks per action, 9.1k Jev tokens per action, Jev's share 53%, $0.086. hn58 now: Jev's share 47% and 53% (before: 49–60%). Waiting for your decision on the merge.

## 12. Final results (2026-10-23, code frozen at `7ac11ec`)

These are the numbers to use. 3 runs per agent on each scenario, all on the same frozen code (branch `jev-agent`). Details: `PROGRESS.md`, Step 16.

| Scenario | Agent | Season finished | Yield loss (crop) | Recovered-grain loss | Actions | Jev's share of decisions | Jev requests per action | Tokens | Cost | Time |
|---|---|---|---|---|---|---|---|---|---|---|
| hn58 | LLM baseline | 3 of 3 | 1.8% / 1.8% / 1.8% (avg 1.8%) | 1.8% / 1.8% / 6.4% (avg 3.3%) | 128 / 100 / 139 (avg 122) | – | – | 3.9M / 2.8M / 3.6M (avg 3.4M) | $0.05 / $0.03 / $0.04 (avg $0.04) | 4.5 min / 3.6 min / 4.9 min (avg 4.3 min) |
| hn58 | Hybrid | 3 of 3 | 1.5% / 1.4% / 1.8% (avg 1.6%) | 6.2% / 6.0% / 4.2% (avg 5.5%) | 133 / 135 / 134 (avg 134) | 57% / 50% / 51% (avg 53%) | 1.10 / 1.04 / 1.04 (avg 1.06) | 3.3M / 3.9M / 3.7M (avg 3.6M) | $0.09 / $0.10 / $0.10 (avg $0.10) | 2.2 min / 2.2 min / 2.2 min (avg 2.2 min) |
| Wetjune disease | LLM baseline | 2 of 3 | 7.3% / 100.0% / 7.2% (avg 38.2%) | 18.3% / 100.0% / 8.0% (avg 42.1%) | 126 / 30 / 116 (avg 91) | – | – | 3.3M / 0.3M / 3.4M (avg 2.4M) | $0.04 / $0.01 / $0.04 (avg $0.03) | 5.0 min / 1.3 min / 4.4 min (avg 3.5 min) |
| Wetjune disease | Hybrid | 2 of 3 | 4.6% / 19.2% / 4.0% (avg 9.3%) | 7.6% / 100.0% / 5.5% (avg 37.7%) | 217 / 136 / 186 (avg 180) | 39% / 25% / 41% (avg 35%) | 1.07 / 1.10 / 1.07 (avg 1.08) | 8.1M / 5.6M / 7.0M (avg 6.9M) | $0.22 / $0.14 / $0.18 (avg $0.18) | 4.5 min / 2.9 min / 3.3 min (avg 3.5 min) |
| Dryer capacity | LLM baseline | 3 of 3 | 0.1% / 0.1% / 0.1% (avg 0.1%) | 0.5% / 14.6% / 0.5% (avg 5.2%) | 185 / 125 / 156 (avg 155) | – | – | 7.3M / 4.9M / 8.0M (avg 6.7M) | $0.08 / $0.06 / $0.09 (avg $0.08) | 7.3 min / 5.1 min / 6.3 min (avg 6.2 min) |
| Dryer capacity | Hybrid | 3 of 3 | -0.0% / -0.0% / -0.0% (avg 0.0%) | 0.0% / 14.1% / 2.0% (avg 5.4%) | 97 / 125 / 124 (avg 115) | 82% / 69% / 63% (avg 71%) | 1.33 / 1.25 / 1.26 (avg 1.28) | 1.1M / 2.1M / 2.3M (avg 1.9M) | $0.04 / $0.07 / $0.07 (avg $0.06) | 1.0 min / 1.5 min / 1.9 min (avg 1.5 min) |

How to read: each cell shows run 1 / run 2 / run 3 and the average. Recovered-grain loss = grain not harvested and stored, compared with the oracle (100% = nothing harvested). Hybrid = Jev, with gpt-6-luna taking the decision when Jev is unsure. LLM baseline = gpt-6-luna alone, reasoning "medium". Same farm and weather in every run (seed 0); runs differ only because the models' answers vary.

**Findings:**
1. **hn58:** both agents finish all 3 runs. The baseline loses less grain (3.3% vs 5.5% on average) and costs less ($0.04 vs $0.10). Jev makes 53% of the hybrid's decisions, with about 1 Jev request per action.
2. **Wetjune disease:** each agent failed to harvest once out of 3.
   - Baseline run 2: one planting attempt failed on 7 May; the LLM then stopped and reported that it could not continue.
   - Hybrid run 2: on 23 June the LLM helper decided the task was done while the crop was still growing, and the run ended. The rule that refuses an early "done" only checks Jev's answers, not the LLM helper's. It also sent the message "done" to the user 4 times.
   - In the runs that finished, the hybrid lost less grain (7.6% and 5.5%) than the baseline (18.3% and 8.0%), but cost about 5× more ($0.18 vs $0.03 on average).
3. **Dryer capacity:** both agents finish all 3 runs with about the same grain loss (5.4% vs 5.2%). Here the hybrid is cheaper ($0.06 vs $0.08) and faster, and Jev makes 71% of the decisions.
4. **Cost overall:** the hybrid is cheaper only on dryer capacity. The baseline's input is about 99% cached at $0.01 per million, which Jev cannot match.
5. **Variation between runs is large** (for example the baseline's grain loss on dryer: 0.5% / 14.6% / 0.5%), so differences of a few points between the agents are not reliable with 3 runs.

Spent on this set: about $1.45. Part 2 total: about $5.65.

## 13. All L3-mini scenarios (2026-10-23)

Fix first: the LLM helper's "done" now gets the same unfinished-work check as Jev's (it had ended a wetjune run in June). Then 19 L3-mini scenarios (all except hn50_hn84_hn58_mixed_stress), 1 run per agent, same settings as section 12. Details: `PROGRESS.md`, Steps 17–18.

| Scenario | Agent | Season finished | Yield loss (crop) | Grain loss (recovered) | Actions | Tokens | Cost | Time | Jev's share |
|---|---|---|---|---|---|---|---|---|---|
| organic_residue_weed_establishment | LLM baseline | yes | 6.46% | 13.65% | 233 | 15.0M | $0.17 | 13.8 min | – |
| organic_residue_weed_establishment | Hybrid | yes | -1.21% | -0.27% | 195 | 6.8M | $0.18 | 3.8 min | 51% |
| organic_patch_weed_mechanical_capacity | LLM baseline | **no** (2026-07-18, 0 of 64 harvested) | 0.02% | 100.00% | 93 | 2.5M | $0.03 | 5.8 min | – |
| organic_patch_weed_mechanical_capacity | Hybrid | yes | 4.18% | 4.18% | 118 | 3.6M | $0.10 | 2.8 min | 39% |
| micronutrient_deficiency_flowering_patch | LLM baseline | **no** (2026-09-22, 16 of 64 harvested) | 0.72% | 80.88% | 73 | 1.4M | $0.02 | 7.1 min | – |
| micronutrient_deficiency_flowering_patch | Hybrid | yes | 0.99% | 8.61% | 128 | 3.0M | $0.08 | 2.5 min | 55% |
| local_soil_constraint_nutrition_patch | LLM baseline | **no** (2026-09-18, 6 of 64 harvested) | -0.45% | 90.39% | 84 | 1.5M | $0.02 | 6.9 min | – |
| local_soil_constraint_nutrition_patch | Hybrid | yes | 0.08% | -9.11% | 167 | 6.7M | $0.17 | 4.1 min | 34% |
| heinong84_edge_low_fertility | LLM baseline | yes | 3.93% | 5.06% | 144 | 6.2M | $0.07 | 6.4 min | – |
| heinong84_edge_low_fertility | Hybrid | yes | 4.42% | 4.66% | 219 | 6.9M | $0.19 | 4.0 min | 57% |
| cloudy_wet_low_radiation_biomass | LLM baseline | **no** (2026-05-05, 0 of 64 harvested) | 0.08% | 100.00% | 38 | 0.5M | $0.01 | 4.0 min | – |
| cloudy_wet_low_radiation_biomass | Hybrid | yes | 0.00% | 0.86% | 91 | 1.9M | $0.05 | 2.3 min | 52% |
| poordrainage_wetjune_disease_trafficability | LLM baseline | yes | 2.27% | 11.30% | 135 | 2.8M | $0.03 | 5.9 min | – |
| poordrainage_wetjune_disease_trafficability | Hybrid | yes | 2.27% | 7.37% | 138 | 3.8M | $0.11 | 3.0 min | 49% |
| staggered_wetjune_canopy_disease | LLM baseline | **no** (2026-05-25, 0 of 64 harvested) | 100.00% | 100.00% | 39 | 0.5M | $0.01 | 4.7 min | – |
| staggered_wetjune_canopy_disease | Hybrid | yes | 1.46% | 9.53% | 124 | 3.8M | $0.10 | 3.0 min | 42% |
| soy_after_soy_wetjune_disease | LLM baseline | yes | 5.60% | 13.19% | 137 | 5.4M | $0.06 | 5.3 min | – |
| soy_after_soy_wetjune_disease | Hybrid | yes | 6.26% | 9.04% | 95 | 1.9M | $0.06 | 1.6 min | 58% |
| dryr5r6_hn58_std_waterlimit | LLM baseline | yes | 1.83% | 1.78% | 154 | 4.6M | $0.05 | 13.7 min | – |
| dryr5r6_hn58_std_waterlimit | Hybrid | yes | 1.77% | 5.23% | 120 | 2.9M | $0.08 | 2.4 min | 57% |
| drought_recovery_false_disease_signal | LLM baseline | yes | 0.29% | 3.10% | 119 | 4.5M | $0.05 | 7.8 min | – |
| drought_recovery_false_disease_signal | Hybrid | yes | 0.58% | 3.43% | 251 | 11.9M | $0.30 | 7.0 min | 28% |
| heinong58_resistant_biotic_water_budget_priority | LLM baseline | yes | 1.04% | 8.41% | 124 | 3.9M | $0.05 | 5.3 min | – |
| heinong58_resistant_biotic_water_budget_priority | Hybrid | yes | 3.42% | 11.53% | 140 | 3.3M | $0.10 | 2.4 min | 60% |
| hn60_high_fastdrain_dryr5r6 | LLM baseline | yes | 0.31% | 0.54% | 120 | 4.6M | $0.05 | 5.4 min | – |
| hn60_high_fastdrain_dryr5r6 | Hybrid | yes | -0.05% | 5.65% | 79 | 1.3M | $0.04 | 1.3 min | 61% |
| dryr5r6_insect_threshold_waterstress | LLM baseline | yes | 0.93% | 7.49% | 116 | 4.0M | $0.05 | 5.4 min | – |
| dryr5r6_insect_threshold_waterstress | Hybrid | yes | 0.84% | 1.22% | 118 | 3.4M | $0.09 | 2.8 min | 39% |
| dryer_capacity_batch_harvest_storage | LLM baseline | yes | 0.10% | 0.10% | 147 | 4.2M | $0.05 | 7.4 min | – |
| dryer_capacity_batch_harvest_storage | Hybrid | yes | -0.00% | 6.09% | 188 | 5.5M | $0.15 | 5.9 min | 51% |
| grain_moisture_sensor_failure_harvest | LLM baseline | **no** (2026-09-06, 22 of 64 harvested) | 0.15% | 65.95% | 89 | 2.1M | $0.03 | 4.7 min | – |
| grain_moisture_sensor_failure_harvest | Hybrid | yes | 0.00% | 0.00% | 91 | 1.5M | $0.05 | 1.8 min | 66% |
| laterain_shattering_drying_tradeoff | LLM baseline | **no** (2026-09-23, 8 of 64 harvested) | 0.13% | 88.81% | 85 | 2.3M | $0.03 | 3.4 min | – |
| laterain_shattering_drying_tradeoff | Hybrid | yes | 0.13% | 0.13% | 76 | 1.5M | $0.04 | 4.6 min | 56% |
| cool_august_lategrain_laterain | LLM baseline | yes | 0.06% | 3.67% | 126 | 5.7M | $0.07 | 11.5 min | – |
| cool_august_lategrain_laterain | Hybrid | yes | -0.00% | 8.35% | 88 | 1.3M | $0.04 | 1.4 min | 70% |
| compacted_headland_stand_recovery | LLM baseline | yes | 0.25% | 8.70% | 166 | 7.1M | $0.08 | 8.3 min | – |
| compacted_headland_stand_recovery | Hybrid | **no** (2026-09-03, 24 of 64 harvested) | 0.83% | 61.53% | 300 | 17.9M | $0.45 | 8.1 min | 26% |

How to read: one run per agent and scenario. **Season finished** = the agent ended on its own with the whole field harvested and stored. Grain loss = grain not harvested and stored, compared with the oracle (100% = nothing harvested; below 0% = more than the oracle). Same farm and weather in every run (seed 0).

**Summary:**

| | LLM baseline | Hybrid |
|---|---|---|
| Seasons finished | 12 of 19 | **18 of 19** |
| Average grain loss, all 19 | 37.0% | **7.3%** |
| Average grain loss, the 11 scenarios both finished | 6.2% | 5.7% |
| Total cost (19 runs) | **$0.94** | $2.37 |
| Average cost per run, the 11 both finished | **$0.06** | $0.12 |
| Average time per run | 7.0 min | **3.4 min** |
| Average Jev share of decisions | – | 50% |

**Runs that ended early, and why:**

| Scenario | Agent | When | Harvested | Why (from the agent's last message) |
|---|---|---|---|---|
| organic patch weed mechanical capacity | LLM baseline | 18 July | 0 of 64 | Stopped at R3: "I did not harvest: the crop is still at R3, not mature". Never advanced time to maturity |
| cloudy wet low radiation biomass | LLM baseline | 5 May | 0 of 64 | Stopped right after planting: "Harvest: none is appropriate now. The crop is newly planted" |
| staggered wetjune canopy disease | LLM baseline | 25 May | 0 of 64 | Planting failed (seedbed too wet on some ridges); it stopped: "the staggered planting plan still needs to be established" |
| micronutrient deficiency flowering patch | LLM baseline | 22 Sept | 16 of 64 | Harvested only the treated ridges 28–43 and stopped |
| local soil constraint nutrition patch | LLM baseline | 18 Sept | 6 of 64 | Harvested only the treated ridges 48–53: "Other ridges were not harvested" |
| grain moisture sensor failure harvest | LLM baseline | 6 Sept | 22 of 64 | Harvested ridges 0–21, then stopped: "Ridges 22–63 remain unharvested" |
| laterain shattering drying tradeoff | LLM baseline | 23 Sept | 8 of 64 | Harvested ridges 0–7, then stopped: "The remaining ridges have not been harvested" |
| compacted headland stand recovery | Hybrid | 3 Sept | 24 of 64 | Used all 300 actions. The LLM took 74% of decisions; many repeated checks, drone/robot charging and waits; 12 messages to the user |

**Findings:**
1. **The hybrid finishes far more seasons** (18 vs 12 of 19). The baseline often stops too early: 3 times before harvest, 4 times after harvesting only part of the field. In the hybrid, Jev and the "done" check keep the run going until the field is harvested.
2. **When both finish, grain loss is about the same** (5.7% vs 6.2% on 11 scenarios).
3. **The hybrid costs about 2× more** per run than the baseline, but is about 2× faster.
4. **Jev makes about half the decisions** (26–70% depending on the scenario).
5. The 16 new task texts are Claude's translations, not reviewed.
6. One run per scenario: single results can vary a lot (section 12).

Spent on this set: about $3.3. Part 2 total: about $9.

### 13.1 Fairness check: same "done" check for the baseline (2026-10-23)

The hybrid refuses an early "done"; the baseline did not, and all 7 baseline failures above were early stops. The baseline now has the same check as an option (off by default). Reran those 7 scenarios with it on. Details: `PROGRESS.md`, Step 19.

| Scenario | Baseline before (no check) | Baseline with check | Hybrid (section 13) | Check used |
|---|---|---|---|---|
| organic patch weed | stopped 18 Jul, 0/64 harvested, 100% | finished, 8.4%, $0.10 | finished, 4.2%, $0.10 | 1 refusal |
| cloudy low radiation | stopped 5 May, 0/64, 100% | finished, 13.8%, $0.02 | finished, 0.9%, $0.05 | 1 refusal |
| staggered wetjune | stopped 25 May, 0/64, 100% | finished, 3.5%, $0.08 | finished, 9.5%, $0.10 | 0 (finished by itself) |
| micronutrient patch | stopped 22 Sep, 16/64, 80.9% | finished, 8.4%, $0.06 | finished, 8.6%, $0.09 | 1 refusal |
| local soil constraint | stopped 18 Sep, 6/64, 90.4% | finished, −9.7%, $0.04 | finished, −9.1%, $0.17 | 1 refusal |
| grain moisture sensor failure | stopped 6 Sep, 22/64, 66.0% | finished, 5.8%, $0.05 | finished, 0.0%, $0.05 | 1 refusal |
| laterain shattering | stopped 23 Sep, 8/64, 88.8% | finished, 14.4%, $0.05 | finished, 0.1%, $0.04 | 0 (finished by itself) |

Percentages = grain loss (grain not harvested and stored vs the oracle; below 0% = more than the oracle).

- **All 7 now finish.** In 5 of them the check refused the early "done" once and the LLM then completed the season. In 2 (staggered, laterain) the check never triggered: the LLM finished on its own this time, so that difference is run-to-run variation, not the check.
- **All 19 L3-mini, baseline with these 7 replaced:** 19 of 19 finished (hybrid 18 of 19); average grain loss 6.4% (hybrid 7.3%, which includes its one failed run at 61.5%); total cost about $1.20 (hybrid $2.37).
- So the gap in finished seasons in section 13 came mostly from the missing check, not from the LLM itself. With the same check, the baseline finishes as often as the hybrid, with similar grain loss, at about half the cost.
- Option: `--done-check true` (default off, so all earlier baseline runs are unchanged). Same rule and limit as Jev (`fairy/agents/jev/done_check.py`). Commit `27c9e48`.

Spent: about $0.40. Part 2 total: about $9.4.

## 14. Full history instead of the snapshot (2026-10-24)

Hybrid on all 19 L3-mini scenarios with `--jev-state history`: Jev sees every earlier action with its full result, not the farm snapshot. Everything else is the same as the Step 18 hybrid runs: same scenarios and task texts, fallback gpt-6-luna at confidence 0.4, 300 actions / 3600 s, seed 0, 1 run each. No code changes (code `1655bd7`; since Step 18 the only change for the hybrid is that the done check moved to a shared file, same rule). History was not shortened.

| Scenario | Finished | Stopped (sim date) | Grain loss | Actions | Jev tokens (last OK request) | Cost | Time | Jev's share | Context errors |
|---|---|---|---|---|---|---|---|---|---|
| organic_residue_weed_establishment | no | 2026-05-12 | 100.0% | 114 | 2.3M (35k) | $0.17 | 3.0 min | 56% | 6 |
| organic_patch_weed_mechanical_capacity | no | 2026-05-09 | 100.0% | 47 | 1.1M (38k) | $0.07 | 0.8 min | 70% | 6 |
| micronutrient_deficiency_flowering_patch | no | 2026-07-14 | 100.0% | 74 | 1.7M (35k) | $0.17 | 2.3 min | 23% | 6 |
| local_soil_constraint_nutrition_patch | no | 2026-05-18 | 100.0% | 76 | 1.7M (34k) | $0.11 | 2.3 min | 68% | 6 |
| heinong84_edge_low_fertility | no | 2026-05-09 | 100.0% | 106 | 2.2M (34k) | $0.15 | 2.1 min | 68% | 6 |
| cloudy_wet_low_radiation_biomass | no | 2026-07-11 | 100.0% | 79 | 1.7M (35k) | $0.15 | 2.2 min | 39% | 6 |
| poordrainage_wetjune_disease_trafficability | no | 2026-05-10 | 100.0% | 103 | 2.2M (37k) | $0.21 | 3.1 min | 30% | 6 |
| staggered_wetjune_canopy_disease | no | 2026-05-08 | 100.0% | 46 | 0.9M (27k) | $0.08 | 2.0 min | 28% | 6 |
| soy_after_soy_wetjune_disease | no | 2026-06-03 | 100.0% | 96 | 1.9M (35k) | $0.17 | 2.7 min | 39% | 6 |
| dryr5r6_hn58_std_waterlimit | no | 2026-05-31 | 100.0% | 68 | 1.1M (32k) | $0.09 | 1.9 min | 41% | 6 |
| drought_recovery_false_disease_signal | no | 2026-05-08 | 100.0% | 89 | 1.8M (34k) | $0.13 | 1.9 min | 55% | 6 |
| heinong58_resistant_biotic_water_budget_priority | no | 2026-05-20 | 100.0% | 106 | 2.3M (36k) | $0.19 | 3.9 min | 41% | 6 |
| hn60_high_fastdrain_dryr5r6 | no | 2026-05-05 | 100.0% | 84 | 1.7M (37k) | $0.15 | 2.5 min | 35% | 6 |
| dryr5r6_insect_threshold_waterstress | no | 2026-05-06 | 100.0% | 79 | 1.7M (31k) | $0.13 | 1.8 min | 48% | 6 |
| dryer_capacity_batch_harvest_storage | no | 2026-05-05 | 100.0% | 45 | 0.8M (31k) | $0.05 | 0.7 min | 64% | 6 |
| grain_moisture_sensor_failure_harvest | no | 2026-05-05 | 100.0% | 43 | 0.9M (25k) | $0.06 | 0.7 min | 51% | 6 |
| laterain_shattering_drying_tradeoff | no | 2026-05-11 | 100.0% | 73 | 1.0M (34k) | $0.09 | 1.4 min | 42% | 6 |
| cool_august_lategrain_laterain | no | 2026-09-07 | 100.0% | 52 | 0.7M (25k) | $0.05 | 0.8 min | 63% | 6 |
| compacted_headland_stand_recovery | no | 2026-05-23 | 100.0% | 87 | 1.9M (34k) | $0.14 | 1.4 min | 57% | 6 |

How to read: **Context errors** = Jev requests refused with `max_tokens_exceeded` (Jev's input limit). Each run has 6: one request, tried once and retried 5 times, all refused, after which the run ends with an error. Jev tokens = total Jev input for the run, with the size of the last request that went through in brackets. Cost = Jev input plus the LLM helper.

**Averages, next to section 13.1:**

| | Hybrid, history | Hybrid, snapshot (section 13) | LLM baseline with done check (section 13.1) |
|---|---|---|---|
| Seasons finished | **0 of 19** | 18 of 19 | 19 of 19 |
| Average grain loss | 100% | 7.3% | 6.4% |
| Total cost (19 runs) | $2.36 | $2.37 | about $1.20 |
| Average time per run | 2.0 min | 3.4 min | 7.1 min |
| Average Jev share of decisions | 48% | 50% | – |
| Runs ended by Jev's input limit | 19 | 0 | – |

- **Every run hit Jev's input limit before harvest.** Mostly in May (planting); the latest stop was 7 Sep (cool August). Nothing was harvested in any run, so grain loss is 100% everywhere.
- The history grows with every action. The last requests that got through were 25–38k tokens; the next one was refused. This happened after 43–114 actions; the snapshot hybrid used 76–251 actions for a full season (section 13).
- Cost is the same as the snapshot hybrid only because the runs ended early: about $0.12 per run for less than half a season.
- Same result as Part 1 on L1 (52 of 78 runs stopped by the input limit) and the reason the snapshot was built. On full seasons, the full history does not work with Jev at all.
- Jev's share (48%) is close to the snapshot hybrid's (50%); the runs did not fail because of low confidence, they could not continue.

Spent: about $2.36. Part 2 total: about $11.8.

## 15. REFLEX-style hybrid (branch `jev-reflex`, 2026-10-24)

Idea from REFLEX (arXiv 2609.26532): Jev always picks the tool. If Jev's confidence on the tool is at or above the threshold (0.4), Jev also picks the arguments, as before. If it is below, Jev's tool is kept and gpt-6-luna only fills in the arguments for that tool (it sees only that tool and cannot change it). Everything else is the same as section 13: snapshot, "done" check, menus, 300 actions / 60 min, seed 0. Two safety nets of the current hybrid also stay: a repeat that changed nothing, and a "done" refused twice, still hand the whole decision to the LLM. Option: `--hybrid-mode reflex` (default `full` = current hybrid, so earlier runs are unchanged). 1 run per scenario, all 19 L3-mini. Details: `PROGRESS.md`, Step 21.

| Scenario | LLM baseline (13.1) | Hybrid (13) | Reflex hybrid | Reflex: Jev picks the tool / tool and arguments | Actions where the LLM filled the arguments |
|---|---|---|---|---|---|
| organic_residue_weed_establishment | finished, 13.7%, $0.17, 233 act. | finished, -0.3%, $0.18, 195 act. | finished, -0.6%, $0.23, 158 act. | 100% / 51% | 78 |
| organic_patch_weed_mechanical_capacity | finished, 8.4%, $0.10, 155 act. | finished, 4.2%, $0.10, 118 act. | finished, 8.4%, $0.47, 295 act. | 67% / 40% | 80 |
| micronutrient_deficiency_flowering_patch | finished, 8.4%, $0.06, 109 act. | finished, 8.6%, $0.08, 128 act. | **not finished** (05-29, max tool calls), 100.0%, $0.36, 300 act. | 94% / 67% | 81 |
| local_soil_constraint_nutrition_patch | finished, -9.7%, $0.04, 120 act. | finished, -9.1%, $0.17, 167 act. | **not finished** (06-04, max tool calls), 100.0%, $0.43, 300 act. | 94% / 64% | 89 |
| heinong84_edge_low_fertility | finished, 5.1%, $0.07, 144 act. | finished, 4.7%, $0.19, 219 act. | **not finished** (05-25, max tool calls), 100.0%, $0.39, 300 act. | 91% / 65% | 79 |
| cloudy_wet_low_radiation_biomass | finished, 13.8%, $0.02, 79 act. | finished, 0.9%, $0.05, 91 act. | finished, 0.2%, $0.08, 123 act. | 93% / 72% | 26 |
| poordrainage_wetjune_disease_trafficability | finished, 11.3%, $0.03, 135 act. | finished, 7.4%, $0.11, 138 act. | **not finished** (05-30, max tool calls), 100.0%, $0.36, 300 act. | 97% / 59% | 115 |
| staggered_wetjune_canopy_disease | finished, 3.5%, $0.08, 172 act. | finished, 9.5%, $0.10, 124 act. | **not finished** (08-13, max tool calls), 100.0%, $0.51, 300 act. | 98% / 50% | 145 |
| soy_after_soy_wetjune_disease | finished, 13.2%, $0.06, 137 act. | finished, 9.0%, $0.06, 95 act. | finished, 2.3%, $0.32, 260 act. | 97% / 66% | 82 |
| dryr5r6_hn58_std_waterlimit | finished, 1.8%, $0.05, 154 act. | finished, 5.2%, $0.08, 120 act. | finished, 4.1%, $0.18, 186 act. | 96% / 70% | 50 |
| drought_recovery_false_disease_signal | finished, 3.1%, $0.05, 119 act. | finished, 3.4%, $0.30, 251 act. | **not finished** (05-28, max tool calls), 100.0%, $0.54, 300 act. | 97% / 49% | 146 |
| heinong58_resistant_biotic_water_budget_priority | finished, 8.4%, $0.05, 124 act. | finished, 11.5%, $0.10, 140 act. | **not finished** (05-26, max tool calls), 100.0%, $0.53, 300 act. | 100% / 31% | 206 |
| hn60_high_fastdrain_dryr5r6 | finished, 0.5%, $0.05, 120 act. | finished, 5.7%, $0.04, 79 act. | finished, 5.7%, $0.09, 123 act. | 97% / 73% | 29 |
| dryr5r6_insect_threshold_waterstress | finished, 7.5%, $0.05, 116 act. | finished, 1.2%, $0.09, 118 act. | **not finished** (06-19, max tool calls), 100.0%, $0.37, 300 act. | 96% / 60% | 107 |
| dryer_capacity_batch_harvest_storage | finished, 0.1%, $0.05, 147 act. | finished, 6.1%, $0.15, 188 act. | **not finished** (10-11, max tool calls), 51.8%, $0.47, 300 act. | 98% / 46% | 156 |
| grain_moisture_sensor_failure_harvest | finished, 5.8%, $0.05, 125 act. | finished, 0.0%, $0.05, 91 act. | finished, 0.1%, $0.08, 116 act. | 100% / 70% | 35 |
| laterain_shattering_drying_tradeoff | finished, 14.4%, $0.05, 120 act. | finished, 0.1%, $0.04, 76 act. | **not finished** (09-23, max tool calls), 16.3%, $0.38, 300 act. | 42% / 26% | 50 |
| cool_august_lategrain_laterain | finished, 3.7%, $0.07, 126 act. | finished, 8.3%, $0.04, 88 act. | finished, 0.3%, $0.12, 155 act. | 99% / 73% | 41 |
| compacted_headland_stand_recovery | finished, 8.7%, $0.08, 166 act. | **not finished** (09-03, max tool calls), 61.5%, $0.45, 300 act. | **not finished** (07-04, max tool calls), 100.0%, $0.43, 300 act. | 92% / 66% | 78 |

Cells: season finished or not (date and why it stopped), grain loss (grain not harvested and stored vs the oracle; 100% = nothing harvested; below 0% = more than the oracle), cost, actions. Baseline = gpt-6-luna alone with the "done" check (the 7 reruns of 13.1, the other 12 from section 13).

**Summary:**

| | LLM baseline (13.1) | Hybrid (13) | Reflex hybrid |
|---|---|---|---|
| Seasons finished | **19 of 19** | 18 of 19 | 8 of 19 |
| Used up all 300 actions | 0 | 1 | 11 |
| Average grain loss, all 19 | **6.4%** | 7.3% | 52.0% |
| Average grain loss, the 8 that reflex finished | 7.6% | 4.1% | **2.6%** |
| Total cost (19 runs) | **$1.19** | $2.37 | $6.36 |
| Cost, the 8 that reflex finished | **$0.57** | $0.60 | $1.57 |
| Average actions per run | 137 | 143 | 248 |
| Average time per run | 7.1 min | **3.4 min** | 4.7 min |
| Jev picks the tool | – | 50% | 92% |
| Jev picks tool and arguments | – | 50% | 58% |

**Findings:**
1. **Reflex is much worse here.** It finished 8 of 19 seasons (hybrid 18, baseline 19). 11 runs used up all 300 actions, 7 of them still in May or June, before any harvest.
2. **Why: in the current hybrid, the LLM mostly fixes Jev's tool, not its arguments.** In the section 13 hybrid runs, when Jev was unsure, the LLM picked a different tool in 68% of hand-offs (914 of 1,348), most often "advance time" instead of another check. Reflex takes that away: Jev's unsure picks (status checks, charging, inspections, short waits) run as they are.
3. **Waiting is the clearest case.** When Jev picks "wait for a notification", the LLM can only choose how long, and it chose 1 hour in 265 of 319 cases. The current hybrid's LLM switches to "advance time" by days. So reflex runs move through the season in small steps and run out of actions.
4. **When reflex does finish, it loses the least grain** (2.6% on its 8 vs 4.1% hybrid and 7.6% baseline on the same 8), but it costs about 2.6× more ($1.57 vs about $0.60) because it takes more actions.
5. **Cost overall:** $6.36 for 19 runs, about 2.7× the hybrid and 5× the baseline. Runs that hit 300 actions cost $0.36–0.54 each.
6. One run per scenario (section 12: single runs vary a lot). The pattern (11 runs out of actions vs 1) is too large to be noise.
7. One run (laterain) hung for 2.5 h in a gpt-6-luna request (FAIRY sets no request timeout); it was stopped and rerun.

Spent: about $7.2 (check run $0.48, 19 runs $6.36, the hung run about $0.40). Part 2 total: about $16.6.

## 16. LLM runs the farm, Jev as a tool (branch `jev-llm-driven`, 2026-10-24)

### 16.1 The idea

The reverse of the hybrid: gpt-6-luna (reasoning "medium", Responses API) runs the farm like the LLM baseline, with the same task, system prompt and tools, plus one extra tool, `ask_jev`. To use it, the LLM writes a farm state itself and a question with a list of options. Jev returns its pick, the probability of each option and its confidence. The LLM decides when to ask and what to do with the answer; no rule makes it ask. The tool description is the only place Jev is explained.

- Agent: `--controller farm_llm_jev --jev-model jev-latest` (`fairy/agents/jev/llm_driven_agent.py`). The Jev agent and the hybrid are unchanged.
- `ask_jev` is not a farm action: it is not in the workflow (scoring sees farm tools only) and does not count toward the 300-action limit (separate cap: 300 asks per run).
- Every ask is logged (`ask_jev` event: state size, question, options, pick, confidence, tokens, cost); the run report counts asks, asks per action and farm actions taken right after an ask.
- Done check on (`--done-check true`), same as the baseline in 13.1. Same limits as section 13: 300 actions, 60 min, seed 0, 1 run per scenario.
- 7 new tests; all 105 tests pass. One real Jev request through `ask_jev` checked by hand (pick, probabilities and confidence came back; cost $0.00002).

### 16.2 Results (19 L3-mini, 1 run each)

Each cell: season finished, grain loss (not harvested and stored, vs the oracle), cost. Baseline = LLM baseline with the done check (section 13.1 set: the 7 reruns with the check, the other 12 from section 13). Hybrid = section 13.

| Scenario | LLM baseline (13.1) | Hybrid (13) | LLM + Jev tool |
|---|---|---|---|
| organic_residue_weed_establishment | yes, 13.65%, $0.17 | yes, -0.27%, $0.18 | yes, 19.05%, $0.11 |
| organic_patch_weed_mechanical_capacity | yes, 8.36%, $0.10 | yes, 4.18%, $0.10 | yes, 8.23%, $0.06 |
| micronutrient_deficiency_flowering_patch | yes, 8.36%, $0.06 | yes, 8.61%, $0.08 | yes, 15.38%, $0.04 |
| local_soil_constraint_nutrition_patch | yes, -9.70%, $0.04 | yes, -9.11%, $0.17 | yes, -11.76%, $0.07 |
| heinong84_edge_low_fertility | yes, 5.06%, $0.07 | yes, 4.66%, $0.19 | yes, 17.12%, $0.09 |
| cloudy_wet_low_radiation_biomass | yes, 13.80%, $0.02 | yes, 0.86%, $0.05 | yes, 4.63%, $0.04 |
| poordrainage_wetjune_disease_trafficability | yes, 11.30%, $0.03 | yes, 7.37%, $0.11 | yes, 7.98%, $0.03 |
| staggered_wetjune_canopy_disease | yes, 3.46%, $0.08 | yes, 9.53%, $0.10 | yes, 9.61%, $0.04 |
| soy_after_soy_wetjune_disease | yes, 13.19%, $0.06 | yes, 9.04%, $0.06 | yes, 7.84%, $0.04 |
| dryr5r6_hn58_std_waterlimit | yes, 1.78%, $0.05 | yes, 5.23%, $0.08 | yes, 8.20%, $0.05 |
| drought_recovery_false_disease_signal | yes, 3.10%, $0.05 | yes, 3.43%, $0.30 | yes, 14.38%, $0.03 |
| heinong58_resistant_biotic_water_budget_priority | yes, 8.41%, $0.05 | yes, 11.53%, $0.10 | yes, 13.86%, $0.04 |
| hn60_high_fastdrain_dryr5r6 | yes, 0.54%, $0.05 | yes, 5.65%, $0.04 | yes, 5.70%, $0.08 |
| dryr5r6_insect_threshold_waterstress | yes, 7.49%, $0.05 | yes, 1.22%, $0.09 | yes, 7.10%, $0.04 |
| dryer_capacity_batch_harvest_storage | yes, 0.10%, $0.05 | yes, 6.09%, $0.15 | yes, 31.95%, $0.09 |
| grain_moisture_sensor_failure_harvest | yes, 5.76%, $0.05 | yes, 0.00%, $0.05 | yes, 0.14%, $0.05 |
| laterain_shattering_drying_tradeoff | yes, 14.39%, $0.05 | yes, 0.13%, $0.04 | yes, 16.23%, $0.07 |
| cool_august_lategrain_laterain | yes, 3.67%, $0.07 | yes, 8.35%, $0.04 | yes, 1.92%, $0.04 |
| compacted_headland_stand_recovery | yes, 8.70%, $0.08 | **no** (2026-09-03, 24/64), 61.53%, $0.45 | yes, 4.11%, $0.10 |

| | LLM baseline (13.1) | Hybrid (13) | LLM + Jev tool |
|---|---|---|---|
| Seasons finished | 19 of 19 | 18 of 19 | 19 of 19 |
| Average grain loss, all 19 | **6.4%** | 7.3% | 9.6% |
| Total cost (19 runs) | $1.19 | $2.37 | **$1.11** |
| Average actions per run | 137 | 143 | 130 |
| Average time per run | 7.1 min | **3.4 min** | 5.4 min |
| Jev asks | – | – | **0** (in 2,470 farm actions) |

### 16.3 Findings

1. **The LLM never asked Jev.** 0 asks in all 19 runs, although `ask_jev` was in the tool list of every LLM call (checked in the logs). Jev cost: $0.
2. So in these runs the agent is the LLM baseline with the done check plus one unused tool. The done check refused an early "done" in 6 runs (once in 5, twice in 1); all 19 finished.
3. Grain loss is higher on average (9.6% vs 6.4%), mostly because of one run (dryer capacity 32.0%; without it 8.4%). With Jev unused, the differences from the baseline are run-to-run variation (section 12: baseline dryer 0.5% / 14.6% / 0.5% over 3 runs), not an effect of Jev.
4. Cost and time are close to the baseline ($1.11 vs $1.19; 5.4 vs 7.1 min).
5. **Takeaway:** offered Jev as an optional tool with no instruction, gpt-6-luna does not use it. Getting any use would need the LLM to be told about Jev or asked to use it (for example in the system prompt), which these runs deliberately did not do.

One run per scenario. The compacted headland run hung once on an LLM request (laptop sleep) and was deleted and rerun.

Spent: about $1.15. Part 2 total: about $10.5.

### 16.4 Rerun with Jev explained in the system prompt (2026-10-24)

Same agent, with one change: a new option `--jev-prompt-note true` (default off) adds this note to the system prompt:

> You also have the tool ask_jev. Jev is a decision model: you give it a farm state that you write, a question and a list of options, and it returns its pick, the probability of each option and its confidence (0 to 1). Jev sees only what you pass. Use it when it helps; the decision stays yours.

Nothing else changed (same task, tools, done check, limits, seed; 1 run per scenario). The note was in the prompt of every LLM call (checked in the logs). Commit `fdbac56`; 1 test added, all 106 pass.

Each cell: season finished, grain loss, cost. The 16.2 column is repeated for comparison.

| Scenario | LLM baseline (13.1) | Hybrid (13) | Jev tool (16.2) | Jev tool + prompt note | Jev calls (16.2 / note) |
|---|---|---|---|---|---|
| organic_residue_weed_establishment | yes, 13.65%, $0.17 | yes, -0.27%, $0.18 | yes, 19.05%, $0.11 | yes, 14.26%, $0.11 | 0 / 0 |
| organic_patch_weed_mechanical_capacity | yes, 8.36%, $0.10 | yes, 4.18%, $0.10 | yes, 8.23%, $0.06 | yes, 8.32%, $0.05 | 0 / 0 |
| micronutrient_deficiency_flowering_patch | yes, 8.36%, $0.06 | yes, 8.61%, $0.08 | yes, 15.38%, $0.04 | yes, 14.06%, $0.04 | 0 / 0 |
| local_soil_constraint_nutrition_patch | yes, -9.70%, $0.04 | yes, -9.11%, $0.17 | yes, -11.76%, $0.07 | yes, -10.31%, $0.10 | 0 / 0 |
| heinong84_edge_low_fertility | yes, 5.06%, $0.07 | yes, 4.66%, $0.19 | yes, 17.12%, $0.09 | yes, 6.94%, $0.06 | 0 / 0 |
| cloudy_wet_low_radiation_biomass | yes, 13.80%, $0.02 | yes, 0.86%, $0.05 | yes, 4.63%, $0.04 | yes, 4.63%, $0.02 | 0 / 0 |
| poordrainage_wetjune_disease_trafficability | yes, 11.30%, $0.03 | yes, 7.37%, $0.11 | yes, 7.98%, $0.03 | yes, 10.44%, $0.03 | 0 / 0 |
| staggered_wetjune_canopy_disease | yes, 3.46%, $0.08 | yes, 9.53%, $0.10 | yes, 9.61%, $0.04 | yes, 15.63%, $0.06 | 0 / 0 |
| soy_after_soy_wetjune_disease | yes, 13.19%, $0.06 | yes, 9.04%, $0.06 | yes, 7.84%, $0.04 | yes, 17.78%, $0.05 | 0 / 0 |
| dryr5r6_hn58_std_waterlimit | yes, 1.78%, $0.05 | yes, 5.23%, $0.08 | yes, 8.20%, $0.05 | yes, 15.55%, $0.05 | 0 / 0 |
| drought_recovery_false_disease_signal | yes, 3.10%, $0.05 | yes, 3.43%, $0.30 | yes, 14.38%, $0.03 | yes, 9.71%, $0.03 | 0 / 0 |
| heinong58_resistant_biotic_water_budget_priority | yes, 8.41%, $0.05 | yes, 11.53%, $0.10 | yes, 13.86%, $0.04 | yes, 7.88%, $0.04 | 0 / 0 |
| hn60_high_fastdrain_dryr5r6 | yes, 0.54%, $0.05 | yes, 5.65%, $0.04 | yes, 5.70%, $0.08 | yes, 7.65%, $0.05 | 0 / 0 |
| dryr5r6_insect_threshold_waterstress | yes, 7.49%, $0.05 | yes, 1.22%, $0.09 | yes, 7.10%, $0.04 | yes, 5.97%, $0.03 | 0 / 0 |
| dryer_capacity_batch_harvest_storage | yes, 0.10%, $0.05 | yes, 6.09%, $0.15 | yes, 31.95%, $0.09 | yes, 15.24%, $0.08 | 0 / 0 |
| grain_moisture_sensor_failure_harvest | yes, 5.76%, $0.05 | yes, 0.00%, $0.05 | yes, 0.14%, $0.05 | yes, 11.26%, $0.17 | 0 / 0 |
| laterain_shattering_drying_tradeoff | yes, 14.39%, $0.05 | yes, 0.13%, $0.04 | yes, 16.23%, $0.07 | yes, 9.53%, $0.04 | 0 / 0 |
| cool_august_lategrain_laterain | yes, 3.67%, $0.07 | yes, 8.35%, $0.04 | yes, 1.92%, $0.04 | yes, 0.05%, $0.03 | 0 / 0 |
| compacted_headland_stand_recovery | yes, 8.70%, $0.08 | **no** (2026-09-03, 24/64), 61.53%, $0.45 | yes, 4.11%, $0.10 | yes, 3.02%, $0.16 | 0 / 0 |

| | LLM baseline (13.1) | Hybrid (13) | Jev tool (16.2) | Jev tool + prompt note (16.4) |
|---|---|---|---|---|
| Seasons finished | 19 of 19 | 18 of 19 | 19 of 19 | 19 of 19 |
| Average grain loss, all 19 | **6.4%** | 7.3% | 9.6% | 8.8% |
| Total cost (19 runs) | $1.19 | $2.37 | **$1.11** | $1.20 |
| Average actions per run | 137 | 143 | 130 | 134 |
| Average time per run | 7.1 min | **3.4 min** | 5.4 min | 5.8 min |
| Jev calls per run | – | – | 0 in every run | 0 in every run |
| LLM followed Jev's pick | – | – | – (no calls) | – (no calls) |

**Findings:**
1. **Still no Jev calls:** 0 in all 19 runs (2,537 farm actions), even with Jev explained in the system prompt. None of the LLM's 2,564 replies mentions Jev. So "how often the LLM followed Jev's pick" cannot be measured: there were no picks.
2. The done check refused an early "done" once in 6 runs; all 19 finished.
3. Results are again those of the LLM baseline with the done check, within run-to-run variation: grain loss 8.8% (16.2: 9.6%, baseline: 6.4%), cost $1.20. Per scenario, 16.2 and 16.4 differ by up to 16 points (dryer capacity 32.0% vs 15.2%) with Jev unused in both, which shows the size of single-run noise.
4. **Takeaway:** with a neutral note ("use it when it helps") gpt-6-luna still never asks Jev. Getting any use would take a stronger instruction (for example when or how often to ask), which this test deliberately did not include.

Spent: about $1.20. Part 2 total: about $11.7.
