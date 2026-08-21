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
- Legacy A2A run reports retain only each wrapper's last expert workflow. If a
  wrapper was delegated more than once, the earlier inner tool calls are absent
  even though the main workflow still contains every `expert_agent` call. Such
  an artifact cannot support exact state replay; do not treat the wrapper
  summary as if it were the missing tool sequence.
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
  observe-after-each-action behavior. In FARM runs, `false` also adds an explicit
  one-tool-per-turn instruction to the system message. Some providers, including
  DeepSeek, may ignore the request option and still return several calls.
  `BaseAgent` therefore enforces `false` after receipt: only the first call enters
  conversation state and executes, while `parallel_tool_call_violation` and
  `llm_call_end` retain raw/effective/dropped call details for audit.
- `--system-prompt-mode are` is an ARE-guidance A/B condition, not a protocol
  rollback. It preserves FAIRY native function calling and ports every
  compatible legacy ARE behavior rule: explicit pre-call reasoning, one-tool
  sequencing, system-provided observations, error recovery, tool economy, and
  using outputs for later decisions. Conflicting text-JSON `Action:`,
  `action_input`, `<end_action>`, example-format, and embedded-tool-catalog
  instructions stay excluded. The default `fairy` mode is unchanged. Both the
  per-run report and batch CSV record the selected mode.
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
- Replay timestamp alignment updates the apps' shared `TimeManager` only. It
  must not call `FarmWorldApp.advance_physics_time()` before every tool: normal
  FAIRY runs let the invoked tool decide when physics advances, and an eager
  replay tick commits pending actions too early and changes harvest/yield.
- Match ARE replay semantics: invoke every executable READ/WRITE tool in trace
  order to rebuild app and physics state, catch tool exceptions, and construct
  evaluation events with the return values recorded in the trace. A replayed
  random READ may return a different sample because FARM app seeds use Python's
  process-salted hash; that new sample must not replace what the agent observed.
- A reconstructed event's `event_time` is its pre-call time. The post-call time
  is used only to align the scenario before the next tool. Using post-call time
  on the event shifts FARM-FOS timing even when final physics state is correct.
- A recorded `TOOL_ERROR` for a missing app or method is a valid failed event
  with no state change. Restore it with its original app/method identity and
  error text; do not skip it and do not require the hallucinated method to exist.
  Conversely, a recorded successful call whose app/method is absent is a corrupt
  or incompatible trace and must fail replay.
- New `run_report.json` files persist `start_time`, `seed`, `scenario_kwargs`,
  and `init_kwargs`. Older batch traces recover constructor/setup kwargs from
  their neighboring `results.csv`. Rebatch must instantiate and set up the
  scenario through the same parameter path as the original CLI run.
