"""Scenarios reuse wheat farm wiring and public tool capture; no fabricated oracle."""

from __future__ import annotations
from dataclasses import asdict, replace
from datetime import datetime, time, timedelta
import hashlib
import json
import inspect
from pathlib import Path
from zoneinfo import ZoneInfo
from fairy.scenarios.scenario import Scenario
from fairy.types import EventRegisterer
from ..common import capture_step, finish_capture
from ..winter_wheat_setup import initialize_wheat_farm
from ..engines.sugarbeet_inputs import SugarBeetInputs
from ..apps.sugarbeet_farm_app import SugarBeetFarm
from ..apps.sugarbeet_tractor_app import SugarBeetTractor
from ..apps.sugarbeet_irrigation_app import SugarBeetIrrigation
from ..apps.sugarbeet_delivery_app import SugarBeetDelivery
from ..apps.sugarbeet_accounts_app import SugarBeetAccounts
from .contracts import RootContract, digest
from .resources import BeetResources


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class SugarBeetScenario(Scenario):
    variant = "full_season"
    level = "L3"
    rotation = False
    objective_metric = "root_yield"
    farm_class = SugarBeetFarm
    yield_management = False
    minimum_wheat_dry_kg_ha = 0.0

    def __init__(
        self, *, input_dir=None, reference_file=None, calibrating=False, **kwargs
    ):
        kwargs.setdefault("scenario_id", type(self).scenario_id)
        backend = kwargs.pop("crop_backend", "wofost")
        if backend != "wofost":
            raise ValueError("Beet scenarios require the native wofost backend")
        if kwargs.get("crop_backend_options"):
            raise ValueError("Configure beet model inputs through the input manifest")
        super().__init__(crop_backend="wofost", **kwargs)
        self.reference_file = Path(reference_file) if reference_file else None
        default_inputs = DATA_DIR / (
            "wheat_beet_rotation_demo" if self.rotation else "sugarbeet_demo"
        )
        self.input_dir = Path(input_dir) if input_dir is not None else default_inputs
        self.use_bundled_reference = (
            reference_file is None
            and not calibrating
            and self.seed == 0
            and self.input_dir.resolve() == default_inputs.resolve()
        )
        self.input_bundle = SugarBeetInputs(self.input_dir)
        cycles = self.input_bundle.cycles
        expected = ("winter_wheat", "sugarbeet") if self.rotation else ("sugarbeet",)
        if tuple(cycle.crop for cycle in cycles) != expected:
            raise ValueError("L3/L4 input calendar does not match the scenario crops")
        self.resources = BeetResources()
        if self.rotation:
            self.resources = replace(
                self.resources,
                fertilizer_stock_kg=1000.0,
                water_stock_m3=5400.0,
                budget_usd=3500.0,
            )
        if self.variant == "water_limit":
            self.resources = replace(self.resources, water_stock_m3=1200.0)
        if self.variant == "nitrogen_limit":
            self.resources = replace(self.resources, fertilizer_stock_kg=250.0)
        if self.variant == "high_water_price":
            self.resources = replace(self.resources, water_usd_m3=0.35)
        self.root_contract = RootContract()
        if self.variant == "delivery_window":
            self.root_contract = replace(
                self.root_contract,
                delivery_daily_gross_kg=15000,
                maximum_holding_days=2,
            )
        beet = cycles[-1]
        self.delivery_open = beet.harvest_open
        self.delivery_close = beet.harvest_close + timedelta(
            days=self.root_contract.maximum_holding_days
        )
        if self.variant == "delivery_window":
            self.delivery_open = max(
                beet.harvest_open, beet.harvest_close - timedelta(days=10)
            )
        if self.delivery_close > self.input_bundle.season.deadline:
            raise ValueError("Delivery needs time after final harvest")
        self.timezone_name = self.input_bundle.season.timezone
        self.simulation_timezone = ZoneInfo(self.timezone_name)
        self.start_time = datetime.combine(
            self.input_bundle.season.start, time(7), self.simulation_timezone
        ).timestamp()
        finish = datetime.combine(
            self.input_bundle.season.deadline, time(23, 59), self.simulation_timezone
        ).timestamp()
        self.duration = finish - self.start_time
        self.ORACLE_REFERENCE = None
        self.initialization_history = []

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("Configure scenario at construction")

        def accounts_factory(**options):
            self.delivery = SugarBeetDelivery(
                self.farm_environment,
                self.root_contract,
                self.delivery_open,
                self.delivery_close,
            )
            return SugarBeetAccounts(delivery=self.delivery, **options)

        initialize_wheat_farm(
            self,
            farm_class=self.farm_class,
            irrigation_factory=SugarBeetIrrigation,
            tractor_factory=SugarBeetTractor,
            accounts_factory=accounts_factory,
        )
        self.apps.append(self.delivery)
        self.delivery.register_time_manager(self.farm_environment.time_manager)
        self.delivery.rng.seed(self.seed)
        self.tractor.delivery = self.delivery
        self.tractor.accounts = self.irrigation.accounts = self.delivery.accounts = (
            self.accounts
        )
        self.farm.rotation_tractor = self.tractor
        self.farm.management_objective = dict(
            metric=self.objective_metric,
            minimum_wheat_dry_kg_ha=self.minimum_wheat_dry_kg_ha,
            performance_definition="root yield ratio, margin improvement index, or ordered root/grain/margin indices; operational completion is reported separately",
        )
        self.initialize_management_history()
        self.scenario_input = self.task_description()
        self.additional_system_prompt = self.scenario_input
        reference_file = self.reference_file
        if self.use_bundled_reference:
            bundled = DATA_DIR / "sugarbeet_oracles" / f"{self.scenario_id}.json"
            if bundled.is_file():
                reference_file = bundled
        if reference_file is not None:
            reference = json.loads(reference_file.read_text(encoding="utf-8"))
            if (
                self.reference_file
                or reference.get("input_fingerprint") == self.input_fingerprint()
            ):
                self.ORACLE_REFERENCE = reference
        self.build_events_flow()

    def initialize_management_history(self):
        """Establish any declared takeover history through public tools."""

    def task_description(self):
        crops = "冬小麦→休耕→次年春播甜菜" if self.rotation else "春播甜菜"
        objective = {
            "root_yield": "最大化糖厂验收的甜菜净鲜根重量",
            "net_operating_margin": "最大化净经营收益",
            "rotation_yield": "在两季达到最低产出要求的基础上，依次优先提高甜菜验收净鲜根重量、小麦安全入库量和整个轮作的净经营收益",
        }[self.objective_metric]
        constraint = {
            "water_limit": "本季灌溉水供应有限，各分块共用同一批水量。",
            "nitrogen_limit": "本季施肥限于现有尿素库存。",
            "high_water_price": "本季灌溉收费较高，经营目标以实际收入和投入成本结算。",
            "delivery_window": "糖厂接收窗口较短，且有日接收上限。",
            "seedling_rescue": "你接管的是已播种的苗期地块，目前存在缺水问题；既有作业、投入和剩余库存均已登记。",
            "soil_water_priority": "各分区土壤持水能力不同，共享的灌溉水量有限。",
            "shared_resources": "两季共用有限的水氮库存，前茬小麦有明确的最低产出要求，需要统筹两季管理。",
        }.get(self.variant, "")
        task = (
            f"你负责管理同一块{self.resources.area_ha:g}公顷土地，完成{crops}的生产任务。目标是{objective}。"
            f"{constraint}用ArableField.get_field_info查询分块、作业日历和产量要求。"
            "用OperatingAccounts.get_accounts查询价格、资源和预算。"
            "在规定作业窗口和资源预算内完成田间管理、收获及后续处理。"
            "甜菜起收后按RootDelivery.get_delivery_info公布的接收时间、运力、质量和扣杂条件交售，以验收净根重量核算产量。"
            + ("小麦需安全入库，规定的休耕期结束后再换茬；两季延续使用同一地块和剩余库存。" if self.rotation else "")
            + "任务结束时汇报产量、实际投入、交售或入库情况及净经营收益。"
        )
        if not self.detailed_briefing:
            return task
        advice = {
            "water_limit": "限水管理要结合土壤储水、作物状态和后续需水统筹安排，每次灌后根据效果与余量更新计划。",
            "nitrogen_limit": "长势偏弱时先区分缺水与供氮不足，结合已有施氮和根区可利用氮安排追肥，避免用追加施肥代替必要的水分管理。",
            "high_water_price": "追加灌水时同时考虑预期增收和实际水费，按净经营收益目标判断投入是否合算。",
            "seedling_rescue": "接管时先核对播种和水氮投入历史，结合苗情与根区墒情判断补水需求；处理后复查，再决定后续水肥措施。",
            "soil_water_priority": "分别比较各区的持水能力、可扎根深度、墒情和生长状态，按实际需要分配灌水，并分区复查效果。",
            "shared_resources": "分开记录两季水氮用量，结合小麦产出要求、当前状态和后茬可用库存调整分配。",
        }.get(self.variant, "")
        wheat_advice = (
            "冬小麦秋播后检查出苗和越冬前后墒情，返青至灌浆结合苗情与根区状态安排水肥。"
            "确认成熟后收割，卸粮后核对含水率，完成必要的干燥和入库。"
            "休耕期间继续跟踪土壤水氮，后茬计划以届时状态和剩余库存为依据；满足换茬条件后使用begin_next_cycle。"
            if self.rotation else ""
        )
        return task + (
            "\n\n管理建议：用WeatherApp、Tractor核对天气、地表适作条件和机具准备。"
            "播种结合窗口、墒情和规定播深安排，已完成的作业以记录为准。"
            "用Sensor.read_root_zone_sensors和Sensor.read_canopy_sensors观察根区与冠层，并与既往读数比较。"
            "甜菜苗期注意保墒和出苗；叶丛建立及块根生长期间，结合降雨、墒情变化和冠层生长判断是否需要补水。"
            "土壤含水量应结合各区田间持水量、萎蔫点和相对可利用水解释，避免把同一含水量当作不同土壤的统一标准。"
            "施氮结合生育阶段、已有投入、长势和根区可利用氮估计安排供给，必要时分次追施，遵守停氮日、单季上限和库存约束。"
            "工具中的施肥量按每块尿素商品公斤输入，灌溉量按毛灌水毫米输入。"
            "水肥作业后复查状态和到账记录，并根据变化安排下一次检查。"
            f"{advice}{wheat_advice}"
            "收获前核对停灌要求、田间条件、农机和接收能力；甜菜使用beet_harvester与harvest_roots起收，按批次安排交售。"
        )

    def input_fingerprint(self):
        extension = Path(__file__).resolve().parents[1]
        files = []
        for directory in ("sugarbeet", "engines", "apps", "evaluation"):
            for p in sorted((extension / directory).glob("*.py")):
                # Include reused wheat and common account code, not mutable run artifacts.
                if directory == "sugarbeet" or any(
                    x in p.name for x in ("wheat", "sugarbeet", "operating_accounts")
                ):
                    files.append(
                        (
                            str(p.relative_to(extension)),
                            hashlib.sha256(p.read_bytes()).hexdigest(),
                        )
                    )
        for relative in ("winter_wheat_setup.py", "common.py"):
            p = extension / relative
            files.append((relative, hashlib.sha256(p.read_bytes()).hexdigest()))
        fairy_root = extension.parents[1]
        for rel in ("apps/farm_world", "crops"):
            for p in sorted((fairy_root / rel).rglob("*.py")):
                files.append(
                    (
                        str(p.relative_to(fairy_root)),
                        hashlib.sha256(p.read_bytes()).hexdigest(),
                    )
                )
        for rel in (
            "physics/wofost_backend.py",
            "types.py",
            "scenarios/scenario.py",
            "apps/system.py",
        ):
            p = fairy_root / rel
            files.append((rel, hashlib.sha256(p.read_bytes()).hexdigest()))
        return digest(
            dict(
                inputs=self.input_bundle.identity,
                resources=asdict(self.resources),
                prices=asdict(self.accounts.prices),
                quality=asdict(self.root_contract),
                variant=self.variant,
                scenario_id=self.scenario_id,
                seed=self.seed,
                pcse_version=self.farm.backends[0].version,
                block_inputs=[backend.bundle.identity for backend in self.farm.backends],
                initialization_history=self.initialization_history,
                management_objective=self.farm.management_objective,
                scenario_code=hashlib.sha256(Path(inspect.getfile(type(self))).read_bytes()).hexdigest(),
                code=files,
            )
        )

    def _validate_oracle_reference(self):
        ref = self.ORACLE_REFERENCE
        if ref:
            if (
                ref.get("input_fingerprint") != self.input_fingerprint()
                or ref.get("scenario_id") != self.scenario_id
            ):
                raise ValueError(
                    "Oracle reference is stale for these inputs/code/resources"
                )
            if not ref.get("fresh_replay_verified"):
                raise ValueError(
                    "Oracle must first pass a separate fresh-world public-tool replay"
                )

    def _build_reference_events_flow(self):
        """Load an explicitly supplied custom workflow, or an archived scenario."""
        self._validate_oracle_reference()
        ref = self.ORACLE_REFERENCE
        with EventRegisterer.capture_mode() as events:
            previous = capture_step(
                None,
                self.aui.send_message_to_agent(self.scenario_input),
                "task",
                "Read crop and resource constraints",
            )
            apps = {app.name: app for app in self.apps}
            for i, step in enumerate(ref["workflow"] if ref else []):
                app = apps[step["app"]]
                allowed = {t.name for t in app.get_tools()}
                if step["tool"] not in allowed:
                    raise ValueError("Oracle refers to a nonpublic tool")
                event = getattr(app, step["tool"])(**step["arguments"])
                previous = capture_step(
                    previous,
                    event,
                    f"beet_{i:05d}",
                    step.get("reason", "Replay verified public tool"),
                )
        return finish_capture(self, events)

    def build_events_flow(self):
        """Archived scenarios use this fallback; active scenes declare literal calls."""
        return self._build_reference_events_flow()

    def validate(self, env=None):
        from ..evaluation.sugarbeet import evaluate

        return evaluate(self, env)
