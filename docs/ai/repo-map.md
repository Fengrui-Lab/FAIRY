# FAIRY Repo Map

- `fairy/controllers/engine.py` is the lightweight runtime entry point. It registers a shared `TimeManager`, dynamic-event scheduler, `SystemApp`, and automatic `FarmWorldApp` physics attachment.
- `fairy/apps/farm_world/` contains the migrated FARM app/action layer and physics orchestrator.
- `fairy/physics/` contains the migrated FARM physics engines and profiles.
- `fairy/scenarios/baseline_farm_world/` contains FarmAgent-style scenarios with `scenario_input` and `oracle_solution()`.
- `fairy/scenarios/farm_world_physics/` and `fairy/scenarios/farm_world_fullseason/` contain ARE-derived event-graph scenarios captured by `EventRegisterer`.
- `fairy/scenarios/farm_worldpp_physics/` contains the migrated round-3 mid-season physics episodes used by `scripts/build_oracle_baselines.py --scenarios all`.
- `fairy/scenarios/farm_world_fullseason_v2/` contains the migrated Harbin L3 full-season v2 pool. The formal 90 scenario ids are tracked in `scripts/fullseason/formal_90_scenario_ids.txt`; registry import must include this package for `scripts/run_scenario.py --list` to expose them.
- `fairy/scenarios/farm_world_fullseason_v2/l2_l1_splits/` contains the selected Harbin L2/L1 split scenario package. `scripts/fullseason/selected_l2_l1_20_30_scenario_ids.txt` is the FAIRY manifest used by `scripts/build_oracle_baselines.py --scenarios selected_l2_l1_20_30`; it currently contains 50 source rows after combining the original selected L1 and selected L2 lists.
- `scripts/build_oracle_baselines.py` builds cached oracle yield baselines by running FAIRY `Engine.run_scenario_oracle()` and extrapolating FARM physics to maturity.
- `scripts/rebatch_fos_from_traces.py` replays FAIRY `*.agent_workflow.json` bundles against fresh FAIRY scenarios, then calls `fairy.scenarios.fos.evaluation.evaluate_fos()` to produce FOS summary CSVs.
- `fairy/controllers/agent_builder.py`, `agent_config.py`, and `research_strategies.py` contain FAIRY's migrated controller family layer: ReAct baseline plus ReWOO, planner-executor, reflection, skill-RAG, specialist, verifier, tree-search, critic, and graph-memory profile ids.
- `scripts/iclr_validation_runner.py`, `scripts/fullseason/run_l3_context_ablation.py`, and `scripts/fullseason/run_l3_skill_retrieval_experiments.py` are the FAIRY-native deepseek context/skill sweep entry points. They pass `detailed_briefing` through `--scenario-kwargs` and read FAIRY `run_report.json` artifacts instead of ARE `output.jsonl`.
