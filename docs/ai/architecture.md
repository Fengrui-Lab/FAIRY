## Oracle Replay And Evaluation Loop

- FAIRY end-to-end scenario execution is:
  `Scenario.setup()` -> `Engine.build_oracle_workflow()` ->
  `Workflow.save_workflow()` -> fresh `Engine.replay_workflow()` ->
  `Engine.evaluation_report()`.
- `build_oracle_workflow(run_oracle=False)` records tool names and arguments
  without mutating scenario state through tool execution. For ARE-derived event
  graph scenarios, positional event arguments are recovered from the captured
  function signature so JSON replay has named `tool_args`.
- Captured ARE-style event graphs need both `dependencies` and `successors`.
  Some full-season v2 scenarios call `collect_event_graph(root)`, which walks
  `successors`; `CapturedEvent.depends_on()` must therefore append the current
  event to each dependency's `successors`.
- Oracle workflow construction writes the dependency closure of oracle events,
  not only events marked `.oracle()`. This preserves upstream briefing nodes
  such as `AgentUserInterface__send_message_to_agent` when later oracle steps
  depend on them.
- The dependency closure must return hidden helper-created dependencies too.
  For example, full-season split harvest helpers return the final store event,
  while the harvest/unload events exist only through `dependencies`; these
  must execute before the final node for recovered-yield baselines to match ARE.
- `replay_workflow()` builds tools from the fresh scenario apps and calls each
  `AppName__method` in workflow order. The replayed workflow stores actual tool
  results in `content`, preserving the original workflow JSON shape.
- `evaluate()` passes a lightweight `EngineEnvironment` to
  `scenario.validate(env)`. The environment exposes `scenario`, `workflow`,
  `apps`, `time_manager`, and `engine`.

## Rice Scenario Runtime And Offline Artifacts

- Rice uses the same event-graph execution protocol as full-season v2. Eight
  explicit L3 modules and twenty source-season-grouped L1/L2 modules register
  the existing 28 `scenario_rice_*` IDs. `rice_scenario_catalog.py` supplies
  `RiceScenarioSpec` and `get_spec()`; each entry uses the shared
  `rice_scenario.py` base and `rice_scenario_helpers.py` helpers.
- `init_rice_apps()` builds the paddy applications and restores any required
  `l2_l1_splits/rice_<variant>/checkpoints/<label>.json` checkpoint through
  `farm_checkpoint_state.py`. `build_rice_events()` turns fixed
  `oracle_plans/<scenario_id>.json` plans into `EventRegisterer`
  nodes, marked with `.oracle()` and linked with `.depends_on()`, for the
  scenario's `build_events_flow()` method. Neither `setup()` nor
  `build_oracle_workflow(run_oracle=False)` executes a full reference season.
- The former dynamically generated rice classes and runtime
  `oracle_solution()` reference-policy override are removed together with
  `rice/scenarios.py` and `rice/reference.py`. There is one runtime path,
  using the normal Engine capture, execute, replay and evaluation loop.
- `scripts/rice_reference_policy.py` holds the observation-driven policy;
  `scripts/build_rice_scenario_artifacts.py` explicitly runs it to generate
  28 fixed plans and 95 source-season checkpoints. Before publication,
  `verify_event_plans(staging, specs)` executes and independently replays all
  28 plans through registered scenarios and Engine, checking task acceptance
  and expected final hashes using the staged artifacts rather than previously
  published files. The generator replaces the `scenario_artifacts.json`
  SHA-256/PCSE manifest last. Plans also record the
  initial checkpoint hash, configuration fingerprint and
  `expected_final_state_sha256`. The default output is `fairy/scenarios/rice/`;
  `--output-dir` selects separate output. Missing files, invalid checksums,
  incompatible versions or checkpoint/configuration mismatches raise explicit
  rebuild errors. Runtime loading never regenerates artifacts or falls back
  to the reference policy.
  This separates expensive reference generation from scenario construction
  and makes source checkpoints and tool plans reviewable on disk.
- Packaged rice artifacts bind PCSE 6.0.13, which is pinned in `uv.lock`.
  The optional dependency still supports the 6.0.x series; using another
  version requires explicit artifact rebuilding in that environment.
- `rice/validation.py` owns target completion, tool-error counting, and
  water/nitrogen/resource/grain acceptance. `rice/evaluation.py` retains
  `rice_outcome` metrics and baseline compatibility checks. Complete harvest
  tasks still require every grain batch to be stored at at most 14% moisture,
  no grain left in machinery or reception, and matching harvested/stored dry
  mass; a resource-balanced partial result is not success.
- Event-protocol reuse does not merge crop physics. Soybean uses the ridge
  orchestrator and its legacy or WOFOST backend. `PaddyWorldApp` drives an
  independent `RiceWofostBackend` per hydraulic plot, with continuous water
  and nitrogen ledgers starting before transplanting. Rice outcome metrics
  remain outside the soybean FOS aggregate and do not establish a common
  cross-crop score.

## Run Observability Artifacts

- FAIRY experiment layout follows the FARM validation-run convention:
  `validation_runs/<phase>/phase5_paper_matrix/<cell>/`, where `cell` is
  `<agent_family>__<scenario_id>__r<repeat>`.
- Oracle baselines belong outside cells at
  `validation_runs/<phase>/oracle_baselines/<scenario_id>.json`; oracle replay
  diagnostics can live under
  `validation_runs/<phase>/oracle_replay/<scenario_id>/`.
- Every productized run cell should expose two human entry points:
  `*.run_report.json` and `*.runtime_log.jsonl`.
- `run_report.json` is the file to open first. It contains run type, scenario,
  controller/model, status, stop reason, limits, wall time, LLM/tool metrics,
  token totals, evaluation, outcome, error, artifact paths, and an
  `artifact_guide` explaining the remaining files.
- `runtime_log.jsonl` is the runtime log. Agent runs write records such as
  `agent_run_start/end`, `llm_call_start/end/error`,
  `tool_call_start/end/error`, `tool_args_parse_error`, and
  `agent_limit_exceeded`. Oracle replay writes `tool_replay` rows derived from
  the replay tool log.
- `agent_workflow.json` remains the replay/audit trace with FAIRY workflow
  shape. Prompt/messages, per-call token/time detail, tool results, errors,
  and limits are in `runtime_log.jsonl`; validation and farm outcome are in
  `run_report.json`.

## Research Controller Runtime

- FAIRY's paper-controller path is:
  `fairy.cli --agent` -> `BaseLLM.llm_builder()` ->
  `build_controller_agent()` -> `Engine.run_scenario_agent()` ->
  `Agent.run()`.
- `Agent.run()` is still the single function-calling loop. Controller families
  hook it through `before_llm_turn()`, `after_llm_message()`,
  `after_tool_response()`, and `after_agent_error()`.
- `ResearchARESimulationAgent` is the FAIRY port of ARE's
  `ResearchARESimulationAgent`: it resets telemetry at run start, injects
  dynamic controller context before each LLM turn, feeds tool observations and
  errors into `ResearchStrategyCoordinator.consume_snapshot()`, and emits a
  final `controller_telemetry` runtime event.
- `AgentConfigBuilder` in `fairy.controllers.agent_config` is the ARE-compatible
  family mapping. Preserve exact paper-facing planning modes such as
  `adaptive_verifier`, `rewoo_modular`, and `critic_refiner`; downstream
  summaries use these labels.
- L3 skill-retrieval context is a separate scenario-level library under
  `fairy/scenarios/farm_world_fullseason_v2/l2_l1_splits/knowledge_library_pilot/`.
  Do not confuse it with the 6 controller JSON skills. The L2 skill pool is
  `scripts/fullseason/l2_skill_scenario_ids.txt` (72 scenarios) and its source
  L3 pool is `scripts/fullseason/l3_skill_source_ids.txt` (20 scenarios).
- Soybean full-season detailed-context modes are documented in both READMEs and are
  implemented by `harbin_l3_context_briefings.py`: `false`, `true`, `kwoo`,
  `library`, `l2_human_same`, `l2_human_differ`, `l2_textsim_differ`,
  `l2_textsim_grouped_differ`, `l2_pathsim_differ`,
  `l2_pathsim_grouped_differ`, `l3_pathsim_same`, `l3_pathsim_differ`,
  `l3_textsim_differ`, and legacy alias `l3_textdiff_differ`.
- Rice currently accepts only `detailed_briefing=false/true`. Kwoo context,
  the scenario skill library, and retrieval modes have not been connected to
  rice; unsupported values raise an explicit error instead of silently using
  a different briefing mode.
- `run_report.json` stores controller telemetry in both
  `controller_telemetry` and `metrics.controller_telemetry`; batch summaries
  should prefer this over legacy `output.jsonl.metadata.telemetry`.

## Agent2Agent App Experts

- FAIRY's A2A path starts in `fairy.cli --agent --a2a true`, after
  `scenario.setup()` and before `build_controller_agent()`. The CLI calls
  `apply_a2a_to_apps()` and replaces `scenario.apps` with the transformed app
  list.
- `apply_a2a_to_apps()` follows ARE's FARM transform semantics: filter out
  `InternalContacts`, `AgentUserInterface`, and `SystemApp`; choose
  `int(len(filtered_apps) * a2a_app_prop)` apps with `random.Random(seed)`;
  keep non-transformed apps and append one `AppAgent` wrapper for each selected
  app.
- Each `AppAgent` wrapper exposes only `<WrappedAppName>Expert__expert_agent`.
  The expert agent inside the wrapper sees the original wrapped app's tools plus
  `FinalAnswerTool__final_answer`. Delegated calls reset the expert message,
  workflow, runtime event, and tool-count state so separate delegations do not
  leak prompt context into each other.
- `typed_experts` uses the ARE mapping: `WeatherApp` ->
  `weather_expert_app_agent`, `SensorApp` -> `sensor_expert_app_agent`,
  `TractorApp`/`FieldOpsApp` -> `machinery_expert_app_agent`, and
  `FarmWorldApp`/`DroneApp`/`RobotApp` -> `operations_expert_app_agent`.
- `Engine._register_scenario_apps()` unwraps `AppAgent.wrapped_app` when looking
  for `FarmWorldApp`, so `SystemApp.advance_time()` still attaches to the real
  farm-world state even when `FarmWorldApp` is transformed.
- `run_report.json` includes an `a2a` section with enablement, app proportion,
  policy, fallback app-agent, model/provider/endpoint, and transformed app list.

## WeatherEvent Boundary

- `WeatherEvent` in `fairy.physics.weather_engine` is physics/weather-generator
  input data, not a FAIRY framework `Event` and not an ARE event-graph node.
- For full-season profiles, rain is injected through
  `PhysicsProfile.weather_events` -> `WeatherGenerator.generate(..., events=...)`
  -> `_apply_events()` -> `_build_weather_inputs()` -> `WeatherApp.set_weather()`.
- Agent-visible weather tools expose the resulting weather state, for example
  `rainfall_mm`, but intentionally do not expose `weather_tags` or the internal
  `rain_event` label as workflow events.
- The regression check is
  `tests/test_fairy_migration_smoke.py::test_weather_event_rain_event_is_physics_input_not_framework_event`.
