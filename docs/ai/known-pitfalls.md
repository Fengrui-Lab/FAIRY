## Deferred Single-Farm Calendar Issue

- [TIME-001](../known-issues.md): legacy single-farm weather/physics/System
  default to UTC while Engine/Agent display Beijing time. The four new
  multi-farm scenes explicitly use Asia/Shanghai. This remains deferred by
  user instruction on 2026-10-24; do not describe the calendar migration as
  covering all existing scenarios.

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

- Correction on 2026-10-18: the output-token default remains **2048**.
  A temporary, unrequested increase to 16384 was reverted. The shared
  `DEFAULT_MAX_OUTPUT_TOKENS=2048` feeds the direct client, CLI and validation
  runner. Explicit caps take precedence; historical configs have not been
  rewritten. An observed historical maximum is not authorization to change
  an experiment's generation budget.
  `agent_run_start` and `run_report` include the resolved `llm_config` and
  `response_policy`; `llm_call_start` also records the client configuration.
  These fields use an allowlist, not client `params` or credentials.
  Changing FAIRY does not impose this cap on the separate ARE runtime.
- VLLM thinking overrides are tri-state and constructor-only: omitted/blank
  means no override; recognized true/false values are parsed strictly;
  invalid values fail configuration instead of silently disabling thinking.
  The thinking environment-variable entry point was removed on 2026-10-18.
  An unset `enable_thinking_override` means the client sends no override;
  it does not establish the server's thinking mode. QwenClient retains its
  request behavior without adding a
  thinking parameter; the extra constructor rejection introduced during
  cleanup was removed. Excluding independent reasoning from prompts and
  logs does not require a thinking request parameter or a provider change.
- `tests/test_llm_runtime.py` covers exclusion of SDK reasoning from logs
  and subsequent requests, rejected-response
  retries and failed CLI reports with fake responses, including unchanged
  requests and billing of discarded attempts. These checks do not call a
  model or establish generation quality.
  Tests invoking workflow evaluation should change cwd to `tmp_path` because
  evaluation writes `workflow_exports/` relative to cwd; CLI tests also need
  that isolation because CLI cleanup removes its export directories.
- As of 2026-10-18, replies with `finish_reason=length`, or no nonblank
  content and no tool calls, are rejected and retried under the existing
  `FAIRY_AGENT_LLM_CALL_RETRIES` budget (default 5 retries, at most 6
  agent-level attempts). OpenAI-compatible SDKs may perform their own HTTP
  retries within an agent attempt; inspect `llm_config.sdk_max_retries`
  rather than treating agent attempts as HTTP request counts.
  A reply with empty content and valid tool calls is accepted unless it is
  marked truncated. Rejected replies never enter history or execute tools;
  their finish reason, content/tool details and usage remain in
  `llm_call_end` (`status=rejected`),
  and their token/runtime costs are included in metrics. Successful retries
  use the same messages/tools, token budget and thinking setting. Retry
  exhaustion fails with `output_truncated` or `empty_response`, rather than
  `agent_finished`. Retry loops check the run deadline before another
  request and cap retry sleep to remaining time; an already-running HTTP
  request still needs its own client request timeout.
  `llm_turn_count`/controller telemetry count accepted turns; runtime metrics
  count all completed response attempts, including rejected ones.
- As of 2026-10-18, independent `reasoning` / `reasoning_content` text is
  excluded from new logs. `llm_call_end` retains full `usage`, `finish_reason`
  and content/tool summaries, but no complete SDK response dump that could
  reintroduce reasoning. A2A message exports remove the two fields from a
  serialized copy, preserving in-memory messages. `rationale` remains a
  copy of content; content itself is not rewritten. Token counts (including
  reasoning-token counts when supplied in usage) remain numeric diagnostics.
  `_llm_compatible_messages` continues to exclude independent reasoning from
  subsequent requests. Existing historical logs are not rewritten.
  `llm_call_start.enable_thinking_override=null` means no client override;
  it does not prove whether the server enabled thinking.
- `management_regime.fertilizer_used_kg` is incremented when fertilizer
  is loaded from farm inventory, so it can differ from actual field use.
  For the 2026-10-17 false run, `load_fertilizer(2600)` loaded the 500 kg
  spreader capacity; `base_fertilize` applied 200 kg and 300 kg remained.
  Compare successful tool return values and equipment inventory before
  describing this field as field application or extra fertilization.
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
- As of 2026-10-17, `VLLMClient` leaves thinking to the server/template
  default; it no longer automatically sends `enable_thinking=false` for Qwen
  model names. Only an explicit `enable_thinking` constructor value adds
  `chat_template_kwargs.enable_thinking` to the request; environment variables
  do not control this setting. This changes model
  generation behavior; record the setting when comparing old and new runs.
  A short output budget can be exhausted in reasoning before content/tool
  calls appear; inspect `finish_reason` and token usage.
  Legacy runtime logs retain content/tool calls and four usage counters, but
  omit separate reasoning and finish_reason; `rationale` duplicates content.
  Tool calling still requires the vLLM server itself to be started with both
  `--enable-auto-tool-choice` and `--tool-call-parser`.
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

- For an exact live/replay terminal-state check, use
  `scripts/rebatch_fos_from_traces.py`; `Engine.replay_workflow()` (CLI
  `--replay --evaluate`) does not restore recorded pre/post timestamps.
  Start both processes with `PYTHONHASHSEED=0` as well as matching scenario
  seed, because app seeds use Python `hash()`. Capture replay outcome before
  FOS extrapolation; constructing a new Engine resets the scenario clock.
- A tool can return an `{"error": ...}` business rejection while the outer
  runtime status remains `ok`. Count these return values separately from
  exceptions. The 2026-10-17 single-scene run had 9 recovered rejections,
  `error_count=0`, and all 109 replay steps restored identical terminal state.
  Artifacts: `validation_runs/qwen36_thinking_default_single_scene_20261017/`.
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
