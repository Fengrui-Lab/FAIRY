# Recap: a Jev-based farm agent in FAIRY, compared with an LLM agent

## In short

I added a new kind of agent to the FAIRY farm simulator. Its decisions are made by **Jev**, a "decision model" from TypeSafe, instead of a language model. I compared it with FAIRY's normal language-model agent (gpt-4o-mini) on 15 small farm tasks, 3 runs each, with the same tasks and limits.

On average the language-model agent matched the reference solution more closely: 53.5 vs 47.1 out of 100. Jev scored higher on 6 of the 15 tasks and lower on 9. Both cost about two cents per run.

## Background

- **FAIRY** simulates a soybean farm. Each **scenario** is one task, for example "prepare the field" or "harvest". An agent completes it by calling actions such as "check the weather" or "attach the grader". Each scenario also contains a **reference solution** (the "oracle"): the list of actions an expert would take.
- **The language-model agent** (already in FAIRY) reads the task and writes each action and its values itself, for example "load 200 kg of fertilizer".
- **Jev** does not write text. You give it a description of the situation and a question with a list of options. It returns the option it picks, a probability for every option, and a confidence (0–1).

## What I built

The Jev agent works in a loop until Jev says "done" or the action limit is reached:

1. Describe the situation to Jev: the task, plus every action taken so far with its result. Jev has no memory, so the history must be included each time.
2. Ask Jev which action comes next. The options are the scenario's 63 actions plus "done".
3. If that action needs values, ask Jev to pick each value from a list of options.
4. Run the action in the simulator exactly as for the language-model agent, and repeat.

Every choice is recorded: the options, the pick, all probabilities, the confidence, the time taken and the cost. Results are saved in the same files FAIRY already produces, so FAIRY's existing scoring works unchanged.

## Design choices and why

| Choice | Why |
|---|---|
| Jev picks the action first, then each value in separate questions | A single list of every action-and-value combination would be far too long (Jev accepts at most 255 options per question). |
| Value options come only from the simulator's code and the farm: every ridge of the field, named items (tools, seed types, sensors), every number written in the task text, and 10 evenly spaced amounts where the code sets a maximum | Using the reference solution would give Jev the answers. With this rule, wrong values are always among the options. |
| Impossible combinations (for example "end ridge before start ridge") are not blocked | The action simply fails and is recorded, the same as when the language-model agent makes a mistake. |
| The end ridge is chosen after the start ridge, in a second question that tells Jev the start ridge | Questions asked together cannot see each other's answers. Without this, Jev often asked for impossible ranges. This was changed after a first test round. |
| Both agents get the same English task text | The original tasks are in Chinese. Jev's documentation says it works best in English. I translated all 15, and they were checked side by side with the originals. |
| Same limits for both: 60 actions and 10 minutes per run | The longest reference solution needs 35 actions, so 60 leaves room for mistakes. |
| Confidence of one action = the lowest confidence among its questions | One wrong value spoils the whole action. This follows TypeSafe's own example. |

## How results were measured

FAIRY compares each agent's list of actions with the reference solution, counting an action as matching only if both the action and its values are the same:

- **Step match** (0–100): how close the two lists are. 100 means identical. This is the main score.
- **Coverage** (0–100): share of the reference actions the agent also did.
- **Order** (0–100): whether the shared actions came in the same order.

FAIRY's built-in headline scores turned out to be empty or always the same for these 15 scenarios, so I used these three instead. I checked that they give sensible numbers before running anything.

## Results (3 runs per agent per task)

| | Language-model agent | Jev agent |
|---|---|---|
| Step match (average) | **53.5** | 47.1 |
| Tasks where it scored higher | 9 | 6 |
| Coverage of reference actions | 84.6 | 68.9 |
| Actions per run | 27 | 40 |
| Runs stopped by the 60-action limit | 4 of 45 | 16 of 45 |
| Cost per run | $0.023 | $0.022 |
| Time per run | 24 s | 24 s |

- **Jev scored higher** on prepare the field (100 vs 53), harvest (90 vs 44), prepare and plant (88 vs 65), planting (80 vs 72), fertilizing (78 vs 46) and pest control (73 vs 56). On these 6 it was also cheaper: $0.016 vs $0.022 per run.
- **The language-model agent scored higher** on the other 9. Eight of those 9 include a waiting step (charging a drone, or waiting for a message from the system). None of the 6 that Jev won do.
- **Getting stuck:** Jev repeated the same action 3 or more times in a row in 27 of its 45 runs; the language-model agent did so in 3 of 45.
- **Confidence as a warning sign:** Jev's average confidence was 0.54 in the runs where it got stuck and 0.81 in the others.
- **Consistency:** Jev's 3 runs on the same task were usually closer to each other than the language-model agent's.

## Why Jev gets stuck

- **Partly our design.** The tasks give waiting times in minutes and hours, but the simulator counts in seconds. Jev's options only contain numbers written in the task, so the right waiting time (for example 7200 seconds) was never on its list. Each short wait ended with nothing happening, and Jev waited again. The language-model agent converts the units itself.
- **Partly Jev.** In the drone task the right option (move the clock forward while the drone charges) was available, but Jev kept checking the drone instead.
- **Unknown.** It is not known why seeing its own repeated actions does not make Jev change course; it gives no explanation for its choices.

## What this does and does not show

- It shows what using Jev as a farm agent looks like in practice: where it works, where it breaks, and that its confidence tracks how well it is doing.
- One language model and one Jev version were tested, with 3 runs each.
- Jev's results depend on how its option lists are built. One change was made after seeing first results: with the earlier version, Jev's average was 30.0.
- The scores measure closeness to the reference solution, not how well the farm ends up.
- The tasks were translated from Chinese. Only the language-model agent also received FAIRY's standard instructions.

## Open items

- **ARE results:** an empty column is ready in the results table for the logs still to come.
- **Optional extra experiment:** convert the task's minutes and hours into seconds for Jev's waiting options, and report it separately from the main result.

## Where to find everything

| What | Where |
|---|---|
| This recap | `docs/jev/recap.md` |
| Step-by-step log of the work | `docs/jev/PROGRESS.md` |
| Detailed results summary | `docs/jev/results/summary.md` |
| Full results table (with empty ARE columns) | `docs/jev/results/comparison.csv` |
| English task texts and side-by-side review | `docs/jev/tasks_en/` |
| Jev agent code | `fairy/agents/jev/` |
| Code repository | github.com/Synkrasis-Labs/fairy-jev, branch `jev-agent` |

Total cost of all experiments: about $2.40.
