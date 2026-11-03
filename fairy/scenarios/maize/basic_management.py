"""W01/N01 v1: free management tasks; reference actions are not acceptance gates."""
from dataclasses import replace
from pathlib import Path
import json
import math
from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.farm_world import FarmWorldApp
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_scenario_helpers import collect_event_graph
from fairy.types import EventRegisterer
from .maize_scenario_helpers import MaizeScenario, init_maize_apps
from .maize_scenario_catalog import SPECS
from .validation import task_state, _audit, validate_maize

DATA = Path(__file__).with_name('basic_management_v1')

def candidate_spec(candidate):
    return replace(SPECS['water_limit' if candidate == 'W01' else 'nitrogen_limit'],
                   variant='basic_' + candidate.lower() + '_v1', fertilizer_stock_kg=360.,
                   fertilizer_quota_kg=360., irrigation_quota_mm=150. if candidate == 'W01' else 0.,
                   topdress_kg=0., irrigation_days=(), irrigation_schedule=(), topdress_schedule=())

def terminal_result(state, per_ridge, audit_failures, positive_failures, pending):
    """Pure terminal contract. No reference dose, cadence or ordering checks."""
    finite = len(per_ridge) == 64 and {r['ridge'] for r in per_ridge} == set(range(64)) and all(
        r['DOM'] is not None and isinstance(r['TWSO'], (int, float))
        and not isinstance(r['TWSO'], bool) and math.isfinite(r['TWSO']) and r['TWSO'] >= 0
        for r in per_ridge)
    zero = finite and all(r['TWSO'] == 0 for r in per_ridge)
    failures = list(audit_failures)
    if not finite: failures.append('missing_or_invalid_native_maturity_yield')
    if zero:
        if set(state['mature']) != set(range(64)) or set(state['harvested']) != set(range(64)):
            failures.append('zero_yield_requires_all64_mature_and_harvested')
        if any(state[k] != 0 for k in ('grain_bin', 'trailer', 'warehouse')):
            failures.append('zero_yield_unsettled_grain')
    else:
        failures.extend(positive_failures)
    if pending: failures.append('unsettled_management')
    complete = not failures
    return dict(status=('zero_yield_completed' if zero else 'completed') if complete else 'incomplete',
                execution_complete=complete, production_success=complete and not zero,
                postharvest_applicability='not_applicable_no_grain' if zero else 'applicable',
                failures=failures, mature_TWSO_kg_DM_ha=sum(r['TWSO'] for r in per_ridge)/64 if finite else None,
                warehouse_kg_at_14pct=state['warehouse'])

def candidate_stored_goals(state, per_ridge, recovery_states):
    """Only proven zero-grain ridges are exempt from postharvest moisture checks."""
    failures = []
    if set(state['mature']) != set(range(64)):
        failures.append('all 64 ridges must reach native physiological maturity')
    if set(state['harvested']) != set(range(64)):
        failures.append('all 64 ridges must be harvested')
    native = {r['ridge']: r for r in per_ridge}
    if set(recovery_states) != set(range(64)):
        failures.append('missing_or_unexpected_recovery_ridges')
    for rid, recovered in recovery_states.items():
        row = native.get(rid, {})
        twso = row.get('TWSO')
        quantity = recovered.recovered_yield_g_m2_at_market_moisture
        valid_quantity = (isinstance(quantity, (int, float)) and not isinstance(quantity, bool)
                          and math.isfinite(quantity) and quantity >= 0)
        if not valid_quantity:
            failures.append(f'invalid_recovered_grain:{rid}')
            continue
        confirmed_zero = (recovered.harvested and row.get('DOM') is not None
                          and isinstance(twso, (int, float)) and not isinstance(twso, bool)
                          and math.isfinite(twso) and twso == 0 and quantity == 0)
        if confirmed_zero:
            continue
        moisture = recovered.grain_moisture_frac
        if (not recovered.harvested or recovered.drying_required
                or not isinstance(moisture, (int, float)) or isinstance(moisture, bool)
                or not math.isfinite(moisture) or not 0 <= moisture <= .14 + 1e-9):
            failures.append(f'harvested_grain_not_safely_dried:{rid}')
    if state['warehouse'] <= 0 or state['trailer'] > 1e-6 or state['grain_bin'] > 1e-6:
        failures.append('all positive grain yield must be stored')
    return failures

class BasicManagementScenario(MaizeScenario):
    candidate = ''
    scenario_version = 'basic-management-v1.1'

    def init_and_populate_apps(self, *args, **kwargs):
        init_maize_apps(self, self.spec)
        self.scenario_input = (DATA / f'{self.candidate}.zh.txt').read_text()

    def build_events_flow(self):
        # Ordinary native oracle event graph, compiled from the preserved public trace.
        # It is a reproducible reference, not a claim of optimality or an exact-path validator.
        reference = json.loads((DATA / f'{self.candidate}.reference.json').read_text())
        apps = {a.name: a for a in self.apps}
        with EventRegisterer.capture_mode():
            first = self.get_typed_app(AgentUserInterface).send_message_to_agent(content=self.scenario_input).with_id('briefing')
            prev = first
            for i, row in enumerate(reference['actions']):
                app, tool = row['tool'].split('__', 1)
                prev = getattr(apps[app], tool)(**row['args']).oracle().with_id(f'reference_{i:04d}').depends_on(prev)
            self.events = collect_event_graph(first)

    def validate(self, env=None):
        workflow = env.workflow if env is not None else self.workflow
        state = task_state(self)
        failures, errors, _ = _audit(self, state, workflow)
        # A recovered tool refusal is diagnostic; unsafe-storage warnings remain failures.
        failures = [f for f in failures if f != 'tool errors or unsafe-storage warnings occurred']
        warnings = [s.name for s in workflow.dag.values() if isinstance(s.content, dict) and s.content.get('warning')]
        if warnings: failures.append('unsafe_or_unreviewed_warning')
        farm = self.get_typed_app(FarmWorldApp); backend = farm.physics.crop_backend
        per = [{'ridge':rid, 'DOM':(r.maturity_snapshot or {}).get('DOM'),
                'TWSO':(r.maturity_snapshot or {}).get('TWSO')} for rid,r in backend._runs.items()]
        positive = candidate_stored_goals(state, per, farm.physics.yield_recovery.states)
        pending = any(backend._pending.values()) or any(farm.physics.pending_management_actions_by_ridge.values())
        result = terminal_result(state, per, failures, positive, pending)
        if result['status']=='zero_yield_completed' and any(
            not s.harvested or s.recovered_yield_g_m2_at_market_moisture != 0
            for s in farm.physics.yield_recovery.states.values()):
            result.update(status='incomplete', execution_complete=False, production_success=False)
            result['failures'].append('zero_recovery_ledger_mismatch')
        water = [{'ridge':rid,'area_m2':268*farm.ridge_width_m,'TOTIRR_cm':r.pcse.get('TOTIRR')}
                 for rid,r in backend._runs.items()]
        valid_water = len(water)==64 and all(isinstance(r['TOTIRR_cm'],(int,float)) and math.isfinite(r['TOTIRR_cm']) for r in water)
        result.update(scenario_version=self.scenario_version, native_per_ridge=per,
                      water_by_ridge=water,effective_irrigation_field_mm=(sum(r['TOTIRR_cm']*10*r['area_m2'] for r in water)/sum(r['area_m2'] for r in water)) if valid_water else None,
                      tool_errors=errors, warnings=warnings,
                      legacy_native_validation=validate_maize(self,self.spec,workflow=workflow).to_dict())
        return ScenarioValidationResult(success=result['production_success'],
             message=result['status'],metadata=result)
