"""Compressed maize waits keep elapsed time and expose the requested briefing."""
import pytest

from fairy.scenarios.registry import get_scenario_class


@pytest.mark.parametrize("variant,total,wait_count,wait_days", [
    ("normal", 113, 10, 99),
    ("water_limit", 106, 9, 100),
    ("nitrogen_limit", 117, 11, 99),
])
def test_one_wait_per_management_window_keeps_original_elapsed_time(
    variant, total, wait_count, wait_days,
):
    scene = get_scenario_class("scenario_maize_l3_" + variant)()
    scene.setup()
    waits = [e for e in scene.events if e.function.__name__ == "advance_time"]
    assert len(scene.events) == total
    assert len(waits) == wait_count
    assert sum(e.kwargs["days"] for e in waits) == wait_days
    assert all(set(e.kwargs) == {"days"} for e in waits)
    assert sum(e.kwargs["days"] * 86400 for e in waits) == wait_days * 86400
    assert all(e.event_id.startswith("o_wait_to_day_") for e in waits)


@pytest.mark.parametrize("variant,plan", [
    ("normal", "第25日300公斤、第50日300公斤"),
    ("water_limit", "参考方案不额外追肥"),
    ("nitrogen_limit", "第15日80公斤、第30日80公斤"),
])
def test_detail_true_adds_current_reference_plan_without_changing_basic_task(variant, plan):
    cls = get_scenario_class("scenario_maize_l3_" + variant)
    basic, detailed = cls(detailed_briefing=False), cls(detailed_briefing=True)
    basic.setup()
    detailed.setup()
    assert detailed.scenario_input.startswith(basic.scenario_input + "\n\n")
    assert "详细管理参考" not in basic.scenario_input
    assert plan in detailed.scenario_input
    assert "不是无条件执行指令" in detailed.scenario_input
    assert "不需要每天重复发送等待命令" in detailed.scenario_input
    assert len(basic.events) == len(detailed.events)


def test_detail_requires_boolean():
    scene = get_scenario_class("scenario_maize_l3_normal")(detailed_briefing="true")
    with pytest.raises(ValueError, match="JSON boolean"):
        scene.setup()
