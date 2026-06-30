# FAIRY Testing Notes

- Use the ARE Python 3.12 virtualenv until FAIRY has its own lockfile:
  `/Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.venv312/bin/python -m pytest`.
- Core migration smoke:
  `PYTHONPATH=. /Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.venv312/bin/python -m pytest tests/test_fairy_migration_smoke.py`.
- Static guard:
  `rg "from are\\.|import are\\.|from rsare\\.|import rsare\\." fairy tests` should return no matches.
- Oracle baseline generation smoke:
  `python scripts/build_oracle_baselines.py --scenarios scenario_farm_world_field_prep_physics_action_tick --output-dir validation_runs/oracle_baseline_smoke --force --include-donothing`.
- Full migrated baseline checks used on 2026-06-30:
  `python scripts/build_oracle_baselines.py --scenarios all --output-dir validation_runs/oracle_baselines_all_current --force --include-donothing` produced 34/34 baselines, and
  `python scripts/build_oracle_baselines.py --scenarios formal90 --output-dir validation_runs/oracle_baselines_formal90_current --force --include-donothing` produced 90/90 baselines.
- Formal90 comparability check:
  compare `validation_runs/oracle_baselines_formal90_current` to `/Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/oracle_baselines_full4`; the 2026-06-30 run matched 90/90 with zero biological/recovered/ridge-count deltas.
- Selected L2/L1 baseline check:
  `python scripts/build_oracle_baselines.py --scenarios selected_l2_l1_20_30 --output-dir validation_runs/oracle_baselines_l2_l1_20_30_current --force --include-donothing`.
  The 2026-06-30 run built 50/50 baselines and matched `/Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/oracle_baselines_l2_l1_20_30` exactly on biological kg, recovered kg, per-ridge yield arrays, and ridge counts. Comparison outputs:
  `validation_runs/oracle_baseline_comparison/l2_l1_20_30_vs_are.csv` and `validation_runs/oracle_baseline_comparison/l2_l1_20_30_vs_are_summary.json`.
- L3 context/skill runner dry-runs:
  `python scripts/fullseason/run_l3_context_ablation.py --groups detail_false,detail_true,detail_kwoo --scenarios scenario_full_season_hb_base_hn84_std_normal --dry-run`
  and
  `python scripts/fullseason/run_l3_skill_retrieval_experiments.py --groups detail_false,detail_true,l2_human_same --scenarios scenario_full_season_hb_base_hn84_std_normal --dry-run`.
  These should emit `deepseek/deepseek-chat` runner commands with `--scenario-kwargs {"detailed_briefing": ...}`.
- Rebatch FOS smoke over an ARE trace:
  `python scripts/rebatch_fos_from_traces.py --root /Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/validation_runs/deepseek_json_l3_remaining70_l2_textsim_grouped_differ_20260606_160418/l2_textsim_grouped_differ --out-root validation_runs/rebatch_fos_smoke --limit 1 --workers 1 --extrapolate --oracle-baselines validation_runs/oracle_baselines_formal90_current --summary-name smoke_summary.csv`.
- Controller smoke includes `farm_baseline_react` and `farm_rewoo_modular` through `tests/test_fairy_migration_smoke.py`.
- End-to-end oracle/replay/evaluation smoke:
  `PYTHONPATH=. /Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.venv312/bin/python scripts/run_scenario.py -s scenario_farm_world_field_prep_physics_action_tick --build-oracle --replay --evaluate --output-dir /tmp/fairy-e2e`.
- L3 full-season e2e smoke:
  `PYTHONPATH=. /Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.venv312/bin/python scripts/run_scenario.py -s scenario_full_season_balanced --build-oracle --replay --evaluate --output-dir /tmp/fairy-l3-e2e`.
- Formal90 v2 registration/e2e smoke is covered by
  `tests/test_fairy_migration_smoke.py`. The direct CLI smoke used during
  migration was:
  `PYTHONPATH=. /Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.venv312/bin/python scripts/run_scenario.py -s scenario_full_season_hb_base_hn84_std_normal --build-oracle --replay --evaluate --output-dir /tmp/fairy_v2_smoke`.
- Real agent runs are available from the same CLI:
  `PYTHONPATH=. /Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.venv312/bin/python scripts/run_scenario.py -s scenario_full_season_balanced --agent --controller farm_baseline_react --provider deepseek --model deepseek-chat --temperature 0.2 --max-tool-calls 300 --timeout-seconds 1200 --output-dir validation_runs/<phase>/phase5_paper_matrix/farm_baseline_react__scenario_full_season_balanced__r1`.
- Batch inspection:
  `PYTHONPATH=. /Users/quao/Desktop/Second-year/CWSN/FarmARE_physics/.venv312/bin/python scripts/summarize_runs.py validation_runs/<phase> --csv validation_runs/<phase>/summary.csv`.
