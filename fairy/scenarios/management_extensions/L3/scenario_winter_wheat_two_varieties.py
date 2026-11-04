"""Manage two official wheat varieties side by side in one flat field."""

from ..apps.winter_wheat_accounts_app import SEED
from ..apps.winter_wheat_variety_farm_app import LATE_SEED
from .scenario_winter_wheat_late_maturing import ScenarioWinterWheatLateMaturing


class ScenarioWinterWheatTwoVarieties(ScenarioWinterWheatLateMaturing):
    scenario_id = "scenario_l3_winter_wheat_two_varieties"
    seed_by_block = (SEED,) * 8 + (LATE_SEED,) * 8

    def task_description(self, detailed=True):
        task = (
            f"经营一座面积{self.resources.area_ha * 10000:g}平方米的冬小麦农场。"
            "全田两半分别指定两个官方 WOFOST 冬小麦参考品种。"
            "按地块分开播种、管理、收获和入库，兼顾产量与净经营收益。"
            "地块的品种分配、库存及价格可在农场查询。"
        )
        if not detailed:
            return task + "通过 OperatingAccounts.get_accounts 查询价格与物资。"
        return task + (
            "\n\n本场使用 Winter_wheat_104 和 Winter_wheat_101。十月上中旬先核对两组地块的种子分配和墒情。101 组在上旬遇到可下地的窗口时可先播，另一组在合适的窗口跟进。"
            "按分配换装种子，换种前确认种箱已空或退回余种，播后逐组核对覆盖。"
            "底肥可参考每块约 8 千克尿素，越冬前检查两组出苗。"
            "\n\n返青时按地块对照冠层和根区可用氮，追肥可参考每块 9–10 千克尿素。"
            "四月冠层扩展时分轮核对墒情及预报，必要时按每轮约 50 毫米补水；"
            "两轮追加尿素可分别参考每块 7–9 和 5–6 千克，保留实际库存余量。"
            "\n\n五月不要用一侧的生育阶段推断另一侧。"
            "101 可能更早开花但灌浆较长，分别检查花前和灌浆中的根区水分、近期降雨和原有水量。"
            "墒情够用时约定复查，投入结算后回到同一组地块确认。"
            "\n\n六月中旬开始分别确认两组成熟和可作业性。"
            "已成熟的一组可以先收，另一组等到本身成熟再收。"
            "换组前卸空粮箱，分批核对含水率并安全入库，最后按品种核对收获与批次，再报告全场账本。"
        )
