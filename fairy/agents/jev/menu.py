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
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from fairy.apps.farm_world import tractor_app as _tractor
from fairy.apps.farm_world.models import SeedType

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
    ("WeatherApp", "get_forecast", "days"): (1, 7),
    ("FarmWorldApp", "dry_grain", "target_moisture_pct"): (11.0, 16.0),
    ("TractorApp", "plant_seeds", "depth_cm"): (3.0, 5.0),
    ("TractorApp", "replant_seeds", "depth_cm"): (3.0, 5.0),
    ("FieldOpsApp", "apply_pesticide_manual", "ridge_count"): (1, 2),
}

EVENLY_SPACED_COUNT = 10


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
) -> ArgMenu:
    key = (tool.class_name, tool.name, arg.name)
    description = descriptions.get(arg.name, "")
    if arg.arg_type == "bool":
        values: list[Any] = [True, False]
        source = "true / false"
    elif arg.arg_type == "int" and arg.name in RIDGE_ARGS:
        values = list(range(num_ridges))
        source = f"every ridge 0-{num_ridges - 1}"
    elif arg.arg_type == "str":
        values, source = _text_values(tool, arg)
    elif arg.arg_type in ("int", "float"):
        values, source = _numeric_values(key, arg.arg_type, numbers)
    else:
        raise ValueError(f"No menu rule for {key} of type {arg.arg_type}")

    if arg.has_default and arg.default is not None:
        default = arg.default
        if arg.arg_type == "float":
            default = round(float(default), 3)
        values.append(default)
        source += " + default"

    seen: dict[str, Any] = {}
    ordered = values if arg.arg_type in ("str", "bool") else sorted(values)
    for value in ordered:
        seen.setdefault(_option_key(value, ridge=arg.name in RIDGE_ARGS), value)
    if not seen:
        raise ValueError(f"Empty menu for {key}")
    if len(seen) > MAX_CHOICE_OPTIONS:
        raise ValueError(f"Menu for {key} has {len(seen)} options (> {MAX_CHOICE_OPTIONS})")
    return ArgMenu(arg.name, arg.arg_type, description, source, seen)


def _text_values(tool: Any, arg: Any) -> tuple[list[Any], str]:
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
    tools_map: dict[str, Any], *, task_text: str, num_ridges: int
) -> dict[str, ToolMenu]:
    """One ToolMenu per tool, in the same order the LLM agent sees them."""
    numbers = task_numbers(task_text)
    menus: dict[str, ToolMenu] = {}
    for tool_name, tool in tools_map.items():
        docs = arg_descriptions(tool.function_description)
        menus[tool_name] = ToolMenu(
            tool_name=tool_name,
            description=first_paragraph(tool.function_description),
            args=[
                build_arg_menu(
                    tool, arg, descriptions=docs, numbers=numbers, num_ridges=num_ridges
                )
                for arg in tool.args
            ],
        )
    if len(menus) + 1 > MAX_CHOICE_OPTIONS:
        raise ValueError(f"Tool menu has {len(menus) + 1} options (> {MAX_CHOICE_OPTIONS})")
    return menus
