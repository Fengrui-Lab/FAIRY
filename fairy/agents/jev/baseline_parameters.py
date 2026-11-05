"""Frozen pre-enhancement parameter policy, retained for controlled comparisons.

Source: typesafe-maize10-harvest-feedback-20261104/FAIRY.
This includes local new-scene compatibility; it is not pristine upstream.
Do not improve this policy in place: add a new version instead.
"""
from __future__ import annotations
import json
from typing import Any
from .menu import (ToolMenu, PASS_WIDTH, DURATION_ARG, dependent_menu,
                   extended_scene_tool, scene_world, build_arg_menu,
                   arg_descriptions, task_numbers, MAX_CHOICE_OPTIONS)
RANGE_END_TO_START = {"end_ridge": "start_ridge", "end": "start"}
def _arg_question_id(arg_name, tool_name=None):
    return f"arg__{tool_name}__{arg_name}" if tool_name else f"arg__{arg_name}"
def _count_key(n):
    return f"{n} ridge" if n == 1 else f"{n} ridges"

class BaselineParameters:
    def _jev_arguments(
        self,
        state: dict[str, Any],
        pick: str,
        options: dict[str, tuple[str, dict[str, Any]]] | None = None,
        answers: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], dict[str, float]]:
        """Jev's arguments for pick: from the fan-out answers, or one more request."""
        menu = self.tool_menus[pick]
        if dependent_menu(self.tools_map[pick]):
            return self._dependent_values(menu, state)
        if options is not None:
            self._fanout["hits"] += 1
        else:
            self._fanout["misses"] += 1
            arg_questions, options = self._value_questions(menu)
            answers = self._ask("arguments", state, arg_questions)
        return self._read_values(menu, options, answers)

    def _value_questions(
        self, menu: ToolMenu, tool_key: str | None = None
    ) -> tuple[dict[str, dict[str, Any]], dict[str, tuple[str, dict[str, Any]]]]:
        """One question per argument, none depending on another's answer.

        A range end is asked as "how many ridges" from the start; _read_values turns
        it into the end ridge. Returns the questions and, per argument, its
        question id and options.
        """
        names = {a.name for a in menu.args}
        questions: dict[str, dict[str, Any]] = {}
        options: dict[str, tuple[str, dict[str, Any]]] = {}
        for a in menu.args:
            qid = _arg_question_id(a.name, tool_key)
            count_from = RANGE_END_TO_START.get(a.name) if RANGE_END_TO_START.get(a.name) in names else None
            if count_from:
                width = self._menu_width(menu)
                opts: dict[str, Any] = {_count_key(n): n for n in range(1, width + 1)}
            else:
                opts = self._arg_options(menu, a, {})
            questions[qid] = {
                "type": "choice",
                "instructions": self._arg_instructions(
                    menu, a, speculative=tool_key is not None, count_from=count_from
                ),
                "criteria": {key: None for key in opts},
            }
            options[a.name] = (qid, opts)
        return questions, options

    def _menu_width(self, menu: ToolMenu) -> int:
        native = self.tools_map[menu.tool_name]
        if extended_scene_tool(native):
            if native.class_name == "ManualOpsApp":
                return 2
            if native.class_name in ("SharedTractorApp", "TractorService"):
                return PASS_WIDTH.get(("TractorApp", native.name), self._num_ridges)
            world = scene_world(native)
            return PASS_WIDTH.get((native.class_name, native.name), getattr(world, "num_ridges", self._num_ridges))
        return PASS_WIDTH.get(tuple(menu.tool_name.split("__", 1))) or self._num_ridges

    def _dependent_values(self, menu: ToolMenu, state: dict[str, Any]):
        """Same Choice/value mapping, resolving entity selectors before dependants."""
        native = self.tools_map[menu.tool_name]
        arguments, confidences = {}, {}
        scope_order = {"farm_id": 0, "asset_id": 1, "plot_id": 2, "machine_id": 2}
        args = sorted(menu.args, key=lambda a: (scope_order.get(a.name, 3), a.name == "batch_id"))
        for arg in args:
            opts = self._arg_options(menu, arg, arguments)
            if arg.name in ("water_mm", "quantity", "liters", "count", "kg"):
                raw_arg = next(a for a in native.args if a.name == arg.name)
                scoped = build_arg_menu(native, raw_arg,
                    descriptions=arg_descriptions(native.function_description),
                    numbers=task_numbers(str(state.get("task", ""))), num_ridges=self._num_ridges,
                    arguments=arguments, steps=self._facts.get("steps", []), task_text=str(state.get("task", "")))
                opts = scoped.options
            count_from = RANGE_END_TO_START.get(arg.name)
            runtime = getattr(native.class_instance, "runtime", None)
            if runtime is not None and arg.name == "asset_id" and arguments.get("farm_id"):
                opts = {k: v for k, v in opts.items() if v is None or arguments["farm_id"] in runtime.assets[v].spec.allowed_farm_ids}
            if runtime is not None and arguments.get("farm_id"):
                from types import SimpleNamespace
                world = runtime.farms[arguments["farm_id"]].farm
                asset = runtime.assets.get(arguments.get("asset_id"))
                caps = runtime.capabilities(SimpleNamespace(farm=world, farm_id=arguments["farm_id"], asset=asset, asset_id=arguments.get("asset_id")))
                if arg.name == "seed_type":
                    opts = {k: v for k, v in opts.items() if v in caps["planting"]["compatible_seed_types"]}
                if arg.name == "depth_cm":
                    lo, hi = caps["planting"]["depth_cm_range"]
                    opts = {**{f"{round(lo+(hi-lo)*i/9,3):g}": round(lo+(hi-lo)*i/9,3) for i in range(10)}, **opts}
            if count_from in arguments:
                world = scene_world(native, arguments)
                width = self._menu_width(menu)
                width = min(width, world.num_ridges - arguments[count_from])
                opts = {_count_key(n): arguments[count_from] + n - 1 for n in range(1, width + 1)}
            if native.name == "measure_grain_moisture":
                if arg.name == "plot_id":
                    batches = next(a for a in menu.args if a.name == "batch_id").options
                    if not any(v is not None for v in batches.values()):
                        opts = {k: v for k, v in opts.items() if v is not None}
                elif arg.name == "batch_id":
                    opts = {k: v for k, v in opts.items() if (v is None) == (arguments.get("plot_id") is not None)}
            if not opts or len(opts) > MAX_CHOICE_OPTIONS:
                raise ValueError(f"Invalid dependent menu: {menu.tool_name}.{arg.name}")
            qid = _arg_question_id(arg.name, None)
            question = {"type": "choice", "instructions": self._arg_instructions(menu, arg, count_from=count_from if count_from in arguments else None),
                        "criteria": {k: None for k in opts}}
            # Include selected scope in the question, not hidden simulator facts.
            question["instructions"] += " Selected arguments: " + json.dumps(arguments)
            answer = self._ask("arguments", state, {qid: question})[qid]
            arguments[arg.name] = opts[answer["choice"]]
            confidences[qid] = answer["confidence"]
        return arguments, confidences

    def _read_values(
        self,
        menu: ToolMenu,
        options: dict[str, tuple[str, dict[str, Any]]],
        answers: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, float]]:
        names = {a.name for a in menu.args}
        ends = [a for a in menu.args if RANGE_END_TO_START.get(a.name) in names]
        arguments: dict[str, Any] = {}
        confidences: dict[str, float] = {}
        for a in [a for a in menu.args if a not in ends] + ends:
            qid, opts = options[a.name]
            answer = answers[qid]
            value = opts[answer["choice"]]
            confidences[qid] = answer["confidence"]
            if a in ends:
                # Count -> end ridge, unchanged even if it does not fit: the farm
                # refuses it, as for the LLM agent (Part 2, Step 15).
                arguments[a.name] = arguments[RANGE_END_TO_START[a.name]] + value - 1
            elif a.name == DURATION_ARG:
                arguments.update(value)
            else:
                arguments[a.name] = value
        return arguments, confidences
