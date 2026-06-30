# AI Change Log

- Migrated FARM business into a standalone `fairy` package with FarmAgent-style controller runtime and local compatibility layers for ARE tool/event decorators.
- Added FAIRY controller family layer for ReAct/ReWOO-style FARM agents and research strategy profiles.
- Added productized run observability: `run_report.json` as the primary
  human-readable run entry point, `events.jsonl` as the runtime event stream,
  structured agent LLM/tool/error/limit events, CLI real-agent execution, and
  `scripts/summarize_runs.py` for batch run tables.
