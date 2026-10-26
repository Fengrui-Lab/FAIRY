"""Eight composable episodes with executable, outcome-checked reference workflows.

These are operational benchmarks, not calibrated regional agronomic prescriptions.
Planting episodes run the crop-aware physics proxy through an establishment tick;
harvest episodes start from explicit mature snapshots to isolate harvest logistics.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world.multi_farm import AssetSpec, FarmFleet, FarmSite
from fairy.apps.system import SystemApp
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.tool_utils import OperationType


@dataclass(frozen=True)
class WorkOrder:
    farm_id: str
    prefix: str
    num_ridges: int
    length_m: float
    width_m: float = 1.1
    crop: str = "soybean"
    task: str = "plant"
    grain_moisture_pct: float = 16.0
    rainfall_mm: float = 0.0
    irrigation_range: tuple[int, int] | None = None
    irrigation_hours: float = 2.0


class DiverseFarmScenario(Scenario):
    orders: tuple[WorkOrder, ...] = ()
    purpose: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        harvest_episode = any(order.task in {"harvest", "hold"} for order in self.orders)
        self.start_time = datetime(2026, 9, 20, 7, tzinfo=timezone.utc).timestamp() if harvest_episode else datetime(2026, 5, 12, 7, tzinfo=timezone.utc).timestamp()
        self.duration = 10 * 86400
        self.expects_agent_harvest = harvest_episode
        self.additional_system_prompt = (
            "This episode uses shared service tools with explicit farm_id and asset_id. "
            "Read the environment directory and each farm overview for exact target bindings, "
            "crop profiles and geometry. Ridge IDs are local to the selected farm. "
            "Weather data, seed stock, quotas and grain batches belong to their declared targets. "
            "Device state belongs to asset_id; this episode declares dedicated equipment per farm. "
            "SystemApp advances the common clock for all farms. Use each crop's planting "
            "depth, spacing and maturity rules. Rice here is dry direct-seeded aerobic rice."
        )

    def init_and_populate_apps(self, *args: Any, **kwargs: Any) -> None:
        sites = [FarmSite.create(farm_id=o.farm_id, name=o.prefix, num_ridges=o.num_ridges,
                                field_length_m=o.length_m, ridge_width_m=o.width_m, crop_type=o.crop,
                                create_devices=False)
                 for o in self.orders]
        assets = [AssetSpec(f"{order.farm_id}_{kind}", kind, (order.farm_id,))
                  for order in self.orders for kind in ("tractor", "robot", "drone")]
        self.fleet = FarmFleet(sites, assets=assets, shared_tools=True, seed=self.seed)
        self.runtime_participants = [self.fleet.runtime]
        self.fleet.runtime.definition_metadata = {
            "scenario_id": self.scenario_id,
            "duration": self.duration,
            "crop_backend": self.crop_backend,
            "crop_backend_options": deepcopy(self.crop_backend_options),
            "orders": [asdict(order) for order in self.orders],
        }
        self.apps = [AgentUserInterface(), *self.fleet.apps, SystemApp()]
        date = datetime.fromtimestamp(self.start_time, timezone.utc).date().isoformat()
        brief = [self.purpose, "All ridge ranges below are inclusive; use passes of at most four ridges."]
        for order, site in zip(self.orders, sites):
            farm = site.farm
            farm._sim_date = date
            site.weather.set_weather(date=date, temp_c=24.0, humidity_pct=55.0,
                                     wind_speed_ms=2.0, rainfall_mm=order.rainfall_mm,
                                     solar_radiation=400.0, avg_soil_vwc=0.26)
            for ridge in farm._ridges:
                ridge.soil_vwc, ridge.soil_temp_c = 0.26, 20.0
            site.tractor._completed_prep_ops = ["level", "base_fertilize", "form_ridges"]
            profile = farm.crop_profile
            if order.task == "plant":
                farm.set_season_phase("planting")
                farm.configure_physics_profile("diverse_establishment", latitude_deg=32.0, random_seed=self.seed)
                # Rain arrives after the dry sowing shift. Pin the entire
                # establishment week so the oracle can verify actual emergence
                # rather than pass with dry, ungerminated seeds after a tick.
                first_day = datetime.fromtimestamp(self.start_time, timezone.utc).date()
                for offset in range(8):
                    farm.physics.set_weather_day_override(
                        day=first_day+timedelta(days=offset), air_temp_mean_c=26.0,
                        air_temp_min_c=22.0, air_temp_max_c=30.0,
                        rain_mm=0.0 if offset == 0 else 2.0,
                        wind_ms=2.0, solar_rad_mj_m2=15.0, relative_humidity_pct=65.0)
                forecast = [{"date": (first_day+timedelta(days=offset)).isoformat(),
                             "temp_c": 26.0, "humidity_pct": 65.0, "wind_speed_ms": 2.0,
                             "rainfall_mm": 2.0, "solar_radiation": 15.0/0.0864}
                            for offset in range(1, 8)]
                site.weather.set_weather(date=date, temp_c=26.0, humidity_pct=65.0,
                                         wind_speed_ms=2.0, rainfall_mm=0.0,
                                         solar_radiation=15.0/0.0864, forecast=forecast,
                                         avg_soil_vwc=0.26)
                brief.append(f"farm_id={order.farm_id} ({order.prefix}): plant {order.num_ridges} {order.crop} ridges 0-{order.num_ridges-1}, "
                             f"length {order.length_m} m, width {order.width_m} m. Field preparation complete. "
                             f"Use {profile.seed_type}, depth {profile.planting_depth_cm} cm, "
                             f"spacing {profile.seed_spacing_cm} cm. A warm, rainy establishment week follows today's dry sowing shift. "
                             "Read the forecast and confirm emergence after seven days.")
            elif order.task == "irrigate":
                farm.set_season_phase("growing")
                lo, hi = order.irrigation_range
                for ridge in farm._ridges:
                    ridge.planted, ridge.seed_type, ridge.growth_stage = True, profile.seed_type, "R3"
                    ridge.soil_vwc = 0.18 if lo <= ridge.ridge_id <= hi else 0.31
                quota = order.irrigation_hours * 5.0 * (hi-lo+1) / order.num_ridges
                farm.configure_management_regime(irrigation_quota_mm_total=quota)
                brief.append(f"farm_id={order.farm_id} ({order.prefix}): irrigate only ridges {lo}-{hi} for {order.irrigation_hours} h. "
                             f"Other ridges have adequate water. Quota {quota:.8f} field-equivalent mm. "
                             "Wait at least two hours after completion, then recheck soil; do not repeat pending irrigation.")
            else:
                farm.set_season_phase("harvest")
                for ridge in farm._ridges:
                    ridge.planted, ridge.seed_type = True, profile.seed_type
                    ridge.growth_stage = profile.mature_stage
                    ridge.days_since_planted = 140
                    ridge.grain_moisture_pct = order.grain_moisture_pct
                farm.configure_postharvest_market(max_storage_moisture_pct=13.5,
                                                 storage_capacity_kg=100000.0,
                                                 drying_capacity_kg_per_day=100000.0)
                if order.task == "hold":
                    brief.append(f"farm_id={order.farm_id} ({order.prefix}): {order.num_ridges} mature ridges; station reports rain. "
                                 "Observe this farm and leave it unharvested, with its stocks and equipment unchanged.")
                else:
                    brief.append(f"farm_id={order.farm_id} ({order.prefix}): harvest all {order.num_ridges} mature {order.crop} ridges "
                                 f"at {order.grain_moisture_pct}% grain moisture. Unload after each pass, "
                                 "dry each local batch to 13%, and store it at the same farm. Leave no grain in the combine or trailer.")
        directory = self.fleet.describe_environment()
        self.workflow_manifest = deepcopy(self.fleet.runtime.registry.manifest)
        target_summary = {key: directory[key] for key in ("farms", "assets", "weather_stations", "clock") if key in directory}
        brief.append("Registered environment targets: " + json.dumps(target_summary, ensure_ascii=False, sort_keys=True))
        self.scenario_input = "\n".join(brief)
        self._initial = {site.spec.farm_id: site.farm.get_state() for site in sites}
        self._initial_tractor = {site.spec.farm_id: site.tractor.get_state() for site in sites}

    def oracle_solution(self, run_oracle: bool = False) -> None:
        self.workflow = Workflow()
        previous: str | None = None
        def step(app, method: str, *, write: bool = False, reason: str, **arguments: Any):
            nonlocal previous
            name = f"step{len(self.workflow)}"
            shared_app, shared_method, canonical_args = self.fleet.route(app, method, arguments)
            content = getattr(shared_app, shared_method)(**canonical_args) if run_oracle else {"oracle_reason": reason}
            result = content.get("data") if isinstance(content, dict) and content.get("ok") is True else content
            if run_oracle and isinstance(result, dict) and (result.get("ok") is False or "error" in result or "warning" in result):
                raise RuntimeError(f"Oracle {shared_app.name}__{shared_method} failed: {content}")
            self.workflow.add_node(WorkflowStep(name=name, content=content,
                op_type="WRITE" if write else "READ", tool_name=f"{shared_app.name}__{shared_method}",
                tool_args=canonical_args, depends_on=[previous] if previous else []))
            previous = name
        for order in self.orders:
            site = self.fleet.get(order.farm_id)
            step(site.farm, "get_farm_overview", reason="Identify local crop, geometry, phase and inventory.")
            step(site.weather, "get_current_weather", reason="Check the station belonging to this farm.")
            step(site.sensor, "read_soil_sensors", reason="Check complete sensor coverage for this farm's actual ridge count.")
            step(site.tractor, "get_status", reason="Check local fuel, hopper and bin capacity.")
            if order.task == "plant":
                p = site.farm.crop_profile
                step(site.weather, "get_forecast", reason="Confirm the warm, rainy establishment week before committing seed.", days=7)
                seeds = site.farm.plants_per_ridge_from_spacing(p.seed_spacing_cm)
                # Each pass receives its exact seed requirement; this also works
                # for large fields whose total requirement exceeds hopper capacity.
                for lo in range(0, order.num_ridges, 4):
                    hi = min(lo+3, order.num_ridges-1)
                    step(site.tractor, "load_seeds", write=True, reason="Load the exact pass requirement from this farm's stock.",
                         seed_type=p.seed_type, count=seeds*(hi-lo+1))
                    step(site.tractor, "plant_seeds", write=True, reason="Use crop-specific depth and density; clamp the last partial pass.",
                         start_ridge=lo, end_ridge=hi, depth_cm=p.planting_depth_cm, seed_spacing_cm=p.seed_spacing_cm)
            elif order.task == "irrigate":
                lo, hi = order.irrigation_range
                step(site.field_ops, "irrigate", write=True, reason="Target only the deficient ridges within this farm's quota.",
                     start=lo, end=hi, hours=order.irrigation_hours)
            elif order.task == "harvest":
                for lo in range(0, order.num_ridges, 4):
                    hi = min(lo+3, order.num_ridges-1)
                    step(site.tractor, "harvest", write=True, reason="Harvest mature grain using this crop's moisture limit.", start_ridge=lo, end_ridge=hi)
                    step(site.tractor, "unload_grain", write=True, reason="Keep each pass within local combine-bin capacity.")
                    step(site.farm, "dry_grain", write=True, reason="Bring this local batch below its storage moisture limit.", target_moisture_pct=13.0)
                    step(site.farm, "store_grain", write=True, reason="Close the batch at its origin farm and empty the trailer.")
        system = self.get_typed_app(SystemApp)
        if any(o.task == "plant" for o in self.orders):
            step(system, "advance_time", reason="Advance every farm's crop and soil engines through establishment.", days=7)
        elif any(o.task == "irrigate" for o in self.orders):
            step(system, "advance_time", reason="Wait for all delayed irrigation deliveries to become observable.", hours=2)
        for site in self.fleet.sites:
            step(site.sensor, "read_soil_sensors", reason="Verify the result with local observations.")
            step(site.farm, "get_farm_overview", reason="Verify every local ridge, phase and grain inventory.")
        step(self.get_typed_app(AgentUserInterface), "send_message_to_user", write=True,
             reason="Report completion and any deliberately deferred rainy field.",
             content="Completed the requested farm-specific operations; checked every site's final state. Rainy hold sites remain untouched.")

    def validate(self, env) -> ScenarioValidationResult:
        """Assess outcomes and causal safety gates, allowing equivalent tool sequences."""
        failures: list[str] = []
        details: dict[str, Any] = {}
        steps = self.fleet.project_workflow_steps(list(env.workflow.dag.values()))
        for item in steps:
            if item.error_stage or (isinstance(item.content, dict) and ("error" in item.content or "warning" in item.content)):
                failures.append(f"tool failure/warning: {item.tool_name}")
        for order in self.orders:
            site = self.fleet.get(order.farm_id)
            farm = site.farm
            state = farm.get_state()
            initial = self._initial[order.farm_id]
            ridges = state["ridges"]
            prefix = order.prefix + ": "
            # Classify writes from the authoritative public contracts. Internal
            # equipment handles deliberately cannot publish another tool catalog.
            local_names = {"Farm": farm.name, "Weather": site.weather.name,
                           "Sensor": site.sensor.name, "FieldOps": site.field_ops.name,
                           "Tractor": f"{site.spec.name}Tractor",
                           "Drone": f"{site.spec.name}Drone", "Robot": f"{site.spec.name}Robot"}
            local_steps = [item for item in steps if (item.tool_args or {}).get("farm_id") == order.farm_id]
            local_mutations = set()
            registry = self.fleet.runtime.registry
            for tool_name in registry.names:
                service, _, method = tool_name.partition("__")
                if (service in local_names and
                        registry.contract(tool_name).operation_type == OperationType.WRITE):
                    local_mutations.add(f"{local_names[service]}__{method}")
            writes = [s for s in local_steps if s.tool_name in local_mutations]
            # A same-farm observation must precede its first mutating operation.
            if writes:
                first = steps.index(writes[0])
                observed = {s.tool_name for s in steps[:first] if (s.tool_args or {}).get("farm_id") == order.farm_id}
                for app, method in ((site.farm, "get_farm_overview"), (site.weather, "get_current_weather"),
                                    (site.sensor, "read_soil_sensors")):
                    if f"{app.name}__{method}" not in observed:
                        failures.append(prefix + f"missing preflight {app.name}__{method}")
                _, _, tractor_args = self.fleet.route(site.tractor, "get_status", {})
                if not any(str(s.tool_name).split("__")[-1] == "get_status" and
                           (s.tool_args or {}).get("asset_id") == tractor_args["asset_id"] for s in steps[:first]):
                    failures.append(prefix + "missing preflight status for the selected tractor asset")
                if order.task == "plant" and f"{site.weather.name}__get_forecast" not in observed:
                    failures.append(prefix + "missing establishment weather forecast")
                after = [s for s in steps[steps.index(writes[-1])+1:] if (s.tool_args or {}).get("farm_id") == order.farm_id]
                if not any(s.tool_name == f"{site.farm.name}__get_farm_overview" for s in after):
                    failures.append(prefix + "missing final farm observation")
            if order.task == "plant":
                p = farm.crop_profile
                expected_seeds = farm.plants_per_ridge_from_spacing(p.seed_spacing_cm)
                if not all(r["planted"] and not r["harvested"] and r["seed_type"] == p.seed_type
                           and r["seeds_planted"] == expected_seeds for r in ridges):
                    failures.append(prefix + "missing planting, wrong crop/density, or unintended harvest")
                if not all(abs(r["seed_spacing_cm"]-p.seed_spacing_cm) < 1e-8 for r in ridges if r["seed_spacing_cm"] is not None):
                    failures.append(prefix + "incorrect spacing")
                consumed = initial["inventory"]["seed_stock"][p.seed_type]-state["inventory"]["seed_stock"][p.seed_type]
                if consumed != expected_seeds * order.num_ridges or site.tractor._seed_hopper != 0:
                    failures.append(prefix + "seed mass balance does not match planted area")
                if any(value != initial["inventory"]["seed_stock"][seed]
                       for seed, value in state["inventory"]["seed_stock"].items() if seed != p.seed_type):
                    failures.append(prefix + "unrelated seed stock consumed")
                if not farm.physics_active or farm.physics.last_physics_sim_time is None or float(farm.physics.last_physics_sim_time) < self.start_time+7*86400:
                    failures.append(prefix + "missing seven-day establishment checkpoint")
                if not all(farm.physics.phenology.states[r["ridge_id"]].emerged for r in ridges):
                    failures.append(prefix + "crop has not emerged at the establishment checkpoint")
                plant_steps = [s for s in local_steps if s.tool_name == f"{site.spec.name}Tractor__plant_seeds"]
                if any((s.tool_args or {}).get("depth_cm") != p.planting_depth_cm for s in plant_steps):
                    failures.append(prefix + "incorrect crop planting depth")
            elif order.task == "irrigate":
                lo, hi = order.irrigation_range
                target_ids = set(range(lo, hi+1))
                log_ids = [entry["ridge_id"] for entry in site.field_ops._irrigation_log]
                if set(log_ids) != target_ids or len(log_ids) != len(target_ids):
                    failures.append(prefix + "irrigation target set or frequency incorrect")
                for ridge in ridges:
                    expected = 0.18 + order.irrigation_hours*0.05 if ridge["ridge_id"] in target_ids else 0.31
                    if abs(ridge["soil_vwc"]-expected) > 1e-6:
                        failures.append(prefix + f"water state incorrect at ridge {ridge['ridge_id']}")
                if state["pending_irrigation"]:
                    failures.append(prefix + "irrigation delivery still pending")
            elif order.task == "harvest":
                expected_kg = round(round(farm.grain_kg_per_ridge, 2)*len(ridges), 2)
                inventory = state["inventory"]
                if not all(r["harvested"] for r in ridges):
                    failures.append(prefix + "unharvested ridges remain")
                if abs(inventory["warehouse_grain_kg"]-expected_kg) > 0.05 or inventory["harvest_grain_kg"] or site.tractor._grain_bin_kg:
                    failures.append(prefix + "recovered grain mass balance/warehouse location incorrect")
                if not inventory["grain_dried"]:
                    failures.append(prefix + "storage batch not dry")
            elif order.task == "hold":
                if any(r["harvested"] for r in ridges) or state["inventory"] != initial["inventory"] or site.tractor.get_state() != self._initial_tractor[order.farm_id] or writes:
                    failures.append(prefix + "rainy farm should remain untouched")
            details[order.farm_id] = {"crop": order.crop, "task": order.task, "ridges": len(ridges),
                                      "planted": sum(r["planted"] for r in ridges), "harvested": sum(r["harvested"] for r in ridges),
                                      "warehouse_grain_kg": state["inventory"]["warehouse_grain_kg"],
                                      "irrigation_used_mm_total": state["management_regime"]["irrigation_used_mm_total"]}
            if order.task == "plant":
                details[order.farm_id]["emerged"] = sum(st.emerged for st in farm.physics.phenology.states.values())
        return ScenarioValidationResult(success=not failures, message="All farm-specific outcome and safety gates passed." if not failures else "; ".join(failures),
                                        metadata={"farms": details, "failures": failures, "oracle_kind": "operational_reference", "workflow_steps": len(steps)})


@register_scenario("scenario_multi_farm_uneven_planting")
class ScenarioMultiFarmUnevenPlanting(DiverseFarmScenario):
    purpose = "Complete soybean planting across three independently stocked farms with unequal layouts."
    orders = (WorkOrder("north", "North", 5, 120), WorkOrder("east", "East", 9, 180), WorkOrder("west", "West", 3, 90))


@register_scenario("scenario_multi_farm_targeted_irrigation")
class ScenarioMultiFarmTargetedIrrigation(DiverseFarmScenario):
    purpose = "Apply limited local irrigation to different dry patches; preserve the healthy ridges at both farms."
    orders = (WorkOrder("north", "North", 7, 120, task="irrigate", irrigation_range=(2, 4)),
              WorkOrder("south", "South", 11, 180, task="irrigate", irrigation_range=(7, 10), irrigation_hours=1.5))


@register_scenario("scenario_multi_farm_harvest_storage")
class ScenarioMultiFarmHarvestStorage(DiverseFarmScenario):
    purpose = "Harvest and close separate soybean grain batches without mixing local warehouse inventories."
    orders = (WorkOrder("north", "North", 5, 120, task="harvest", grain_moisture_pct=16),
              WorkOrder("south", "South", 7, 180, task="harvest", grain_moisture_pct=17))


@register_scenario("scenario_multi_farm_weather_isolation")
class ScenarioMultiFarmWeatherIsolation(DiverseFarmScenario):
    purpose = "Harvest only the dry farm; defer the other farm because its own weather station reports rain."
    orders = (WorkOrder("dry", "Dry", 5, 120, task="harvest"),
              WorkOrder("rainy", "Rainy", 9, 180, task="hold", rainfall_mm=12))


@register_scenario("scenario_multi_crop_maize_planting")
class ScenarioMultiCropMaizePlanting(DiverseFarmScenario):
    purpose = "Establish maize using its own seed, row count, sowing depth, density and crop phenology."
    orders = (WorkOrder("maize", "Maize", 7, 140, 0.75, "maize"),)


@register_scenario("scenario_multi_crop_rice_planting")
class ScenarioMultiCropRicePlanting(DiverseFarmScenario):
    purpose = "Establish dry direct-seeded aerobic rice in shallow, densely planted rows, and observe the crop after seven days."
    orders = (WorkOrder("rice", "Rice", 9, 100, 1.0, "rice"),)


@register_scenario("scenario_multi_crop_mixed_planting")
class ScenarioMultiCropMixedPlanting(DiverseFarmScenario):
    purpose = "Coordinate soybean, maize and rice establishment with separate crop profiles and inventories under one clock."
    orders = (WorkOrder("soy", "Soy", 5, 120), WorkOrder("maize", "Maize", 7, 140, 0.75, "maize"),
              WorkOrder("rice", "Rice", 9, 100, 1.0, "rice"))


@register_scenario("scenario_multi_crop_harvest_storage")
class ScenarioMultiCropHarvestStorage(DiverseFarmScenario):
    purpose = "Harvest mature maize and rice using each crop's stage and grain-moisture rules, dry and store each local batch."
    orders = (WorkOrder("maize", "Maize", 7, 140, 0.75, "maize", "harvest", 22),
              WorkOrder("rice", "Rice", 9, 100, 1.0, "rice", "harvest", 23))


SCENARIO_IDS = (
    "scenario_multi_farm_uneven_planting", "scenario_multi_farm_targeted_irrigation",
    "scenario_multi_farm_harvest_storage", "scenario_multi_farm_weather_isolation",
    "scenario_multi_crop_maize_planting", "scenario_multi_crop_rice_planting",
    "scenario_multi_crop_mixed_planting", "scenario_multi_crop_harvest_storage",
)
