# FAIRY Testing Notes

- Use the ARE Python 3.12 virtualenv until FAIRY has its own lockfile:
  `/Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.venv312/bin/python -m pytest`.
- Core migration smoke:
  `PYTHONPATH=. /Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.venv312/bin/python -m pytest tests/test_fairy_migration_smoke.py`.
- Static guard:
  `rg "from are\\.|import are\\.|from rsare\\.|import rsare\\." fairy tests` should return no matches.
- Controller smoke includes `farm_baseline_react` and `farm_rewoo_modular` through `tests/test_fairy_migration_smoke.py`.
- End-to-end oracle/replay/evaluation smoke:
  `PYTHONPATH=. /Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.venv312/bin/python scripts/run_scenario.py -s scenario_farm_world_field_prep_physics_action_tick --build-oracle --replay --evaluate --output-dir /tmp/fairy-e2e`.
- L3 full-season e2e smoke:
  `PYTHONPATH=. /Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.venv312/bin/python scripts/run_scenario.py -s scenario_full_season_balanced --build-oracle --replay --evaluate --output-dir /tmp/fairy-l3-e2e`.
- Real agent runs are available from the same CLI:
  `PYTHONPATH=. /Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.venv312/bin/python scripts/run_scenario.py -s scenario_full_season_balanced --agent --controller farm_baseline_react --provider deepseek --model deepseek-chat --temperature 0.2 --max-tool-calls 300 --timeout-seconds 1200 --output-dir validation_runs/<phase>/phase5_paper_matrix/farm_baseline_react__scenario_full_season_balanced__r1`.
- Batch inspection:
  `PYTHONPATH=. /Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.venv312/bin/python scripts/summarize_runs.py validation_runs/<phase> --csv validation_runs/<phase>/summary.csv`.
