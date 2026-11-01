"""Harvest-only revisions must improve recovery through legal public tools."""
import pytest

from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class


@pytest.mark.parametrize('scenario_id,old_waits', [
    ('scenario_two_farm_full_season_hn84_normal',
     {'wait_both_farms_harvest_34_days': 39}),
    ('scenario_three_farm_full_season_hn84_normal',
     {'wait_all_three_farms_harvest_34_days': 39}),
    ('scenario_two_farm_maize_soybean_full_season',
     {'wait_soybean_harvest': 17, 'wait_maize_harvest': 25}),
])
def test_earlier_soybean_harvest_improves_recovery_without_changing_growth(scenario_id, old_waits):
    def execute(obsolete=False):
        scenario = get_scenario_class(scenario_id)()
        scenario.setup()
        engine = Engine(None, scenario)
        if obsolete:
            workflow = engine.run_scenario_oracle(False)
            # Restore only the former waits; all management and public tools
            # remain identical, providing a causal harvest-timing comparison.
            for name, days in old_waits.items():
                workflow.dag[name].tool_args = {'days': days}
            workflow = engine.replay_workflow(workflow)
        else:
            workflow = engine.run_scenario_oracle(True)
        errors = [step.name for step in workflow.dag.values()
                  if step.error_stage or isinstance(step.content, dict)
                  and (step.content.get('error') or step.content.get('status') in ('failed', 'error', 'partial'))]
        assert not errors
        results = {}
        for farm_id, context in scenario.farm_environment.farms.items():
            farm = context.world
            states = farm.physics.yield_recovery.states.values()
            area = farm.field_length_m * farm.ridge_width_m / 1000
            results[farm_id] = {
                'bio': sum(y.biological_yield_g_m2 * area for y in states),
                'recovered': sum(y.recovered_yield_g_m2_at_market_moisture * area for y in states),
                'harvest_times': [(step.time_before, step.time_after)
                                  for step in workflow.dag.values()
                                  if step.tool_name == 'Tractor__harvest'
                                  and step.tool_args.get('farm_id') == farm_id],
            }
            assert all(y.harvested for y in states)
            batches = [batch for batch in scenario.warehouse.grain_batches.values()
                       if batch.origin_farm_id == farm_id]
            assert len(batches) == farm.num_ridges // 4
            assert all(batch.status == 'stored' and batch.quantity_kg > 0
                       and batch.moisture_pct <= scenario.warehouse._storage_limit(batch)
                       for batch in batches)
        assert scenario.tractor.grain_origin_farm_id is None
        assert scenario.tractor.get_state()['grain_bin_kg'] == 0
        return results

    revised = execute()
    former = execute(obsolete=True)
    for farm_id in revised:
        assert revised[farm_id]['bio'] == pytest.approx(former[farm_id]['bio'])
        if farm_id == 'maize_field':
            assert revised[farm_id]['harvest_times'] == former[farm_id]['harvest_times']
            assert revised[farm_id]['recovered'] == pytest.approx(former[farm_id]['recovered'])
        else:
            assert revised[farm_id]['recovered'] > former[farm_id]['recovered']
