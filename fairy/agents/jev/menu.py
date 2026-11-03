"""Action menus for the Jev agent (see docs/jev/PROGRESS.md, "Step 3 – rules").

Jev cannot write arguments, so every argument gets a Choice over a fixed list of
values. The lists come only from the tool code and the farm state, never from the
oracle:

- ridge ids: every ridge on the farm;
- text arguments: the fixed list in the code or the values the farm holds;
- booleans: true / false;
- numbers with a maximum in the code: 10 evenly spaced values + task-text numbers;
- small whole-number ranges in the code: every whole number in the range + task numbers;
- numbers with no maximum in the code: task-text numbers only;
- arguments with a default: the default is added as one more value.

Task-text numbers are every number found in the task text by a plain text search,
applied to every numeric argument (whole numbers only for integer arguments).

Part 2 additions (docs/jev/PROGRESS.md, Part 2):
- waiting (advance_time, wait_for_notification): one question in plain units,
  see WAIT_STEPS;
- the report to the user: one option, filled with a report written by code;
- per turn, the agent narrows ridge options (end >= start, PASS_WIDTH, and no
  harvesting/planting of ridges the farm overview shows as already done).

Rice irrigation uses public effective canal flow to convert existing WAIT_STEPS
and task durations into water-depth ranges. Each range uses the same ten-value
spacing; quota/opening limits clip candidates, never set their spacing. This is
a scene-specific extension of the finite-menu policy, not an optimal dose rule.
"""

from __future__ import annotations

import re
import json
import math
from itertools import combinations
from types import SimpleNamespace
from dataclasses import dataclass, field
from typing import Any

from fairy.apps.farm_world import tractor_app as _tractor
from fairy.apps.farm_world.models import SeedType
from fairy.agents.jev.snapshot import _failed, _result_data

DONE_OPTION = "done"
DONE_DESCRIPTION = "All steps of the task are complete; stop and report."
MAX_CHOICE_OPTIONS = 255  # TypeSafe Choice limit

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

# Integer arguments that name a ridge (all checked against num_ridges in the apps).
RIDGE_ARGS = frozenset({"ridge_id", "start_ridge", "end_ridge", "start", "end"})

# Tank / hopper capacities: an amount above the capacity is cut to fit.
CAPACITY_MAX: dict[tuple[str, str, str], float] = {
    ("TractorApp", "refuel", "liters"): _tractor._FUEL_TANK_MAX_L,
    ("TractorApp", "refill_pesticide_tank", "liters"): _tractor._PESTICIDE_TANK_MAX_L,
    ("TractorApp", "load_fertilizer", "kg"): _tractor._FERTILIZER_SPREADER_MAX_KG,
    ("TractorApp", "load_pesticide", "liters"): _tractor._PESTICIDE_TANK_MAX_L,
    # load_fungicide checks against _PESTICIDE_TANK_MAX_L as well.
    ("TractorApp", "load_fungicide", "liters"): _tractor._PESTICIDE_TANK_MAX_L,
    ("TractorApp", "load_seeds", "count"): _tractor._SEED_HOPPER_MAX_PLANTS,
}

# Explicit ranges written in the tool bodies (rejected or clamped outside).
CODE_RANGES: dict[tuple[str, str, str], tuple[float, float]] = {
    ("PaddyOpsApp", "soak", "hours"): (1, 72),
    ("WeatherApp", "get_forecast", "days"): (1, 7),
    ("PaddyOpsApp", "apply_fertilizer", "kg_per_ha"): (0, 300),
    ("PaddyOpsApp", "dry_grain", "target_moisture_pct"): (14, 14),
    ("FarmWorldApp", "dry_grain", "target_moisture_pct"): (11.0, 16.0),
    ("TractorApp", "plant_seeds", "depth_cm"): (3.0, 5.0),
    ("TractorApp", "replant_seeds", "depth_cm"): (3.0, 5.0),
    ("FieldOpsApp", "apply_pesticide_manual", "ridge_count"): (1, 2),
    # Stated in the tool description ("typical 0.5-1.5"), not enforced by the code.
    ("FarmWorldApp", "apply_fertigation", "nutrient_amount"): (0.5, 1.5),
}

EVENLY_SPACED_COUNT = 10

# Most ridges one pass may cover: max_width in TractorApp._validate_ridge_window calls.
PASS_WIDTH: dict[tuple[str, str], int] = {
    ("TractorApp", "plant_seeds"): 4,
    ("TractorApp", "replant_seeds"): 4,
    ("TractorApp", "harvest"): 4,
    ("TractorApp", "apply_fertilizer"): 10,
    ("TractorApp", "apply_pesticide"): 10,
    ("TractorApp", "spray_pesticide"): 10,
    ("TractorApp", "apply_fungicide"): 10,
    ("TractorApp", "apply_herbicide"): 10,
    ("TractorApp", "mechanical_weed_control"): 10,
    ("TractorApp", "incorporate_residue"): 10,
}

# Waiting is one question in plain units (Part 1 offered seconds/minutes/hours/days
# separately, filled only with task numbers). Common intervals, not taken from any
# oracle; durations written in the task and time left until a pending effect
# (added per turn by the agent) are offered as well.
WAIT_STEPS: list[tuple[str, int]] = [
    ("minutes", 30), ("hours", 1), ("hours", 2), ("hours", 6), ("hours", 12),
    *[("days", d) for d in range(1, 8)], ("days", 10), ("days", 14),
]
UNIT_SECONDS = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}
_DURATION_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(days?|hours?|h|minutes?|min|seconds?)\b", re.IGNORECASE
)
_UNIT_ALIASES = {"day": "days", "hour": "hours", "h": "hours", "minute": "minutes",
                 "min": "minutes", "second": "seconds"}
DURATION_ARG = "duration"

# The report to the user is free text, which Jev cannot write. It gets one option;
# the agent replaces it with a factual report built by code from the snapshot.
REPORT_OPTION = "send the factual report of this run (written by code from the farm snapshot)"


class EmptyMenuError(ValueError):
    """An argument has no value to offer."""

    def __init__(self, message: str, *, reason: str = "missing_rule"):
        super().__init__(message)
        self.reason = reason


@dataclass
class ArgMenu:
    name: str
    arg_type: str
    description: str
    source: str
    options: dict[str, Any] = field(default_factory=dict)  # option key -> typed value


@dataclass
class ToolMenu:
    tool_name: str
    description: str
    args: list[ArgMenu]


def first_paragraph(text: str | None) -> str:
    """Text up to the first blank line, joined into one line."""
    para = (text or "").strip().split("\n\n", 1)[0]
    return " ".join(line.strip() for line in para.splitlines()).strip()


def arg_descriptions(doc: str | None) -> dict[str, str]:
    """Parse 'name: text' lines from a docstring's Args section."""
    out: dict[str, str] = {}
    lines = (doc or "").splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "Args:")
    except StopIteration:
        return out
    current = None
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped:
            current = None
            continue
        match = re.match(r"^(\w+)\s*:\s*(.*)$", stripped)
        if match:
            current = match.group(1)
            out[current] = match.group(2).strip()
        elif current:
            out[current] = f"{out[current]} {stripped}".strip()
    return out


def task_numbers(task_text: str) -> list[float]:
    return sorted({float(x) for x in _NUMBER_RE.findall(task_text or "")})


def _option_key(value: Any, *, ridge: bool = False) -> str:
    if value is None:
        return "default (null)"
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if ridge:
        return f"ridge {value}"
    if isinstance(value, int):
        return str(value)
    return f"{value:g}"


def _numeric_values(
    key: tuple[str, str, str], arg_type: str, numbers: list[float]
) -> tuple[list[float], str]:
    is_int = arg_type == "int"
    if key in CAPACITY_MAX:
        top = CAPACITY_MAX[key]
        spaced = [top * i / EVENLY_SPACED_COUNT for i in range(1, EVENLY_SPACED_COUNT + 1)]
        source = f"10 evenly spaced up to code max {top:g} + task numbers"
    elif key in CODE_RANGES:
        lo, hi = CODE_RANGES[key]
        if is_int:
            spaced = list(range(int(lo), int(hi) + 1))
            source = f"every whole number in code range {lo:g}-{hi:g} + task numbers"
        else:
            step = (hi - lo) / (EVENLY_SPACED_COUNT - 1)
            spaced = [lo + step * i for i in range(EVENLY_SPACED_COUNT)]
            source = f"10 evenly spaced in code range {lo:g}-{hi:g} + task numbers"
    else:
        spaced = []
        source = "task numbers only (no max in code)"
    values = list(spaced) + list(numbers)
    if is_int:
        values = [int(v) for v in values if float(v).is_integer()]
    else:
        values = [round(float(v), 3) for v in values]
    return values, source


def build_arg_menu(
    tool: Any,
    arg: Any,
    *,
    descriptions: dict[str, str],
    numbers: list[float],
    num_ridges: int,
    arguments: dict[str, Any] | None = None,
    steps: list[Any] | tuple = (),
    task_text: str = "",
    enforced_tool_adaptor: bool = False,
) -> ArgMenu:
    schema = getattr(tool, "parameters_schema", {}).get("properties", {}).get(arg.name, {})
    if arg.arg_type == "Annotated":
        kind = schema.get("type")
        nullable_schema = False
        if isinstance(kind, list):
            nullable_schema = "null" in kind
            kind = next((k for k in kind if k != "null"), None)
        if "anyOf" in schema:
            kinds = [x.get("type") for x in schema["anyOf"]]
            nullable_schema = "null" in kinds
            kind = next((k for k in kinds if k != "null"), None)
        mapped = {"string": "str", "integer": "int", "number": "float", "boolean": "bool", "array": "list"}.get(kind)
        if mapped is None:
            raise ValueError(f"No menu rule for native schema {schema}")
        arg = SimpleNamespace(name=arg.name, arg_type=mapped + (" | None" if nullable_schema else ""), has_default=arg.has_default, default=arg.default)
    key = (tool.class_name, tool.name, arg.name)
    description = descriptions.get(arg.name, "")
    parts = {p.strip() for p in arg.arg_type.split("|")}
    nullable = "None" in parts
    base_types = parts - {"None"}
    arg_type = next(iter(base_types)) if len(base_types) == 1 else arg.arg_type
    if arg_type == "bool":
        values: list[Any] = [True, False]
        source = "true / false"
    elif arg_type == "int" and arg.name in RIDGE_ARGS:
        values = list(range(num_ridges))
        source = f"every ridge 0-{num_ridges - 1}"
    elif arg_type == "str":
        values, source = scene_text_values(tool, arg, numbers=numbers, steps=steps, task_text=task_text) or _text_values(tool, arg)
    elif arg_type in ("list", "list[str]", "List[str]") and tool.class_name == "PaddyDroneApp" and arg.name == "plot_ids":
        ids = [p.plot_id for p in scene_world(tool).field.plots]
        if 2 ** len(ids) - 1 > MAX_CHOICE_OPTIONS:
            raise ValueError("Plot subset menu exceeds Choice limit")
        values = [list(c) for n in range(1, len(ids) + 1) for c in combinations(ids, n)]
        source = "all nonempty subsets of visible plot IDs"
    elif arg_type in ("int", "float") and "enum" in schema and extended_scene_tool(tool):
        values, source = list(schema["enum"]), "native tool JSON schema enum"
    elif arg_type in ("int", "float"):
        values, source = scene_numeric_values(tool, arg, numbers, arguments=arguments, steps=steps, task_text=task_text) or _numeric_values(key, arg_type, numbers)
    else:
        raise ValueError(f"No menu rule for {key} of type {arg.arg_type}")

    if enforced_tool_adaptor and key == ("TractorApp", "load_seeds", "count"):
        from fairy.agents.jev.seed_candidates import seed_amount_hint
        hint, note = seed_amount_hint(scene_world(tool), (arguments or {}).get("seed_type"),
                                      task_text, steps, _tractor._SEED_HOPPER_MAX_PLANTS)
        if hint is not None:
            values.append(hint)
        if note:
            description += " " + note

    if arg_type == "int":
        values = [int(v) for v in values if float(v).is_integer()]
    if arg.has_default and arg.default is not None:
        default = arg.default
        if arg_type == "float":
            default = round(float(default), 3)
        values.append(default)
        source += " + default"

    seen: dict[str, Any] = {}
    ordered = values if arg_type in ("str", "bool", "list", "list[str]", "List[str]") else sorted(values)
    for value in ordered:
        seen.setdefault(_option_key(value, ridge=arg.name in RIDGE_ARGS), value)
    if nullable and arg.has_default and arg.default is None:
        seen["default (null)"] = None
        source += " + nullable default"
    if not seen:
        raise EmptyMenuError(f"Empty menu for {key}", reason=(
            "empty_resources" if extended_scene_tool(tool) and arg.name in
            ("batch_id", "plot_id", "machine_id", "asset_id", "farm_id", "channel_id") else "missing_rule"))
    if len(seen) > MAX_CHOICE_OPTIONS:
        raise ValueError(f"Menu for {key} has {len(seen)} options (> {MAX_CHOICE_OPTIONS})")
    return ArgMenu(arg.name, arg.arg_type, description, source, seen)


def duration_key(unit: str, amount: int) -> str:
    """('days', 1) -> '1 day'; ('hours', 6) -> '6 hours'."""
    return f"{amount} {unit[:-1] if amount == 1 else unit}"


def task_durations(task_text: str) -> list[tuple[str, int]]:
    """Durations written in the task, as whole numbers of their unit (or of seconds)."""
    out: list[tuple[str, int]] = []
    for value, unit in _DURATION_RE.findall(task_text or ""):
        unit = _UNIT_ALIASES.get(unit.lower(), unit.lower())
        amount = float(value)
        if amount <= 0:
            continue
        if amount.is_integer():
            out.append((unit, int(amount)))
        else:
            out.append(("seconds", int(round(amount * UNIT_SECONDS[unit]))))
    return out


def wait_menu(tool: Any, task_text: str) -> ArgMenu:
    """One choice for advance_time (argument dict) or wait_for_notification (seconds)."""
    steps = list(dict.fromkeys(WAIT_STEPS + task_durations(task_text)))
    steps.sort(key=lambda s: s[1] * UNIT_SECONDS[s[0]])
    if tool.name == "advance_time":
        options = {duration_key(u, n): {u: n} for u, n in steps}
        return ArgMenu(DURATION_ARG, "duration", "How long to advance the clock.",
                       "common intervals + task durations + time left to pending effects", options)
    options = {duration_key(u, n): n * UNIT_SECONDS[u] for u, n in steps}
    return ArgMenu("timeout", "int", "Longest time to wait for a notification.",
                   "common intervals + task durations + time left to pending effects", options)


def _text_values(tool: Any, arg: Any) -> tuple[list[Any], str]:
    if arg.name == "content" and tool.name == "send_message_to_user":
        return [REPORT_OPTION], "one report written by code from the farm snapshot"
    if arg.name == "implement":
        return list(_tractor._ATTACH_WIDTH_M), "implements in tractor code"
    if arg.name == "seed_type":
        return [s.value for s in SeedType], "SeedType values in code"
    if arg.name == "sensor_id":
        if tool.name == "read_soil_sensor":
            sensors = tool.class_instance._soil_sensors
        elif tool.name == "read_canopy_sensor":
            sensors = tool.class_instance._canopy_sensors
        else:
            raise ValueError(f"No sensor list for {tool.name}")
        return [s["sensor_id"] for s in sensors], "sensors on the farm"
    raise ValueError(f"No menu rule for text argument {tool.class_name}.{tool.name}.{arg.name}")


def build_tool_menus(
    tools_map: dict[str, Any], *, task_text: str, num_ridges: int,
    steps: list[Any] | tuple = (),
    enforced_tool_adaptor: bool = False,
) -> dict[str, ToolMenu]:
    """One ToolMenu per tool, in the same order the LLM agent sees them."""
    numbers = task_numbers(task_text)
    menus: dict[str, ToolMenu] = {}
    for tool_name, tool in tools_map.items():
        docs = arg_descriptions(tool.function_description)
        if tool.class_name == "SystemApp" and tool.name in ("advance_time", "wait_for_notification"):
            args = [wait_menu(tool, task_text)]
        else:
            try:
                args = [
                    build_arg_menu(
                        tool, arg, descriptions=docs, numbers=numbers, num_ridges=tool_ridge_count(tool, num_ridges), steps=steps, task_text=task_text, enforced_tool_adaptor=enforced_tool_adaptor
                    )
                    for arg in tool.args
                ]
            except EmptyMenuError:
                # e.g. an amount with no maximum in the code and no number in the task:
                # Jev cannot call this tool (the jev_menu event lists the tools offered).
                continue
        menus[tool_name] = ToolMenu(
            tool_name=tool_name,
            description=first_paragraph(tool.function_description),
            args=args,
        )
    if len(menus) + 1 > MAX_CHOICE_OPTIONS:
        raise ValueError(f"Tool menu has {len(menus) + 1} options (> {MAX_CHOICE_OPTIONS})")
    return menus

# New scene support uses the same finite-value menus, not a second planner.
def scene_world(tool: Any, arguments: dict[str, Any] | None = None) -> Any:
    app = tool.class_instance
    runtime = getattr(app, "runtime", None)
    if runtime is not None:
        target = (arguments or {}).get("farm_id")
        if target in runtime.farms:
            return runtime.farms[target].farm
        if len(runtime.farms) == 1:
            return next(iter(runtime.farms.values())).farm
    env = getattr(app, "farm_environment", None)
    if env is not None:
        target = (arguments or {}).get("farm_id") or getattr(app, "bound_farm_id", None)
        if target in env.farms:
            return env.farms[target].world
    for name in ("farm", "_farm", "world", "_farm_world_app"):
        world = getattr(app, name, None)
        if world is not None:
            return world
    return app


def extended_scene_tool(tool: Any) -> bool:
    app = tool.class_instance
    return (hasattr(app, "runtime") or tool.class_name.startswith(("Shared", "Paddy")) or
            tool.class_name == "WarehouseApp" or
            getattr(app, "farm_environment", None) is not None or
            getattr(scene_world(tool), "crop_id", "soybean") != "soybean")


def scene_text_values(tool: Any, arg: Any, *, numbers: list[float] = (), steps=(), task_text="") -> tuple[list[Any], str] | None:
    if not extended_scene_tool(tool):
        return None
    app = tool.class_instance
    schema = getattr(tool, "parameters_schema", {}).get("properties", {}).get(arg.name, {})
    if "enum" in schema:
        return list(schema["enum"]), "native tool JSON schema enum"
    if arg.name == "farm_id" and getattr(app, "farm_environment", None) is not None:
        return list(app.farm_environment.farms), "farm IDs in native FarmEnvironment"
    choices = getattr(app, "tool_parameter_choices", {}).get(arg.name)
    if choices is not None:
        return list(choices), "native tool_parameter_choices"
    contract = getattr(app, "get_tool_contract", lambda _: None)(tool.name)
    parameter = contract.parameters.get(arg.name) if contract else None
    if parameter and parameter.choices is not None:
        return list(parameter.choices), "native tool contract choices"
    if tool.class_name == "WarehouseApp" and arg.name == "batch_id":
        return [b.batch_id for b in app.grain_batches.values() if b.status == "pending"], "pending batches in get_grain_batches"
    if tool.class_name == "SharedTractorApp" and arg.name == "batch_id":
        existing = app.farm_environment.warehouse.grain_batches
        n = 1
        while f"jev-batch-{n:06d}" in existing:
            n += 1
        return [f"jev-batch-{n:06d}"], "one deterministic unused batch label; no action policy"
    if tool.class_name.startswith("Paddy"):
        field = scene_world(tool).field
        if arg.name == "plot_id":
            if tool.name in RICE_OBS_AMOUNTS or tool.name == "irrigate":
                ids, reasons = [], []
                for plot in field.plots:
                    try:
                        _rice_amount_values(tool, numbers, {"plot_id": plot.plot_id}, steps, task_text)
                        ids.append(plot.plot_id)
                    except EmptyMenuError as exc:
                        reasons.append(exc)
                if not ids:
                    raise reasons[0]
                return ids, "public plot IDs with amount candidates; no extra observations"
            return [p.plot_id for p in field.plots], "plot IDs in get_farm_overview"
        if arg.name == "machine_id":
            if tool.name in ("attach_implement", "detach_implement"):
                return [m.machine_id for m in field.machines if m.kind == "tractor"], "native implement operations accept tractors only"
            return [m.machine_id for m in field.machines], "machine IDs in get_machine_status"
        if arg.name == "channel_id":
            return [c.channel_id for c in field.channels], "channel IDs in get_inventory"
        if arg.name == "batch_id":
            if tool.name in ("load_seedlings", "transplant"):
                return [field.seedlings.batch_id], "seedling batch in get_inventory"
            return [b.batch_id for b in field.grain_batches
                    if tool.name == "measure_grain_moisture" or b.location == "reception"], "grain batches in get_inventory"
        if arg.name == "implement":
            return ["puddler", "spreader", "sprayer"], "PaddyMachineryApp.attach_implement accepted names"
        if arg.name == "product_id":
            return ["urea"], "PaddyOpsApp fertilizer product"
    return None


RICE_OBS_AMOUNTS = {"drain": "water_mm", "replant_seedlings": "quantity"}


def _latest_observation(steps, method, plot_id):
    for step in reversed(steps):
        if (step.op_type != "TOOL" or _failed(step) or
                step.tool_name != "PaddyObservationApp__" + method or
                (step.tool_args or {}).get("plot_id") != plot_id):
            continue
        data = _result_data(step.content)
        if isinstance(data, dict) and data.get("plot_id") == plot_id:
            return data, getattr(step, "time", None)
    raise EmptyMenuError(f"{plot_id}: awaiting successful {method}", reason="awaiting_observation")


def _rice_amount_values(tool, numbers, arguments, steps, task_text=""):
    """Bounds from public inventory/area or already acquired observations only."""
    world = scene_world(tool)
    plots = [p for p in world.field.plots if not arguments.get("plot_id") or p.plot_id == arguments["plot_id"]]
    values, sources, errors = [], [], []
    for plot in plots:
        try:
            candidates = None
            if tool.name == "irrigate":
                channel = next(c for c in world.field.channels if c.channel_id == "supply")
                top = max(0., channel.quota_m3 - channel.withdrawn_m3) * channel.efficiency * 1000 / plot.area_m2
                if plot.plot_id not in channel.connected_plots:
                    top = 0
                # Inverse of the native tool's volume / effective-flow duration.
                mm_per_hour = channel.flow_m3_hour * (1 - channel.blockage_fraction) * channel.efficiency * 1000 / plot.area_m2
                if (channel.open_hour, channel.close_hour) != (0, 24):
                    # Full declared window only, not a plan to wait for it. The
                    # native tool still validates the actual start/end times.
                    top = min(top, mm_per_hour * (channel.close_hour - channel.open_hour))
                durations = list(dict.fromkeys(WAIT_STEPS + task_durations(task_text)))
                candidates = [
                    min(top, mm_per_hour * amount * UNIT_SECONDS[unit] / 3600 * i / EVENLY_SPACED_COUNT)
                    for unit, amount in durations for i in range(1, EVENLY_SPACED_COUNT + 1)
                ] + list(numbers)
                source = (f"{plot.plot_id}: public effective flow={mm_per_hour:g} mm/hour; "
                          "WAIT_STEPS + task durations, 10 evenly spaced per duration; "
                          "clipped by remaining quota and declared channel opening span; "
                          "actual-time checks remain native")
            elif tool.name == "drain":
                obs, timestamp = _latest_observation(steps, "read_water_sensors", plot.plot_id)
                top = obs.get("surface_water_mm")
                source = f"{plot.plot_id}: acquired surface_water_mm; observation time={obs.get('timestamp', timestamp)}"
            else:
                obs, timestamp = _latest_observation(steps, "inspect_establishment", plot.plot_id)
                stand = obs.get("stand_fraction_estimate")
                if not isinstance(stand, (int, float)) or not math.isfinite(stand) or not 0 <= stand <= 1:
                    raise EmptyMenuError(f"{plot.plot_id}: invalid stand observation", reason="invalid_observation")
                # Native transplant density: 20 cm x 20 cm, three seedlings per hill.
                missing = math.floor((1 - stand) * plot.area_m2 * 75 + 1e-7)
                top = min(missing, world.field.seedlings.loaded)
                source = f"{plot.plot_id}: observed stand estimate * public area * native density, capped by loaded seedlings; observation time={obs.get('timestamp', timestamp)}"
            if not isinstance(top, (int, float)) or not math.isfinite(top):
                raise EmptyMenuError(f"{plot.plot_id}: invalid amount bound", reason="invalid_observation")
            if top <= 0:
                raise EmptyMenuError(f"{plot.plot_id}: no positive amount from current public resources/observation", reason="empty_resources")
            if candidates is None:
                candidates = [top * i / EVENLY_SPACED_COUNT for i in range(1, EVENLY_SPACED_COUNT + 1)] + list(numbers)
            if tool.name == "replant_seedlings":
                candidates = [math.floor(v) for v in candidates]
            else:
                candidates = [math.floor(v * 1000 + 1e-9) / 1000 for v in candidates]
            candidates = [v for v in candidates if 0 < v <= top]
            if not candidates:
                raise EmptyMenuError(f"{plot.plot_id}: no representable positive amount", reason="empty_resources")
            values.extend(candidates); sources.append(source)
        except EmptyMenuError as exc:
            errors.append(exc)
    if not values:
        if errors:
            raise errors[0]
        raise EmptyMenuError("No matching public plot", reason="empty_resources")
    return values, "10 evenly spaced + task numbers within bound; " + "; ".join(sources)


def scene_numeric_values(tool: Any, arg: Any, numbers: list[float], *, arguments=None, steps=(), task_text="") -> tuple[list[Any], str] | None:
    if not extended_scene_tool(tool):
        return None
    app = tool.class_instance
    arguments = arguments or {}
    if tool.class_name.startswith("Paddy"):
        world = scene_world(tool)
        if (tool.name == "irrigate" and arg.name == "water_mm" or
                RICE_OBS_AMOUNTS.get(tool.name) == arg.name):
            return _rice_amount_values(tool, numbers, arguments, steps, task_text)
        top = None
        if tool.name == "load_seedlings" and arg.name == "quantity":
            top = world.machine("transplanter").seedling_capacity
        elif tool.name == "refuel" and arg.name == "liters":
            top = max(m.tank_capacity_liters for m in world.field.machines
                      if not arguments.get("machine_id") or m.machine_id == arguments["machine_id"])
        elif tool.name == "load_fertilizer" and arg.name == "kg":
            top = world.machine("tractor").fertilizer_capacity_kg
        if top is not None:
            vals = [top * i / 10 for i in range(1, 11)] + numbers
            if arg.arg_type == "int": vals = [int(v) for v in vals if float(v).is_integer()]
            return vals, "10 evenly spaced up to public machine capacity + task numbers"
    runtime = getattr(app, "runtime", None)
    if runtime is not None and tool.class_name == "TractorService":
        capacity = {"refuel": ("liters", "fuel_tank_l"), "load_seeds": ("count", "seed_hopper_count"),
                    "load_fertilizer": ("kg", "fertilizer_spreader_kg"),
                    **{name: ("liters", "pesticide_tank_l") for name in ("load_pesticide", "load_fungicide", "refill_pesticide_tank")}}.get(tool.name)
        if capacity and arg.name == capacity[0]:
            values = []
            for asset in runtime.assets.values():
                if asset.kind != "tractor" or arguments.get("asset_id") not in (None, asset.asset_id):
                    continue
                farm_ids = [fid for fid in asset.spec.allowed_farm_ids if arguments.get("farm_id") in (None, fid)]
                if not farm_ids:
                    continue
                fid = farm_ids[0]
                caps = runtime.capabilities(SimpleNamespace(farm=runtime.farms[fid].farm, farm_id=fid, asset=asset, asset_id=asset.asset_id))
                top = caps["asset_capacities"][capacity[1]]
                values.extend(top * i / EVENLY_SPACED_COUNT for i in range(1, EVENLY_SPACED_COUNT + 1))
            if not values:
                raise EmptyMenuError("No eligible public asset capacity", reason="empty_resources")
            return values + list(numbers), "10 evenly spaced up to selected public asset capacity + task numbers"
    schema = getattr(tool, "parameters_schema", {}).get("properties", {}).get(arg.name, {})
    if "minimum" in schema and "maximum" in schema:
        lo, hi = schema["minimum"], schema["maximum"]
        values = (list(range(math.ceil(lo), math.floor(hi) + 1)) if arg.arg_type == "int" else
                  [round(lo + (hi - lo) * i / 9, 3) for i in range(10)])
        return values + list(numbers), "native JSON schema range + task numbers"
    contract = getattr(app, "get_tool_contract", lambda _: None)(tool.name)
    parameter = contract.parameters.get(arg.name) if contract else None
    if parameter and parameter.numeric:
        schema = parameter.numeric.json_schema()
        lo, hi = schema.get("minimum", 0), schema.get("maximum")
        if hi is not None:
            if arg.arg_type == "int":
                values = list(range(int(lo), int(hi) + 1))
            else:
                values = [round(lo + (hi - lo) * i / 9, 3) for i in range(10)]
            return values + numbers, "native numeric contract range + task numbers"
    if tool.class_name == "SharedTractorApp":
        return _numeric_values(("TractorApp", tool.name, arg.name), arg.arg_type, numbers)
    if tool.class_name == "WarehouseApp" and arg.name == "target_moisture_pct":
        return _numeric_values(("FarmWorldApp", "dry_grain", arg.name), arg.arg_type, numbers)
    return None


def dependent_menu(tool: Any, *, enforced_tool_adaptor: bool = False) -> bool:
    names = {a.name for a in tool.args}
    if enforced_tool_adaptor and tool.class_name == "TractorApp" and tool.name == "load_seeds":
        return True
    return extended_scene_tool(tool) and (("farm_id" in names or "asset_id" in names) or
        tool.name == "measure_grain_moisture" and {"plot_id", "batch_id"} <= names or
        tool.class_name.startswith("Paddy") and (tool.name in (*RICE_OBS_AMOUNTS, "irrigate") or "machine_id" in names))


def tool_ridge_count(tool: Any, default: int) -> int:
    app = tool.class_instance
    if hasattr(app, "runtime"):
        return max(site.farm.num_ridges for site in app.runtime.farms.values())
    world = scene_world(tool)
    if hasattr(world, "num_ridges"):
        return world.num_ridges
    if getattr(app, "farm_environment", None) is not None:
        return max(f.world.num_ridges for f in app.farm_environment.farms.values())
    return default
