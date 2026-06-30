# AI Change Log

- Migrated FARM business into a standalone `fairy` package with FarmAgent-style controller runtime and local compatibility layers for ARE tool/event decorators.
- Added FAIRY controller family layer for ReAct/ReWOO-style FARM agents and research strategy profiles.
- Added productized run observability: `run_report.json` as the primary
  human-readable run entry point, `events.jsonl` as the runtime event stream,
  structured agent LLM/tool/error/limit events, CLI real-agent execution, and
  `scripts/summarize_runs.py` for batch run tables.
- Migrated oracle baseline and FOS rebatch tooling into FAIRY:
  `scripts/build_oracle_baselines.py`, `scripts/rebatch_fos_from_traces.py`,
  the real `fairy.scenarios.fos` evaluation modules, and the round-3
  `farm_worldpp_physics` scenario package. Verified `all` (34/34) and
  formal90 (90/90) baseline generation; formal90 matched ARE
  `oracle_baselines_full4` exactly on yield/ridge metrics.
- Migrated the selected fullseason v2 L2/L1 split pool and context sweep
  tooling: `fairy/scenarios/farm_world_fullseason_v2/l2_l1_splits/`,
  `scripts/fullseason/selected_l2_l1_20_30_scenario_ids.txt`,
  `scripts/iclr_validation_runner.py`, Kwoo context JSONs, and the
  false/true/Kwoo/skill retrieval wrappers. Verified
  `build_oracle_baselines.py --scenarios selected_l2_l1_20_30` built 50/50
  baselines and matched ARE `oracle_baselines_l2_l1_20_30` exactly.
