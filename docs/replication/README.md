# FAIRY experiment replication

This is the shortest supported path from a clean checkout to FAIRY FARM results.
Run every command from the repository root.

## 1. Clone and pin the code

The current integration branch is `main`.

```bash
git clone git@github.com:quaoq/FAIRY.git
# HTTPS alternative: git clone https://github.com/quaoq/FAIRY.git
cd FAIRY
git switch main
git pull --ff-only

# Refuse to start a published run from uncommitted code.
test -z "$(git status --porcelain)"

# Keep this hash with the experiment. Oracle baselines, runs, and replay should
# all use the same clean commit. If old traces must be rescored after a bug fix,
# record both the original run commit and the replay/scorer commit.
git rev-parse HEAD
```

Install Python 3.10 or newer. `uv` is the recommended environment manager:

```bash
python3 -m pip install uv  # omit when uv is already installed
uv sync
PYTHONPATH=. uv run python -m fairy.cli --list-controllers
PYTHONPATH=. uv run python -m fairy.cli --list | head
PYTHONPATH=. uv run pytest -q tests/test_fairy_migration_smoke.py
```

Without `uv`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 2. Configure a cloud provider

### DeepSeek Cloud

```bash
export DEEPSEEK_API_KEY='<key>'
# Optional OpenAI-compatible endpoint override:
# export DEEPSEEK_API_BASE='https://api.deepseek.com'
```

Do not put the key in a committed script. The batch runner also reads the
repository `.env`, but an exported environment variable is the least ambiguous
setup.

Run one scenario before starting a large sweep:

```bash
PYTHONPATH=. uv run python scripts/iclr_validation_runner.py \
  --phase deepseek_smoke \
  --output-root validation_runs/deepseek_smoke/phase5_paper_matrix \
  --families farm_baseline_react \
  --scenarios scenario_full_season_hb_base_hn84_std_normal \
  --repeats 1 \
  --provider deepseek \
  --model deepseek-chat \
  --model-family DeepSeek \
  --detail true \
  --a2a false \
  --system-prompt-mode fairy \
  --parallel-tool-calls false \
  --max-output-tokens 2048 \
  --agent-max-iterations 200 \
  --max-concurrent 1 \
  --cell-timeout-s 3600 \
  --progress-interval-s 60 \
  --cost-cap-dollars 9999
```

### Qwen Cloud

Use the OpenAI-compatible DashScope endpoint with the Qwen provider. The
rolling model alias is `qwen3.6-flash`; use the dated
`qwen3.6-flash-2026-04-16` snapshot when a published experiment must not move
to a newer backend revision.

```bash
export QWEN_API_KEY='<key>'
# DASHSCOPE_API_KEY is accepted as an alternative.
# Optional endpoint override:
# export QWEN_API_BASE='https://dashscope.aliyuncs.com/compatible-mode/v1'

PYTHONPATH=. uv run python scripts/iclr_validation_runner.py \
  --phase qwen36_flash_smoke \
  --output-root validation_runs/qwen36_flash_smoke/phase5_paper_matrix \
  --families farm_baseline_react \
  --scenarios scenario_farm_world_field_prep_physics_action_tick \
  --repeats 1 \
  --provider qwen \
  --model qwen3.6-flash-2026-04-16 \
  --model-family Qwen \
  --a2a false \
  --system-prompt-mode fairy \
  --parallel-tool-calls false \
  --max-output-tokens 2048 \
  --agent-max-iterations 200 \
  --max-concurrent 1 \
  --cell-timeout-s 3600 \
  --progress-interval-s 60 \
  --cost-cap-dollars 9999
```

This path was verified with the rolling `qwen3.6-flash` alias: the physics
smoke completed all 14 oracle tool steps with no LLM, tool, or parallel-call
errors. The short scenario reduces the number of tool turns, but keeps the same
`2048` output-token, `200` iteration, and `3600` second limits used for L3 runs.
Qwen3.6 Flash returned `reasoning_content`, so this configuration uses the
provider's default thinking mode; FAIRY does not currently override
`enable_thinking`.

The batch runner currently uses the `fairy.cli` default temperature `0.1` for
all providers. The same value is passed to the main agent and, when enabled,
all A2A agents. Confirm it in `run_report.json` under `temperature`.

`--parallel-tool-calls false` requests one tool call per model turn, adds that
rule to the system message, and keeps only the first call if a provider still
returns multiple calls. Change it to `true` only when multi-tool responses are
an intentional experiment factor.
`--detail true` selects the detailed scenario briefing. This full-season smoke
is a paid run and can consume millions of mostly cached input tokens. The runner
checks `--cost-cap-dollars` only after a cell finishes: at 80% it cancels queued
cells, but it cannot stop a cell that is already running. Treat the cap as a
batch guard, not a per-request or per-cell spending limit.

## 3. Select a scenario set

The runner accepts a comma-separated list of real scenario IDs. It does not
expand pool nicknames. Validate IDs with:

```bash
PYTHONPATH=. uv run python -m fairy.cli --list
```

Built-in manifests:

| Set | Source | Selection command |
|---|---|---|
| Formal L3 (90) | `scripts/fullseason/formal_90_scenario_ids.txt` | `SCENARIOS=$(grep -vE '^[[:space:]]*(#|$)' scripts/fullseason/formal_90_scenario_ids.txt \| paste -sd, -)` |
| L3-mini (20) | `scripts/fullseason/l3_mini_20_scenario_ids.txt` | `SCENARIOS=$(grep -vE '^[[:space:]]*(#|$)' scripts/fullseason/l3_mini_20_scenario_ids.txt \| paste -sd, -)` |
| Selected L2 (20) | `scripts/fullseason/selected_l2_l1_20_30_scenario_ids.txt` | `SCENARIOS=$(awk -F, '$1=="L2" {print $3}' scripts/fullseason/selected_l2_l1_20_30_scenario_ids.txt \| paste -sd, -)` |
| Selected L1 (30) | same manifest | `SCENARIOS=$(awk -F, '$1=="L1" {print $3}' scripts/fullseason/selected_l2_l1_20_30_scenario_ids.txt \| paste -sd, -)` |
| Selected L2+L1 (50) | same manifest | `SCENARIOS=$(awk -F, 'NF>=3 && $1 !~ /^#/ {print $3}' scripts/fullseason/selected_l2_l1_20_30_scenario_ids.txt \| paste -sd, -)` |
| L2 skill set (72) | `scripts/fullseason/l2_skill_scenario_ids.txt` | `SCENARIOS=$(grep -vE '^[[:space:]]*(#|$)' scripts/fullseason/l2_skill_scenario_ids.txt \| paste -sd, -)` |

`L3-mini` contains exactly these 20 scenarios:

```text
scenario_full_season_hb_organic_residue_weed_establishment
scenario_full_season_hb_organic_patch_weed_mechanical_capacity
scenario_full_season_hb_micronutrient_deficiency_flowering_patch
scenario_full_season_hb_local_soil_constraint_nutrition_patch
scenario_full_season_heinong84_edge_low_fertility
scenario_full_season_hb_cloudy_wet_low_radiation_biomass
scenario_full_season_hb_poordrainage_wetjune_disease_trafficability
scenario_full_season_hb_staggered_wetjune_canopy_disease
scenario_full_season_hb_soy_after_soy_wetjune_disease
scenario_full_season_hb_dryr5r6_hn58_std_waterlimit
scenario_full_season_hb_drought_recovery_false_disease_signal
scenario_full_season_hb_heinong58_resistant_biotic_water_budget_priority
scenario_full_season_hb_hn60_high_fastdrain_dryr5r6
scenario_full_season_hb_dryr5r6_insect_threshold_waterstress
scenario_full_season_hb_dryer_capacity_batch_harvest_storage
scenario_full_season_hb_grain_moisture_sensor_failure_harvest
scenario_full_season_hb_laterain_shattering_drying_tradeoff
scenario_full_season_hb_cool_august_lategrain_laterain
scenario_full_season_hb_compacted_headland_stand_recovery
scenario_full_season_hb_hn50_hn84_hn58_mixed_stress
```

After setting `SCENARIOS`, reuse the command in section 2 with:

```bash
--scenarios "$SCENARIOS"
```

Keep `detail`, controller, system-prompt mode, parallel-tool policy, model,
timeouts, output-token cap, and commit hash fixed when comparing runs.

## 4. Build oracle baselines and launch the sweep

Build the corresponding no-LLM oracle baseline on the same commit. Named pool
aliases are supported by this oracle script, even though the batch runner does
not expand them:

```bash
# Use formal90, l3_mini_20, selected_l2_l1_20_30, or l2_skill_72.
PYTHONPATH=. uv run python scripts/build_oracle_baselines.py \
  --scenarios formal90 \
  --output-dir validation_runs/oracle_baselines_formal90 \
  --include-donothing \
  --continue-on-error
```

For L3-mini, the oracle builder accepts its named alias directly:

```bash
PYTHONPATH=. uv run python scripts/build_oracle_baselines.py \
  --scenarios l3_mini_20 \
  --output-dir validation_runs/oracle_baselines_l3_mini_20 \
  --include-donothing \
  --continue-on-error
```

For any other custom set, pass the same expanded CSV used by the runner.

Then run the full batch by replacing the smoke scenario with
`--scenarios "$SCENARIOS"`. Each completed cell is checkpointed immediately in
`results.csv`; interrupted runs therefore retain completed results. Use a new
output directory for retries so the original evidence is not overwritten.

## 5. Inspect and score a run

Read artifacts in this order:

1. `*.run_report.json`: completion state, stop reason, aggregate tokens, tool
   calls, LLM time, outcome, and artifact paths. A subprocess killed by the
   outer batch timeout may exit before this file is written.
2. `*.runtime_log.jsonl`: exact message context plus per-call LLM timing,
   prompt/completion/cached tokens, returned text, tool calls, and errors.
3. `*.agent_workflow.json`: ordered semantic tool trace used for replay.
4. `*.progress.jsonl`: live lightweight events; useful even when a cell times out.
5. `stdout.log`, `stderr.log`, and batch `results.csv`: process diagnostics and
   outer timeout status (`timed_out`, `force_killed`, and `return_code`). These
   are authoritative when no final `run_report` exists. `results.csv` is not the
   authoritative final FOS table.

Create a quick run-status table:

```bash
PYTHONPATH=. uv run python scripts/summarize_runs.py \
  validation_runs/<experiment>/phase5_paper_matrix \
  --csv validation_runs/<experiment>/run_summary.csv
```

Replay saved traces and calculate paper metrics without another LLM call:

```bash
PYTHONPATH=. uv run python scripts/rebatch_fos_from_traces.py \
  --root validation_runs/<experiment>/phase5_paper_matrix \
  --out-root validation_runs/<experiment>/rebatch_fos \
  --oracle-baselines validation_runs/<matching_oracle_baselines> \
  --extrapolate \
  --workers 4
```

Use `rebatch_fos/summary_v2.csv` as the metric table. Important columns are:

| Group | Columns |
|---|---|
| Outcome | `yield_loss(%)`, `recovered_yield_loss(%)`, `recovered_yield_loss_v2(%)`, `agent_biological_kg`, `oracle_biological_kg` |
| Generic FOS components | `fos(%)`, `outcome(%)`, `decision(%)`, `efficiency(%)` |
| Tool/path baselines | `path_correctness(%)`, `ktc_score(%)`, `core_path_correctness(%)`, `ktc(%)`, `bfcl_success(%)` |
| FARM metrics | `farm_fos(%)`, `farm_fos_v2_total(%)`, its path/parameter/terminal components, and diagnosis columns |
| Work/cost | `agent_tool_calls`, `llm_calls_with_usage`, average input/output/cached tokens per call, total tokens per scenario, average LLM seconds per call, runtime per scenario |
| Replay execution | `replayed_events`, `replay_executed_actions`, `replay_restored_error_events`, `replay_exec_errors`, exact/legacy timing step counts |

`yield_loss(%)` is biological loss relative to the matching oracle baseline.
Recovered-yield loss also reflects harvest/post-harvest execution. Do not average
rows whose `status` is not `ok`; first inspect their replay and run error columns.
Replay follows ARE semantics: it executes every executable recorded tool in
order to rebuild scenario state, while evaluation events retain the return
values recorded in the original trace. Random sensor reads are therefore not
required to reproduce the same random sample in a new process.
Legacy A2A runs are an exception when their artifacts retain only the last
expert workflow per wrapped app: the omitted earlier expert tool calls cannot
be reconstructed from the main `expert_agent` summary call. Do not report an
exact replay for such a bundle.
Some full-season scenarios define no generic decision gates; their
`decision_breakdown` is empty and `decision(%)` is therefore zero. For those
scenarios, report the FARM-specific scores and their diagnostic columns instead
of interpreting generic `fos(%)` as the headline decision-quality score.

## 6. Add a scenario

Start from the closest scenario in
`fairy/scenarios/farm_world_fullseason_v2/`, not from a blank file.

1. Choose a unique `SCENARIO_ID` and decorate the class with
   `@register_scenario(SCENARIO_ID)`.
2. In `init_and_populate_apps`, call `install_common_farm_apps(...)` and
   configure the physics profile/initial state. Add or replace apps there.
3. In `build_events_flow`, create the briefing and timestamped oracle DAG.
   Oracle actions use `.oracle().with_id(...).depends_on(...)`.
4. Finish with `self.events = collect_event_graph(briefing)`.
5. Add the scenario ID to a versioned manifest if it belongs to an experiment
   pool, then build a fresh oracle baseline.

The registry walks the known scenario packages automatically, so a module under
the existing package does not need a manual import in `__init__.py`.

Minimum checks:

```bash
PYTHONPATH=. uv run python -m fairy.cli --list | grep '<new_scenario_id>'
PYTHONPATH=. uv run python -m fairy.cli \
  -s <new_scenario_id> --build-oracle --run-oracle-tools \
  --output-dir validation_runs/oracle_smoke/<new_scenario_id>
```

## 7. Add sensors, a rover, or another API tool

FAIRY currently models derived, ridge-level observations rather than raw image
files. The existing drone path already provides multispectral NDVI and thermal
canopy temperature; `ObservationModel` also implements UAV LiDAR. `RobotApp`
already provides ridge, pest, crop-health, and emergence inspection.

Use the smallest applicable extension path:

### Expose an existing modality

For example, to expose the existing UAV LiDAR product, add an agent-facing
method to `DroneApp` that calls `observation_model.observe_uav_lidar(...)`,
returns a JSON-serializable product, and accounts for mission time/battery.
No new physics truth is required.

### Add a genuinely new sensor stream

1. Add hidden truth only if the physics engines do not already model the
   quantity.
2. Add modality/product enums, noise, latency, coverage, and an `observe_*`
   method in `fairy/physics/observation_model.py`.
3. Register its `SensorAsset` in `FarmPhysicsState` or scenario setup.
4. Add a typed, documented tool method to `SensorApp`, `DroneApp`, or
   `RobotApp`; return observations, never hidden truth.
5. Add the app to `scenario.apps`, use the tool in the oracle DAG, and add FOS
   gates/validation that make the new evidence operationally necessary.

To add more observation times rather than a new modality, keep the same sensor
tool and add repeated oracle read nodes separated by `SystemApp.advance_time`.
Set revisit/latency parameters in `ObservationModelParameters` when the stream
must not be available continuously.

### Add an HZAU rover

If the rover has the same ground-inspection semantics, instantiate `RobotApp`
with a distinct `name` and description in scenario setup. If it has different
mobility, battery, payload, or actions, implement a dedicated app using
`RobotApp` as the behavioral reference, then append that instance to
`scenario.apps`. Every app receives the shared simulation clock automatically.

An agent-visible API method follows the existing pattern:

```python
@type_check
@app_tool()
@event_registered(operation_type=OperationType.READ)
def read_new_sensor(self, ridge_id: int, samples: int = 1) -> dict[str, Any]:
    """Read the new sensor product for one ridge."""
    ...
```

Use `WRITE` instead of `READ` when the call changes state, consumes a resource,
or advances time. Tool names and schemas are generated automatically as
`<AppName>__<method>`. Parameters without defaults are required; parameters
with defaults are optional. The docstring becomes the model-visible tool
description, so it is part of experiment behavior.

Add tests for the observation/noise behavior, state/time/resource effects,
generated tool schema, oracle execution, and replay. Re-run the migration smoke
test before publishing the new scenario or API.

## Reproducibility checklist

- Record commit hash, scenario manifest, provider/model, controller, seed/repeat,
  detail mode, system prompt mode, parallel-tool setting, token/iteration/time
  limits, and A2A settings.
- Build oracle baselines and replay with the same code revision as the agent run.
- Preserve original run directories; retry failures into a separate directory.
- Report failed/time-out cells separately and aggregate only verified replay rows.
