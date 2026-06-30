# FAIRY

[中文说明](README.zh-CN.md)

FAIRY is an independent Python runtime for farm-agent simulation, scenario
execution, oracle replay, and evaluation. It packages the FARM business logic
that was previously embedded in ARE into a standalone `fairy` package with
lightweight FarmAgent-style controllers and OpenAI-compatible function calling.

FAIRY is designed for reproducible agricultural-agent experiments: the same
scenario can be initialized, converted into an oracle workflow, replayed against
fresh farm state, and evaluated from the resulting workflow and physics state.

## Highlights

- Standalone `fairy` Python package, decoupled from ARE runtime imports.
- Farm-world apps for weather, sensors, drones, robots, tractors, field
  operations, inventory, time control, and user messages.
- Physics engines for soil water, weather, phenology, canopy and biomass,
  management effects, biotic pressure, observation, and recovered yield.
- Baseline farm scenarios, action-tick physics scenarios, and L3 full-season
  scenarios.
- Oracle workflow generation with the stable JSON shape:
  `name`, `content`, `op_type`, `tool_name`, `tool_args`, `depends_on`, `time`.
- Workflow replay against fresh scenario state.
- Evaluation reports for oracle-sequence matching and scenario validation.
- OpenAI-compatible function-tool runtime for DeepSeek, OpenAI, and similar chat
  completion providers.
- Controller families including ReAct-style, planner-executor, ReWOO-style,
  reflective memory, verifier, tree-search, critic-refiner, and graph-memory
  variants.

## Repository Layout

```text
fairy/
  agents/        LLM clients, tool-calling loop, message handling
  apps/          Base app layer, SystemApp, FarmWorld apps
  controllers/   Engine, scenario runtime, replay/evaluation, controller families
  physics/       FARM physics engines and profiles
  scenarios/     Scenario base class, registry, FARM scenario suites
scripts/         CLI entrypoints
tests/           Migration, oracle, replay, and controller smoke tests
docs/ai/         Maintainer notes for execution paths and test commands
```

## Installation

FAIRY currently targets Python 3.10 or newer. From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

For local development in the original FARM checkout, the existing Python 3.12
environment can also be used:

```bash
PYTHONPATH=. /Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.venv312/bin/python scripts/run_scenario.py --list
```

## Quick Start

List migrated scenarios:

```bash
fairy-run --list
```

List available controller families:

```bash
fairy-run --list-controllers
```

Build an oracle workflow, replay it against fresh state, and evaluate it:

```bash
fairy-run \
  -s scenario_farm_world_field_prep_physics_action_tick \
  --build-oracle --replay --evaluate \
  --workflow validation_runs/fairy_smoke/oracle_baselines/scenario_farm_world_field_prep_physics_action_tick.json \
  --output-dir validation_runs/fairy_smoke/oracle_replay/scenario_farm_world_field_prep_physics_action_tick
```

The command writes a run bundle. Open `*.run_report.json` first; it explains
the status, metrics, evaluation, outcome, and all artifact paths:

```text
validation_runs/fairy_smoke/oracle_baselines/scenario_farm_world_field_prep_physics_action_tick.json
validation_runs/fairy_smoke/oracle_replay/scenario_farm_world_field_prep_physics_action_tick/scenario_farm_world_field_prep_physics_action_tick.run_report.json
validation_runs/fairy_smoke/oracle_replay/scenario_farm_world_field_prep_physics_action_tick/scenario_farm_world_field_prep_physics_action_tick.events.jsonl
validation_runs/fairy_smoke/oracle_replay/scenario_farm_world_field_prep_physics_action_tick/scenario_farm_world_field_prep_physics_action_tick.replay.json
validation_runs/fairy_smoke/oracle_replay/scenario_farm_world_field_prep_physics_action_tick/scenario_farm_world_field_prep_physics_action_tick.evaluation.json
```

Run an L3 full-season oracle/replay/evaluation smoke:

```bash
fairy-run \
  -s scenario_full_season_balanced \
  --build-oracle --replay --evaluate \
  --workflow validation_runs/fairy_l3/oracle_baselines/scenario_full_season_balanced.json \
  --output-dir validation_runs/fairy_l3/oracle_replay/scenario_full_season_balanced
```

Run a real DeepSeek function-calling agent with wall-time and tool-call limits:

```bash
fairy-run \
  -s scenario_full_season_balanced \
  --agent \
  --controller farm_baseline_react \
  --provider deepseek \
  --model deepseek-chat \
  --temperature 0.2 \
  --max-tool-calls 300 \
  --timeout-seconds 1200 \
  --output-dir validation_runs/fairy_l3/phase5_paper_matrix/farm_baseline_react__scenario_full_season_balanced__r1
```

## Runtime Model

FAIRY uses one scenario entry point:

```python
scenario.setup()
```

Migrated code can still use compatibility hooks:

```python
scenario.initiate_scenario()
scenario.init_and_populate_apps()
```

The core execution path is:

```text
Scenario.setup()
  -> Engine.build_oracle_workflow()
  -> Workflow.save_workflow()
  -> fresh Engine.replay_workflow()
  -> Engine.evaluation_report()
```

Agent execution uses OpenAI-compatible function calling:

```text
ControllerAgent.run()
  -> chat.completions.create(..., tools=[...])
  -> message.tool_calls
  -> AppName__method(**tool_args)
  -> workflow step recorded
```

Tool names are preserved as:

```text
AppName__method_name
```

## Scenarios

FAIRY includes three migrated FARM scenario groups:

- Baseline farm-world scenarios, such as field preparation, planting,
  irrigation, pesticide response, drone survey, and harvest.
- Physics action-tick scenarios, where tool actions update farm physics and
  time-dependent state.
- L3 full-season scenarios, including balanced season, adverse weather,
  aphid-pressure, dry pod-fill, wet June disease pressure, resource-limited,
  nutrient differential, and Tangyan5 calibration scenarios.

Example scenario identifiers:

```text
scenario_farm_world_field_prep
scenario_farm_world_field_prep_physics_action_tick
scenario_farm_world_harvest_physics_action_tick
scenario_full_season_balanced
scenario_full_season_dry_pod_fill
scenario_tangyan5_base_full_season
```

## Physics And Yield Recovery

FAIRY preserves the FARM physics model used by the migrated scenarios. The
full-season path includes:

- daily soil and weather updates,
- phenology and maturity,
- canopy, biomass, and biological yield potential,
- management effects from planting, irrigation, fertilizer, pesticide, and
  harvest actions,
- biotic pressure,
- grain moisture,
- field loss,
- machine/header loss,
- recovered yield,
- drying and storage state.

Recovered-yield state is represented with fields such as:

```text
biological_yield_g_m2
field_loss_fraction
machine_loss_fraction
recovered_yield_g_m2_at_market_moisture
recovered_yield_kg_ha_at_market_moisture
quality_discount_fraction
```

Final grain inventory is exposed through farm inventory fields such as:

```text
harvest_grain_kg
warehouse_grain_kg
grain_dried
```

## Evaluation

Evaluation currently supports:

- oracle sequence matching for physics action-tick scenarios,
- scenario-provided validation hooks,
- replay reports containing workflow step counts, matched tools, missing tools,
  score, threshold, and environment metadata,
- L3 full-season replay and validation entrypoints.

The validation report is written as JSON and can be consumed by experiment
pipelines.

## Run Artifacts And Logs

FAIRY follows the FARM experiment layout:

```text
validation_runs/<phase>/phase5_paper_matrix/<agent_family>__<scenario_id>__r<repeat>/
validation_runs/<phase>/oracle_baselines/<scenario_id>.json
validation_runs/<phase>/oracle_replay/<scenario_id>/
```

Each cell directory is intentionally a bundle. For normal experiment reading,
start with only two files inside the cell:

```text
*.run_report.json   status, stop reason, limits, wall time, token totals,
                    evaluation, outcome, errors, and artifact guide
*.events.jsonl      runtime event stream: agent, LLM, tool, limit, and error
                    events in chronological order
```

Deep debugging files are kept separately:

```text
*.agent_workflow.json   replay/audit workflow with tool names, args, results,
                        dependencies, and simulation time
*.messages.json         raw LLM conversation and tool responses
*.runtime_metrics.json  per-call LLM/tool timing and token details
*.evaluation.json       validation and FARM outcome summary
*.run_summary.json      legacy machine-readable summary
*.run_log.jsonl         replay tool log for oracle/replay runs
```

If an agent stops because of `--timeout-seconds` or `--max-tool-calls`, the
run still writes `run_report.json` and `events.jsonl`. The report contains
`status`, `stopped_reason`, `limits`, `metrics`, and `error`; the event stream
contains `agent_limit_exceeded` plus the final `agent_run_error` row. LLM API
errors are logged as `llm_call_error`; malformed function-call arguments are
logged as `tool_args_parse_error`; tool exceptions are logged as
`tool_call_error`.

Summarize many runs as a table:

```bash
PYTHONPATH=. python scripts/summarize_runs.py validation_runs/<phase> --csv validation_runs/<phase>/summary.csv
```

## LLM Providers

FAIRY's agent path is function-call based. DeepSeek is supported through an
OpenAI-compatible client:

```bash
export DEEPSEEK_API_KEY=...
```

Then run with `fairy-run --agent ...` or construct a controller agent in user
code with a DeepSeek client and a scenario's app toolsets.

## Testing

Run the migration smoke suite:

```bash
PYTHONPATH=. python -m pytest tests/test_fairy_migration_smoke.py -q
```

Check that runtime code no longer imports ARE or rsare:

```bash
rg "from are\.|import are\.|from rsare\.|import rsare\." fairy tests
```

The smoke suite covers:

- module import checks,
- scenario registry checks,
- baseline oracle workflow checks,
- physics action-tick oracle checks,
- full-season oracle checks,
- `SystemApp.advance_time()` physics behavior,
- controller-family construction,
- oracle build, workflow replay, and evaluation.

## Release Status

FAIRY v1 is ready as a standalone FARM scenario runtime and evaluation
foundation. The FARM business logic, physics engines, controllers, scenarios,
oracle workflow generation, replay, and evaluation entrypoints are packaged in
the independent `fairy` runtime.

The product roadmap includes stricter L3 outcome metrics, broader yield-loss
evaluation summaries, packaging metadata, CI, and published API documentation.
