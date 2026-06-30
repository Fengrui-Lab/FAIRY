# FAIRY Repo Map

- `fairy/controllers/engine.py` is the lightweight runtime entry point. It registers a shared `TimeManager`, dynamic-event scheduler, `SystemApp`, and automatic `FarmWorldApp` physics attachment.
- `fairy/apps/farm_world/` contains the migrated FARM app/action layer and physics orchestrator.
- `fairy/physics/` contains the migrated FARM physics engines and profiles.
- `fairy/scenarios/baseline_farm_world/` contains FarmAgent-style scenarios with `scenario_input` and `oracle_solution()`.
- `fairy/scenarios/farm_world_physics/` and `fairy/scenarios/farm_world_fullseason/` contain ARE-derived event-graph scenarios captured by `EventRegisterer`.
- `fairy/controllers/agent_builder.py`, `agent_config.py`, and `research_strategies.py` contain FAIRY's migrated controller family layer: ReAct baseline plus ReWOO, planner-executor, reflection, skill-RAG, specialist, verifier, tree-search, critic, and graph-memory profile ids.
