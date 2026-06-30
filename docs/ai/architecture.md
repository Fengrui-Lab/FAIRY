## Oracle Replay And Evaluation Loop

- FAIRY end-to-end scenario execution is:
  `Scenario.setup()` -> `Engine.build_oracle_workflow()` ->
  `Workflow.save_workflow()` -> fresh `Engine.replay_workflow()` ->
  `Engine.evaluation_report()`.
- `build_oracle_workflow(run_oracle=False)` records tool names and arguments
  without mutating scenario state through tool execution. For ARE-derived event
  graph scenarios, positional event arguments are recovered from the captured
  function signature so JSON replay has named `tool_args`.
- `replay_workflow()` builds tools from the fresh scenario apps and calls each
  `AppName__method` in workflow order. The replayed workflow stores actual tool
  results in `content`, preserving the original workflow JSON shape.
- `evaluate()` passes a lightweight `EngineEnvironment` to
  `scenario.validate(env)`. The environment exposes `scenario`, `workflow`,
  `apps`, `time_manager`, and `engine`.

## Run Observability Artifacts

- FAIRY experiment layout follows the FARM validation-run convention:
  `validation_runs/<phase>/phase5_paper_matrix/<cell>/`, where `cell` is
  `<agent_family>__<scenario_id>__r<repeat>`.
- Oracle baselines belong outside cells at
  `validation_runs/<phase>/oracle_baselines/<scenario_id>.json`; oracle replay
  diagnostics can live under
  `validation_runs/<phase>/oracle_replay/<scenario_id>/`.
- Every productized run cell should expose two human entry points:
  `*.run_report.json` and `*.events.jsonl`.
- `run_report.json` is the file to open first. It contains run type, scenario,
  controller/model, status, stop reason, limits, wall time, LLM/tool metrics,
  token totals, evaluation, outcome, error, artifact paths, and an
  `artifact_guide` explaining the remaining files.
- `events.jsonl` is the runtime log. Agent runs write `agent_run_start/end`,
  `llm_call_start/end/error`, `tool_call_start/end/error`,
  `tool_args_parse_error`, and `agent_limit_exceeded`. Oracle replay writes
  `tool_replay` rows derived from the replay tool log.
- `agent_workflow.json` remains the replay/audit trace with FAIRY workflow
  shape. `messages.json` is raw LLM conversation state. `runtime_metrics.json`
  is per-call token/time detail. `evaluation.json` is validation and farm
  outcome. `run_summary.json` is legacy machine summary for old scripts.
