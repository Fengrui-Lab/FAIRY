"""Task and expert briefings share the same contract without disclosing Oracle recipes."""

from importlib import import_module
import re

import pytest

from scripts.sugarbeet_oracle import SCENARIOS


@pytest.mark.parametrize("name", SCENARIOS)
def test_task_and_expert_briefings_share_facts_and_keep_management_choices_open(name):
    module, class_name = SCENARIOS[name]
    cls = getattr(import_module("fairy.scenarios.management_extensions." + module), class_name)
    scene = cls(calibrating=True, detailed_briefing=False, seed=0)
    basic = scene.task_description()
    scene.detailed_briefing = True
    expert = scene.task_description()
    assert expert.startswith(basic)
    for text in (basic, expert):
        assert "ArableField.get_field_info" in text
        assert "OperatingAccounts.get_accounts" in text
        assert "RootDelivery.get_delivery_info" in text
        assert "任务结束时汇报" in text
        assert not any(word in text for word in ("Oracle", "评分", "参考策略", "最优策略"))
        # Dates, trigger fractions, allocation shares and dose recipes come from
        # observations/decisions, rather than the frozen benchmark policy.
        assert re.findall(r"\d+(?:\.\d+)?", text) == [f"{scene.resources.area_ha:g}"]
    assert "管理建议" not in basic
    assert "read_root_zone_sensors" not in basic
    assert "read_canopy_sensors" not in basic
    assert "read_root_zone_sensors" in expert
    assert "read_canopy_sensors" in expert
    assert "生育阶段" in expert and "复查" in expert
    assert "必要时分次追施" in expert
    if scene.rotation:
        assert "最低产出" in basic and "安全入库" in basic
        assert "begin_next_cycle" in expert
    if name == "seedling_rescue":
        assert "已播种" in basic and "投入历史" in expert
    if name == "high_water_price":
        assert "最大化净经营收益" in basic and "实际水费" in expert
