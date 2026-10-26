"""Test-only registered-tool runner for native model mechanism experiments.

This module is deliberately outside ``fairy``. Scientific controls may execute
prespecified test interventions and record their effects; production scenarios
use the ordinary static Oracle graph and never discover this experiment API.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from datetime import time as daytime, timedelta
from math import ceil, isfinite
import time

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.tool_execution import ToolResult


class ModelExperimentSession:
    """Record real tools for scientific assertions, without changing physics."""

    def __init__(self, engine):
        self.engine = engine
        self.scenario = engine.scenario
        _, _, self.tools = build_toolset(list(self.scenario.apps))
        self.workflow = Workflow()
        self.scenario.workflow = self.workflow
        self.previous = None
        self.counter = 0
        self.timezone = self.scenario.simulation_timezone
        self.deadline = engine.start_time + self.scenario.duration
        self.decisions = []

    @property
    def now(self):
        return self.engine.time_manager.time()

    @property
    def today(self):
        return datetime.fromtimestamp(self.now, self.timezone).date()

    def call(self, label: str, tool_name: str, arguments: dict | None = None):
        if tool_name not in self.tools:
            raise ValueError(f"Experiment references an unregistered tool: {tool_name}")
        if self.now > self.deadline:
            raise RuntimeError("Experiment operation starts after the scene deadline")
        self.counter += 1
        name = f"{self.counter:05d}_{label}"
        args = deepcopy(arguments or {})
        before, started = self.now, time.perf_counter()
        exception = None
        try:
            result = self.tools[tool_name](**args)
        except Exception as exc:
            exception = exc
            result = {"error": str(exc), "exception_type": type(exc).__name__}
        after = self.now
        step = WorkflowStep(name=name, tool_name=tool_name, tool_args=args,
            content=deepcopy(result), depends_on=[self.previous] if self.previous else [],
            op_type="WRITE" if getattr(self.tools[tool_name], "write_operation", False) else "READ",
            time=self.engine._format_timestamp(after), time_before=before, time_after=after)
        self.workflow.add_node(step)
        self.previous = name
        failed = (isinstance(result, ToolResult) and not result.ok) or (
            isinstance(result, dict) and (bool(result.get("error"))
                or result.get("status") in {"error", "failed", "partial"}))
        exceeded = after > self.deadline
        if failed or exceeded:
            step.error_stage = (result.error.get("stage", "execution")
                if isinstance(result, ToolResult) and not result.ok else "execution")
        self.engine._record_run_log(step_name=name, phase="experiment", tool_name=tool_name,
            tool_args=args, status="error" if failed or exceeded else "ok", sim_time_before=before,
            sim_time_after=after, wall_time_seconds=time.perf_counter()-started,
            content=result, error=str(result) if failed else
            "Experiment operation exceeded the scene deadline" if exceeded else None)
        if exception is not None:
            raise exception
        if failed:
            raise RuntimeError(f"Experiment tool {tool_name} failed: {result}")
        if exceeded:
            raise RuntimeError("Experiment operation exceeded the scene deadline")
        return result

    def advance_to(self, label: str, timestamp: float):
        if not isfinite(timestamp):
            raise ValueError("Experiment wait timestamp must be finite")
        if timestamp > self.deadline:
            raise RuntimeError("Experiment wait would exceed the scene deadline")
        seconds = int(ceil(timestamp - self.now))
        if seconds > 0:
            if self.now + seconds > self.deadline:
                raise RuntimeError("Integer-second wait cannot fit the remaining scene duration")
            return self.call(label, self._system_tool("advance_time"), {"seconds": seconds})
        return self.call(label, self._system_tool("get_current_time"))

    def _system_tool(self, method: str) -> str:
        matches = [name for name, tool in self.tools.items()
            if name.endswith("__" + method)
            and isinstance(getattr(tool, "class_instance", None), SystemApp)]
        if len(matches) != 1:
            raise ValueError(f"Experiment requires one registered SystemApp {method} tool; found {matches}")
        return matches[0]

    def decide(self, label: str, observations: dict, action: str, reason: str):
        self.decisions.append({"label": label, "timestamp": self.now,
            "observations": deepcopy(observations), "action": action, "reason": reason})

    def finish(self):
        if not len(self.workflow):
            raise RuntimeError("Experiment produced an empty workflow")
        self.scenario.experiment_decisions = deepcopy(self.decisions)
        return self.workflow


class ModelExperimentEngine(Engine):
    """Explicit test API; the production Oracle entry is inherited unchanged."""

    def run_experiment(self, **setup_kwargs):
        self.scenario.setup(**setup_kwargs)
        self._register_scenario_apps()
        session = ModelExperimentSession(self)
        self.scenario.run_experiment(session)
        self.scenario.workflow = session.finish()
        return self.scenario.workflow


class ExperimentalFarmTools:
    def __init__(self, scene, session):
        self.scene, self.s = scene, session
        self.world = scene.WORLD

    def call(self, label, app, method, **arguments):
        return self.s.call(label, app + '__' + method, arguments)

    def rows(self, label, start=0, end=None):
        if end is None:
            end = self.world.num_ridges - 1
        return self.call(label, 'FarmWorldApp', 'get_ridge_range_state', start=start, end=end)['ridges']

    def next_morning(self, label):
        tomorrow = self.s.today + timedelta(days=1)
        target = datetime.combine(tomorrow, daytime(7), self.s.timezone).timestamp()
        return self.s.advance_to(label, target)

    def ready(self, label, operation, start=0, end=None):
        """Use registered target states and weather, bounded by the scene season."""
        for attempt in range(240):
            target = self.rows(label + f'_target_{attempt}', start, end)
            soil = self.call(label + f'_soil_{attempt}', 'SensorApp', 'read_soil_sensors')
            probes = soil['soil_sensors']
            last = self.world.num_ridges-1 if end is None else end
            target_probes = [p for p in probes if p['ridge_end'] >= start and p['ridge_start'] <= last]
            if not target_probes or any(p.get('vwc') is None or p.get('temp_c') is None for p in probes):
                raise RuntimeError('Public soil sensor observations are unavailable')
            weather = self.call(label + f'_weather_{attempt}', 'WeatherApp', 'get_current_weather')
            dry_weather = float(weather['rainfall_mm']) == 0
            trafficable = sum(p['vwc'] for p in probes)/len(probes) <= .35
            ok = trafficable
            if operation == 'plant':
                ok = ok and all(.20 <= p['vwc'] <= .35 and p['temp_c'] >= 10 for p in target_probes)
            elif operation == 'harvest':
                ok = ok and dry_weather and all(r['growth_stage'] == 'R8'
                    and r['grain_moisture_pct'] <= 18 for r in target)
            elif operation == 'spray':
                ok = ok and dry_weather and float(weather['wind_speed_ms']) < 6
            if ok:
                return target, weather
            self.next_morning(label + f'_wait_{attempt}')
        raise RuntimeError(f'No legal {operation} window before the polling limit')

    def fuel(self, label):
        status = self.call(label + '_status', 'TractorApp', 'get_status')
        if status['fuel_tank_l'] < 20:
            self.call(label + '_refuel', 'TractorApp', 'refuel', liters=100.)

    def load_seeds_for(self, label, count):
        """Size a real hopper transfer; no initial free equipment payload."""
        status = self.call(label + '_hopper', 'TractorApp', 'get_status')
        missing = max(0, count - int(status['seed_hopper']))
        if missing:
            self.call(label + '_load', 'TractorApp', 'load_seeds',
                      seed_type=self.world.seed_type, count=missing)

    def inspect(self, label, start, end):
        """Ground-truth the explicit target, charging before each <=4-ridge pass."""
        observations = {}
        for first in range(start, end+1, 4):
            last = min(end, first+3)
            status = self.call(label + f'_battery_{first}', 'Robot0', 'check_status')
            if status.get('charging') or status['battery_pct'] < 50:
                self.call(label + f'_charge_{first}', 'Robot0', 'charge')
                self.s.advance_to(label + f'_charge_wait_{first}', self.s.now+3600)
            response = self.call(label + f'_ground_{first}', 'Robot0', 'inspect_crop_health',
                                 start_ridge=first, end_ridge=last)
            if set(response.get('covered_ridges', [])) != set(range(first, last+1)):
                raise RuntimeError('Experiment ground inspection did not cover its explicit target')
            observations.update({int(rid): row for rid, row in response['observations'].items()})
        return observations

    def prepare_spray(self, label, kind, required_liters):
        self.ready(label + '_window', 'spray')
        self.fuel(label + '_fuel')
        self.implement(label + '_implement', 'sprayer')
        status = self.call(label + '_tank', 'TractorApp', 'get_status')
        tank = 'fungicide_tank_l' if kind == 'disease' else 'pesticide_tank_l'
        missing = max(0., required_liters - status[tank])
        if missing:
            method = 'load_fungicide' if kind == 'disease' else 'refill_pesticide_tank'
            self.call(label + '_load', 'TractorApp', method, liters=missing)

    def implement(self, label, implement):
        status = self.call(label + '_status', 'TractorApp', 'get_status')
        attached = status['attached_implement']
        if attached and attached != implement:
            self.call(label + '_detach', 'TractorApp', 'detach_implement')
        if attached != implement:
            self.call(label + '_attach', 'TractorApp', 'attach_implement', implement=implement)

    def inventory(self, label):
        return self.call(label, 'FarmWorldApp', 'get_inventory')

    def water(self, label, start, end, mm):
        """Clip a requested pulse to the actual public whole-field allowance."""
        public = self.inventory(label + '_allowance')
        regime = public['management_regime']
        cap, used = regime['irrigation_quota_mm_total'], regime['irrigation_used_mm_total']
        if cap is not None:
            mm = min(mm, max(0., cap-used) * self.world.num_ridges/(end-start+1))
        if mm < .1:
            return False
        self.call(label, 'FieldOpsApp', 'irrigate', start=start, end=end, hours=mm/5.)
        return True

    @staticmethod
    def confirmed(observations, kind):
        key = {'weed': 'weed_present', 'insect': 'pest_present', 'disease': 'disease_present'}[kind]
        confidence = {'weed': 'weed_confidence', 'insect': 'pest_confidence', 'disease': 'disease_confidence'}[kind]
        return [rid for rid, row in observations.items()
                if row.get(key) is True and float(row.get(confidence, 0)) >= .6]
