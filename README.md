# FAIRY

[中文说明](README.zh-CN.md)

FAIRY is an independent farm-agent simulation runtime for FARM scenario execution, oracle workflow generation, replay, and evaluation. It extracts the FARM business logic that used to live inside ARE into a standalone `fairy` Python package, while preserving the lightweight FarmAgent-style controller runtime and the OpenAI-compatible function-calling tool path.

## System Scope

FAIRY executes FARM scenarios as reproducible agent experiments. A run is defined by the following inputs:

| Input | Meaning |
|---|---|
| `scenario_id` | FARM scenario. Defines initial farm state, available apps, task objective, and validation rules. |
| `controller_id` | Agent controller. Defines ReAct, ReWOO, planner, verifier, critic, memory, graph-memory, or related execution strategy. |
| `provider` / `model` | OpenAI-compatible function-calling model service. |
| `scenario_kwargs` | Scenario constructor options, including full-season detailed-context modes. |
| `limits` | Execution bounds such as maximum tool calls and wall-clock timeout. |
| `output_dir` | Complete artifact directory for one run. |

The primary output is a run bundle. The default entry point is:

```text
<output_dir>/<scenario_id>.run_report.json
```

`run_report.json` indexes the run status, stop reason, token/tool metrics, evaluation summary, error summary, and artifact paths.

## Execution Modes

| Mode | CLI flags | Input | Output | Purpose |
|---|---|---|---|---|
| Agent run | `--agent` | Scenario, controller, model | `run_report.json`, `runtime_log.jsonl`, `agent_workflow.json` | Execute a real function-calling agent. |
| Oracle build | `--build-oracle` | Scenario | `oracle.json` | Export the scenario's reference workflow. |
| Workflow replay | `--replay --workflow <file>` | Any workflow JSON | `replay.json`, `runtime_log.jsonl`, `run_report.json` | Re-execute a workflow in a fresh scenario state. |
| Evaluation | `--replay --evaluate --workflow <file>` | Any workflow JSON | `run_report.json` | Validate the replayed workflow and resulting farm state. |
| Batch run | `scripts/iclr_validation_runner.py` | Controller set, scenario set | `results.csv` plus per-cell run bundles | Execute a controller × scenario matrix. |
| FOS rebatch | `scripts/rebatch_fos_from_traces.py` | FAIRY agent run bundles, oracle baselines | `summary_v2.csv` | Recompute FOS, yield loss, and error columns from existing `agent_workflow.json` runs. |

## Quick Start

### 1. Execute A Real Agent

This command runs a small FARM baseline scenario with DeepSeek function calling and writes all artifacts to one run directory.

```bash
PYTHONPATH=. python -m fairy.cli \
  -s scenario_farm_world_field_prep \
  --agent \
  --controller farm_baseline_react \
  --provider deepseek \
  --model deepseek-chat \
  --temperature 0.1 \
  --max-tool-calls 20 \
  --timeout-seconds 300 \
  --output-dir validation_runs/quickstart/agent/farm_baseline_react__scenario_farm_world_field_prep__r1
```

After completion, open:

```text
validation_runs/quickstart/agent/farm_baseline_react__scenario_farm_world_field_prep__r1/scenario_farm_world_field_prep.run_report.json
```

Key fields:

| Field | Meaning |
|---|---|
| `status` | `completed`, `stopped`, or `failed`. |
| `stopped_reason` | Stop reason, such as `completed`, `max_tool_calls`, `timeout`, or `error`. |
| `metrics.token_usage` | Model token usage. |
| `metrics.tool_call_count` | Number of executed tool calls. |
| `evaluation` | Scenario validation summary. |
| `artifacts` | Paths to all files produced by this run. |

Inspect agent-run artifacts in this order:

```text
1. <scenario>.run_report.json      # status, wall time, tokens, tool count, evaluation, outcome
2. <scenario>.runtime_log.jsonl    # full prompts/messages, model calls, tool calls, errors, limits
3. <scenario>.agent_workflow.json  # tools the agent actually executed
```

If `status=stopped` and `stopped_reason=max_tool_calls`, the run reached the configured `--max-tool-calls` bound. Increase that limit for longer traces.

### 2. Validate The Oracle/Replay/Evaluate Pipeline Offline

This command does not call an LLM. It exports the reference workflow, replays that workflow in a fresh scenario, and runs scenario validation.

```bash
PYTHONPATH=. python -m fairy.cli \
  -s scenario_farm_world_field_prep_physics_action_tick \
  --build-oracle --replay --evaluate \
  --workflow validation_runs/quickstart/oracle/scenario_farm_world_field_prep_physics_action_tick.json \
  --output-dir validation_runs/quickstart/oracle_replay/scenario_farm_world_field_prep_physics_action_tick
```

After completion, open:

```text
validation_runs/quickstart/oracle_replay/scenario_farm_world_field_prep_physics_action_tick/scenario_farm_world_field_prep_physics_action_tick.run_report.json
```

Key fields:

- `status=completed`: oracle/replay/evaluate ran through.
- `evaluation.validation.success=true`: scenario validation passed.
- `artifacts.oracle_workflow`: where the oracle workflow is.
- `artifacts.replay_workflow`: where the replayed workflow is.
- `artifacts.evaluation`: where the evaluation details are.

### 3. Execute A Full-Season Scenario With Context Modes

Full-season detailed context is passed to the scenario constructor through `--scenario-kwargs`.

```bash
PYTHONPATH=. python -m fairy.cli \
  -s scenario_full_season_hb_base_hn84_std_normal \
  --agent \
  --controller farm_baseline_react \
  --provider deepseek \
  --model deepseek-chat \
  --scenario-kwargs '{"detailed_briefing": false}' \
  --max-tool-calls 300 \
  --timeout-seconds 1200 \
  --output-dir validation_runs/quickstart/fullseason/detail_false
```

Complete `detailed_briefing` values:

| Value | JSON form | Meaning | Extra dependency |
|---|---|---|---|
| `false` | `{"detailed_briefing": false}` | Use only the base L3 prompt; no extra detail/context. | None |
| `true` | `{"detailed_briefing": true}` | Use the scenario's built-in human detailed briefing. | Scenario `detailed_briefing_text` |
| `kwoo` | `{"detailed_briefing": "kwoo"}` | Append Kwoo-generated expert context to the base prompt. | `FARM_FAIRY_KWOO_CONTEXT_PATH`; legacy `FARM_ARE_KWOO_CONTEXT_PATH` is accepted |
| `library` | `{"detailed_briefing": "library"}` | Append same-L3 structured L2 skill-library context. This is not a Python package; it comes from `knowledge_library_pilot/<scenario_slug>/library_same_l3.md`. | Scenario-specific `library_same_l3.md` |
| `l2_human_same` | `{"detailed_briefing": "l2_human_same"}` | Same-source-L3 human/structured L2 skill context. | Same-L3 skill JSON under `knowledge_library_pilot` |
| `l2_human_differ` | `{"detailed_briefing": "l2_human_differ"}` | Cross-L3 transferred human/structured L2 skill context. | Cross-L3 skill JSON under `knowledge_library_pilot` |
| `l2_textsim_differ` | `{"detailed_briefing": "l2_textsim_differ"}` | Cross-L3 L2 skills retrieved by text similarity. | Generated retrieval context |
| `l2_textsim_grouped_differ` | `{"detailed_briefing": "l2_textsim_grouped_differ"}` | Text-similar cross-L3 L2 skills grouped by establishment/management/harvest quotas. | Generated retrieval context |
| `l2_pathsim_differ` | `{"detailed_briefing": "l2_pathsim_differ"}` | Cross-L3 L2 skills retrieved by workflow/path similarity. | `FARM_FAIRY_RETRIEVED_CONTEXT_PATH`; legacy `FARM_ARE_RETRIEVED_CONTEXT_PATH` is accepted |
| `l2_pathsim_grouped_differ` | `{"detailed_briefing": "l2_pathsim_grouped_differ"}` | Path-similar cross-L3 L2 skills grouped by farming stage. | `FARM_FAIRY_RETRIEVED_CONTEXT_PATH` |
| `l3_pathsim_same` | `{"detailed_briefing": "l3_pathsim_same"}` | Same-L3 reference context retrieved by workflow/path similarity. | `FARM_FAIRY_RETRIEVED_CONTEXT_PATH` |
| `l3_pathsim_differ` | `{"detailed_briefing": "l3_pathsim_differ"}` | Cross-L3 reference context retrieved by workflow/path similarity. | `FARM_FAIRY_RETRIEVED_CONTEXT_PATH` |
| `l3_textsim_differ` | `{"detailed_briefing": "l3_textsim_differ"}` | Cross-L3 reference context retrieved by text similarity. | `FARM_FAIRY_RETRIEVED_CONTEXT_PATH` |
| `l3_textdiff_differ` | `{"detailed_briefing": "l3_textdiff_differ"}` | Backward-compatible legacy experiment name; normalized to `l3_textsim_differ` at runtime. | `FARM_FAIRY_RETRIEVED_CONTEXT_PATH` |

`iclr_validation_runner.py --detail <value>` merges the same value into `--scenario-kwargs` as `detailed_briefing`.

### 4. Run A Controller × Scenario Batch

Batch experiments use the validation runner. Each controller/scenario/repeat cell produces a separate run bundle.

```bash
PYTHONPATH=. python scripts/iclr_validation_runner.py \
  --phase smoke \
  --output-root validation_runs/quickstart/batch/phase5_paper_matrix \
  --families farm_baseline_react,farm_rewoo_modular \
  --scenarios scenario_farm_world_field_prep,scenario_farm_world_planting \
  --repeats 1 \
  --provider deepseek \
  --model deepseek-chat \
  --max-concurrent 1 \
  --cell-timeout-s 600 \
  --agent-max-iterations 100 \
  --cost-cap-dollars 5
```

After completion, open:

```text
validation_runs/quickstart/batch/phase5_paper_matrix/results.csv
```

Complete `results.csv` columns:

| Column | Meaning |
|---|---|
| `family` | Controller id. |
| `scenario` | Scenario id. |
| `level` | Scenario level inferred by the runner from the scenario id. |
| `repeat` | Repeat index, starting at 1. |
| `provider` | Provider requested by the user. |
| `command_provider` | Provider actually passed to `fairy.cli`; some providers are normalized. |
| `model` | Model name. |
| `model_family` | Reporting label; inferred from provider/model if omitted. |
| `endpoint` | Effective endpoint override. |
| `a2a_enabled` | Whether A2A is enabled. |
| `a2a_app_prop` | A2A app-wrapper proportion; `0.0` when A2A is off. |
| `a2a_policy` | A2A policy; `off` when A2A is disabled. |
| `a2a_app_agent` | A2A fallback app-agent profile; empty when A2A is off. |
| `detail_enabled` | Normalized `--detail` value; empty when unset. |
| `scenario_kwargs` | JSON string passed to `fairy.cli --scenario-kwargs`. |
| `scenario_initialization_kwargs` | JSON string passed to `fairy.cli --init-kwargs`. |
| `wall_s` | Cell subprocess wall-clock seconds. |
| `return_code` | Cell subprocess exit code. `0` means the process exited successfully. |
| `timed_out` | Whether `--cell-timeout-s` fired. |
| `force_killed` | Whether the process was terminated/killed after graceful shutdown failed. |
| `timeout_grace_s` | Graceful shutdown window after timeout; empty when no timeout occurred. |
| `score` | `1.0` when `run_report.evaluation.validation.success` is true, otherwise `0.0`. |
| `status` | `run_report.status`, for example `completed`, `stopped`, or `failed`. |
| `workflow_combined` | Workflow combined score parsed from legacy `output.jsonl` rationale; may be empty for new run-report-only cells. |
| `fos` | Total FOS score from legacy rationale or FOS report. |
| `outcome` | FOS outcome component. |
| `decision` | FOS decision component. |
| `efficiency` | FOS efficiency component. |
| `reasoning_steps` | LLM call count, or legacy output-jsonl estimate if LLM metrics are unavailable. |
| `llm_calls` | `run_report.metrics.llm_call_count`. |
| `tool_calls` | `run_report.metrics.tool_call_count`. |
| `planned_steps` | Controller telemetry planned steps; falls back to workflow steps when telemetry is absent. |
| `executed_steps` | Controller telemetry executed steps; falls back to workflow steps when telemetry is absent. |
| `skill_hits` | Compatibility telemetry column. Bundled FAIRY controllers do not use this column, so it is normally `0` unless a custom profile enables skills. |
| `reflection_signals` | Reflective-controller telemetry. |
| `replan_signals` | Planner/ReWOO telemetry. |
| `delegation_signals` | Delegation/A2A/controller telemetry. |
| `verification_signals` | Verifier/critic telemetry. |
| `error_count` | Telemetry error count; set to `1` when `run_report.error` is present. |
| `safety_violations` | FOS outcome safety violation count. |
| `crop_loss` | FOS crop loss count; may be overwritten by `yield_recovery.avg_field_loss_fraction` from run_report. |
| `gates_matched` | Number of matched FOS decision gates. |
| `gates_total` | Total number of FOS decision gates. |
| `estimated_cost_dollars` | Estimated cell cost from the runner model price table. |
| `cell_dir` | Cell run-bundle directory. |
| `run_report_path` | Path to `<scenario>.run_report.json`. |
| `stdout_path` | Path to the cell stdout log. |
| `stderr_path` | Path to the cell stderr log. |
| `exception` | Runner-level exception; present only for provider/env preparation failures or future exceptions. |

Each cell directory layout:

```text
<output-root>/<controller>__<scenario>__r1/
  stdout.log
  stderr.log
  <scenario>.run_report.json
  <scenario>.agent_workflow.json
  <scenario>.runtime_log.jsonl
```

### 5. Compute Yield Loss / FOS

Yield loss needs oracle yield baselines. To compute `crop_loss_pct`, `yield_loss(%)`, and `fos(%)`, run two steps.

Build oracle baselines:

```bash
PYTHONPATH=. python scripts/build_oracle_baselines.py \
  --scenarios formal90 \
  --output-dir validation_runs/quickstart/oracle_baselines_formal90 \
  --max-days 180 \
  --force \
  --include-donothing
```

Replay completed agent traces and recompute FOS:

```bash
PYTHONPATH=. python scripts/rebatch_fos_from_traces.py \
  --root validation_runs/quickstart/batch/phase5_paper_matrix \
  --out-root validation_runs/quickstart/rebatch_fos \
  --oracle-baselines validation_runs/quickstart/oracle_baselines_formal90 \
  --extrapolate \
  --workers 4
```

Open this first:

```text
validation_runs/quickstart/rebatch_fos/summary_v2.csv
```

Key columns:

- `fos(%)`: total FOS score.
- `outcome(%)` / `decision(%)` / `efficiency(%)`: FOS components.
- `agent_biological_kg`: biological yield after agent replay.
- `oracle_biological_kg`: oracle baseline yield.
- `crop_loss_pct(%)` / `yield_loss(%)`: yield loss against oracle.
- `run_error_*` / `stderr_traceback_tail`: failure diagnostics.

## Artifact Reading Guide

Select artifacts by analysis objective:

| Question | File |
|---|---|
| Did this run succeed, why did it stop, how long did it take, how many tokens? | `run_report.json` |
| What prompt did the model see, and how did it call functions? | `runtime_log.jsonl` |
| What tools did the agent actually execute, with which args and results? | `agent_workflow.json` |
| Which step failed, had bad JSON args, API error, timeout, or limit stop? | `runtime_log.jsonl` |
| What happened inside A2A experts? | `run_report.a2a` and `runtime_log.jsonl` |
| What is the oracle answer workflow? | `oracle.json` |
| What workflow was replayed in a fresh scenario? | `replay.json` |
| What was the final validation/farm result? | `run_report.json` |
| Where is the batch summary table? | `results.csv` or `summary_v2.csv` |

Human inspection starts from `run_report.json`. Per-turn prompt/tool/error details are in `runtime_log.jsonl`.

## Architecture Overview

The central object is a `Scenario`. A scenario creates farm apps such as weather, sensors, drones, robots, tractor operations, field operations, inventory, physics, and system time. An agent sees those apps as function tools. Tool names are always:

```text
AppName__method_name
```

Typical execution path:

```text
Scenario.setup()
  -> apps + physics + initial farm state
  -> Engine
  -> oracle workflow or real agent function calls
  -> workflow/replay/evaluation/run_report artifacts
```

Time and physics path:

```text
SystemApp.advance_time()
  -> FarmWorldApp.prepare_for_time_advance()
  -> FarmWorldApp.advance_physics_time()
  -> physics orchestrator daily ticks
  -> weather / soil / phenology / biomass / pest / yield state
```

## Repository Layout

```text
fairy/
  agents/        LLM clients, function-calling agent loop, messages/runtime metrics
  apps/          App base class, SystemApp, farm_world apps
  controllers/   Engine, controllers, A2A app-agents, run artifacts
  physics/       FARM physics engines and profiles
  scenarios/     Scenario base class, registry, baseline/action-tick/full-season suites
  evaluation/    Migrated FARM evaluation/FOS helpers
scripts/
  build_oracle_baselines.py     Build oracle yield baselines
  rebatch_fos_from_traces.py    Replay FAIRY agent workflows and recompute FOS/yield loss
  iclr_validation_runner.py     Batch controller x scenario x repeat runs
  summarize_runs.py             Summarize run_report.json files
tests/                          Smoke, oracle, physics, controller, A2A tests
docs/ai/                        Maintainer notes and known pitfalls
```

## Installation

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Without installing the console script, use:

```bash
PYTHONPATH=. python -m fairy.cli --list
```

After installation:

```bash
fairy-run --list
```

## LLM Provider Environment Variables

FAIRY's agent path uses OpenAI-compatible chat completions with function calling.

Supported providers:

- DeepSeek
  - `--provider deepseek`
  - Common model: `deepseek-chat`
  - Environment variables: `DEEPSEEK_API_KEY`, optional `DEEPSEEK_API_BASE`
  - Default endpoint: `https://api.deepseek.com`

- OpenAI
  - `--provider openai`
  - Common models: `gpt-4o-mini`, `gpt-4o`
  - Environment variable: `OPENAI_API_KEY`
  - Endpoint: OpenAI SDK default

- Generic OpenAI-compatible service
  - `--provider llama-api` or `--provider openai-compatible`
  - Model name: service-specific
  - Environment variables: `LLAMA_API_KEY` or `OPENAI_API_KEY`
  - Endpoint: set `--endpoint` or `LLAMA_API_BASE`

- Qwen / DashScope
  - `--provider qwen`
  - Common models: `qwen-plus`, `qwen-max`
  - Environment variables: `QWEN_API_KEY` or `DASHSCOPE_API_KEY`, optional `QWEN_API_BASE`
  - Default endpoint: `https://dashscope.aliyuncs.com/compatible-mode/v1`

- vLLM
  - `--provider vllm`
  - Model name: the model exposed by your local vLLM server
  - Environment variables: optional `VLLM_API_KEY`, optional `VLLM_API_BASE`
  - Default endpoint: `http://localhost:8000/v1`

`deepseek-json` and `qwen-json` are legacy ARE labels. In FAIRY they are compatibility aliases for function calling, not JSON-only agents.

## One End-to-End Command

Build an oracle workflow, replay it, and evaluate it:

```bash
fairy-run \
  -s scenario_farm_world_field_prep_physics_action_tick \
  --build-oracle --replay --evaluate \
  --workflow validation_runs/example/oracle_baselines/scenario_farm_world_field_prep_physics_action_tick.json \
  --output-dir validation_runs/example/oracle_replay/scenario_farm_world_field_prep_physics_action_tick
```

Open this first:

```text
validation_runs/example/oracle_replay/scenario_farm_world_field_prep_physics_action_tick/scenario_farm_world_field_prep_physics_action_tick.run_report.json
```

`run_report.json` is the entry point for every run bundle. It records status, elapsed wall time, token usage, tool calls, evaluation, outcome, errors, and the paths to every other artifact.

## Main Command: `fairy-run`

Equivalent entry points:

```bash
fairy-run ...
PYTHONPATH=. python -m fairy.cli ...
PYTHONPATH=. python scripts/run_scenario.py ...   # compatibility wrapper around fairy.cli
```

### 1. Inspect Available Objects

List scenarios:

```bash
fairy-run --list
```

List controllers:

```bash
fairy-run --list-controllers
```

Current controller IDs:

```text
default
farm_world
farm_baseline_react
farm_planner_executor
farm_reflective_memory
farm_multi_specialist
farm_adaptive_verifier
farm_rewoo_modular
farm_tree_search
farm_critic_refiner
farm_graph_memory
```

### 2. Oracle / Replay / Evaluate Mode

```bash
fairy-run \
  -s <scenario_id> \
  --build-oracle \
  --replay \
  --evaluate \
  --workflow <path/to/oracle.json> \
  --output-dir <path/to/run_dir>
```

Parameters:

| Parameter | Type/values | Default | Meaning |
|---|---|---|---|
| `-s`, `--scenario` | scenario id | required | Scenario to run. Use `--list` to inspect IDs. |
| `--build-oracle` | flag | false | Build and save the scenario's oracle workflow. |
| `--run-oracle-tools` | flag | false | Execute tools while building the oracle. Usually off for workflow baselines; turn on when you also need live physics state during oracle construction. |
| `--replay` | flag | false | Replay `--workflow` against a fresh scenario instance. |
| `--evaluate` | flag | false | Evaluate the replayed workflow and store the result in `run_report.evaluation`. |
| `--workflow` | path | `<output-dir>/<scenario>.oracle.json` | Output path for `--build-oracle`; input path for `--replay` and `--evaluate`. |
| `--output-dir` | path | `runs` | Output directory for the run bundle. |
| `--scenario-kwargs` | JSON object string | `{}` | Arguments passed when the scenario object is created. Detail/context such as `'{\"detailed_briefing\":\"kwoo\"}'` belongs here. |
| `--init-kwargs` | JSON object string | `{}` | Arguments passed to `scenario.setup(**init_kwargs)`. Most FARM scenarios do not need this. |

Common commands:

Build only:

```bash
fairy-run -s scenario_full_season_balanced \
  --build-oracle \
  --workflow validation_runs/oracle/scenario_full_season_balanced.json \
  --output-dir validation_runs/oracle_build/scenario_full_season_balanced
```

Replay and evaluate an existing workflow:

```bash
fairy-run -s scenario_full_season_balanced \
  --replay --evaluate \
  --workflow validation_runs/oracle/scenario_full_season_balanced.json \
  --output-dir validation_runs/oracle_replay/scenario_full_season_balanced
```

Compatibility direct-oracle print mode:

```bash
fairy-run -s scenario_farm_world_field_prep --oracle
```

`--oracle` / `-o` runs `Engine.run_scenario_oracle(run_oracle=True)` and prints the workflow to stdout. It is mainly for quick debugging and does not write a full run bundle. For formal experiments, prefer `--build-oracle --replay --evaluate`.

### 3. Agent Mode

```bash
fairy-run \
  -s <scenario_id> \
  --agent \
  --controller <controller_id> \
  --provider <provider> \
  --model <model> \
  --temperature 0.1 \
  --max-tool-calls 300 \
  --timeout-seconds 1200 \
  --output-dir <path/to/run_dir>
```

Parameters:

| Parameter | Type/values | Default | Meaning |
|---|---|---|---|
| `--agent` | flag | false | Run a real function-calling agent. |
| `--controller` | controller id | `farm_baseline_react` | Controller family. Use `--list-controllers` to inspect. |
| `--provider` | `deepseek`, `openai`, `llama-api`, `openai-compatible`, `qwen`, `vllm` | `deepseek` | LLM client type. |
| `--model` | string | `deepseek-chat` | Model name for the selected provider. |
| `--temperature` | float | `0.1` | Sampling temperature. Some reasoning/OpenAI models may ignore it. |
| `--endpoint` | URL | provider default | Override OpenAI-compatible base URL. Passed to the client as `base_url`. |
| `--max-tool-calls` | int | `300` | Maximum main-agent tool calls. If reached, `run_report.status=stopped` and `stopped_reason=max_tool_calls`. |
| `--timeout-seconds` | float | `1200.0` | Maximum main-agent wall time. If reached, `stopped_reason=timeout`. |
| `--scenario-kwargs` | JSON object string | `{}` | Arguments passed when the scenario object is created. Put `detailed_briefing` / detail-context mode here. |
| `--init-kwargs` | JSON object string | `{}` | Arguments passed to `scenario.setup(**init_kwargs)`. Most FARM scenarios do not need this; keep `{}` unless a scenario's `setup()` explicitly requires extra initialization arguments. |

Difference between `--scenario-kwargs` and `--init-kwargs`:

- `--scenario-kwargs` controls how the scenario object is constructed. Full-season `detailed_briefing` is a dataclass/constructor field, so it belongs here.
- `--init-kwargs` controls how `setup()` initializes the already-created scenario. Most migrated FARM scenarios do not use it.

The detail true/false/kwoo modes all use `--scenario-kwargs`:

```bash
# detail false: no extra detailed context
--scenario-kwargs '{"detailed_briefing": false}'

# detail true: use the scenario's built-in detailed briefing
--scenario-kwargs '{"detailed_briefing": true}'

# Kwoo context
--scenario-kwargs '{"detailed_briefing": "kwoo"}'

# knowledge library context
--scenario-kwargs '{"detailed_briefing": "library"}'

# L2/L3 retrieval context
--scenario-kwargs '{"detailed_briefing": "l2_textsim_differ"}'
--scenario-kwargs '{"detailed_briefing": "l3_pathsim_differ"}'
```

JSON booleans are lowercase `true` / `false`. String modes need double quotes, for example `"kwoo"`.

DeepSeek example:

```bash
fairy-run \
  -s scenario_full_season_balanced \
  --agent \
  --controller farm_baseline_react \
  --provider deepseek \
  --model deepseek-chat \
  --temperature 0.1 \
  --max-tool-calls 300 \
  --timeout-seconds 1200 \
  --output-dir validation_runs/manual/farm_baseline_react__scenario_full_season_balanced__r1
```

Qwen example:

```bash
fairy-run \
  -s scenario_full_season_balanced \
  --agent \
  --controller farm_baseline_react \
  --provider qwen \
  --model qwen-plus \
  --output-dir validation_runs/manual/qwen__farm_baseline_react__scenario_full_season_balanced__r1
```

vLLM example:

```bash
fairy-run \
  -s scenario_full_season_balanced \
  --agent \
  --controller farm_baseline_react \
  --provider vllm \
  --model Qwen/Qwen3-1.7B \
  --endpoint http://localhost:8000/v1 \
  --output-dir validation_runs/manual/vllm__farm_baseline_react__scenario_full_season_balanced__r1
```

## A2A: Agent2Agent App Experts

When A2A is enabled, the main agent no longer sees all direct app tools. Some apps are replaced by expert wrappers exposing one tool:

```text
<AppName>Expert__expert_agent(task)
```

The expert agent receives the task and can only call the wrapped app's tools plus `FinalAnswerTool__final_answer`. Expert summary metrics and traces are stored inside:

```text
<scenario>.run_report.json
```

Command:

```bash
fairy-run \
  -s scenario_farm_world_drone_survey \
  --agent \
  --controller farm_multi_specialist \
  --provider deepseek \
  --model deepseek-chat \
  --a2a true \
  --a2a-app-prop 1.0 \
  --a2a-policy typed_experts \
  --output-dir validation_runs/manual/farm_multi_specialist__scenario_farm_world_drone_survey__a2a_on
```

A2A parameters:

| Parameter | Type/values | Default | Meaning |
|---|---|---|---|
| `--a2a` | bool: `true/false`, `1/0`, `yes/no`, `on/off` | `false` | Enable app-agent wrappers. |
| `--a2a-app-prop` | float, `0.0` to `1.0` | `0.5` | Fraction of eligible apps to wrap. `1.0` wraps all eligible apps. |
| `--a2a-policy` | `typed_experts` or `generic` | `typed_experts` | `typed_experts` chooses expert profiles by app type; `generic` uses the fallback profile. |
| `--a2a-app-agent` | app-agent profile | `default_app_agent` | Fallback profile. With `generic`, every wrapped app uses this. |
| `--a2a-model` | model string | main model | Expert-agent model. |
| `--a2a-provider` | provider string | main provider | Expert-agent provider. |
| `--a2a-endpoint` | URL | main endpoint | Expert-agent endpoint. |

App-agent profiles:

```text
default_app_agent
weather_expert_app_agent
sensor_expert_app_agent
machinery_expert_app_agent
operations_expert_app_agent
```

`typed_experts` mapping:

| App class | Expert |
|---|---|
| `WeatherApp` | `weather_expert_app_agent` |
| `SensorApp` | `sensor_expert_app_agent` |
| `TractorApp`, `FieldOpsApp` | `machinery_expert_app_agent` |
| `FarmWorldApp`, `DroneApp`, `RobotApp` | `operations_expert_app_agent` |
| `SystemApp`, `AgentUserInterface` | never wrapped |

Important: if the main agent delegates a task that is too broad, one expert can loop until its own `max_tool_calls` limit. When A2A is slow or fails, inspect `run_report.a2a.expert_metrics` and `runtime_log.jsonl`.

## Output Files

Every `fairy-run` command writes a run bundle under `--output-dir`. File names usually start with `<scenario_id>`.

### Agent Run Files By Debugging Question

An agent run is a real model run: the model reads the prompt, emits function calls, FAIRY executes tools, and tool results are fed back to the model. One run should answer five questions.

Question 1: did the run succeed?

```text
<scenario>.run_report.json
```

Open this first. It contains `status`, `stop_reason`, `limits`, `wall_time_seconds`, tokens, LLM/tool call counts, controller telemetry, A2A summary, evaluation, outcome, and error. This is the human entry point.

Question 2: was the prompt correct, and where are token/error logs?

```text
<scenario>.runtime_log.jsonl
```

This is the chronological runtime log. For each `record_type=llm_call_start`, `messages` contains the exact messages sent to the model and `tool_names` lists the available function tools. The same file also records LLM token usage, tool arguments, tool results, API errors, JSON parse errors, timeout, and step-limit stops.

Question 3: which tools did the model actually call?

```text
<scenario>.agent_workflow.json
```

This is the semantic workflow: USER/TOOL nodes, tool names, arguments, return values, dependencies, and environment times. Use it for path comparison, manual audit, and later replay.

Question 4: where is the final validation/farm result?

Open `run_report.json`; its `evaluation` and `outcome` fields contain the validation result and farm state summary.

### Oracle / Replay / Evaluate Files By Step

Oracle/replay/evaluate outputs are not a flat pile of files. They come from three steps.

Step 1: `--build-oracle`

```text
<scenario>.oracle.json
```

This is the standard-answer workflow. It records the oracle's tool names, arguments, dependencies, and environment times. Use it as a baseline, as replay input, and as the reference path when comparing agent workflows.

Step 2: `--replay`

```text
<scenario>.replay.json
<scenario>.runtime_log.jsonl
```

`replay.json` is the workflow produced after replaying the input workflow in a fresh scenario state. It proves the workflow can actually drive FARM apps.

`runtime_log.jsonl` is the replay runtime log, one tool replay record per line. Use it to debug which replay step ran, what it returned, and whether it failed.

Step 3: `--evaluate`

```text
<scenario>.run_report.json
```

The validation result is stored in `run_report.evaluation`. Use it to check whether scenario validation passed and whether inventory/yield/physics state looks correct.

Final overview:

```text
<scenario>.run_report.json
```

`run_report.json` is the entry point. Open it first; it links all files above and summarizes status, metrics, outcome, and errors.

### `run_report.json` Fields

| Field | Meaning |
|---|---|
| `schema_version` | Report schema version. |
| `run_type` | `agent` or `oracle_replay_evaluate`. |
| `scenario_id` | Scenario ID. |
| `controller_id` | Agent controller; `null` for oracle/replay mode. |
| `provider`, `model`, `temperature` | LLM configuration. |
| `status` | `completed`, `stopped`, or `failed`. |
| `stopped_reason` | `agent_finished`, `completed`, `max_tool_calls`, `timeout`, `error`, etc. |
| `limits` | The configured `max_tool_calls` and `timeout_seconds`. |
| `metrics.wall_time_seconds` | Real elapsed wall time from Python `time.perf_counter()`. |
| `metrics.workflow_steps` | Number of workflow nodes. |
| `metrics.tool_call_count` | Main-agent or replay tool-call count. |
| `metrics.llm_call_count` | Main-agent LLM call count. |
| `metrics.token_usage` | Main-agent prompt, completion, cached, and total tokens. |
| `controller_telemetry` | Planner/skill/ReWOO/tree/critic/graph counters. |
| `a2a` | A2A config, wrapped apps, expert tool/LLM/token totals. |
| `evaluation` | Scenario validation and outcome. |
| `outcome` | Farm state summary, such as inventory, yield recovery, and physics state. |
| `error` | Fatal error type and message. Normal tool-call limits and timeouts are not fatal errors. |
| `artifacts` | Paths to all other output files. |
| `artifact_guide` | Human-readable purpose for each artifact. |
| `created_at` | Report timestamp in CST/UTC+8. |

## Recommended Directory Layout

Single manual run:

```text
validation_runs/manual/<controller>__<scenario>__r1/
```

A2A:

```text
validation_runs/manual/<controller>__<scenario>__a2a_on__r1/
```

Batch experiment:

```text
validation_runs/<experiment_name>/phase5_paper_matrix/<controller>__<scenario>__r<repeat>/
```

Keep oracle baselines, agent runs, and rebatch FOS outputs in separate directories:

```text
validation_runs/<experiment>/
  oracle_baselines/
    <scenario>.json
  phase5_paper_matrix/
    <controller>__<scenario>__r1/
      <scenario>.run_report.json
      ...
  rebatch_fos/
    summary_v2.csv
    <controller>__<scenario>__r1/
      fos/
      workflows/
```

## Scenario Pools

List every registered scenario:

```bash
fairy-run --list
```

Common examples:

```text
scenario_farm_world_field_prep
scenario_farm_world_planting
scenario_farm_world_irrigation
scenario_farm_world_pesticide
scenario_farm_world_drone_survey
scenario_farm_world_harvest
scenario_farm_world_field_prep_physics_action_tick
scenario_farm_world_planting_physics_action_tick
scenario_farm_world_irrigation_physics_action_tick
scenario_farm_world_pesticide_physics_action_tick
scenario_full_season_balanced
scenario_full_season_balanced_v2
```

`scripts/build_oracle_baselines.py --scenarios` supports these group names:

| Group | Meaning |
|---|---|
| `all` | Default FARM baseline groups: round12, round3, round4, Tangyan5. |
| `round12` | 8 action-tick baseline physics scenarios. |
| `round3` | 8 mid-season physics/FOS scenarios. |
| `round4` | Older full-season round4 group. |
| `full`, `formal90`, `l3_fullseason` | 90 formal L3 scenarios from `scripts/fullseason/formal_90_scenario_ids.txt`. |
| `selected_l2_l1_20_30`, `l2_l1_20_30` | Selected L2/L1 split scenario pool. |
| `l2_skill_72`, `l2_skills`, `l2_skill` | 72 L2 skill scenarios. |
| comma-separated scenario IDs | Run exactly those scenarios. |

## Full-Season Detail/Context Modes

Set these through `--scenario-kwargs '{"detailed_briefing": ...}'` or `iclr_validation_runner.py --detail`.

`fairy-run` example:

```bash
fairy-run \
  -s scenario_full_season_hb_base_hn84_std_normal \
  --agent \
  --controller farm_baseline_react \
  --provider deepseek \
  --model deepseek-chat \
  --scenario-kwargs '{"detailed_briefing":"kwoo"}' \
  --output-dir validation_runs/manual/kwoo_example
```

Equivalent batch-run form:

```bash
PYTHONPATH=. python scripts/iclr_validation_runner.py \
  --phase l3_context \
  --output-root validation_runs/l3_context/phase5_paper_matrix \
  --families farm_baseline_react \
  --scenarios scenario_full_season_hb_base_hn84_std_normal \
  --detail kwoo \
  --provider deepseek \
  --model deepseek-chat
```

`iclr_validation_runner.py --detail kwoo` is automatically merged into:

```text
--scenario-kwargs '{"detailed_briefing":"kwoo"}'
```

Values:

| Value | Meaning |
|---|---|
| `false` | No extra L3 detail/context. |
| `true` | Original detailed L3 briefing. |
| `kwoo` | Kwoo-generated expert context. |
| `library` | Same-L3 `knowledge_library_pilot` context. |
| `l2_human_same` | Human/structured L2 skills from the same source L3. |
| `l2_human_differ` | Human/structured L2 skills transferred from other L3 sources. |
| `l2_textsim_differ` | Cross-L3 L2 skills retrieved by text similarity. |
| `l2_textsim_grouped_differ` | Text-similar cross-L3 L2 skills grouped by establishment, management, harvest. |
| `l2_pathsim_differ` | Cross-L3 L2 skills retrieved by workflow/path similarity. |
| `l2_pathsim_grouped_differ` | Path-similar cross-L3 L2 skills grouped by farm stage. |
| `l3_pathsim_same` | Same-L3 context retrieved by L3 workflow/path similarity. |
| `l3_pathsim_differ` | Cross-L3 context retrieved by L3 workflow/path similarity. |
| `l3_textsim_differ` | Cross-L3 context retrieved by L3 text similarity. |
| `l3_textdiff_differ` | Legacy compatibility alias. |

Related assets:

```text
scripts/fullseason/formal_90_scenario_ids.txt
scripts/fullseason/selected_l2_l1_20_30_scenario_ids.txt
scripts/fullseason/l2_skill_scenario_ids.txt
scripts/fullseason/l3_skill_source_ids.txt
scripts/kwoo_expansion_result.json
scripts/kwoo_l1l2_expansion_result.json
```

## Oracle Baselines: Where Yield Loss Comes From

`scripts/build_oracle_baselines.py` runs each scenario under oracle control, optionally extrapolates physics to R8 maturity, and writes an oracle yield baseline. The main FOS yield-loss denominator comes from this file:

```text
crop_loss_pct = 1 - agent_biological_kg / oracle_biological_kg
```

Command:

```bash
PYTHONPATH=. python scripts/build_oracle_baselines.py \
  --scenarios formal90 \
  --output-dir validation_runs/oracle_baselines_formal90 \
  --max-days 180 \
  --force \
  --include-donothing
```

Parameters:

| Parameter | Type/values | Default | Meaning |
|---|---|---|---|
| `--scenarios` | group name or comma-separated IDs | `all` | Scenarios to build. Supports `all`, `round12`, `round3`, `round4`, `formal90`, `selected_l2_l1_20_30`, `l2_skill_72`. |
| `--output-dir` | path | `oracle_baselines_full` | Directory for `<scenario_id>.json`. |
| `--max-days` | int | `180` | Maximum extra days to tick to R8. |
| `--force` | flag | false | Rebuild existing baseline files. Without it, existing files are skipped. |
| `--continue-on-error` | flag | false | Continue after one scenario fails. |
| `--include-donothing` | flag | false | Also build a do-nothing baseline for normalized yield score. |

Baseline JSON fields:

| Field | Meaning |
|---|---|
| `scenario_id` | Scenario ID. |
| `schema_version` | Baseline schema version. |
| `ridge_area_m2` | Area per ridge. |
| `ridges_total`, `ridges_planted`, `ridges_r8`, `ridges_harvested` | Ridge counts. |
| `biological_yield_g_m2_per_ridge` | Per-ridge biological yield. |
| `biological_yield_kg_total` | Total oracle biological yield in kg. Main FOS yield-loss denominator. |
| `recovered_yield_g_m2_per_ridge` | Per-ridge recovered yield at market moisture. |
| `recovered_yield_kg_total` | Total recovered yield in kg. |
| `extrapolation` | Extra maturity extrapolation status. |
| `donothing` | Optional do-nothing yield baseline. |
| `tool_errors` | Tool-error returns preserved from the oracle workflow. These do not always mean the baseline failed. |

## Rebatch FOS: Recompute FOS/Yield Loss From FAIRY Runs

If you already have FAIRY agent run bundles and do not want to spend more LLM tokens, run:

```bash
PYTHONPATH=. python scripts/rebatch_fos_from_traces.py \
  --root validation_runs/<experiment>/phase5_paper_matrix \
  --out-root validation_runs/<experiment>/rebatch_fos \
  --oracle-baselines validation_runs/oracle_baselines_formal90 \
  --extrapolate \
  --workers 4
```

This script:

1. Finds each cell's saved trace/run artifacts.
2. Re-instantiates the same scenario.
3. Replays recorded tool calls.
4. Extrapolates physics to R8.
5. Reads oracle baselines.
6. Writes per-cell FOS JSON and `summary_v2*.csv`.

Rebatch output layout:

```text
<out-root>/
  summary_v2_<out-root-name>.csv      # primary CSV unless --summary-name overrides it
  summary_v2.csv                      # compatibility copy
  <cell>/
    fos/
      fos_<scenario>.json             # per-cell FOS details
    workflows/
      workflow_agent_<scenario>.json  # replayed agent workflow
      workflow_oracle_<scenario>.json # oracle workflow/path reference
    path_corr_v2_<scenario>.json      # path matching details when v2 is enabled
```

File meanings:

| File | Purpose |
|---|---|
| `summary_v2*.csv` | Main table/statistics entry point. One row per cell. |
| `fos/fos_<scenario>.json` | Per-cell FOS components, decision gates, and outcome breakdown. |
| `workflows/workflow_agent_<scenario>.json` | Agent tool sequence reconstructed from trace replay. Use it to inspect what the agent did. |
| `workflows/workflow_oracle_<scenario>.json` | Oracle tool sequence for the same scenario. Used for path correctness / KTC comparison. |
| `path_corr_v2_<scenario>.json` | Detailed matching output for relaxed numeric path correctness v2. |

Parameters:

| Parameter | Type/values | Default | Meaning |
|---|---|---|---|
| `--root` | path, repeatable | required | Sweep/cell root. Without `--recursive`, only immediate children are checked. |
| `--out-root` | path | required | Rebatch output directory. |
| `--summary-name` | filename | `summary_v2_<out-root-name>.csv` | Primary summary CSV name. A compatibility copy `summary_v2.csv` is always written. |
| `--extrapolate` | flag | false | Tick physics to R8 after replay. Recommended for full-season and mid-season scenarios. |
| `--extrapolation-max-days` | int | `180` | Maximum extra tick days. |
| `--oracle-baselines` | path | none | Directory of oracle baseline JSONs. Required for oracle-relative yield loss. |
| `--workers` | int | half CPU count | Parallel workers. |
| `--limit` | int | none | Process only the first N cells for debugging. |
| `--cells` | cell dir names | none | Process only specific cells. |
| `--recursive` | flag | false | Search the whole subtree under `--root`. |
| `--donothing-inline` | flag | false | Compute do-nothing yield inline. Requires `--extrapolate`. |
| `--path-correctness-v2` / `--no-path-correctness-v2` | bool | on | Compute relaxed numeric path correctness v2. |
| `--pc2-tol` | float | `2.0` | Numeric tolerance ratio for path correctness v2. |
| `--focus-ridges-config` | JSON path | none | Scenario-to-ridge subset map for focus yield metrics. |
| `--exclude-dir` | path, repeatable | none | Exclude directories from discovery. |

Important `summary_v2.csv` columns:

| Column | Meaning |
|---|---|
| `status` | Whether the cell was successfully re-evaluated. |
| `cell`, `cell_dir`, `cell_output_rel` | Cell name and paths. |
| `agent_family`, `scenario`, `level` | Controller, scenario, scenario level. |
| `llm_model`, `model_type_size` | Model labels. |
| `run_level`, `detail_status`, `detailed_briefing`, `a2a_status`, `a2a_enabled` | Experimental condition labels. |
| `llm_calls_with_usage`, `total_tokens_per_scenario`, `runtime_s_per_scenario` | Token/runtime summaries. |
| `fos(%)`, `outcome(%)`, `decision(%)`, `efficiency(%)` | FOS total and components, 100-scale. |
| `agent_biological_kg`, `oracle_biological_kg`, `donothing_biological_kg` | Agent/oracle/do-nothing biological yield. |
| `yield_preserved_ratio(%)` | Agent preserved yield ratio. |
| `yield_loss(%)`, `crop_loss_pct(%)` | Yield-loss metrics. |
| `normalized_yield_score(%)` | Yield score normalized by the do-nothing floor. |
| `growing_loss`, `harvest_loss`, `unharvested_mature`, `safety_violations` | Loss buckets and safety violations. |
| `path_correctness(%)`, `coverage(%)`, `ktc_score(%)`, `combined(%)` | Workflow path metrics. |
| `farm_fos(%)`, `farm_fos_v2_*` | FARM-FOS agricultural action metrics. |
| `run_error_*`, `stderr_traceback_tail`, `error`, `traceback` | Failure diagnostics. |

## Batch Real-Agent Runs: `iclr_validation_runner.py`

Use this for controller x scenario x repeat sweeps. Each cell is a separate subprocess and writes its own stdout/stderr plus FAIRY run artifacts.

```bash
PYTHONPATH=. python scripts/iclr_validation_runner.py \
  --phase smoke \
  --output-root validation_runs/smoke/phase5_paper_matrix \
  --families farm_baseline_react,farm_rewoo_modular \
  --scenarios scenario_farm_world_field_prep,scenario_farm_world_planting \
  --repeats 1 \
  --provider deepseek \
  --model deepseek-chat \
  --cost-cap-dollars 5 \
  --max-concurrent 1 \
  --cell-timeout-s 600 \
  --agent-max-iterations 100
```

Parameters:

| Parameter | Type/values | Default | Meaning |
|---|---|---|---|
| `--config` | JSON path | none | Load defaults from JSON. CLI args override config values. |
| `--phase` | string | required | Experiment phase label. Used for logging/organization. |
| `--output-root` | path | required | Root directory for cell outputs and `results.csv`. |
| `--families` | comma-separated or config list | required | Controller list. |
| `--scenarios` | comma-separated or config list | required | Scenario list. |
| `--repeats` | int | `1` | Runs per family x scenario pair. |
| `--model`, `--provider`, `--endpoint` | string | `gpt-4o-mini`, `llama-api`, none | LLM configuration. |
| `--model-family` | string | inferred | Reporting label for CSV. |
| `--cost-cap-dollars` | float | `10.0` | Estimated spend cap. Remaining cells are cancelled at 80 percent of cap. |
| `--max-concurrent` | int | `1` | Parallel cells. |
| `--cell-timeout-s` | int | `300` | Per-cell subprocess timeout. |
| `--cell-timeout-grace-s` | int | `60` | After timeout, wait this long after SIGINT before terminate/kill. |
| `--agent-max-iterations` | int | `200` | Passed to `fairy-run --max-tool-calls`. |
| `--wait-for-user-input-timeout` | float | `5.0` | Legacy runner field; current FAIRY CLI does not directly use it. |
| `--scenario-kwargs`, `--init-kwargs` | JSON object string | none | Passed through to FAIRY CLI. |
| `--detail` | detail mode | none | Merged into `--scenario-kwargs` as `detailed_briefing`. |
| `--a2a`, `--a2a-*` | same as FAIRY CLI | off | Batch A2A settings. |

Outputs:

| File | Purpose |
|---|---|
| `<output-root>/results.csv` | One row per cell: return code, status, cost, tool/LLM calls, telemetry, run_report path. |
| `<output-root>/<family>__<scenario>__rN/stdout.log` | Cell stdout. |
| `<output-root>/<family>__<scenario>__rN/stderr.log` | Cell stderr, timeout notes, tracebacks. |
| `<output-root>/<family>__<scenario>__rN/<scenario>.run_report.json` | Main cell report. |
| Other `<scenario>.*` artifacts | Same as ordinary agent run. |

## Summarize Reports: `summarize_runs.py`

Scan all `*.run_report.json` files under a directory:

```bash
PYTHONPATH=. python scripts/summarize_runs.py validation_runs/manual \
  --csv validation_runs/manual/summary.csv
```

Columns:

```text
run_dir, run_type, scenario_id, controller_id, model, status,
stopped_reason, success, wall_time_seconds, workflow_steps,
tool_call_count, total_tokens, cached_tokens, warehouse_grain_kg,
harvested_ridges, yield_g_m2
```

## Reading Status, Errors, Timeouts, Tokens

Start with `run_report.json`:

- `status=completed`: finished normally.
- `status=stopped`: hit a configured limit such as `max_tool_calls` or `timeout`. This is not a fatal error.
- `status=failed`: fatal error. Read `error.type` and `error.message`.

Then inspect `runtime_log.jsonl`:

- `record_type=llm_call_start` / `llm_call_end`: LLM calls. `llm_call_start.messages` is the exact prompt/messages sent to the model.
- `record_type=tool_call_start` / `tool_call_end`: tool calls.
- `record_type=tool_args_parse_error`: model returned invalid JSON function arguments.
- `record_type=tool_call_error`: tool raised an exception or an A2A expert failed internally.
- `record_type=agent_limit_exceeded`: main agent reached max tool calls or timeout.
- `record_type=agent_run_end` with `status=stopped`: normal limit stop.
- `record_type=agent_run_error`: real exception.

API errors are usually visible in:

```text
<run_dir>/<scenario>.runtime_log.jsonl
<run_dir>/stderr.log              # iclr_validation_runner.py batch runs
<run_dir>/command_stderr.log      # hand-written subprocess smoke runs
<run_dir>/<scenario>.run_report.json error field
```

Prompt inspection:

```text
<scenario>.runtime_log.jsonl      # record_type=llm_call_start has full messages
```

Token and runtime:

```text
run_report.metrics.token_usage
run_report.metrics.llm_wall_time_seconds
run_report.metrics.tool_wall_time_seconds
run_report.a2a.expert_metrics     # expert-layer token/runtime when A2A is on
runtime_log.jsonl                 # per-call details
```

## Tests

```bash
PYTHONPATH=. pytest -q tests/test_fairy_migration_smoke.py -q
python -m py_compile fairy/cli.py fairy/controllers/app_agent.py fairy/controllers/run_artifacts.py
rg "from are\\.|import are\\.|from rsare\\.|import rsare\\." fairy tests scripts \
  --glob '!scripts/selected_four_figures/data/**' \
  --glob '!scripts/iclr_validation_runner*.json'
```

For the `rg` guard, no output and return code 1 means no ARE/rsare runtime imports were found.

## Migration Boundaries And Known Limits

- FAIRY migrates FARM business logic, not the entire ARE benchmark framework.
- `farm_rewoo_modular` can enter `ReWOO plan fallback`; that means it is not yet full paper-run-level ReWOO planning.
- A2A on can significantly increase wall time and expert tokens. Always compare both main-agent token usage and `a2a.expert_metrics`.
- `tool_errors` in oracle baselines may be part of the intended scenario management plan; they do not always mean baseline construction failed.
