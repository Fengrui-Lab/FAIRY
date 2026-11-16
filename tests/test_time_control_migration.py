from __future__ import annotations

from types import SimpleNamespace

import pytest

from fairy.apps.farm_world import FarmWorldApp
from fairy.apps.system import SystemApp
from fairy.scenarios.fos.spatiotemporal import _season_day_map
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.workflow_validation import workflow_from_oracle_events
from fairy.types import CapturedEvent, EventRegisterer
from scripts.build_oracle_baselines import (
    _formal_fullseason_scenarios,
    _selected_l2_l1_scenarios,
)
from scripts.fullseason.build_time_control_references import comparable


SCENARIOS = sorted(set(_formal_fullseason_scenarios() + _selected_l2_l1_scenarios()))


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_approved_oracles_only_call_exposed_tools(scenario_id: str) -> None:
    scenario = get_scenario_class(scenario_id)()
    scenario.setup()
    for event in scenario.events:
        if not event.is_oracle:
            continue
        name = event.function.__name__
        assert name not in {"commit_daily_physics", "wait_for_notification"}
        assert name in {tool.name for tool in event.app.get_tools()}


def test_unregistered_time_helpers_keep_event_capture_and_internal_execution() -> None:
    system = SystemApp()
    farm = FarmWorldApp()
    assert "wait_for_notification" not in {tool.name for tool in system.get_tools()}
    assert "commit_daily_physics" not in {tool.name for tool in farm.get_tools()}
    called = []
    system.wait_for_next_notification = lambda: called.append(True)
    assert not farm.physics_active
    with EventRegisterer.capture_mode():
        wait = system.wait_for_notification(timeout=3)
        commit = farm.commit_daily_physics()
    assert isinstance(wait, CapturedEvent)
    assert isinstance(commit, CapturedEvent)
    assert not called
    wait.execute()
    assert called == [True]
    assert system.wait_for_notification_timeout.timeout == 3
    assert commit.execute() == {"status": "noop", "reason": "physics_inactive"}


def test_existing_workflow_export_and_scoring_count_migrated_day() -> None:
    system = SystemApp()
    with EventRegisterer.capture_mode() as events:
        start = system.get_current_time().oracle().with_id("start")
        day = system.advance_time(days=1).oracle().with_id("day").depends_on(start)
        system.get_current_time().oracle().with_id("after").depends_on(day)
    workflow = workflow_from_oracle_events(SimpleNamespace(events=events))
    days = _season_day_map(workflow)
    assert days["step0"] == 0
    assert days["step2"] == 1
    assert workflow["step2"]["depends_on"] == ["step1"]


def test_reference_comparison_preserves_operation_durations_and_state() -> None:
    before = {"mission_id": "random-a", "duration_s": 10, "grain_kg": 100}
    after = {"mission_id": "random-b", "duration_s": 10, "grain_kg": 100}
    assert comparable(before) == comparable(after)
    assert comparable(before) != comparable({**after, "duration_s": 11})
    assert comparable(before) != comparable({**after, "grain_kg": 101})
