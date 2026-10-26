"""Shared constraints and acceptance for explicitly registered rice scenarios.

Concrete scenarios implement init_and_populate_apps/build_events_flow, just like
farm_world_fullseason_v2. Oracle execution is inherited from Scenario/Engine.
"""
from __future__ import annotations

from fairy.scenarios.scenario import Scenario
from fairy.scenarios.rice.rice_scenario_catalog import RiceScenarioSpec
from fairy.scenarios.rice.validation import validate_rice_task


class RiceScenario(Scenario):
    spec: RiceScenarioSpec
    crop_name = "rice"

    def __init__(self, **kwargs):
        spec = getattr(type(self), "spec", None)
        if not isinstance(spec, RiceScenarioSpec):
            raise TypeError("Instantiate a registered rice scenario with its declared spec")
        if kwargs.get("crop_backend", "wofost") != "wofost":
            raise ValueError("Rice scenarios require WOFOST; legacy is not substituted")
        if kwargs.get("crop_backend_options"):
            raise ValueError("Rice uses its versioned model profile; soybean overrides are not applicable")
        if kwargs.get("scenario_id", spec.scenario_id) != spec.scenario_id:
            raise ValueError("Rice scenario ID must match its registered specification")
        if kwargs.get("start_time", 1767225600.) != 1767225600.:
            raise ValueError("Rice seasons start on 2026-01-01; later starts come from checkpoints")
        mode = kwargs.get("detailed_briefing", True)
        if isinstance(mode, str) and mode.lower() in {"true", "false"}:
            mode = mode.lower() == "true"
        if not isinstance(mode, bool):
            raise ValueError("Rice detailed_briefing supports true/false; other context modes have no rice library")
        kwargs.update(crop_backend="wofost", scenario_id=spec.scenario_id, detailed_briefing=mode)
        kwargs.setdefault("start_time", 1767225600.)
        kwargs.setdefault("scenario_input", spec.detailed_briefing_text if mode else spec.briefing_text)
        super().__init__(**kwargs)
        self.task, self.variant, self.level = spec.task, spec.variant, spec.level
        self.source_l3_scenario_id = spec.source_l3_scenario_id
        self.source_checkpoint_label = spec.source_checkpoint_label
        self.source_slug = spec.source_slug

    def validate(self, env):
        return validate_rice_task(self, env)
