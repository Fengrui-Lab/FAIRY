"""Random inspection labels must not obscure real partial-response drift."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from fairy.controllers.engine import ReplayDivergenceError
from fairy.scenarios.management_extensions.apps.winter_wheat_scouting_apps import WheatScoutRobot
from fairy.scenarios.workflow import WorkflowStep
from scripts.rebatch_fos_from_traces import _verify_saved_trace_response


def response():
    return dict(status="partial", farm_id="wheat", covered_blocks=[4], uncovered_blocks=[5],
                observations=[dict(block_id=4, inspection_id="1234abcd", spad_proxy=45.6,
                                   observed_at="2020-04-28T13:53:16+08:00")],
                duration_s=280., battery_remaining_pct=0., warning="Battery below required level")


def tool():
    return SimpleNamespace(name="inspect_blocks", class_instance=WheatScoutRobot.__new__(WheatScoutRobot))


def test_only_uuid_label_changes_are_accepted_without_mutating_results():
    original = response()
    actual = deepcopy(original)
    actual["observations"][0]["inspection_id"] = "abcd1234"
    step = WorkflowStep(name="inspect", tool_name="Robot__inspect_blocks", content=original)
    assert _verify_saved_trace_response(step, actual, tool()) is True
    assert original["observations"][0]["inspection_id"] == "1234abcd"
    assert actual["observations"][0]["inspection_id"] == "abcd1234"


@pytest.mark.parametrize("change", [
    lambda x: x.update(farm_id="another_field"),
    lambda x: x.update(covered_blocks=[5]),
    lambda x: x.update(battery_remaining_pct=1.),
    lambda x: x["observations"][0].update(spad_proxy=45.61),
    lambda x: x["observations"][0].update(observed_at="2020-04-28T13:53:17+08:00"),
    lambda x: x["observations"][0].update(inspection_id="not-a-uuid"),
])
def test_physical_data_and_unrecognized_tokens_remain_exact(change):
    original, actual = response(), response()
    actual["observations"][0]["inspection_id"] = "abcd1234"
    change(actual)
    with pytest.raises(ReplayDivergenceError):
        _verify_saved_trace_response(WorkflowStep(name="inspect", tool_name="Robot__inspect_blocks", content=original), actual, tool())


def test_uuid_exception_does_not_apply_to_other_partial_writes():
    original, actual = response(), response()
    actual["observations"][0]["inspection_id"] = "abcd1234"
    other = SimpleNamespace(name="inspect_blocks", class_instance=object())
    with pytest.raises(ReplayDivergenceError):
        _verify_saved_trace_response(WorkflowStep(name="inspect", tool_name="AnotherApp__inspect_blocks", content=original), actual, other)
