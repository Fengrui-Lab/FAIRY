## Migrated Scenario Class Defaults

- ARE FARM scenarios often define runtime configuration such as `start_time`,
  `duration`, `queue_based_loop`, and `time_increment_in_seconds` as class
  attributes on `Scenario` subclasses.
- FAIRY's `Scenario` base is a dataclass, so inherited field defaults can
  shadow those class attributes on new instances. If `start_time` falls back to
  `None`, `Engine` starts at Unix timestamp `0` and full-season weather/physics
  logs drift to 1970.
- `Scenario.__post_init__` now copies subclass class attributes onto the
  instance only when the instance still equals the base dataclass default.
  Explicit constructor values still win.

## Captured Event Graph Completeness

- ARE event graphs maintain both `dependencies` and `successors`; FAIRY's
  lightweight `CapturedEvent` must do the same. Without `successors`,
  full-season v2 helpers that call `collect_event_graph(briefing)` only return
  the root briefing node.
- Some scenarios mark briefing messages as dependencies but do not call
  `.oracle()` on them. FAIRY should include these dependency-closure nodes in
  oracle workflow JSON so `depends_on` references point to real workflow nodes.
- Some helper builders, especially `harvest_range()`, return only the final
  node while hiding internal harvest/unload nodes behind `dependencies`.
  `Engine._oracle_event_dependency_closure()` must return the actual
  dependency objects in dependency-first order, not filter back down to only
  `scenario.events`. Filtering back caused selected L2/L1 harvest baselines to
  execute `store_grain` without executing the harvest passes.

## Oracle Baseline Tool Errors

- Some migrated oracle flows intentionally trigger tool-error returns as part
  of the correct management plan. Example: the planting action-tick scenario
  attempts a pass when the seed hopper is short, then reloads and retries.
- `scripts/build_oracle_baselines.py` should preserve these returned errors in
  baseline metadata (`tool_errors`) but must not fail the whole baseline build
  solely because a workflow step returned `{"error": ...}`.
- Treat true fatal failures separately: missing FarmWorldApp, inactive physics
  after oracle run, scenario not in registry, or Python exceptions during
  scenario construction/execution.
