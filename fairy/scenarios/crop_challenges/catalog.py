"""Human-readable farming plans, not claims of field-calibrated crop response."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Challenge:
    crop: str
    name: str
    question: str
    controls: tuple[str, ...]
    focus: tuple[int | str, ...]
    metric: str = "biological_dry_kg"
    deadline_days: int = 180

    @property
    def source_id(self):
        return f"scenario_{self.crop}_l3_{self.name}"


CHALLENGES = {
    c.source_id: c for c in (
        Challenge("maize", "zonal_water_priority",
                  "不同土层的六个传感器分区共享有限水额；辨别缺水位置，保留正常区用水。",
                  ("omit", "uniform", "wrong_zone"), tuple(range(22))),
        Challenge("maize", "zonal_nitrogen_recovery",
                  "局部原生氮池发生显式外部亏缺；结合根水和模型氮遥测定向追肥。此扰动不代表自然淋失。",
                  ("omit", "uniform", "wrong_zone"), tuple(range(22, 44))),
        Challenge("maize", "compound_water_n_limit",
                  "缺水、缺氮、共限及正常区域并存；分别分配水肥，不把所有低长势都当成同一原因。",
                  ("omit", "water_only", "nitrogen_only", "uniform"), tuple(range(54))),
        Challenge("maize", "staggered_water_priority",
                  "同品种分三期首次播种；结合各区阶段和根水安排灌溉。只考粗阶段，不假定精细授粉损伤。",
                  ("omit", "uniform", "wrong_zone"), tuple(range(64))),
        Challenge("maize", "rain_aware_irrigation",
                  "利用确定性的近期降雨预报，区分必须灌水和可以等雨的窗口，节水同时保全产量。",
                  ("omit", "immediate"), tuple(range(64)), "water_used", 180),
        Challenge("maize", "rainy_harvest_window",
                  "逐区核实成熟、25%收获水分、天气与通行性，在期限内分批收卸、干燥至14%并安全入库。烘干没有真实能耗模型。",
                  ("miss_window",), tuple(range(64)), "stored_kg_at_14pct", 160),
        Challenge("rice", "zonal_water_n_allocation",
                  "两田格供氮和耙后渗透不同；结合有适用范围的氮信号、水层与根水区别管理。",
                  ("omit", "water_only", "nitrogen_only", "wrong_zone"), ("p1", "p2")),
        Challenge("rice", "infrastructure_water_priority",
                  "漏埂、堵渠和窄供水窗口叠加；权衡救急灌水与修复耗时，疏渠恢复流量、修埂减少漏水。",
                  ("omit", "repair_all_first", "irrigate_first"), ("p1", "p2")),
        Challenge("rice", "zonal_crop_protection",
                  "两田格虫病草组成不同；巡查确诊后按雨风和水层选择处理对象、药种和除草时机。",
                  ("omit", "wrong_zone", "uniform"), ("p1", "p2")),
        Challenge("rice", "rainy_harvest_capacity",
                  "晚雨与小粮箱、有限干燥能力限制收储；排空田面水后还需核实根区可通行性和粮食水分。",
                  ("miss_window",), ("p1", "p2"), "stored_kg_at_14pct", 150),
    )
}

TASKS = {}
for definition in CHALLENGES.values():
    for level in ("L3", "L2"):
        TASKS[f"scenario_{definition.crop}_{level.lower()}_{definition.name}"] = (definition.source_id, level, "diagnosis")
for crop, task, source in (
    ("maize", "targeted_irrigation", "zonal_water_priority"),
    ("maize", "targeted_fertilization", "zonal_nitrogen_recovery"),
    ("rice", "targeted_protection", "zonal_crop_protection"),
    ("rice", "channel_clearance", "infrastructure_water_priority"),
):
    TASKS[f"scenario_{crop}_l1_{task}"] = (f"scenario_{crop}_l3_{source}", "L1", task)
