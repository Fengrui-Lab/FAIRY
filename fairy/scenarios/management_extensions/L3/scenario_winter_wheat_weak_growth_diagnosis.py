"""Diagnose similar winter wheat canopy symptoms with different root-zone causes."""

from copy import copy, deepcopy
import json
from pathlib import Path
from typing import ClassVar

from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered

from ..apps.winter_wheat_accounts_app import WheatResources
from ..engines.winter_wheat_inputs import fingerprint
from ..winter_wheat_workflow import capture_wheat_oracle
from .scenario_winter_wheat_block_scouting import (
    ScenarioWinterWheatBlockScouting,
    ScoutingWheatFarm,
)


REFERENCE_PATH = (
    Path(__file__).parents[1]
    / "data/winter_wheat_oracles"
    / "scenario_l3_winter_wheat_weak_growth_diagnosis.json"
)


class WeakGrowthWheatFarm(ScoutingWheatFarm):
    """Two complete sensor zones have different native soil constraints."""

    shallow_blocks = (0, 1)
    low_n_blocks = (8, 9)

    def block_inputs(self, block_id):
        if block_id in self.low_n_blocks:
            return super().block_inputs(block_id)
        inputs = copy(self.bundle)
        inputs.manifest = deepcopy(self.bundle.manifest)
        site = inputs.manifest["native_site_parameters"]
        site["NAVAILI"] = 55.0
        if block_id in self.shallow_blocks:
            inputs.manifest["native_soil_parameters"].update(
                SMW=0.10, SMFCF=0.23, SM0=0.41, RDMSOL=30.0
            )
            site.update(WAV=8.0, SMLIM=0.23)
        inputs.manifest["soil_status"] = "benchmark soil profile; not a surveyed field"
        inputs.identity = fingerprint(inputs.manifest)
        return inputs

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_field_info(self) -> dict:
        """Read block geometry, physical soil limits and wheat operation rules.

        Returns:
            Block ID, rootable depth (cm), field capacity and wilting point
            (m³/m³) for each block, plus area and sowing/harvest requirements.
            Read the root-zone probes for today's soil water and nitrogen.
        """
        result = super().get_field_info()
        profiles = []
        for index, backend in enumerate(self.backends):
            soil = backend.bundle.manifest["native_soil_parameters"]
            profiles.append(
                {
                    "block_id": index,
                    "rootable_depth_cm": soil["RDMSOL"],
                    "field_capacity_vwc": soil["SMFCF"],
                    "wilting_point_vwc": soil["SMW"],
                }
            )
        result["block_soils"] = profiles
        return result


class ScenarioWinterWheatWeakGrowthDiagnosis(ScenarioWinterWheatBlockScouting):
    scenario_id = "scenario_l3_winter_wheat_weak_growth_diagnosis"
    farm_class = WeakGrowthWheatFarm
    resources: ClassVar = WheatResources(
        fertilizer_stock_kg=400.0, water_stock_m3=2100.0
    )
    ORACLE_REFERENCE: ClassVar = None

    def task_description(self, detailed=True):
        basic = (
            f"经营一座面积{self.resources.area_ha * 10000:g}平方米的冬小麦农场。"
            "春季有些地块长势偏弱，先判断各块缺什么，再决定是否局部处理。"
            "完成播种、成熟收获和安全入库，在资源限制下提高净经营收益。"
        )
        if not detailed:
            return (
                basic + "通过WheatField.get_field_info查地块与作业条件，"
                "通过OperatingAccounts.get_accounts查价格和资源。"
            )
        return basic + (
            "\n\n秋播前检查播期、土壤墒情、设备、库存和价格。"
            "十月中旬前后整地分块条播，播深约3 cm，入冬前核对出苗。"
            "\n\n返青到四月冠层扩展时，先比较各区根区水氮与冠层读数。"
            "天气允许时用无人机比较各块冠层绿度和温度，再用地面观测比较弱块与同生育阶段的正常邻块。"
            "用各块自己的田间持水量和萎蔫点判断是否缺水。"
            "水分已足而根区可用氮和叶片读数都偏低时，再考虑补氮。"
            "证据不一致时增加邻块地面抽查，等有把握再处理。"
            "确认偏干的块，局部水深可参考约50–55 mm。确认缺氮的块，首轮可参考约8 kg尿素/块。"
            "按原地块读数和库存调整。"
            "等水肥结算后复查原块和邻块，确认水氮读数和长势是否按预期变化。"
            "\n\n四月下旬和五月花前，如预期全田供氮不足，追肥可分别参考约11–12和8–9 kg尿素/块。"
            "开花前后及灌浆时继续复查墒情，结合降雨到达时间和余量决定是否补水，单轮约45–50 mm可作参考。"
            "六月成熟时按地块状态和作业天气分批收获，核对粮箱、批次含水率和安全入库。"
            "最后报告产量、投入与净经营收益。"
        )

    def build_events_flow(self):
        if self.calibrating:
            return []
        data = json.loads(REFERENCE_PATH.read_text())
        self.ORACLE_REFERENCE = data["reference"]
        return capture_wheat_oracle(self, data["steps"])
