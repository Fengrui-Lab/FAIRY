"""L3 winter wheat: identify a waterlogged pocket and drain ponded surface water."""

from copy import copy, deepcopy
from dataclasses import replace
from datetime import date
from math import isclose
import json
from pathlib import Path

from ..apps.winter_wheat_drainage_app import WheatDrainage, WaterloggingWheatAccounts
from ..apps.winter_wheat_farm_app import WinterWheatFarm
from ..engines.winter_wheat_inputs import WeatherSeries, fingerprint
from ..engines.winter_wheat_waterlogging import WaterloggingWheatBackend
from ..winter_wheat_setup import initialize_wheat_farm, wheat_fingerprint
from ..winter_wheat_workflow import capture_wheat_oracle
from .scenario_winter_wheat_full_season import ScenarioWinterWheatFullSeason


LOW_BLOCKS = (6, 7, 8, 9)
STORM_RAIN_ADDITIONS_MM = {date(2020, 5, 7): 60.0, date(2020, 5, 8): 60.0}
PUMP_FLOW_M3_PER_HOUR = 30.0
PUMP_USD_PER_M3 = 0.10
REFERENCE_PATH = (
    Path(__file__).parents[1]
    / "data/winter_wheat_oracles"
    / "scenario_l3_winter_wheat_local_drainage.json"
)


class WaterloggingWheatFarm(WinterWheatFarm):
    """Independent native blocks with a small, poorly drained depression."""

    def block_inputs(self, block_id):
        if block_id not in LOW_BLOCKS:
            return super().block_inputs(block_id)
        inputs = copy(self.bundle)
        inputs.manifest = deepcopy(self.bundle.manifest)
        inputs.manifest["native_site_parameters"]["SSMAX"] = 5.0
        inputs.manifest["native_soil_parameters"].update(
            RDMSOL=55.0, SM0=0.43, SMFCF=0.34, SOPE=2.0, KSUB=0.15
        )
        inputs.manifest["crop"].update(
            parameter_overrides={
                **inputs.manifest["crop"].get("parameter_overrides", {}),
                "IOX": 1,
            },
            override_provenance="Scenario-local PCSE oxygen stress, with a poorly drained soil profile.",
        )
        inputs.manifest["soil_status"] = (
            "Benchmark depression profile, not a surveyed field."
        )
        inputs.identity = fingerprint(inputs.manifest)
        return inputs

    def make_block_backend(self, block_id):
        if block_id in LOW_BLOCKS:
            return WaterloggingWheatBackend(self.block_inputs(block_id))
        return super().make_block_backend(block_id)

    def crop_backend_provenance(self):
        provenance = super().crop_backend_provenance()
        provenance["weather_stress_test"] = self.bundle.manifest["weather_stress_test"]
        provenance["block_input_fingerprints"] = [
            backend.bundle.identity for backend in self.backends
        ]
        return provenance


class ScenarioWinterWheatLocalDrainage(ScenarioWinterWheatFullSeason):
    scenario_id = "scenario_l3_winter_wheat_local_drainage"
    ORACLE_REFERENCE = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._add_benchmark_storm()

    def setup(self, *args, **kwargs):
        if self.apps:
            return
        if args or kwargs:
            raise ValueError("Configure inputs at construction")
        initialize_wheat_farm(
            self,
            farm_class=WaterloggingWheatFarm,
            accounts_factory=WaterloggingWheatAccounts,
        )
        self.drainage = WheatDrainage(
            self.farm,
            flow_m3_per_hour=PUMP_FLOW_M3_PER_HOUR,
            cost_usd_per_m3=PUMP_USD_PER_M3,
        )
        self.drainage.register_time_manager(self.farm_environment.time_manager)
        self.drainage.rng.seed(self.seed)
        self.accounts.drainage = self.drainage
        self.apps.append(self.drainage)
        self.scenario_input = (
            self.task_description(self.detailed_briefing)
            if self._input_override is None
            else self._input_override
        )
        self.additional_system_prompt = (
            self._system_override if self._has_system_override else self.scenario_input
        )
        self.build_events_flow()

    def _add_benchmark_storm(self):
        bundle = copy(self.input_bundle)
        bundle.manifest = deepcopy(bundle.manifest)
        weather = bundle.weather
        if STORM_RAIN_ADDITIONS_MM.keys() - weather.rows.keys():
            raise ValueError(
                "The drainage scenario needs weather for the benchmark storm"
            )
        bundle.weather = WeatherSeries(
            [
                replace(row, rain_mm=row.rain_mm + STORM_RAIN_ADDITIONS_MM[row.day])
                if row.day in STORM_RAIN_ADDITIONS_MM
                else row
                for row in weather.rows.values()
            ]
        )
        bundle.manifest["weather_stress_test"] = {
            "source": "Synthetic precipitation additions on the pinned NASA POWER forcing",
            "added_rain_mm": {
                day.isoformat(): amount
                for day, amount in STORM_RAIN_ADDITIONS_MM.items()
            },
            "effective_weather_sha256": bundle.weather.sha256,
        }
        bundle.identity = fingerprint(bundle.manifest)
        self.input_bundle = bundle

    def input_fingerprint(self):
        return fingerprint(
            {
                "wheat": wheat_fingerprint(self),
                "drainage": "native_surface_water_only_v1",
                "flow_m3_per_hour": PUMP_FLOW_M3_PER_HOUR,
                "cost_usd_per_m3": PUMP_USD_PER_M3,
            }
        )

    def validate(self, env=None):
        result = super().validate(env)
        area_ha = self.farm.ridge_area_m2 / 10000
        result.metadata["low_lying_blocks_dry_grain_kg"] = {
            block_id: (self.farm.backends[block_id].values.get("TWSO") or 0) * area_ha
            for block_id in LOW_BLOCKS
        }
        drainage = result.metadata["drainage"]
        pending_m3 = sum(
            action["amount"] * self.farm.ridge_area_m2 / 1000
            for block_id in LOW_BLOCKS
            for action in self.farm.backends[block_id].pending
            if action["kind"] == "drain"
        )
        if not isclose(
            drainage["pumped_volume_m3"],
            drainage["native_settled_volume_m3"] + pending_m3,
            abs_tol=1e-6,
        ):
            message = "Surface drainage and native water receipts do not balance"
            result.success = False
            result.metadata["operational_success"] = False
            result.message = result.rationale = f"{result.message}; {message}"
        return result

    def task_description(self, detailed=True):
        task = (
            f"经营一座面积{self.resources.area_ha * 10000:g}平方米的冬小麦农场。"
            "春季连雨后留意局部积水，按地块安排必要的排涝和水肥作业。"
            "完成秋播、成熟收获与安全入库，在资源约束下提高净经营收益。"
        )
        if not detailed:
            return task + (
                "通过Drainage.inspect_blocks查积水和抽排条件，"
                "通过OperatingAccounts.get_accounts查库存与价格。"
            )
        return task + (
            "\n\n十月中旬前后，先检查播期、天气、墒情、库存和价格，地面适合时整地、分块播种。"
            "播深约3 cm，底肥可参考约8 kg尿素/块，入冬前确认出苗。"
            "\n\n二月下旬至三月上旬返青，结合可用氮与长势决定是否追肥，可参考约9–10 kg尿素/块。"
            "四月上旬和中下旬冠层扩展时复查水氮，仍需氮时可分别参考约8和5–6 kg尿素/块。"
            "分区看墒情和降雨。普通地块确有缺水风险时单轮可参考约50 mm。浅土低洼区每次单独判断，灌后复查。"
            "\n\n五月上旬开花前后，连雨前后加密检查。"
            "逐块比较积水深度、根区含水率及连续过湿天数，先区分地表短时湿润和有水持续补给根区的地块。"
            "雨后若有可排积水且根区已接近饱和，查抽排能力与费用，优先处理这些地块。"
            "下一天复查同一块和邻块，若仍有积水且根区仍过湿，再判断是否需要继续抽排。"
            "根区未退湿时先暂停该块灌溉，并复核近期降雨。"
            "\n\n五月中下旬灌浆时分区复查墒情。一般地块干了可参考约50 mm，低洼块等积水消退、根区转干后再单独判断，可参考约40–45 mm。"
            "六月中旬前后核对地块成熟状态和作业天气，分批收获、干燥与安全入库。"
            "核对全部地块和粮批后，报告实际产量、排水量、成本和净经营收益。"
        )

    def build_events_flow(self):
        if self.calibrating:
            return []
        data = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
        self.ORACLE_REFERENCE = data["reference"]
        if self.input_fingerprint() != self.ORACLE_REFERENCE["input_fingerprint"]:
            raise ValueError("The drainage scenario requires its frozen Oracle inputs")
        return capture_wheat_oracle(self, data["steps"])
