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
  call, while real app-tool details live in `run_report.a2a` and
  `<scenario>.runtime_log.jsonl`.
- Runtime log JSONL uses `record_type`, not `event` or `event_type`, at the
  top level. Nested A2A expert traces inside `run_report.a2a.expert_traces`
  still contain the agent's in-memory `event_type` records.
- Always inspect `run_report.a2a.expert_metrics` when comparing A2A on/off.
  Main-agent token usage can drop while expert-agent token usage rises sharply.
- In the 2026-07-01 controller/A2A smoke audit,
  `farm_multi_specialist + scenario_farm_world_drone_survey + A2A on` failed
  because the main agent delegated a broad full-field survey to
  `Mavic3MExpert__expert_agent`; the drone expert looped until its
  `max_tool_calls=70` limit instead of completing bounded `fly_survey` calls.
  Treat this as an A2A task-decomposition/expert-prompt issue, not an API
  parse failure.
- In the 2026-07-02 L3 A2A smoke, the main agent's `--max-tool-calls=6` did
  not originally bound the child expert loop; `TractorApp` executed many expert
  turns. The CLI now forwards `--max-tool-calls` as the default child cap unless
  `--a2a-max-tool-calls` is set.

## LLM Runtime Observability

- `runtime_log.jsonl` is finalized only after a cell exits because it contains
  full per-turn contexts. During execution, use `<scenario>.progress.jsonl` or
  the batch runner heartbeat. The progress stream omits full `messages` to keep
  logging cost independent of context-window size and survives timeout/kill.
- The validation runner checkpoints `results.csv` after every completed cell.
  A killed batch therefore retains completed rows; do not regress to writing
  the CSV only after the whole matrix exits. Final runtime JSONL files are
  written through a temporary file and atomically renamed.
- `llm_call_end` should record both the exact assistant content returned by the
  provider and whether it is empty. Function-call responses can have empty
  content while still carrying valid tool calls; do not infer missing reasoning
  from a tool call alone.
- Long provider reads can block beyond the outer agent-loop wall-time limit.
  Use `FAIRY_LLM_REQUEST_TIMEOUT_S` or a client `timeout` config to bound a
  single OpenAI-compatible HTTP request so the failure is logged and retried or
  surfaced.
- Qwen served through vLLM can return `reasoning` with empty `content` unless
  the request passes `chat_template_kwargs.enable_thinking=false`. FAIRY's
  `VLLMClient` does this by default for model names containing `qwen`. Tool
  calling still requires the vLLM server itself to be started with both
  `--enable-auto-tool-choice` and `--tool-call-parser`; otherwise every request
  containing OpenAI `tools` fails before the agent loop can act.
- Agent-facing tool descriptions come directly from app method docstrings via
  `AppTool.to_open_ai()`. Removing a docstring makes the corresponding OpenAI
  tool `description` empty, which changes model-visible behavior even though
  the Python tool still executes.
- `--parallel-tool-calls` controls whether OpenAI-compatible providers may
  return multiple tool calls in one LLM turn. The default is `true` for backward
  compatibility; set it to `false` when an experiment requires strict
  observe-after-each-action behavior.
- Every real-agent LLM call has a completion cap. `fairy.cli` and
  `scripts/iclr_validation_runner.py` expose it as `--max-output-tokens`
  (alias `--max-tokens`), defaulting to `2048`; direct `BaseLLM` construction
  uses `FAIRY_LLM_MAX_OUTPUT_TOKENS` when no explicit value is supplied. The
  effective cap is recorded as `run_report.limits.max_output_tokens` and in
  runner `results.csv`. This cap prevents unbounded generation but does not
  interrupt a provider that stalls without producing tokens; request and cell
  timeouts remain separate controls.

## Paper-Controller Smoke Gaps

- `farm_rewoo_modular` currently falls back when it cannot parse structured
  steps from the task. The smoke audit recorded planner calls and parse
  failures, but the controller context was the fallback path rather than a
  successful plan-work-solve plan.
- Research family names represent lightweight context and telemetry strategies
  around one ReAct loop. Planner, verifier, critic, tree-search, and graph-memory
  profiles are not separate model processes or parallel execution engines.

## Retrieval Oracle Workflow Shape

- Path-similarity retrieval must use `workflow_from_oracle_events()` after
  scenario setup, not the executed `Engine.build_oracle_workflow()` export.
  The executed export contains formatted string timestamps, AUI nodes, and
  synthetic daily `advance_time` calls introduced by FAIRY's scheduler.
- Bind captured positional arguments against the tool function signature and
  apply defaults before scoring. Otherwise workflow arguments become `arg0`,
  `arg1`, and no longer match ARE's named-argument workflow representation.

## Workflow Output Paths

- `Workflow.save_workflow()` creates parent directories before writing. README
  quickstart commands intentionally point `--workflow` at fresh directories; do
  not reintroduce call sites that require users to run `mkdir` first.

## Rebatch Replay Time Contract

- Agent workflow `time` is the human-readable **post-tool** timestamp. Never
  align a fresh scenario to that value before invoking the recorded tool;
  doing so applies every simulated tool duration twice, most severely for
  `SystemApp__advance_time`.
- New agent traces also store exact epoch values in `time_before` and
  `time_after`. Rebatch must use those fields when present. For old traces it
  reconstructs `advance_time`'s pre-call timestamp as post time minus the
  requested duration, uses the previous post time for writes, and treats a
  read's timestamp as its observation time.
- Replay physics is monotonic. A requested timestamp earlier than
  `physics.last_physics_sim_time` is a divergence, not a clock adjustment.
- Rebatch validates mutating-tool success/error semantics and return values,
  then compares the complete final FARM inventory and yield summary with
  `run_report.outcome`. A mismatch must fail the cell; never emit FOS or yield
  metrics from a divergent state. A bundle without that outcome checkpoint is
  also unverified and must fail rather than produce metrics.
- Sensor observations are not byte-reproducible across Python processes
  because `App.set_seed()` currently derives RNG seeds with Python's salted
  `hash()`. Preserve the recorded read return in EventLog, count observation
  mismatches separately, and rely on strict writes plus the final outcome
  checkpoint for state-replay validity.
