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

---

# Part 2 – Full-season (L3) runs with a Jev + LLM hybrid

**Goal:** run full-season (L3) scenarios end to end with a yield close to the LLM agent's (gpt-6-luna), at lower token cost. Target: paper, 2026-11-05.

**Rules:** one scenario at a time, never a full manifest; a cost estimate and your OK before every AI run; debug on L1/L2, not L3.

## Step 1 – Read and plan (2026-10-21, no AI, free)

**Read:** the recap, this log, and Ouyang's two branches (`pure-jev`, `llm-jev-hybrid` at github.com/StarryNight2953/fairy-jev).

**His findings that matter here:**
- 52 of his 78 L1 runs were stopped by Jev's input limit (about 32k tokens per question, 64k per request), because the full history was sent each time.
- 958 of 1,124 failed actions were "harvest" on ridges already harvested or "plant" on ridges already planted.
- In the hybrid, the LLM summary once turned a water quota of 1.4 into "unlimited", and LLM updates took most of the run time.
- He has no yield numbers, so there is nothing to compare our target against.

**Reused as ideas (rewritten in our code):** waiting values in seconds (task minutes/hours converted, plus time left until a pending effect is ready); ridge ranges limited to one machine pass and excluding ridges already harvested/planted in this run; "charging until …" shown for drone and robot.
**Not reused:** his separate agent framework, report texts built from templates, LLM updates every 4 steps.

**Decisions (agreed):**

| Choice | Why |
|---|---|
| Jev sees a short farm snapshot built by code, plus the last 5 actions, instead of the full history | Full history hits Jev's input limit; code-built facts cannot be misreported like LLM summaries |
| The snapshot uses only data the agent's own tools could return; the advantage this gives Jev is stated in the paper | Fair to the LLM agent, which must spend tool calls for the same data |
| "Done" is checked by our own simple rules (no unchecked pending effect, task ridge ranges covered), not FAIRY's evaluator | The evaluator would show Jev the grader's verdict, which the LLM never gets |
| The LLM picks an action only when Jev's confidence is low, Jev is repeating itself, or "done" was refused twice; it gets the same snapshot and options | Pay for the LLM only where Jev is unsure (confidence 0.54 in stuck runs vs 0.81 otherwise) |

**Scenarios:**
- Dev: `scenario_l1_hb_wetcold_high_residue_planting_execution`, `scenario_l1_hb_heihe43_apply_targeted_herbicide`, `scenario_l1_hb_coldspring_heihe50_harvest_store_ready`, `scenario_l2_hb_coldspring_heihe50_harvest_drydown_store`, `scenario_l2_hb_wetcold_high_residue_replant_recovery` (the two L2s have waiting steps; the L1s have none).
- Test (L3-mini): `scenario_full_season_hb_dryr5r6_hn58_std_waterlimit`, `scenario_full_season_hb_staggered_wetjune_canopy_disease`, `scenario_full_season_hb_dryer_capacity_batch_harvest_storage`.

## Step 2 – Oracle baselines and checks before coding (2026-10-21, no AI, free)

**Did:** built oracle baselines for the 8 scenarios (`validation_runs/jev_l3/oracle_baselines/`, not in git). Ran two oracles through `fairy.cli` to see their length and task text.

**Fixed:** `scripts/build_oracle_baselines.py` failed for every L1/L2 scenario on Windows (backslashes in the module path). One-line fix (`as_posix()`); the L3 ones were not affected.

**Baselines (biological yield, oracle vs do-nothing, kg):**

| Scenario | Oracle | Do-nothing |
|---|---|---|
| L1 wetcold planting | 7,773 | 0 |
| L1 heihe43 herbicide | 9,150 | 8,911 |
| L1 heihe50 harvest (recovered) | 5,226 | 0 |
| L2 heihe50 harvest drydown (recovered) | 5,226 | 0 |
| L2 wetcold replant | 7,840 | 7,773 |
| L3 hn58 water limit | 9,171 | 0 |
| L3 wetjune disease | 7,372 | 0 |
| L3 dryer capacity harvest | 8,860 | 0 |

The herbicide L1 and replant L2 differ from do-nothing by only 2.7% and 0.9%, so yield loss tells little on those two; step match and coverage matter more there.

**Found:**
- **L3 is long:** the hn58 L3 oracle has 262 actions, 144 of them "advance time 1 day". The 60-action limit from Part 1 cannot work; L3 needs about 300.
- **Waits in L3 are in days**, not seconds. The wait options must include days.
- **Jev never saw notifications.** FAIRY stores messages from the environment as "system" steps; Jev's input only listed actions. (None of the 8 chosen scenarios sends notifications; the snapshot shows them anyway.)
- **Reading the farm for the snapshot is invisible to the evaluator** (the event decorator only records during scenario setup). Side effects: see Step 3.
- **Tasks are in Chinese,** and the Part 1 way to give English text (`scenario_input`) is ignored for these scenarios, because FAIRY uses the briefing event instead.
- **All three L3-mini test scenarios are long:** their oracles have 262, 262 and 243 actions (126–144 of them "advance time"). "Mini" means 20 of the 90 L3 scenarios, not shorter scenarios.

**Decided:**

| Choice | Why |
|---|---|
| Both agents get English task texts (translated by Claude, not reviewed) | Same as Part 1; Jev works best in English |
| Limits for both agents: L3 300 actions / 60 min; L1/L2 60 actions / 10 min | L3-mini oracles need up to 262 actions |

## Step 3 – Snapshot, new menus, done check (2026-10-21, no AI, free)

**Built:**
- `fairy/agents/jev/snapshot.py`: the farm snapshot. Jev's input is now task + snapshot + last 5 actions (+ notes), not the full history.
- `menu.py` / `jev_agent.py`: the new menus and the done check (table below).
- English task switch: new scenario field `agent_task_override` (via `--scenario-kwargs`); the engine gives it to every agent instead of the briefing. Texts in `docs/jev/tasks_en/`.
- `scripts/jev_offline_check.py`: free test. A fake Jev follows the oracle through the real agent loop and reports oracle actions/values missing from the menus, "done" refusals and request sizes. `--no-snapshot` turns all farm reads off.

**Decisions:**

| Choice | Why |
|---|---|
| Snapshot reads stored values; it never calls the farm-overview or sensor tools | Those tools move the physics to "now", and the physics depends on how often that happens: calling them changed soil temperature by 1.4 °C on day 1 and made an L3 planting fail |
| Sensor zones shown without sensor noise, rounded (vwc 3 decimals, NDVI 2) | Same averages the sensor tools report; noise would need the simulator's random numbers |
| Waiting = one question: 30 min, 1/2/6/12 h, 1–7/10/14 days, task durations, "until <pending effect> is ready" | Part 1's wait options (task numbers in seconds) caused loops; L3 waits in days |
| End ridge ≥ start ridge; tractor work limited to the ridges per pass set in the code (4 or 10); harvest/planting options leave out ridges already harvested/planted | Ouyang's runs: most failed actions were impossible ranges or repeats on done ridges |
| Report to the user = one option, text written by code from the snapshot | Jev cannot write text |
| "Done" refused (max 2 times, reasons shown to Jev) if: an effect is still pending; task says harvest and planted ridges are unharvested; task says plant and ridges are unplanted; grain in the tractor bin or not stored (task says store); task says report and none was sent | Jev said "done" too early; rules use only visible facts and the task text |
| A tool whose argument has no possible value (no code limit, no number in the task) is left off Jev's menu | It crashed the agent at start |
| Fertigation nutrient amount: 10 values in 0.5–1.5 | Range stated in the tool's own description |

**Checks (all 8 scenarios, fake Jev following the oracle):**
- Every oracle action is on the menu. Values not on the menu: load amounts (e.g. 240 kg fertilizer; Jev can load more), replant spacing 7.9 (not in that task), fertigation 0.22 / 0.5, and waits of 8 days (L2 replant).
- No "done" refusals once the oracle has finished.
- **Snapshot leaves the simulation unchanged:** with and without snapshot, every action result is identical, apart from random inspection/mission IDs. Needs `PYTHONHASHSEED=0`: FAIRY seeds sensor noise with Python's `hash()`, so without it every run differs anyway.
- **Yield loss vs oracle baseline** (oracle steps through our menus): 0.00% on 7 scenarios, 0.15% on L3 hn58.
- **Request size:** 8–12k characters on average, max 17k (well under Jev's limit). Fake-Jev totals, estimated as characters ÷ 4: L1/L2 0.06–0.2M tokens, L3 1.2–1.5M tokens per run, i.e. about $0.05–0.06 per L3 run at Jev's $0.042 per million.
- Jev tests updated to the new behaviour; all 7 pass. FAIRY smoke test: 70 pass, 1 fails as before (missing search tool).

## Step 4 – LLM fallback (2026-10-21, no AI, free)

**Built:** `--fallback-model` (and `--fallback-provider`, `--fallback-confidence`) for `farm_jev`. Without them the agent behaves as in Step 3 (checked: same actions on L1 herbicide and L3 hn58). gpt-6-luna added to FAIRY's OpenAI client (same mode as gpt-5: no temperature; confirmed on the first paid run).

**Decisions:**

| Choice | Why |
|---|---|
| The LLM gets Jev's state (task, snapshot, last 5 actions, notes) plus FAIRY's normal tool list, and calls one action itself | It can write values Jev's menu lacks (exact loads, 8-day waits); it never writes the farm state (Ouyang's hybrid problem) |
| Triggers: Jev's action confidence below the threshold; Jev repeats a call whose last two results were identical or both failed; "done" refused twice | Repeated daily waits change the result, so they do not trigger |
| If the LLM call fails or names an unknown tool, Jev's choice stands | A run never stops because of the fallback |
| Jev and LLM tokens counted separately in the run report (`jev_input_tokens`, `llm_tokens` with cached tokens) | Needed for the cost comparison |
| Threshold set from runs of the new agent, not Part 1 | Part 1 data (old inputs): threshold 0.6 would send 58% of actions to the LLM (0.5: 45%) |

**Prices:** Jev $0.042 per million input tokens (output free). gpt-6-luna $0.10 input, $0.01 cached input, $0.50 output per million (OpenAI pricing page, 2026-10-21). The LLM agent's repeated history is mostly cached, so fewer tokens do not automatically mean lower cost; both are reported.

**Also fixed:** the "report not sent" done-rule now applies only when the scenario has a report tool (otherwise it could never be met).

**Tests:** 10 Jev tests pass (3 new: low confidence, repeat, done refused twice — with a fake LLM).

## Step 5 – First paid runs, L1 herbicide (2026-10-21)

**Run A – Jev only (no fallback):** stopped at the 60-action limit after 48 s. Jev called "read ridges 44–55" 60 times in a row, with confidence 0.7–0.9 every time, also after the snapshot's repeat warning. It skipped task steps 1–2 (weather and soil are already in the snapshot). 180 Jev requests, 652k input tokens (2.1–3.8k per request), about $0.027.
- Confidence did not flag this loop, so a confidence threshold alone would not have handed it to the LLM; the "repeat without change" trigger would have.

**Run B – gpt-6-luna LLM agent:** failed on its first call (no charge): OpenAI rejects tools on `/v1/chat/completions` for gpt-6-luna unless reasoning is set to "none". FAIRY's client uses that route and sets no reasoning level.

**Fix (your choice):** gpt-6-luna runs with reasoning "none" (the only way it accepts tools on FAIRY's route). The paper must state this.

**Run A2 – Jev only, with a one-line history of all steps and an instruction not to repeat:** the same loop (60 × "read ridges 44–55"). Confidence fell to 0.38–0.6 after the first step, so a 0.6 threshold would now trigger the fallback. 661k tokens, about $0.028. History adds about 28% to request size (L3: ~1.9M Jev tokens per run instead of 1.5M).

**Run B – gpt-6-luna LLM agent:** followed the task step by step, 13 actions, 30 s. 124k tokens, 111k of them cached: about $0.003.

| Run | Yield loss | Coverage | Tokens | Cost |
|---|---|---|---|---|
| A Jev | 2.61% (= do nothing) | 0% | 652k | $0.027 |
| A2 Jev + history | 2.61% | 0% | 661k | $0.028 |
| B gpt-6-luna | 0.00% | 90% | 124k | $0.003 |

**Cost finding:** even a perfect Jev run on this task (fake Jev following the oracle: ~56k tokens, ~$0.0024) costs about the same as the LLM run, because the LLM's repeated input is cached at $0.01 per million. Jev uses fewer tokens, but not fewer dollars.

**Run C – Jev, Part 1 input (full history with full results, no snapshot; `--jev-state history`), same new menus:** did task steps 1–10 in order (same as gpt-6-luna), then looped: spray ridges 44–53 → tank empty → refill → spray 44–53 again, never ridges 54–55. Yield loss −1.12% (repeated spraying of 44–53 beat the oracle), coverage 80%. 1.95M tokens (max 19k per request), about $0.082 — above my estimate of $0.03, because full history grows each step.
- **So the snapshot input caused the first loop.** Jev tracks progress through the task from full action results. Likely cause to test: the snapshot cuts each recent result to 300 characters, so a "read ridges" result looks incomplete.

Spent so far in Part 2: about $0.14.

**Run D – snapshot input with the last 5 results in full (not cut to 300 characters):** the same loop as A (60 × "read ridges 44–55"); confidence 0.46–0.86. 2.23M tokens, about $0.094 — above my estimate of $0.06 (full ridge results made requests ~12k tokens, not 7k).
- Cutting the results was not the cause. In C and D the first choice already differs: with the snapshot, Jev skips the weather/soil steps and starts at "read ridges 44–55", then repeats it; with the full history it follows the steps in order.

Spent so far in Part 2: about $0.23.

**Single-question tests** (frozen states from the runs, input variants, 2 repeats each; $0.007 in all; `validation_runs/jev_l3/probe/`):
1. After the first ridge read in D: with weather and soil readings in the snapshot, Jev re-read ridges 44–55 (0.48–0.91); without them, or without the snapshot, it went back to step 1 "weather" (0.98–0.99).
2. After the ridge read in E (weather/soil removed): the action "read ridge state" was right (task step 4 = reference ridges 24–35), but the **ridge question** picked 44 again (0.69–0.94), with any input — also Part 1's. Adding "earlier calls of this action in this run: (start=44, end=55). Choose the value for the next step of the task that is not done yet." to the question → ridge 24 (0.86, both repeats).

**Decisions:**

| Choice | Why |
|---|---|
| No weather, forecast or sensor readings in the snapshot | Test 1; Jev takes them with its own actions, like the LLM agent (also fairer) |
| Each value question lists this action's earlier calls in the run (last 5) and asks for the value of the next undone task step | Test 2 |
| Recent results cut at 1,500 characters (not 300, not full) | Cutting was not the cause (run D); full results cost 3× |
| `--jev-state history` kept as an option (Part 1 input, for comparison only) | Used in run C |

**Run E – weather/soil removed:** steps 1–3 right, then 57 × "read ridges 44–55" (the ridge question, test 2). $0.040.
**Run E2 – plus earlier calls in value questions:** the whole task in order, 11 actions in 9 s (gpt-6-luna: 12; Jev skipped "check inventory"). 102k tokens, $0.004 (gpt-6-luna $0.003).

| Run | Yield loss | Coverage | Actions | Cost |
|---|---|---|---|---|
| B gpt-6-luna | 0.00% | 90% | 12 | $0.003 |
| E2 Jev (current) | 0.00% | 80% | 11 | $0.004 |

Spent so far in Part 2: about $0.28.

## Step 6 – Dev set: Jev only vs gpt-6-luna (2026-10-21)

One run each, 60 actions / 10 min, English tasks, `PYTHONHASHSEED=0`. Yield loss = biological (recovered for harvest tasks).

| Scenario | Jev yield loss | LLM yield loss | Jev coverage | LLM coverage | Jev cost | LLM cost |
|---|---|---|---|---|---|---|
| L1 herbicide (E2) | 0.00% | 0.00% | 80% | 90% | $0.004 | $0.003 |
| L1 harvest + store | 0.00% | 0.00% | 100% | 100% | $0.011 | $0.010 |
| L1 planting | **82.2%** | 0.00% | 76% | 96% | $0.034 | $0.004 |
| L2 harvest drydown (waits) | 18.7% | 62.5% | 76% | 48% | $0.024 | $0.014 |
| L2 replant (waits) | 0.85% | −0.15% | 47% | 71% | $0.030 | $0.006 |

**What went wrong for Jev:**
- **Report spam** (planting, replant): after a few steps Jev sends the report, then alternates one useful step with up to 5 reports, until the action limit. The code-written report changes slightly each time (timestamp), so the repeat trigger does not fire.
- **Value not on the menu** (replant): spacing 7.9 cm is not in that task's text, so Jev replanted with 15 cm, and only ridges 0–3.
- **Repeated "load seeds" when the hopper is already full** (replant), between reports.
- **Both agents ran out of actions** on L2 harvest drydown (oracle: 50 actions; both waited 1 day at a time and re-checked each day). Jev got further (ridges 0–51 vs 0–23).
- **Waiting worked:** Jev used "until <effect> is ready" (3,598 s for robot charging) and day steps.

**Cost:** Jev cost more than gpt-6-luna in dollars on all 5 ($0.103 vs $0.037), although it used fewer tokens on 3. The LLM's input is ~97% cached ($0.01 per million); Jev's is not. 58–78% of each Jev request is the state, sent again with every question (2–3 per action).

Spent so far in Part 2: about $0.42.

## Step 7 – Hybrid on the dev set (2026-10-21)

**Fix first:** the report is not offered again straight after a report. **Limit:** L2 raised to 100 actions for both agents (oracle needs 50; both agents check daily while waiting).

Hybrid = Jev + gpt-6-luna fallback at confidence 0.6. One run each.

| Scenario | Hybrid yield loss | LLM yield loss | Hybrid coverage | LLM coverage | LLM share of hybrid decisions | Hybrid cost | LLM cost |
|---|---|---|---|---|---|---|---|
| L1 herbicide | 0.00% | 0.00% | 100% | 90% | 3 / 12 | $0.007 | $0.003 |
| L1 harvest + store | 0.00% | 0.00% | 100% | 100% | 4 / 37 | $0.011 | $0.010 |
| L1 planting | −2.8% | 0.00% | 92% | 96% | 26 / 50 | $0.034 | $0.004 |
| L2 harvest drydown | 4.7% | 0.00% (100 actions) | 92% | 92% | 55 / 97 | $0.058 | $0.012 |
| L2 replant | 0.60% | −0.15% | 59% | 71% | 89 / 99 (hit limit) | $0.103 | $0.006 |

- The hybrid fixes Jev's failures on the L1s (planting from 82% loss to −2.8%).
- On the L2s Jev's confidence is mostly below 0.6, so the LLM takes 57–90% of decisions.
- Cost: hybrid $0.21 vs LLM-only $0.035 on the 5 tasks. Fallback calls are only partly cached (~60%), and Jev requests are never cached.

Spent so far in Part 2: about $0.66.

## Step 8 – Threshold 0.4 on L2, first L3 run (2026-10-21)

**Hybrid at threshold 0.4 (L2, 100 actions):**

| Scenario | Yield loss 0.6 → 0.4 | LLM decisions 0.6 → 0.4 | Cost 0.6 → 0.4 |
|---|---|---|---|
| L2 harvest drydown | 4.7% → 0.00% | 55 → 4 | $0.058 → $0.028 |
| L2 replant | 0.60% → 1.69% | 89 → 25 | $0.103 → $0.028 |

**Decision:** threshold 0.4 from now on (much cheaper, yield loss similar).

**L3-mini hn58 (300 actions / 60 min):**
- **gpt-6-luna:** stopped after 2 actions. It read the overview, saw "all ridges unplanted, phase full_season", judged the setup invalid and sent a report saying it cannot do the season. Yield loss 100%. Cost ~$0.01.
- **Hybrid (0.4):** planted the whole field, then used up the 300 actions by 29 May (25 days into the season). Biological yield loss 1.8% (FAIRY extrapolates the crop to maturity), recovered 100% (no harvest). Cost $0.37 (Jev $0.20, LLM $0.17), 15 min.
  - 255 of 300 decisions went to the LLM; **the LLM fallback wasted the actions**: 140 farm-overview reads, 51 soil reads, 22 ridge reads. Jev's own decisions were plantings (17) and day advances (17).

Spent so far in Part 2: about $1.1.

## Step 9 – L3 reruns (2026-10-21)

**Change:** the fallback prompt says the snapshot already shows crop, inventory and machines; read tools only for values it does not show.

**Hybrid (0.4), hn58:** overview reads dropped (140 → 5), but the fallback now re-reads sensors (115 soil, 88 canopy reads). The season got to 29 July (before: 29 May) when the 300 actions ran out; no harvest. 264 of ~300 decisions by the LLM; Jev's own: plantings and charging. Biological yield loss 1.8%, recovered 100%. $0.41, 26 min.

**gpt-6-luna, hn58 (second run):** prepared the field and planted all 64 ridges (38 actions), then stopped on 5 May: "R5/R6, maturity, grain moisture and harvest conditions have not occurred… I cannot truthfully…". It never advanced time. Biological yield loss 1.8%, recovered 100%. ~$0.03.

**Finding:** neither agent completes an L3 season yet. gpt-6-luna (reasoning off) stops instead of advancing the clock; the hybrid advances but its LLM fallback, which has no memory between calls, spends the action budget re-reading.

Spent so far in Part 2: about $1.6.

## Step 10 – gpt-6-luna with reasoning on (Responses API) (2026-10-22)

**Built:** OpenAI's Responses API route in `fairy/agents/llm/openai_llm.py`, chosen by the new `--reasoning-effort` option. For gpt-6-luna any value other than "none" uses `/v1/responses`; without the option every model runs as before. Replies are turned into the same object as on the chat route, so the agents are unchanged. 3 free tests in `tests/test_openai_responses.py`.

**Decisions:**

| Choice | Why |
|---|---|
| Reasoning "medium" | OpenAI's default; accepted values are none, minimal, low, medium, high, xhigh, max |
| Same agent (`farm_baseline_react`), tools, English task and action/time limits; only the model setting changes | Your rule |
| Output limit per call 8,192 tokens (was 2,048) | Reasoning tokens count toward it; a cut reply would be retried |
| Stateless calls; reasoning text not sent back in later calls | Same as FAIRY's chat route ("exclude" policy) |
| Hybrid fallback stays on reasoning "none" | Not asked to change; item 2 changes only its memory |

**Runs (one each):**

| Scenario | Yield loss (crop / recovered) | Coverage | Actions | Tokens (cached) | Cost | Reasoning off |
|---|---|---|---|---|---|---|
| L1 herbicide | 0.0% / – | 90% | 13, finished | 125k (89%) | $0.003 | 0.0%, $0.003 |
| L2 harvest drydown | 0.0% / 12.5% | 80% | 100, hit limit | 11.0M (98%) | $0.13 | 0.0%, $0.012 |
| **L3 hn58** | **1.7% / 4.2%** | 76% | 134, finished | 6.2M (99%) | **$0.07** | stopped after planting, 100% recovered loss |

- **L3 completed the season:** planted 5 May, waited in large steps (14, 35, 40, 35 days), irrigated once, harvested all 64 ridges, dried and stored 8,022 kg (oracle 8,374 kg). 5.5 min. 1,337 reasoning tokens in total (it thinks briefly).
- **L2 cost 10× more than reasoning off:** while waiting it advanced one day at a time and re-read all 64 ridges every day (~6k tokens per read), and ran out of actions with 8 ridges unharvested.

Spent in this step: about $0.20. Part 2 total: about $1.8.

## Step 11 – Fallback LLM with memory (2026-10-22)

**Built** (`fairy/agents/jev/jev_agent.py`): the fallback LLM now keeps one conversation per run: fixed rules and task first, then for each earlier fallback call the request it saw, its own tool call and the result (with time), then "Jev's actions since your last decision" (time + result cut at 300 characters) and the current state. Instruction added: Jev takes the other steps; do not repeat a read whose result above is still current. Test added (11 Jev tests pass).

**Caching test (direct API calls, ~$0.01):** gpt-6-luna only caches a request that begins with a whole earlier request (repeat: 5,179 of 5,182 tokens cached; earlier request + new messages: 4,996 cached). A request that shares only part of an earlier one gets nothing cached, even when the shared part is 4,000+ tokens. My first version shortened old turns, so only the fixed start was cached.

**Decisions:**

| Choice | Why |
|---|---|
| Append-only history: each request = the previous request + the LLM's call, its result, and the new turn | Caching test above |
| Window of 20 earlier turns, cut back to 10 when full | Cache restarts once every 10 calls; a bigger window costs more per call |
| The fallback state leaves out "last 5 actions with results" | Its own results and "actions since" already cover them |
| Hybrid settings as before: threshold 0.4, gpt-6-luna reasoning "none" | Only the memory changes |

**L2 debug runs (hybrid, 0.4):**

| Scenario | Yield loss before → now | LLM decisions before → now | LLM input cached | Cost before → now |
|---|---|---|---|---|
| L2 replant | 1.7% → 0.65% | 25/42 → 3/14 | 82% | $0.028 → $0.006 |
| L2 harvest drydown | recovered 0.0% → 4.7% | 4/71 → 12/77 | 90% | $0.028 → $0.033 |

Drydown: Jev chose to start the harvest about a day earlier than in the old run; not an LLM decision.

**L3 hn58, one run:**

| | gpt-6-luna reasoning on (Step 10) | Hybrid before (Step 9) | Hybrid with memory |
|---|---|---|---|
| Season | finished | ran out of actions on 29 July | **finished** (30 Sept) |
| Yield loss crop / recovered | 1.7% / 4.2% | 1.8% / 100% | 1.8% / **6.3%** (7,847 kg stored) |
| Coverage | 76% | – | 72% |
| Actions | 134 | 300 | 189 |
| Decisions Jev / LLM | – | 36 / 264 | **94 / 96** (49% / 51%) |
| Tokens | 6.2M (99% cached) | Jev 6.1M + LLM 2.8M | Jev 2.7M + LLM 4.4M (89% cached) |
| Cost | **$0.07** | $0.41 | $0.20 (Jev $0.11, LLM $0.09) |
| Time | 5.5 min | 26 min | 5 min |

**Why Jev's confidence is low on L3 (the 96 hand-offs):**
- 77 of 96 were on "which action", not on a value. Jev's top choice had only 0.2–0.4; the rest was spread over 2–3 other reasonable actions.
- **Mid-season is almost all LLM:** June–August 53 of 62 decisions. The task says "check growth, nutrition, pests, disease; at R5/R6 decide on water" with no fixed order, so several actions are equally good (inspect, fly survey, read sensors, wait). Planting (May: 15 of 54) and harvest (Sept: 28 of 74) are step by step and mostly Jev.
- **Machine upkeep:** robot/drone battery steps compete (check status / charge / wait 65 min), e.g. 1 June 05:33: four hand-offs in a row.
- **Two drones with the same action:** "fly_survey" appears twice (Mavic3M, Matrice4T); in 12 hand-offs Jev split its probability between the two (e.g. 0.26 vs 0.24).
- **Wait length:** 7 hand-offs on how long to wait, spread over 1/7/10/14 days (e.g. 0.18 / 0.15 / 0.13 / 0.13); the task gives no number.
- **Harvest window:** in September Jev's top pick was "harvest" (0.2–0.4) while weather check and waiting scored close; the LLM checked weather and waited a day.
- The LLM chose the same action as Jev in 31 of 96 hand-offs.

Spent in this step: about $0.25. Part 2 total: about $2.05.
