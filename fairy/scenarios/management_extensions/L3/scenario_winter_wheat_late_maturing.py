"""Full-season wheat with the official, longer grain-filling Winter_wheat_101."""

import json
from functools import partial
from pathlib import Path

from fairy.scenarios.validation_result import ScenarioValidationResult

from ..apps.winter_wheat_variety_farm_app import LATE_SEED, VarietyWheatFarm
from ..evaluation.winter_wheat import evaluate
from ..winter_wheat_setup import initialize_wheat_farm
from ..winter_wheat_workflow import capture_wheat_oracle
from .scenario_winter_wheat_full_season import ScenarioWinterWheatFullSeason


ORACLES = Path(__file__).resolve().parents[1] / "data/winter_wheat_oracles"


class ScenarioWinterWheatLateMaturing(ScenarioWinterWheatFullSeason):
    scenario_id = "scenario_l3_winter_wheat_late_maturing"
    seed_by_block = (LATE_SEED,) * 16

    def __init__(self, **kwargs):
        self._oracle = (
            {}
            if kwargs.get("calibrating", False)
            else json.loads((ORACLES / f"{self.scenario_id}.json").read_text(encoding="utf-8"))
        )
        self.ORACLE_REFERENCE = self._oracle.get("reference")
        super().__init__(**kwargs)

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("Configure inputs at construction")
        initialize_wheat_farm(
            self, farm_class=partial(VarietyWheatFarm, seed_by_block=self.seed_by_block)
        )
        self.scenario_input = (
            self._input_override
            if self._input_override is not None
            else self.task_description(self.detailed_briefing)
        )
        self.additional_system_prompt = (
            self._system_override if self._has_system_override else self.scenario_input
        )
        self.build_events_flow()

    def task_description(self, detailed=True):
        task = (
            f"经营一座面积{self.resources.area_ha * 10000:g}平方米的冬小麦农场，"
            "按地块完成秋播、水肥管理、成熟收获和安全入库，兼顾产量与净经营收益。"
            "全田使用灌浆期较长的官方 WOFOST 冬小麦参考品种，农场可查询适用种子、物资和价格。"
        )
        if not detailed:
            return task + "通过 OperatingAccounts.get_accounts 查询价格与物资。"
        return task + (
            "\n\n本场使用 Winter_wheat_101。十月上中旬先核对播期、地块墒情和近期天气，再整平并分批播种。"
            "底肥约每块 8 千克尿素。播后核对播种覆盖，出苗后和越冬期间复查苗情。"
            "\n\n返青时先核对冠层变化和根区可用氮，追肥可参考每块 9–10 千克尿素。"
            "四月冠层扩展时，按相同地块的墒情趋势、预报和剩余库存安排水肥。"
            "四月初和中下旬的两轮追肥可分别参考每块 7–9 和 5–6 千克尿素，复核累计用量。"
            "水深每轮约 50 毫米，土壤暂时湿润时，约定下一次检查。"
            "\n\n本场品种通常五月上旬先开花，灌浆持续较久。"
            "花前及花后分别核对生育阶段、根区水分、降雨到达时间，必要时按原地块补水。"
            "施肥和灌水后按生效时间复查同地块，再判断是否追加。"
            "\n\n六月下旬先逐块核对原生成熟和地面可作业性，再分批收获、卸粮、干燥和入库。"
            "最后核实全田已收、粮箱已卸、粮批安全入库，并据账本报告产量、实际成本和净经营收益。"
        )

    def build_events_flow(self):
        return capture_wheat_oracle(self, self._oracle.get("steps", ()))

    def validate(self, env=None):
        result = evaluate(self, env)
        by_variety = {}
        area_ha = self.farm.ridge_area_m2 / 10000
        for block, backend in enumerate(self.farm.backends):
            crop = backend.values
            row = by_variety.setdefault(
                backend.bundle.cultivar,
                {
                    "blocks": [],
                    "dry_grain_kg": 0.0,
                    "stored_grain_kg": 0.0,
                    "flowering_dates": set(),
                    "maturity_dates": set(),
                },
            )
            row["blocks"].append(block)
            row["dry_grain_kg"] += (crop.get("TWSO") or 0) * area_ha
            if crop.get("DOA"):
                row["flowering_dates"].add(crop["DOA"])
            if crop.get("DOM"):
                row["maturity_dates"].add(crop["DOM"])
        for row in by_variety.values():
            for key in ("flowering_dates", "maturity_dates"):
                row[key] = sorted(row[key])
        for batch in self.warehouse.grain_batches.values():
            if batch.status == "stored" and batch.cultivar_id in self.farm.varieties:
                cultivar = self.farm.varieties[batch.cultivar_id]
                by_variety[cultivar]["stored_grain_kg"] += batch.quantity_kg
        result.metadata["varieties"] = by_variety
        batch_cultivars_invalid = any(
            len(batch.cultivar_ids) != 1
            or set(batch.cultivar_ids)
            != {self.seed_by_block[block] for block in batch.ridge_ids}
            for batch in self.warehouse.grain_batches.values()
        )
        if batch_cultivars_invalid:
            result.metadata["operational_success"] = False
            message = "Each stored grain lot must preserve its field cultivar identity"
            return ScenarioValidationResult(
                success=False,
                message=message if result.success else f"{result.message}. {message}",
                metadata=result.metadata,
            )
        return result
