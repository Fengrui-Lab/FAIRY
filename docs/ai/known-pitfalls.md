## Migrated Scenario Class Defaults

- ARE FARM scenarios often define runtime configuration such as `start_time`,
  `duration`, `queue_based_loop`, and `time_increment_in_seconds` as class
  attributes on `Scenario` subclasses.
- FAIRY's `Scenario` base is a dataclass, so inherited field defaults can
  shadow those class attributes on new instances. If `start_time` falls back to
  `None`, `Engine` starts at Unix timestamp `0` and full-season weather/physics
  logs drift to 1970.
- `Scenario.__post_init__` now copies subclass class attributes onto the
  instance only when the instance still equals the base dataclass default.
  Explicit constructor values still win.

## Captured Event Graph Completeness

- ARE event graphs maintain both `dependencies` and `successors`; FAIRY's
  lightweight `CapturedEvent` must do the same. Without `successors`,
  full-season v2 helpers that call `collect_event_graph(briefing)` only return
  the root briefing node.
- Some scenarios mark briefing messages as dependencies but do not call
  `.oracle()` on them. FAIRY should include these dependency-closure nodes in
  oracle workflow JSON so `depends_on` references point to real workflow nodes.
- Some helper builders, especially `harvest_range()`, return only the final
  node while hiding internal harvest/unload nodes behind `dependencies`.
  `Engine._oracle_event_dependency_closure()` must return the actual
  dependency objects in dependency-first order, not filter back down to only
  `scenario.events`. Filtering back caused selected L2/L1 harvest baselines to
  execute `store_grain` without executing the harvest passes.

## Oracle Baseline Tool Errors

- Some migrated oracle flows intentionally trigger tool-error returns as part
  of the correct management plan. Example: the planting action-tick scenario
  attempts a pass when the seed hopper is short, then reloads and retries.
- `scripts/build_oracle_baselines.py` should preserve these returned errors in
  baseline metadata (`tool_errors`) but must not fail the whole baseline build
  solely because a workflow step returned `{"error": ...}`.
- Treat true fatal failures separately: missing FarmWorldApp, inactive physics
  after oracle run, scenario not in registry, or Python exceptions during
  scenario construction/execution.

## A2A Expert Loop Diagnostics

- A2A app wrappers hide direct app tools from the main agent and expose
  `<AppName>Expert__expert_agent`; main-run workflows then show the delegation
  call, while real app-tool details live in `<scenario>.a2a_traces.json`.
- Always inspect `run_report.a2a.expert_metrics` when comparing A2A on/off.
  Main-agent token usage can drop while expert-agent token usage rises sharply.
- In the 2026-07-01 controller/A2A smoke audit,
  `farm_multi_specialist + scenario_farm_world_drone_survey + A2A on` failed
  because the main agent delegated a broad full-field survey to
  `Mavic3MExpert__expert_agent`; the drone expert looped until its
  `max_tool_calls=70` limit instead of completing bounded `fly_survey` calls.
  Treat this as an A2A task-decomposition/expert-prompt issue, not an API
  parse failure.

## Paper-Controller Smoke Gaps

- `farm_rewoo_modular` currently falls back when it cannot parse structured
  steps from the task. The smoke audit recorded planner calls and parse
  failures, but the controller context was the fallback path rather than a
  successful plan-work-solve plan.

## Workflow Output Paths

- `Workflow.save_workflow()` creates parent directories before writing. README
  quickstart commands intentionally point `--workflow` at fresh directories; do
  not reintroduce call sites that require users to run `mkdir` first.
