# Migration Audit 2026-07-01

This note records the concrete FAIRY migration checks run on 2026-07-01.
Generated artifacts live under `validation_runs/migration_audit_20260701/`.

## Command Log

```bash
mkdir -p validation_runs/migration_audit_20260701/{logs,oracle,agent,rebatch,reports,tmp} && find validation_runs/migration_audit_20260701 -maxdepth 2 -type d | sort
sed -n '1,220p' pyproject.toml
PYTHONPATH=. uv run python -m fairy.cli --help
PYTHONPATH=. uv run python scripts/build_oracle_baselines.py --help
PYTHONPATH=. uv run python scripts/rebatch_fos_from_traces.py --help
pwd && git status --short && sed -n '1,220p' .gitignore && sed -n '1,80p' tests/test_fairy_migration_smoke.py
sed -n '1,260p' /Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.codex/skills/karpathy-code-method/SKILL.md
rg -n "WeatherEvent|weather_event|rain_event|_build_weather_inputs|SystemApp__advance_time|run_log|runtime_metrics|farm_skill_rag|controller" tests/test_fairy_migration_smoke.py fairy docs/ai README.md README.zh-CN.md scripts
rg -n "def _build_weather_inputs|class WeatherEvent|def get_current_weather|def advance_time|def commit_daily_physics|WeatherEvent\\(" fairy/apps/farm_world fairy/physics fairy/apps/system.py
sed -n '80,260p' tests/test_fairy_migration_smoke.py
sed -n '680,760p' fairy/apps/farm_world/physics_orchestrator.py
sed -n '40,115p' fairy/apps/farm_world/weather_app.py && sed -n '180,230p' fairy/apps/farm_world/weather_app.py
sed -n '355,405p' fairy/physics/weather_engine.py && sed -n '384,405p' fairy/physics/weather_engine.py
sed -n '190,235p' fairy/physics/profiles.py
sed -n '1,90p' fairy/scenarios/registry.py && rg -n "def get_scenario|scenario_full_season_hb_wetjune_short_spray_window|WetjuneShort" fairy/scenarios
PYTHONPATH=. uv run python - <<'PY'
from datetime import date
from fairy.scenarios.registry import get_scenario_class
from fairy.apps.farm_world import FarmWorldApp, WeatherApp
from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs

cls = get_scenario_class('scenario_full_season_hb_wetjune_short_spray_window')
scenario = cls()
scenario.setup()
farm = scenario.get_typed_app(FarmWorldApp)
weather = scenario.get_typed_app(WeatherApp)
inputs = _build_weather_inputs(weather, date(2026, 6, 15), farm.physics)
print('profile', farm.physics.profile.name)
print('soil_rain_mm', inputs['soil'].rain_mm)
print('weather_tool', weather.get_current_weather())
print('forecast_first', weather.get_forecast(1)['forecast'][0])
PY
tail -n 80 docs/ai/architecture.md
PYTHONPATH=. uv run pytest -q tests/test_fairy_migration_smoke.py
PYTHONPATH=. uv run python -m fairy.cli --list-controllers
rg "from are\\.|import are\\.|from rsare\\.|import rsare\\." fairy tests scripts
find fos_exports workflow_exports -maxdepth 2 -type f | sort | head -50
PYTHONPATH=. uv run python - <<'PY'
from fairy.scenarios.registry import list_scenarios
scenarios = list_scenarios()
formal = [x.strip() for x in open('scripts/fullseason/formal_90_scenario_ids.txt') if x.strip()]
selected = [x.strip() for x in open('scripts/fullseason/selected_l2_l1_20_30_scenario_ids.txt') if x.strip()]
l2 = [x.strip() for x in open('scripts/fullseason/l2_skill_scenario_ids.txt') if x.strip() and not x.lstrip().startswith('#')]
print('registered_total', len(scenarios))
print('formal90_count', len(formal), 'missing', sorted(set(formal)-set(scenarios)))
print('selected_l2_l1_20_30_count', len(selected), 'missing', sorted(set(selected)-set(scenarios)))
print('l2_skill_72_count', len(l2), 'missing', sorted(set(l2)-set(scenarios)))
PY
PYTHONPATH=. uv run python - <<'PY'
from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_batch_catalog import HARbIN_L3_SPECS
specs = HARbIN_L3_SPECS
with_weather = [s for s in specs if s.weather_events]
with_rain = [s for s in specs if any(e.event_type == 'rain_event' for e in s.weather_events)]
print('catalog_specs', len(specs))
print('with_weather_events', len(with_weather))
print('with_rain_event', len(with_rain))
PY
rg -n "HARBIN|SPECS|selected_l2_l1" fairy/scenarios/farm_world_fullseason_v2/harbin_l3_batch_catalog.py scripts/build_oracle_baselines.py scripts/rebatch_fos_from_traces.py
sed -n '1,90p' scripts/fullseason/selected_l2_l1_20_30_scenario_ids.txt && sed -n '1,160p' scripts/build_oracle_baselines.py
PYTHONPATH=. uv run python - <<'PY'
from fairy.scenarios.registry import list_scenarios
from scripts.build_oracle_baselines import _selected_l2_l1_scenarios
scenarios = set(list_scenarios())
selected = _selected_l2_l1_scenarios()
print('selected_l2_l1_20_30_count', len(selected))
print('missing', sorted(set(selected)-scenarios))
PY
PYTHONPATH=. uv run python - <<'PY'
from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_batch_catalog import SPECS
specs = list(SPECS.values())
with_weather = [s for s in specs if s.weather_events]
with_rain = [s for s in specs if any(e.event_type == 'rain_event' for e in s.weather_events)]
print('catalog_specs', len(specs))
print('with_weather_events', len(with_weather))
print('with_rain_event', len(with_rain))
PY
sed -n '1,120p' fairy/scenarios/farm_world_fullseason_v2/harbin_l3_batch_catalog.py && rg -n "PHYSICS_PROFILES|profiles\\[|def get_physics_profile|weather_events" fairy/physics/profiles.py fairy/physics/__init__.py
sed -n '1,95p' fairy/physics/profiles.py && sed -n '70,115p' fairy/physics/__init__.py
PYTHONPATH=. uv run python - <<'PY'
from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_batch_catalog import SPECS
from fairy.physics.profiles import get_profile
profiles = [get_profile(spec.profile_name) for spec in SPECS.values()]
missing = [spec.scenario_id for spec, profile in zip(SPECS.values(), profiles) if profile is None]
with_weather = [profile for profile in profiles if profile and profile.weather_events]
with_rain = [profile for profile in profiles if profile and any(e.event_type == 'rain_event' for e in profile.weather_events)]
print('catalog_specs', len(SPECS))
print('missing_profiles', len(missing), missing[:10])
print('with_weather_events', len(with_weather))
print('with_rain_event', len(with_rain))
PY
PYTHONPATH=. uv run python scripts/build_oracle_baselines.py --scenarios selected_l2_l1_20_30 --output-dir validation_runs/migration_audit_20260701/oracle/selected_l2_l1_20_30 --max-days 180 --force --include-donothing --continue-on-error
PYTHONPATH=. uv run python scripts/build_oracle_baselines.py --scenarios formal90 --output-dir validation_runs/migration_audit_20260701/oracle/formal90 --max-days 180 --force --include-donothing --continue-on-error
PYTHONPATH=. uv run python scripts/build_oracle_baselines.py --scenarios l2_skill_72 --output-dir validation_runs/migration_audit_20260701/oracle/l2_skill_72 --max-days 180 --force --include-donothing --continue-on-error
PYTHONPATH=. uv run python - <<'PY'
import os
for key in ['DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'QWEN_API_KEY', 'DASHSCOPE_API_KEY', 'VLLM_API_KEY']:
    print(key, 'set' if os.getenv(key) else 'missing')
PY
PYTHONPATH=. uv run python -m fairy.cli -s scenario_farm_world_field_prep --agent --controller farm_baseline_react --provider deepseek --model deepseek-chat --temperature 0.1 --max-tool-calls 20 --timeout-seconds 300 --output-dir validation_runs/migration_audit_20260701/agent/farm_baseline_react__scenario_farm_world_field_prep__r1
PYTHONPATH=. uv run python -m fairy.cli -s scenario_full_season_hb_wetjune_short_spray_window --agent --controller farm_rewoo_modular --provider deepseek --model deepseek-chat --temperature 0.1 --max-tool-calls 60 --timeout-seconds 600 --scenario-kwargs '{"detailed_briefing":"kwoo"}' --output-dir validation_runs/migration_audit_20260701/agent/farm_rewoo_modular__scenario_full_season_hb_wetjune_short_spray_window__kwoo__r1
PYTHONPATH=. uv run python - <<'PY'
import json
from pathlib import Path
for p in [
Path('validation_runs/migration_audit_20260701/agent/farm_baseline_react__scenario_farm_world_field_prep__r1/scenario_farm_world_field_prep.run_report.json'),
Path('validation_runs/migration_audit_20260701/agent/farm_rewoo_modular__scenario_full_season_hb_wetjune_short_spray_window__kwoo__r1/scenario_full_season_hb_wetjune_short_spray_window.run_report.json'),
]:
    r=json.loads(p.read_text())
    print('FILE', p)
    print('status', r.get('status'), 'stop_reason', r.get('stop_reason'), 'wall', r.get('wall_time_seconds'))
    print('scenario', r.get('scenario_id'), 'controller', r.get('controller_id'), 'model', r.get('model'))
    print('limits', r.get('limits'))
    print('metrics', r.get('metrics'))
    print('a2a', r.get('a2a'))
    print('evaluation', r.get('evaluation'))
PY
wc -l validation_runs/migration_audit_20260701/agent/farm_baseline_react__scenario_farm_world_field_prep__r1/scenario_farm_world_field_prep.events.jsonl validation_runs/migration_audit_20260701/agent/farm_rewoo_modular__scenario_full_season_hb_wetjune_short_spray_window__kwoo__r1/scenario_full_season_hb_wetjune_short_spray_window.events.jsonl && tail -n 8 validation_runs/migration_audit_20260701/agent/farm_rewoo_modular__scenario_full_season_hb_wetjune_short_spray_window__kwoo__r1/scenario_full_season_hb_wetjune_short_spray_window.events.jsonl
PYTHONPATH=. uv run python - <<'PY'
import json
from pathlib import Path
p=Path('validation_runs/migration_audit_20260701/agent/farm_rewoo_modular__scenario_full_season_hb_wetjune_short_spray_window__kwoo__r1/scenario_full_season_hb_wetjune_short_spray_window.messages.json')
data=json.loads(p.read_text())
for i, msg in enumerate(data[:4]):
    print('MSG', i, msg.get('role'))
    content=str(msg.get('content'))
    print(content[:1200].replace('\n',' ') if content else '')
PY
sed -n '1,220p' fairy/controllers/run_artifacts.py
rg -n "stop_reason|wall_time_seconds|write_run_report|build_run_report|agent_limit_exceeded|stopped_reason" fairy/cli.py fairy/controllers fairy/agents tests/test_fairy_migration_smoke.py
sed -n '520,660p' tests/test_fairy_migration_smoke.py
sed -n '660,720p' tests/test_fairy_migration_smoke.py
PYTHONPATH=. uv run pytest -q tests/test_fairy_migration_smoke.py
PYTHONPATH=. uv run python -m fairy.cli -s scenario_farm_world_field_prep --agent --controller farm_baseline_react --provider deepseek --model deepseek-chat --temperature 0.1 --max-tool-calls 5 --timeout-seconds 180 --output-dir validation_runs/migration_audit_20260701/agent/report_field_check__scenario_farm_world_field_prep__r1
PYTHONPATH=. uv run python - <<'PY'
import json
p='validation_runs/migration_audit_20260701/agent/report_field_check__scenario_farm_world_field_prep__r1/scenario_farm_world_field_prep.run_report.json'
r=json.load(open(p))
print('status', r['status'])
print('stopped_reason', r['stopped_reason'])
print('stop_reason', r['stop_reason'])
print('wall_time_seconds', r['wall_time_seconds'])
print('metrics.wall_time_seconds', r['metrics']['wall_time_seconds'])
print('token_usage', r['metrics']['token_usage'])
PY
tail -n 6 validation_runs/migration_audit_20260701/agent/report_field_check__scenario_farm_world_field_prep__r1/scenario_farm_world_field_prep.events.jsonl
PYTHONPATH=. uv run python -m fairy.cli -s scenario_farm_world_field_prep_physics_action_tick --build-oracle --replay --evaluate --workflow validation_runs/migration_audit_20260701/oracle_replay/scenario_farm_world_field_prep_physics_action_tick/scenario_farm_world_field_prep_physics_action_tick.oracle.json --output-dir validation_runs/migration_audit_20260701/oracle_replay/scenario_farm_world_field_prep_physics_action_tick
PYTHONPATH=. uv run python scripts/rebatch_fos_from_traces.py --root validation_runs/migration_audit_20260701/agent --out-root validation_runs/migration_audit_20260701/rebatch/agent_runs --recursive --oracle-baselines validation_runs/migration_audit_20260701/oracle/formal90 --extrapolate --workers 1
head -n 1 validation_runs/migration_audit_20260701/rebatch/agent_runs/summary_v2.csv | tr ',' '\n' | nl -ba
sed -n '1,6p' validation_runs/migration_audit_20260701/rebatch/agent_runs/summary_v2.csv
find validation_runs/migration_audit_20260701 -maxdepth 3 -type f | sort | sed -n '1,160p'
rm -rf fos_exports workflow_exports && git status --short
```

## Results

- Smoke tests: `37 passed`.
- Static import guard: no runtime `are.*` or `rsare.*` imports in `fairy`, `tests`, or `scripts`.
- Controller list: `default`, `farm_world`, `farm_baseline_react`, `farm_planner_executor`,
  `farm_reflective_memory`, `farm_multi_specialist`, `farm_adaptive_verifier`,
  `farm_rewoo_modular`, `farm_tree_search`, `farm_critic_refiner`, `farm_graph_memory`.
- Scenario registration: 310 total registered scenarios; formal90 = 90/90 present;
  selected L2/L1 = 50/50 present; L2 skill = 72/72 present.
- Oracle baselines:
  - `selected_l2_l1_20_30`: ok=50, fail=0.
  - `formal90`: ok=90, fail=0.
  - `l2_skill_72`: ok=72, fail=0.
- Real DeepSeek function-call agent:
  - `farm_baseline_react__scenario_farm_world_field_prep__r1`: completed, 13 tool calls,
    14 LLM calls, 134828 total tokens, validation success.
  - `farm_rewoo_modular__scenario_full_season_hb_wetjune_short_spray_window__kwoo__r1`:
    stopped at `max_tool_calls=60`, 47 LLM calls, 956447 total tokens. This is an
    intentionally bounded L3 real-agent run, not a completed full-season run.
  - `report_field_check__scenario_farm_world_field_prep__r1`: stopped at
    `max_tool_calls=5`; used to verify top-level `stop_reason` and
    `wall_time_seconds` fields.
- Offline oracle/replay/evaluate:
  - `scenario_farm_world_field_prep_physics_action_tick`: replay/evaluate success,
    matched 14/14 oracle steps, score=1.0.
- Rebatch/FOS:
  - Wrote `validation_runs/migration_audit_20260701/rebatch/agent_runs/summary_v2.csv`
    with 92 columns including token/time fields, yield loss, recovered yield loss,
    FOS, replayed events, skipped/errors, and focus-yield fields.

## WeatherEvent Boundary

Fact: `WeatherEvent(event_type="rain_event")` is used by full-season physics
profiles, but it is not a FAIRY framework `Event`.

Observed path:

`PhysicsProfile.weather_events` -> `WeatherGenerator.generate(..., events=...)`
-> `WeatherGenerator._apply_events()` -> `_build_weather_inputs()` ->
`WeatherApp.set_weather()` -> agent-visible `WeatherApp__get_current_weather`.

The regression case for `scenario_full_season_hb_wetjune_short_spray_window`
showed `rainfall_mm=94.76` on 2026-06-15. The agent-visible weather tool did
not expose `weather_tags` or `rain_event` as workflow data.

## Code Changes From This Audit

- Added a regression test for `WeatherEvent` being physics input rather than a
  framework workflow event.
- Added top-level `stop_reason` and `wall_time_seconds` aliases to
  `run_report.json`, while preserving existing `stopped_reason` and
  `metrics.wall_time_seconds`.
- Added tests for the report aliases.
- Added `fos_exports/` and `workflow_exports/` to `.gitignore`.
- Added durable architecture notes for WeatherEvent semantics.

## Remaining Gaps

- The L3 `farm_rewoo_modular` bounded run shows `plan_parse_failures=47`.
  Function calling works, but the current ReWOO structured-plan parser is not
  extracting structured steps from DeepSeek responses. It falls back to ReAct,
  so behavior is runnable but not paper-grade ReWOO.
- `rebatch_fos_from_traces.py` currently prints tool return dicts to stdout
  during replay. The CSV is correct, but the command log is noisy.
- `farm_rewoo_modular` L3 run used `STANDARD` seed, 0.75m ridges, and 15cm
  spacing in a scenario whose prompt expects a full-season Harbin management
  problem. This is an agent decision quality issue in the observed run, not a
  migration constant change.
- This audit verifies migrated paths by tests and runs; it is not a formal
  byte-for-byte proof that every physics/tool constant matches the original
  ARE checkout.
