# Better hybrid: decisions and results

Branch `jev-better-hybrid`. Goal: a Jev + LLM hybrid better than the current one. All new behaviour is behind options, off by default; `--controller farm_jev` with no new flags is unchanged (test: `tests/test_jev_better_hybrid.py`).

## What the old logs showed (19 hybrid runs)

- Cost: Jev $1.11, LLM $1.26 (uncached input $0.69, cached input $0.55, output $0.02).
- LLM input was 42.5k tokens per call, 89% cached. LLM alone: 35k per call, 98.7% cached.
- Cause: every remembered turn held the full state (15-17k characters), up to 20 turns, and cutting old turns restarted the cache every 10 calls.
- Jev made only 28 of the 372 wait decisions. When unsure it mostly picked a check; the LLM moved the clock.
- Forcing Jev's tool does not work: REFLEX tried it and 11 of 19 runs ran out of actions.
- Fan-out questions are 25% of Jev's input, but removing them moves the same input into second requests. Left alone.
- The hybrid's LLM is not the same setup as LLM alone: Chat Completions with reasoning `none`, against Responses API with reasoning `medium`. Earlier reports do not say this.

## Options added

| Option | What it does |
|---|---|
| `--fallback-memory lean` | Each remembered turn keeps a short state: time, crop, pending effects, and inventory or machines only if changed. No step list. Append-only; cut at 80 turns to 40. |
| `--plan-note true` | On every hand-off the LLM also writes its expected next steps. Jev sees them as `plan_from_advisor` until the next hand-off, and is told to follow them unless the farm has changed. |
| `--budget-note true` | Jev and the LLM see actions used, left and a rough number needed for harvest, with a warning past half or when short. |
| `--fallback-reasoning-effort medium` | Same reasoning setting as LLM alone. |

## Decisions

- Plan note is a required tool argument, `next_steps`, removed before the tool runs. A test call showed the model writes no text next to a tool call.
- Lean memory must be append-only: in a test call, cache hits came only when a request extended a whole earlier one.
- The budget's harvest need is rough code arithmetic (ridges left / 4 x 3 actions). No oracle data.
- Prices as in the run README.
- Runs and scores are kept outside the repo, in `Synkrasis\jev_better_hybrid_runs`.

## Small test (2026-11-04)

4 scenarios, 1 run per setting: compacted headland, drought recovery, dryer capacity, soy after soy. These were chosen for being bad or expensive in the old runs, so they are not a fair sample.

| Setting | Finished | Grain loss | Cost, 4 runs | Min/run | Actions/run | Jev share |
|---|---|---|---|---|---|---|
| Old results (Oct 23) | 3/4 | 20.0% | $0.96 | not computed | 193 | not computed |
| Current hybrid, rerun today | 4/4 | 8.7% | $0.63 | 3.4 | 153 | 49% |
| Lean | 4/4 | 2.1% | $0.49 | 3.9 | 186 | 52% |
| Lean + plan | 4/4 | 3.7% | $0.44 | 3.3 | 187 | 65% |
| Lean + plan + budget | 4/4 | 4.5% | $0.30 | 2.5 | 139 | 64% |
| Lean + plan + budget + medium | 4/4 | 1.3% | $0.39 | 4.2 | 163 | 68% |
| LLM alone (Oct 23) | 4/4 | 6.3% | about $0.24 | not computed | not computed | - |

What this does and does not show:

- Cost is the firmest result: LLM cost per run fell to about a third (cache 97%).
- Jev's share rose from about 50% to about 65% with the plan note.
- When Jev is unsure the LLM still picks a different tool in about 60-75% of hand-offs. The hand-offs are fewer; the disagreement is not lower.
- The 300-action failure did not repeat, but it did not repeat for the unchanged hybrid either. It was bad luck, not something fixed here.
- The budget warning almost never fired (8 requests in one run, near harvest). Its drop in actions may be noise.
- Grain-loss differences on 4 single runs mean little. The same setting moved 61.5% to 1.9% on one scenario.
- Cost is still above LLM alone; Jev is now the larger share of the bill.
