"""Standard captured-event runtime and independent outcome acceptance."""
import math
import sys

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.types import EventRegisterer
from . import artifacts
from .catalog import CHALLENGES, TASKS
from .worlds import maize_spec, init_maize, rice_configuration


def measurements(scenario):
    """Private evaluation only; never an input to the reference policy."""
    if scenario.crop_name == "maize":
        from fairy.apps.farm_world import FarmWorldApp
        from fairy.scenarios.maize.validation import task_state
        farm = scenario.get_typed_app(FarmWorldApp)
        state = task_state(scenario)
        area_ha = 268 * farm.ridge_width_m / 10000
        runs = farm.physics.crop_backend._runs
        focus = scenario.definition.focus
        return dict(time=state["time"], day=state["native_last_day"],
            biological_dry_kg=sum(float(runs[r].pcse.get("TWSO") or 0) * area_ha for r in focus if r in runs),
            biomass_dry_kg=sum(float(runs[r].pcse.get("TAGP") or 0) * area_ha for r in focus if r in runs),
            stored_kg_at_14pct=state["warehouse"], water_used=state["water_used"],
            fertilizer_used=state["fertilizer_used"], stress_days=state["stress_days"],
            inputs={str(k): v for k, v in state["inputs"].items()},
            crop_fingerprint=farm.physics.crop_backend.snapshot()["provenance"]["config_fingerprint"])
    from fairy.apps.paddy.world import PaddyWorldApp
    world = scenario.get_typed_app(PaddyWorldApp)
    plots = [p for p in world.field.plots if p.plot_id in scenario.definition.focus]
    return dict(time=world.sim_time, day=str(next(iter(world.backends.values())).model.day),
        biological_dry_kg=sum(p.unit.mass_kg(float(world.backends[p.plot_id].crop_values.get("TWSO") or 0)) for p in plots),
        biomass_dry_kg=sum(p.unit.mass_kg(float(world.backends[p.plot_id].crop_values.get("TAGP") or 0)) for p in plots),
        stored_kg_at_14pct=sum(p.stored_dry_kg / .86 for p in plots),
        water_used=world.channel("supply").withdrawn_m3,
        fertilizer_used=world.field.fertilizer_applied_kg,
        energy_used_kwh=world.field.energy_used_kwh,
        insecticide_used_liters=world.field.chemicals_used["insecticide_liters"],
        fungicide_used_liters=world.field.chemicals_used["fungicide_liters"],
        repair_used_kg=world.field.repair_used_kg,
        fuel_used_liters=world.field.fuel_used_liters,
        infrastructure={"blockage": world.channel("supply").blockage_fraction,
                        "leaks": {p.plot_id: p.bund_leak_mm_day for p in plots}},
        pressures={p.plot_id: {k: getattr(p, k) for k in ("pests", "disease", "weeds")} for p in plots},
        crop_fingerprint=world.crop_backend_provenance()["config_fingerprint"])


class CropChallengeScenario(Scenario):
    """Each registered ID resolves to a fixed source and task checkpoint."""
    challenge_id = ""

    def __init__(self, **kwargs):
        sid = type(self).challenge_id
        source, level, checkpoint = TASKS[sid]
        self.definition = CHALLENGES[source]
        self.crop_name, self.level = self.definition.crop, level
        self.task = "season" if level == "L3" else checkpoint
        self.source_l3_scenario_id = source
        self.source_checkpoint_label = "initial" if level == "L3" else checkpoint
        self.spec = maize_spec(self.definition.name) if self.crop_name == "maize" else None
        if kwargs.pop("crop_backend", "wofost") != "wofost" or kwargs.pop("crop_backend_options", {}):
            raise ValueError("Challenges use their declared WOFOST configuration")
        if kwargs.pop("scenario_id", sid) != sid or "start_time" in kwargs:
            raise ValueError("Challenge identity/time come from its fixed world or checkpoint")
        from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_scenario_helpers import harbin_start_time
        start = harbin_start_time(2026, 5, 5) if self.crop_name == "maize" else 1767225600.
        kwargs.setdefault("duration", self.definition.deadline_days * 86400)
        super().__init__(scenario_id=sid, start_time=start, crop_backend="wofost",
            crop_backend_options=self.spec.backend_options() if self.spec else {},
            queue_based_loop=True, **kwargs)
        self._source_start = start

    def init_and_populate_apps(self):
        if self.crop_name == "maize":
            init_maize(self)
        else:
            from fairy.apps.paddy.world import PaddyWorldApp
            from fairy.scenarios.rice.rice_scenario_helpers import populate_rice_apps
            field, weather = rice_configuration(self.definition.name)
            populate_rice_apps(self, PaddyWorldApp(field=field, weather=weather))
        from fairy.time_manager import TimeManager
        clock = TimeManager()
        clock.reset(self.start_time)
        clock.real_time_passed = lambda: 0.
        for app in self.apps:
            app.register_time_manager(clock)
        if self.level != "L3":
            data = artifacts.load(self.source_l3_scenario_id)
            checkpoint = data["checkpoints"][self.source_checkpoint_label]
            self._restore(checkpoint)
            self._initial_checkpoint_digest = artifacts.digest(checkpoint)
        else:
            self._initial_checkpoint_digest = artifacts.digest(self.export_checkpoint("initial"))
        self._initial_measurements = measurements(self)
        self.scenario_input = self.definition.question + "\n" + (
            "完成完整季与全部目标的安全收储，报告分区管理证据、产量和投入。"
            if self.level == "L3" else
            "从真实来源季检查点开始，只完成本诊断管理窗口，保留窗口外的后续资源。")
        if not getattr(self, "_authoring", False):
            data = artifacts.load(self.source_l3_scenario_id)
            task = data["tasks"][self.scenario_id]
            if self._initial_checkpoint_digest != task["initial_checkpoint_digest"]:
                raise ValueError("Challenge initial checkpoint differs from reviewed evidence")
            self.scenario_input += "\n" + task["briefing"]
            self._challenge_evidence = data

    def export_checkpoint(self, label):
        if self.crop_name == "maize":
            from fairy.scenarios.maize.farm_checkpoint_state import export_maize_checkpoint
            return export_maize_checkpoint(self, label, source_digest=artifacts.source_digest("maize"))
        from fairy.apps.paddy.world import PaddyWorldApp
        return self.get_typed_app(PaddyWorldApp).get_state()

    def _restore(self, checkpoint):
        if self.crop_name == "maize":
            from fairy.scenarios.maize.farm_checkpoint_state import restore_maize_checkpoint
            restore_maize_checkpoint(self, checkpoint)
        else:
            from fairy.apps.paddy.world import PaddyWorldApp
            from fairy.scenarios.rice.rice_scenario_helpers import populate_rice_apps
            world = self.get_typed_app(PaddyWorldApp)
            world.load_state(checkpoint)
            populate_rice_apps(self, world)

    def build_events_flow(self):
        if getattr(self, "_authoring", False):
            self.events = []
            return
        data = self._challenge_evidence
        task = data["tasks"][self.scenario_id]
        if self.crop_name == "maize":
            plan = artifacts.load_maize_plans(self.source_l3_scenario_id, data)[self.scenario_id]
            if artifacts.digest(plan) != task["plan_digest"]:
                raise ValueError("Maize Python plan differs from reviewed evidence")
        else:
            plan = task["plan"]
        apps = {app.name: app for app in self.apps}
        allowed = {app.name: {t.name for t in app.get_tools()} for app in self.apps}
        entries = []
        for step in plan:
            app, sep, method = step["tool_name"].partition("__")
            args, duration = step["tool_args"], step["duration_seconds"]
            if not sep or method not in allowed.get(app, set()) or not isinstance(args, dict):
                raise ValueError("Unknown challenge tool or invalid arguments")
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
                raise ValueError("Invalid challenge duration")
            explicit = sum(args.get(k, 0) * scale for k, scale in
                           (("days", 86400), ("hours", 3600), ("minutes", 60), ("seconds", 1))) if app == "SystemApp" and method == "advance_time" else 0
            if duration < explicit - 1e-6:
                raise ValueError("Challenge duration is shorter than its time advance")
            entries.append((apps[app], method, args, max(0., duration - explicit)))
        with EventRegisterer.capture_mode() as events:
            prev = self.get_typed_app(AgentUserInterface).send_message_to_agent(content=self.scenario_input).with_id("briefing")
            for index, (app, method, args, delay) in enumerate(entries):
                prev = getattr(app, method)(**args).oracle().with_id(f"challenge_{index:04d}_{method}").depends_on(prev, delay_seconds=delay)
        self.events = list(events)

    def validate(self, env=None):
        workflow = env.workflow if env is not None else self.workflow
        failures = []
        if self.crop_name == "maize":
            from fairy.scenarios.maize.validation import task_state, _audit, _stored_goals
            state = task_state(self)
            failures, errors, _ = _audit(self, state, workflow)
            if self.level == "L3":
                _stored_goals(self, state, failures)
        else:
            from fairy.apps.paddy.world import PaddyWorldApp
            from fairy.scenarios.rice.validation import audit_world, _all_harvested_grain_stored
            world = self.get_typed_app(PaddyWorldApp)
            if not audit_world(world)["success"]:
                failures.append("water/nitrogen/resource audit failed")
            if self.level == "L3" and not _all_harvested_grain_stored(world):
                failures.append("all harvested rice must be safely stored")
            errors = [s for s in workflow.dag.values() if s.error_type or s.op_type == "TOOL_ERROR"
                      or isinstance(s.content, dict) and (s.content.get("error") or s.content.get("warning"))] if workflow else []
            if errors:
                failures.append("workflow contains tool errors or unsafe warnings")
        actual = measurements(self)
        if actual["time"] > self._source_start + self.definition.deadline_days * 86400:
            failures.append("season deadline exceeded")
        execution_ok = not failures
        calibrated = False
        if not getattr(self, "_authoring", False):
            task = self._challenge_evidence["tasks"][self.scenario_id]
            calibrated = task["status"] == "calibrated"
            if not calibrated:
                failures.append("experimental: decision mechanism has not passed matched-control calibration")
            if actual["crop_fingerprint"] != task["reference"]["crop_fingerprint"]:
                failures.append("crop configuration differs from calibrated reference")
            if self.level != "L3" and actual["day"] != task["reference"]["day"]:
                failures.append("finish on the stated observation day")
            for metric, budget in task.get("window_budgets", {}).items():
                used = actual[metric] - self._initial_measurements[metric]
                if used > budget + 1e-6:
                    failures.append(f"window resource budget exceeded: {metric}")
            for gate in task.get("gates", []):
                value = actual[gate["metric"]]
                if (gate["direction"] == "lower" and value > gate["threshold"] + 1e-6
                        or gate["direction"] == "higher" and value < gate["threshold"] - 1e-6):
                    failures.append(f"outcome gate failed: {gate['metric']}")
            if self.level == "L1":
                failures.extend(self._action_failures(actual, task))
            steps = list(workflow.dag.values()) if workflow else []
            writes = [i for i, s in enumerate(steps) if s.op_type == "WRITE" and not (s.tool_name or "").startswith("AgentUserInterface__")]
            if not writes or not any(s.op_type == "READ" for s in steps[writes[-1] + 1:]):
                failures.append("post-operation public recheck required")
        return ScenarioValidationResult(success=not failures, message="; ".join(failures) or "Challenge outcome and accounting passed",
            metadata={"execution_success": execution_ok, "calibrated": calibrated,
                      "goal_met": not failures, "failures": failures, "measurements": actual,
                      "source_l3_scenario_id": self.source_l3_scenario_id,
                      "initial_checkpoint_digest": self._initial_checkpoint_digest})

    def _action_failures(self, actual, task):
        failures = []
        expected = task["reference"]
        initial = self._initial_measurements
        if self.crop_name == "maize":
            for rid, row in actual["inputs"].items():
                for resource in ("water", "fertilizer"):
                    want = expected["inputs"][rid][resource] - initial["inputs"][rid][resource]
                    got = row[resource] - initial["inputs"][rid][resource]
                    if abs(got - want) > max(1e-6, abs(want) * .01):
                        failures.append("targeted action dose/coverage mismatch")
                        return failures
        elif self.task == "channel_clearance":
            if actual["infrastructure"]["blockage"] != 0:
                failures.append("supply channel remains blocked")
        else:
            for pid, values in expected["pressures"].items():
                for key, value in values.items():
                    if actual["pressures"][pid][key] > value + .01:
                        failures.append("targeted protection outcome not reached")
        return failures


def register_challenges(crop, module):
    from fairy.scenarios.registry import register_scenario
    for sid, (source, level, checkpoint) in TASKS.items():
        if CHALLENGES[source].crop != crop:
            continue
        cls = type("".join(part.title() for part in sid.split("_")), (CropChallengeScenario,),
                   {"challenge_id": sid, "__module__": module})
        setattr(sys.modules[module], cls.__name__, cls)
        register_scenario(sid)(cls)
