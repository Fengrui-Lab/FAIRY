# Results summary: Jev vs LLM agent on 15 small farm scenarios

Facts only. The full numbers are in `comparison.csv` (same folder), which also has empty `are_*` columns for the ARE results.

## How to read this

- **Scenario**: one farm task in the FAIRY simulator, for example "prepare the field" or "harvest".
- **Oracle**: the reference solution written into each scenario. Scores compare an agent's actions with it.
- **Step match** (0–100): how close the agent's list of actions is to the oracle's. 100 means identical.
- **Coverage** (0–100): share of the oracle's actions the agent also did.
- **Order** (0–100): whether the actions both did came in the same order. It counts only those shared actions.
- **Confidence** (0–1): how sure Jev said it was about each choice. The LLM gives no such number.
- All numbers are the mean of 3 runs per agent per scenario.

## What was compared

| | LLM agent | Jev agent |
|---|---|---|
| Decision maker | gpt-4o-mini (OpenAI) | jev-latest = jev-1.13.0 (TypeSafe) |
| How it chooses an action | Writes the action and its values itself | Picks the action, then each value, from lists of options |
| What it is told | English task text + FAIRY's standard instructions | Same English task text, no extra instructions |
| Limits per run | 60 actions, 600 seconds | Same |
| Runs | 3 per scenario, 45 in total | Same |

Jev's options come only from the simulator's code and the farm's state. The oracle was not used to build them.

## Results

| Scenario | Oracle actions | LLM step match | Jev step match | LLM actions | Jev actions | LLM cost per run | Jev cost per run | Jev confidence |
|---|---|---|---|---|---|---|---|---|
| drone_survey | 9 | 36.7 | 5.0 | 35.3 | 60.0 | $0.053 | $0.018 | 0.58 |
| drone_survey_plus | 12 | 27.8 | 7.0 | 44.3 | 60.0 | $0.029 | $0.022 | 0.42 |
| fertilizer | 9 | 45.8 | 77.8 | 18.7 | 9.0 | $0.019 | $0.002 | 0.84 |
| field_prep | 13 | 52.5 | 100.0 | 21.0 | 13.0 | $0.019 | $0.003 | 0.95 |
| field_prep_planting | 33 | 65.4 | 87.8 | 45.7 | 35.3 | $0.033 | $0.017 | 0.84 |
| field_prep_plus | 16 | 36.2 | 13.7 | 25.0 | 57.7 | $0.026 | $0.017 | 0.46 |
| harvest | 35 | 43.6 | 89.8 | 56.7 | 35.7 | $0.030 | $0.052 | 0.77 |
| irrigation | 6 | 83.3 | 8.2 | 6.0 | 49.3 | $0.007 | $0.021 | 0.53 |
| pesticide | 9 | 56.1 | 72.7 | 14.7 | 11.0 | $0.016 | $0.003 | 0.74 |
| pesticide_outbreak | 17 | 56.9 | 46.8 | 15.3 | 29.0 | $0.012 | $0.019 | 0.71 |
| pesticide_outbreak_plus | 27 | 43.2 | 13.8 | 19.3 | 55.3 | $0.017 | $0.017 | 0.54 |
| planting | 25 | 72.0 | 79.9 | 24.7 | 34.0 | $0.015 | $0.019 | 0.76 |
| planting_plus | 28 | 55.5 | 19.5 | 40.0 | 60.0 | $0.030 | $0.047 | 0.33 |
| survey_fertilizer_irrigation | 19 | 72.9 | 62.4 | 19.7 | 25.7 | $0.021 | $0.011 | 0.70 |
| survey_pesticide_irrigation | 19 | 54.4 | 22.2 | 19.0 | 60.0 | $0.012 | $0.057 | 0.58 |
| **Average** | 18.5 | **53.5** | **47.1** | 27.0 | 39.7 | $0.023 | $0.022 | 0.65 |

Other averages (LLM / Jev):

| Measure | LLM | Jev |
|---|---|---|
| Coverage | 84.6 | 68.9 |
| Order | 98.4 | 100 |
| Time per run | 23.6 s | 24.2 s |
| Runs stopped by the 60-action limit | 4 of 45 | 16 of 45 |

Which agent had the better mean, scenario by scenario:

| Measure | Jev better | LLM better | Equal |
|---|---|---|---|
| Step match | 6 | 9 | 0 |
| Coverage | 5 | 8 | 2 |
| Fewer actions | 5 | 10 | 0 |
| Lower cost | 8 | 7 | 0 |
| Shorter time | 6 | 9 | 0 |

### Cost, split by which agent scored higher

| Scenarios | Count | LLM step match | Jev step match | LLM cost per run | Jev cost per run |
|---|---|---|---|---|---|
| Jev higher (field_prep, field_prep_planting, fertilizer, harvest, pesticide, planting) | 6 | 55.9 | 84.7 | $0.022 | $0.016 |
| LLM higher (the other 9) | 9 | 51.9 | 22.1 | $0.023 | $0.025 |
| All | 15 | 53.5 | 47.1 | $0.023 | $0.022 |

Waiting steps: 8 of the 9 scenarios where the LLM scored higher include a waiting step in the oracle (charging a drone or waiting for a notification). None of the 6 scenarios where Jev scored higher do.

Cost uses public prices per million "tokens" (a token is roughly ¾ of a word): LLM $0.15 for text sent in and $0.60 for text sent back; Jev $0.042 for text sent in, nothing for answers.

## Runs where an agent got stuck

"Stuck" means doing the same action with the same values 3 or more times in a row. The oracle never repeats an identical action, even twice.

| | LLM | Jev |
|---|---|---|
| Stuck runs | 3 of 45 (all in drone_survey) | 27 of 45 |
| Jev confidence in stuck runs | – | 0.54 |
| Jev confidence in other runs | – | 0.81 |

In the 3 scenarios that had both stuck and normal Jev runs, the stuck runs had lower confidence: harvest 0.75 vs 0.78, pesticide_outbreak 0.67 vs 0.73, planting 0.71 vs 0.78.

### Why Jev gets stuck: what is known and what is not

> **Flag for readers:** part of the cause lies in how the options were built (our design), and part lies in Jev itself.

| Cause | Status | Evidence | Scenarios |
|---|---|---|---|
| The right waiting time is not among Jev's options. The task gives waits in minutes and hours; the tool counts in seconds. Jev's waiting options are only numbers from the task text (for example 0–10, 22, 30), while the oracle waits 1800, 7200 or 21600 seconds. So each wait ends with nothing happening, the situation looks the same, and Jev waits again. | **Known, from our design** | Option lists and oracle values in the run files | irrigation, field_prep_plus, planting_plus |
| A usable option was there, but Jev did not pick it. In drone_survey it kept checking the drone (about 0.5) instead of moving the clock forward while the drone charged (about 0.17). The farm clock moved only 6 minutes in 60 actions. | **Known, from Jev's choices** | Jev's recorded choices and the farm clock | drone_survey |
| Why seeing its own repeats does not make Jev change course. All earlier actions are in what Jev receives, yet it picks the same one again. | **Not known** | Jev gives no explanation for its choices. TypeSafe's own docs list related weak spots (counting, reasoning over several steps, units). | all stuck runs |

The LLM does not have the first problem, because it converts minutes to seconds itself.

## What the run logs show

The same check was done for both agents: run 1 of each agent's 5 lowest-scoring scenarios.

| | LLM (5 lowest) | Jev (5 lowest) |
|---|---|---|
| Longest run of the same action in a row | 2, 10, 7, 3, 16 | 54, 14, 20, 35, 7 |
| Actions that returned an error | 17/33, 44/60, 4/25, 0/18, 40/60 | 0/60, 4/60, 1/51, 0/53, 1/46 |
| Used an action the oracle does not use | 5 of 5 | 3 of 5 |
| Skipped an action the oracle uses | 5 of 5 | 4 of 5 |

- LLM's 5 lowest: drone_survey_plus, drone_survey, field_prep_plus, pesticide_outbreak_plus, harvest.
- Jev's 5 lowest: drone_survey, drone_survey_plus, irrigation, field_prep_plus, pesticide_outbreak_plus.
- Jev's confidence was 0.70 or higher in exactly the 8 scenarios where it scored highest. Across all 15, confidence and score rose and fell together.
- Jev's 3 runs per scenario were usually closer to each other than the LLM's.

## Things that affect the comparison

- One LLM (gpt-4o-mini) and one Jev version were tested.
- The original tasks are in Chinese. Both agents got the same English translation. Only the LLM also got FAIRY's standard instructions.
- Jev's results depend on how its option lists are built. One change was made during testing: the end ridge is now chosen after the start ridge. Before that change, Jev's average step match was 30.0 (1 run per scenario).
- These 15 scenarios have no built-in pass/fail check. The scores measure how close the actions are to the oracle, not how well the farm ends up.
- 3 runs per agent per scenario.
