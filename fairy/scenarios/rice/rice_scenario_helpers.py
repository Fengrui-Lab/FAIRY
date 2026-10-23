"""App assembly and captured-event construction shared by rice L1/L2/L3."""
from __future__ import annotations

import math

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.paddy.world import PaddyWorldApp
from fairy.apps.paddy.operations import PaddyOpsApp
from fairy.apps.paddy.observations import PaddyObservationApp
from fairy.apps.paddy.machinery import PaddyMachineryApp
from fairy.apps.paddy.infrastructure import PaddyInfrastructureApp
from fairy.apps.paddy.drone import PaddyDroneApp
from fairy.apps.system import SystemApp
from fairy.scenarios.rice.farm_checkpoint_state import (
    ARTIFACT_SCHEMA, REBUILD_COMMAND, load_checkpoint, load_oracle_plan,
)
from fairy.scenarios.rice.rice_scenario_catalog import configuration
from fairy.types import EventRegisterer


def init_rice_apps(scenario, spec):
    field, weather = configuration(spec.variant)
    world = PaddyWorldApp(field=field, weather=weather)
    if spec.checkpoint_label:
        world.load_state(load_checkpoint(spec.variant, spec.checkpoint_label))
    populate_rice_apps(scenario, world)


def populate_rice_apps(scenario, world):
    """Bind a prepared world; also used by the offline artifact authoring tool."""
    scenario.start_time = world.sim_time
    scenario._initial_state = world.get_state()
    scenario._initial_action_count = len(world.actions)
    scenario.apps = [world, PaddyOpsApp(world), PaddyObservationApp(world), PaddyMachineryApp(world),
                     PaddyInfrastructureApp(world), PaddyDroneApp(world), world._weather_app,
                     SystemApp(), AgentUserInterface()]


def build_rice_events(scenario, spec):
    """Capture public tools without executing a planning world or mutating apps."""
    plan = load_oracle_plan(spec.scenario_id)
    world = scenario.get_typed_app(PaddyWorldApp)
    expected = {
        "schema_version": ARTIFACT_SCHEMA,
        "scenario_id": spec.scenario_id,
        "task": spec.task,
        "variant": spec.variant,
        "source_l3_scenario_id": spec.source_l3_scenario_id,
        "source_checkpoint_label": spec.source_checkpoint_label,
        "initial_checkpoint_sha256": scenario._initial_state["sha256"],
        "config_fingerprint": world.crop_backend_provenance()["config_fingerprint"],
    }
    if any(plan.get(key) != value for key, value in expected.items()):
        raise ValueError(f"Rice oracle plan configuration/checkpoint mismatch; rebuild with {REBUILD_COMMAND}")
    apps = {app.name: app for app in scenario.apps}
    allowed = {app.name: {tool.name for tool in app.get_tools()} for app in scenario.apps}
    # Validate the complete plan before capturing any events.
    entries = []
    for step in plan.get("steps", []):
        app_name, separator, method = step.get("tool_name", "").partition("__")
        args, duration = step.get("tool_args"), step.get("duration_seconds")
        if not separator or method not in allowed.get(app_name, set()) or not isinstance(args, dict):
            raise ValueError("Rice oracle plan contains an unknown tool or invalid arguments")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
            raise ValueError("Rice oracle plan contains an invalid operation duration")
        explicit = 0.
        if app_name == "SystemApp" and method == "advance_time":
            explicit = sum(float(args.get(key, 0)) * scale for key, scale in
                           (("seconds", 1), ("minutes", 60), ("hours", 3600), ("days", 86400)))
        if duration < explicit - 1e-6:
            raise ValueError("Rice oracle plan duration is shorter than its explicit time advance")
        entries.append((apps[app_name], method, args, max(0., duration - explicit)))
    if not entries:
        raise ValueError("Rice oracle plan has no tool steps")
    with EventRegisterer.capture_mode() as events:
        prev = scenario.get_typed_app(AgentUserInterface).send_message_to_agent(
            content=scenario.scenario_input).with_id("briefing")
        for index, (app, method, args, delay) in enumerate(entries):
            prev = getattr(app, method)(**args).oracle().with_id(
                f"o_{index:04d}_{method}").depends_on(prev, delay_seconds=delay)
    scenario.events = list(events)
