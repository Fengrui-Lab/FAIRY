# A2A with Jev: decisions and results log

Branch `jev-a2a-wip`. Status: working, tested on 3 scenarios, no full run yet.

## What was built

**Global LLM with local Jev experts.** gpt-6-luna is the manager. Every field app (farm, weather, sensors, 2 drones, robot, tractor, field ops) is hidden behind `<App>__expert_agent(task)`. The clock and the message to the user stay with the LLM.

One job: the LLM writes it in plain text; that app's Jev expert picks actions and arguments from menus over that app's tools until it says "done". Code writes the reply: status, each action with its result.

Run it: setting `a2a_llm_manager_jev_experts` in `scripts/jev_run_l3mini.py`. Code: `fairy/agents/jev/a2a_expert.py`, `SharedTraceAppAgent` in `fairy/controllers/app_agent.py`. Off by default; turned on by `--a2a true --a2a-provider typesafe`.

## Decisions

| Decision | Why |
|---|---|
| Global LLM + local Jev, not global Jev + local LLMs | Handing out work needs written text and only the LLM writes. Numbers in the job text become Jev's menu options, so the LLM can steer Jev. Global Jev would only route, and could not say what to do. |
| No optional path: the LLM cannot touch field tools directly | In 38 earlier runs the LLM never called Jev when Jev was optional. |
| Expert's real actions go in the main workflow (`SharedTraceAppAgent`) | Scoring replays the workflow. Plain A2A drops the expert's actions, so its runs cannot be replayed or scored. |
| Unsure or stuck Jev ends the job and reports to the LLM | No LLM inside an expert. Threshold 0.4, same as the hybrid. The LLM rewrites or splits the job. |
| Reply says what Jev wanted and what it was least sure of | So the LLM can rewrite the job usefully. |
| "done" not offered before the first action of a job | In the first run 80 of 231 jobs did nothing because Jev said "done" at once. |
| A ridge range in the job limits the ridge menus | Jev picked ridges 3-5 when told exactly 0-3, and planted 46-63 when told 42-45. |
| At most 10 actions per job | Bounds a confused expert. The LLM can send another job. |
| Each real farm action counts toward the 300; a delegation that acts does not add one; a job with no action counts 1 | Same limit as other settings, in real actions. |
| Expert sees the job and the farm snapshot, not the season task | The manager decides; shorter Jev input. Numbers in the season task are still menu options. |
| All field apps wrapped (`--a2a-app-prop 1.0`) | Simplest and cleanest to explain. |
| Same 300 actions, 3600 s, seed 0, done check on the main agent | Comparable with the earlier L3-mini settings. |

The comparison setting `a2a_llm_manager_llm_experts` is FAIRY's existing A2A with app-prop 1.0, typed experts, done check, plus two changes: the shared trace (else it cannot be scored) and `reasoning_effort` passed to the experts. It does not get the manager note or the tool list.

## Changes outside the new code

- `snapshot.py`: reads through A2A wrappers; delegation calls are not listed as farm actions.
- `engine.py`: `outcome_summary` reads through wrappers (it returned nothing when the farm app was wrapped).
- `rebatch_fos_from_traces.py`: for shared-trace runs only, skips delegation and final-answer steps. Plain A2A runs still fail replay on purpose rather than scoring as "did nothing".
- `jev_agent.py`: small hooks, no change in behaviour for `farm_jev`.

## Test results

See the table in the message / `../jev_a2a_runs/`. Fill in after the full run.
