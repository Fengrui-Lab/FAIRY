# AI Change Log

- 2026-07-25: Added an auditable FARM system-prompt switch for tool-use A/B
  experiments. `fairy-run` and `scripts/iclr_validation_runner.py` accept
  `--system-prompt-mode fairy|are`; `fairy` preserves the existing prompt and
  `are` ports all legacy ARE behavior rules compatible with native function
  calling. Only the conflicting text-JSON action format, markers, examples, and
  embedded tool catalog remain excluded. Run reports and batch CSV rows record
  the selected mode.

- 2026-07-24: Added a provider-enforced per-call output-token cap for real
  agents. Both FAIRY CLI entry points accept `--max-output-tokens` /
  `--max-tokens`, default `2048`; vLLM, DeepSeek, Qwen, generic
  OpenAI-compatible, and OpenAI clients now forward the cap using the
  provider-appropriate request field. Run reports and batch CSV rows preserve
  the effective value for experiment audits.

- 2026-07-10: Repaired L2/L3 path-similarity retrieval to score the canonical
  declared oracle action graph with ARE-equivalent named/default arguments;
  added path-sim entry tests, parallel-tool-call forwarding, and accurate
  controller/skill capability documentation.

- Migrated FARM business into a standalone `fairy` package with FarmAgent-style controller runtime and local compatibility layers for ARE tool/event decorators.
- Added FAIRY controller family layer for ReAct/ReWOO-style FARM agents and research strategy profiles.
- Added productized run observability: `run_report.json` as the primary
  human-readable run entry point, `runtime_log.jsonl` as the runtime log,
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
- Ported ARE paper-controller runtime pieces into FAIRY:
  `ResearchARESimulationAgent`, ARE-compatible `AgentConfigBuilder`,
  `DynamicSkillLibrary` plus six JSON skills, Qwen/vLLM/OpenAI-compatible
  function-call clients, and controller telemetry export in `run_report.json`.
  New smoke tests verify config labels, skill retrieval, fake-LLM controller
  telemetry, and provider client construction without network calls.
- Promoted the L2 skill scenario pool to a first-class FAIRY set:
  `scripts/fullseason/l2_skill_scenario_ids.txt` (72 IDs),
  `l3_skill_source_ids.txt` (20 source L3 IDs), and ARE audit CSV/summary.
  The scenario registry now recursively imports nested scenario packages, so
  all 72 L2 skill scenarios are discoverable by `get_scenario_class()`.
  Verified `build_oracle_baselines.py --scenarios l2_skill_72` built 72/72.
- Documented the full-season context/skill-library product surface in both
  READMEs, including the `formal_90`, `selected_l2_l1_20_30`,
  `l2_skill_72`, Kwoo, `knowledge_library_pilot`, and all 14
  detailed-context modes.
- Added FAIRY A2A app-agent support: ARE-compatible app-agent profile names,
  typed expert mapping, deterministic app wrapping by `a2a_app_prop`, expert
  wrappers exposing `<AppName>Expert__expert_agent`, CLI and validation-runner
  `--a2a-*` plumbing, `run_report.a2a` metadata, and focused smoke tests.
- Added A2A expert observability and limit semantics during the 2026-07-01
  controller/A2A audit: `run_report.a2a`, `runtime_log.jsonl`,
  `run_report.a2a.expert_metrics`, expert `max_iterations` wired to
  `max_tool_calls`, and main-agent limit stops recorded as
  `agent_run_end status=stopped` instead of event-level errors.
- Rewrote both README files as product/user manuals: system purpose,
  installation, provider environment variables, `fairy-run` oracle/replay/agent
  modes, every public CLI parameter, A2A settings, output-file semantics,
  `run_report.json` field meanings, recommended run directory layout, scenario
  pools, full-season context modes, oracle baseline/yield-loss construction,
  FOS rebatching, batch runner usage, summarization, and debugging guidance.
- Restructured the README opening and output sections into task-first runbooks:
  copy-paste commands for oracle/replay/evaluate, real function-call agent runs,
  full-season context modes, batch validation, yield-loss/FOS generation, plus
  file-reading paths organized by debugging question instead of flat artifact
  tables.
- Reworked the README opening again into a formal operator manual structure:
  system scope, run inputs, execution modes, quick-start commands, artifact
  contracts, and architecture overview. Agent execution is documented as the
  primary entry point; oracle/replay/evaluate are documented as explicit
  supporting modes rather than conversational explanations.
- Completed README parameter contracts for full-season context modes and batch
  validation output: the quick-start section now lists every supported
  `detailed_briefing` value, explains `library` as scenario-specific
  `knowledge_library_pilot` context, names required Kwoo/retrieval environment
  variables, and enumerates every `iclr_validation_runner.py` `results.csv`
  column. Runner `--detail` help text now lists the L3 modes as well.
- Changed `scripts/rebatch_fos_from_traces.py` to FAIRY-only input discovery:
  it now consumes cell bundles with `*.agent_workflow.json` plus
  `*.run_report.json`, reads token/runtime metrics from `run_report`, and no
  longer discovers or reads the previous ARE trace export format.
- Corrected FAIRY rebatch time semantics: agent workflows now record exact
  pre/post tool epochs, legacy `advance_time` steps are reconstructed from the
  post-call timestamp without advancing twice, physics cannot rewind, and
  divergent mutating returns or final FARM outcome checkpoints fail the cell.
  The exact20 27B and 35B detail=true traces passed 40/40 strict outcome
  replays after the change.
- Added live long-cell observability without changing experiment inputs:
  agents emit a lightweight `<scenario>.progress.jsonl` as events occur, and
  `iclr_validation_runner.py` prints configurable LLM/tool/token heartbeats.
  Full message contexts remain in the final `runtime_log.jsonl` so progress
  logging overhead does not scale with context size.
  Runner subprocesses are unbuffered, `results.csv` is atomically checkpointed
  after every cell, and final JSONL artifacts use atomic replacement so an
  interrupted batch retains completed summaries without exposing half-written
  final logs.
