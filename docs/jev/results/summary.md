# Jev vs LLM agent – 15 small farm scenarios

Data: `comparison.csv` (same folder). It has empty `are_*` columns for ARE results.

## What was compared

| | LLM agent | Jev agent |
|---|---|---|
| Decision maker | gpt-4o-mini (OpenAI), temperature 0.1 | jev-latest (= jev-1.13.0, TypeSafe) |
| How it acts | Writes its own tool calls and arguments | Picks the tool, then each argument, from fixed lists of options |
| Input | English task text + FAIRY system prompt | Same English task text, no system prompt |
| Limits | 60 actions, 600 s per run | Same |
| Runs | 3 per scenario (45 total) | Same |

Jev's argument options come only from the tool code and the farm state (all ridges, named items, numbers from the task text, evenly spaced values up to a maximum in the code). The reference solution (oracle) was not used to build them.

## How it was measured

All scores come from FAIRY's existing comparison with the oracle, matching tool **and** exact arguments:
- **Step match**: how close the agent's action sequence is to the oracle's (100 = identical).
- **Coverage**: share of the oracle's distinct actions the agent performed.
- **Order**: whether the shared actions come in the oracle's order. It counts only actions both did.
- **Cost**: LLM $0.15 / $0.60 per million input / output tokens; Jev $0.042 per million input tokens, output free.

## Results (mean of 3 runs)

| Scenario | Oracle actions | LLM step match | Jev step match | LLM actions | Jev actions | LLM cost/run | Jev cost/run | Jev confidence |
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
- coverage 84.6 / 68.9;
- order 98.4 / 100;
- time per run 23.6 s / 24.2 s;
- runs that hit the 60-action limit 4 / 16 (of 45).

### Cost, split by which agent had the higher step match

| Scenarios | Count | LLM step match | Jev step match | LLM cost/run | Jev cost/run |
|---|---|---|---|---|---|
| Jev higher (field_prep, field_prep_planting, fertilizer, harvest, pesticide, planting) | 6 | 55.9 | 84.7 | $0.022 | $0.016 |
| LLM higher (the other 9) | 9 | 51.9 | 22.1 | $0.023 | $0.025 |
| All | 15 | 53.5 | 47.1 | $0.023 | $0.022 |

### Jev's confidence in runs where it got stuck

"Stuck" = the same action with the same arguments 3 or more times in a row. The oracle never repeats an identical action even twice in these scenarios.

| | Runs | Jev average confidence |
|---|---|---|
| Stuck runs | 27 of 45 | 0.54 |
| Other runs | 18 of 45 | 0.81 |

- In the 3 scenarios that had both kinds of run, the stuck runs had lower confidence: harvest 0.75 vs 0.78, pesticide_outbreak 0.67 vs 0.73, planting 0.71 vs 0.78.
- The LLM had 3 stuck runs of 45 (all in drone_survey).
- Confidence here is the average over all of a run's actions, not only the repeated ones.

Per-scenario counts (which agent had the better mean):

| Measure | Jev better | LLM better | Equal |
|---|---|---|---|
| Step match | 6 | 9 | 0 |
| Coverage | 5 | 8 | 2 |
| Fewer actions | 5 | 10 | 0 |
| Lower cost | 8 | 7 | 0 |
| Shorter time | 6 | 9 | 0 |

## Observations from the run logs

Checked the same way for both agents: run 1 of each agent's 5 lowest-scoring scenarios.

| | LLM (5 lowest) | Jev (5 lowest) |
|---|---|---|
| Longest run of the same action in a row | 2, 10, 7, 3, 16 | 54, 14, 20, 35, 7 |
| Actions that returned an error | 17/33, 44/60, 4/25, 0/18, 40/60 | 0/60, 4/60, 1/51, 0/53, 1/46 |
| Used a tool the oracle does not use | 5 of 5 | 3 of 5 |
| Skipped a tool the oracle uses | 5 of 5 | 4 of 5 |

LLM's 5 lowest: drone_survey_plus, drone_survey, field_prep_plus, pesticide_outbreak_plus, harvest.
Jev's 5 lowest: drone_survey, drone_survey_plus, irrigation, field_prep_plus, pesticide_outbreak_plus.

- Jev's average confidence was 0.70 or higher in the 8 scenarios where its step match was highest. Across the 15 scenarios, confidence and step match moved together (correlation 0.9).
- The spread between Jev's 3 runs was usually smaller than the LLM's (see the min/max columns in the CSV).

## Setup facts that affect the comparison

- One LLM (gpt-4o-mini) and one Jev version were tested.
- The original task texts are in Chinese. Both agents received English translations; the LLM also received FAIRY's system prompt.
- Jev's results depend on how its options are built. One change was made during testing: the end ridge is asked after the start ridge. Before that change, Jev's average step match was 30.0 (1 run per scenario).
- These 15 scenarios have no built-in success check; the scores measure similarity to the oracle, not farm outcome.
- 3 runs per agent per scenario.
