"""Native receipt and public candidate regressions; no oracle or model calls."""
import copy
from types import SimpleNamespace as NS

import pytest

from test_jev_new_tools import setup
from fairy.agents.jev.menu import (
    build_tool_menus, build_arg_menu, arg_descriptions, EmptyMenuError, dependent_menu,
)
from fairy.agents.jev.snapshot import _failed, _result_data, build_snapshot, pending_effects

RICE = 'scenario_rice_l3_normal'
SHARED = 'scenario_multi_crop_full_season_maize'


def step(name, args, content, op='TOOL', time=123):
    return NS(tool_name=name, tool_args=args, content=content, op_type=op, time=time)


def menus(agent, steps=()):
    return build_tool_menus(agent.tools_map, task_text='Manage the farm.',
                            num_ridges=agent._num_ridges, steps=steps)


def arg_menu(agent, name, arg, *, args=None, steps=()):
    tool = agent.tools_map[name]
    return build_arg_menu(tool, next(a for a in tool.args if a.name == arg),
        descriptions=arg_descriptions(tool.function_description), numbers=[],
        num_ridges=agent._num_ridges, arguments=args, steps=steps)


@pytest.mark.parametrize('content,op,failed', [
    ({'ok': True, 'data': {'count': 1}, 'error': None}, 'TOOL', False),
    ({'ok': False, 'data': None, 'error': {'code': 'REJECTED'}}, 'TOOL', True),
    ({'ok': False, 'data': None, 'error': None}, 'TOOL', True),
    ({'ok': True, 'data': {}, 'error': None}, 'TOOL_ERROR', True),
    ({'status': 'ok'}, 'TOOL', False),
    ({'error': 'legacy'}, 'TOOL', True),
    ({'error': None}, 'TOOL', True),  # Preserve the legacy non-receipt rule.
    ('plain result', 'TOOL', False),
])
def test_result_failure_contract(content, op, failed):
    original = copy.deepcopy(content)
    assert _failed(step('tool', {}, content, op)) is failed
    _result_data(content)
    assert content == original


def test_native_success_progress_and_receipt_clock_do_not_confuse_stuck():
    s, a = setup(SHARED)
    name = 'Tractor__load_seeds'
    args = dict(farm_id='maize_a', asset_id='tractor_shared', seed_type='MAIZE_STANDARD', count=1)
    results = [a.tools_map[name](**args), a.tools_map[name](**args)]
    assert all(r['ok'] for r in results)
    steps = [step(name, args, r) for r in results]
    a._facts = {'steps': steps}
    assert not a._is_stuck(name, args)
    snapshot, _ = build_snapshot(s.apps, NS(dag=dict(enumerate(steps))), s.start_time)
    assert all(not x['failed'] for x in snapshot['recent_actions'])
    assert snapshot['farm_now']['actions_this_run']
    same = copy.deepcopy(results[0]); same['time_after'] = 99999999
    a._facts = {'steps': [steps[0], step(name, args, same)]}
    assert a._is_stuck(name, args)
    a._facts = {'steps': [step(name, args, {'ok': False, 'data': {}, 'error': str(i)}) for i in range(2)]}
    assert a._is_stuck(name, args)


def test_existing_pending_fields_in_receipt_data():
    result = {'ok': True, 'data': {'effect_ready_at': 150}, 'error': None}
    steps = [step('tool', {}, result)]
    assert pending_effects(steps, 100)[0]['seconds_left'] == 50
    assert pending_effects([step('tool', {}, {**result, 'ok': False})], 100) == []


def test_native_public_capacity_and_schema_with_no_task_digits():
    _, a = setup(SHARED)
    ms = menus(a)
    for name, param, top in [('load_seeds', 'count', 300000), ('refuel', 'liters', 100),
                              ('load_fertilizer', 'kg', 500), ('load_pesticide', 'liters', 800),
                              ('load_fungicide', 'liters', 800)]:
        m = next(x for x in ms['Tractor__' + name].args if x.name == param)
        assert top in m.options.values()
        if param == 'count': assert all(isinstance(v, int) for v in m.options.values())
    dry = arg_menu(a, 'Farm__dry_grain', 'target_moisture_pct')
    assert {11., 13., 16.} <= set(dry.options.values())


def test_selected_asset_capacity_is_rebuilt_not_taken_from_union(monkeypatch):
    _, a = setup('scenario_multi_farm_uneven_planting')
    runtime = a.tools_map['Tractor__refuel'].class_instance.runtime
    original = runtime.capabilities
    assets = [x for x in runtime.assets.values() if x.kind == 'tractor']
    assert len(assets) >= 2
    tops = {asset.asset_id: 50 * (i + 1) for i, asset in enumerate(assets)}
    def capacities(ctx):
        result = copy.deepcopy(original(ctx))
        if ctx.asset_id in tops: result['asset_capacities']['fuel_tank_l'] = tops[ctx.asset_id]
        return result
    monkeypatch.setattr(runtime, 'capabilities', capacities)
    for asset in assets:
        am = arg_menu(a, 'Tractor__refuel', 'liters', args={
            'asset_id': asset.asset_id, 'farm_id': asset.spec.allowed_farm_ids[0]})
        assert max(am.options.values()) == tops[asset.asset_id]


def observation(method, plot, **values):
    return step('PaddyObservationApp__' + method, {'plot_id': plot},
                {'plot_id': plot, 'timestamp': 123, **values})


def test_rice_initial_rules_distinguish_waiting_from_missing():
    _, a = setup(RICE)
    ms = menus(a)
    assert 'PaddyOpsApp__irrigate' in ms
    assert set(arg_menu(a, 'PaddyOpsApp__soak', 'hours').options.values()) == set(range(1, 73))
    for name, param in [('drain', 'water_mm'), ('replant_seedlings', 'quantity')]:
        with pytest.raises(EmptyMenuError) as error:
            arg_menu(a, 'PaddyOpsApp__' + name, param)
        assert error.value.reason == 'awaiting_observation'
        assert 'PaddyOpsApp__' + name not in ms


def test_rice_water_bounds_and_native_execution():
    s, a = setup(RICE)
    world = next(app for app in s.apps if type(app).__name__ == 'PaddyWorldApp')
    plot = world.field.plots[0]
    channel = next(c for c in world.field.channels if c.channel_id == 'supply')
    # Synthetic finite supply fixture, followed by actual native operations.
    channel.quota_m3 = plot.area_m2 * .02 / channel.efficiency
    args = {'plot_id': plot.plot_id}
    water = arg_menu(a, 'PaddyOpsApp__irrigate', 'water_mm', args=args)
    assert max(water.options.values()) == pytest.approx(20)
    assert a.tools_map['PaddyOpsApp__irrigate'](**args, water_mm=20)['status'] == 'ok'
    result = a.tools_map['PaddyObservationApp__read_water_sensors'](**args)
    steps = [step('PaddyObservationApp__read_water_sensors', args, result)]
    before = copy.deepcopy(world.get_state())
    m = arg_menu(a, 'PaddyOpsApp__drain', 'water_mm', args=args, steps=steps)
    assert max(m.options.values()) <= result['surface_water_mm']
    assert world.get_state() == before
    assert a.tools_map['PaddyOpsApp__drain'](**args, water_mm=min(m.options.values()))['status'] == 'ok'


def test_rice_observation_scope_freshness_failures_and_zero():
    _, a = setup(RICE)
    old = observation('read_water_sensors', 'p1', surface_water_mm=10)
    newer = observation('read_water_sensors', 'p1', surface_water_mm=2)
    unrelated = observation('read_water_sensors', 'p2', surface_water_mm=90)
    failed = observation('read_water_sensors', 'p1', surface_water_mm=100); failed.op_type = 'TOOL_ERROR'
    steps = [old, unrelated, newer, failed]
    am = arg_menu(a, 'PaddyOpsApp__drain', 'water_mm', args={'plot_id': 'p1'}, steps=steps)
    assert max(am.options.values()) == 2
    assert 'observation time=123' in am.source
    m = menus(a, [old])['PaddyOpsApp__drain']
    assert list(m.args[0].options.values()) == ['p1']
    with pytest.raises(EmptyMenuError, match='no positive') as error:
        arg_menu(a, 'PaddyOpsApp__drain', 'water_mm', args={'plot_id': 'p1'},
                 steps=[observation('read_water_sensors', 'p1', surface_water_mm=0)])
    assert error.value.reason == 'empty_resources'


def test_rice_no_sensor_or_hidden_state_access_for_candidates(monkeypatch):
    s, a = setup(RICE)
    world = next(app for app in s.apps if type(app).__name__ == 'PaddyWorldApp')
    def forbidden(*a, **k): raise AssertionError('Must not query or read backend')
    for backend in world.backends.values(): monkeypatch.setattr(backend.water, 'ledger', forbidden)
    monkeypatch.setattr(world, 'advance_physics_time', forbidden)
    assert menus(a)
    assert arg_menu(a, 'PaddyOpsApp__drain', 'water_mm', steps=[observation('read_water_sensors', 'p1', surface_water_mm=12)])


def test_rice_replant_estimate_loaded_cap_and_native_execution():
    s, a = setup(RICE)
    world = next(app for app in s.apps if type(app).__name__ == 'PaddyWorldApp')
    plot = world.field.plots[0]
    # Public observation fixture; menu must not use true stand_fraction.
    world.field.seedlings.loaded = 100
    obs = observation('inspect_establishment', plot.plot_id, stand_fraction_estimate=.9)
    am = arg_menu(a, 'PaddyOpsApp__replant_seedlings', 'quantity', args={'plot_id': plot.plot_id}, steps=[obs])
    assert max(am.options.values()) == 100
    assert all(type(v) is int and 0 < v <= 100 for v in am.options.values())
    # Establish explicit native preconditions in this synthetic tool fixture.
    plot.planted = True
    plot.transplant_timestamp = world.sim_time
    plot.stand_fraction = .8
    world.backends[plot.plot_id].water.states.SS = 2
    world.backends[plot.plot_id].water.states.SM = .45
    result = a.tools_map['PaddyOpsApp__replant_seedlings'](
        plot_id=plot.plot_id, quantity=min(am.options.values()))
    assert result['status'] == 'ok'
    world.field.seedlings.loaded = 0
    with pytest.raises(EmptyMenuError) as error:
        arg_menu(a, 'PaddyOpsApp__replant_seedlings', 'quantity', steps=[obs])
    assert error.value.reason == 'empty_resources'


def test_zero_canal_quota_and_rounded_stand_are_not_invented():
    s, a = setup(RICE)
    world = next(app for app in s.apps if type(app).__name__ == 'PaddyWorldApp')
    channel = next(c for c in world.field.channels if c.channel_id == 'supply')
    channel.withdrawn_m3 = channel.quota_m3
    with pytest.raises(EmptyMenuError) as error:
        arg_menu(a, 'PaddyOpsApp__irrigate', 'water_mm')
    assert error.value.reason == 'empty_resources'
    world.field.seedlings.loaded = 100
    world.field.plots[0].stand_fraction = .996  # Hidden truth must not override rounded observation.
    with pytest.raises(EmptyMenuError) as error:
        arg_menu(a, 'PaddyOpsApp__replant_seedlings', 'quantity',
                 steps=[observation('inspect_establishment', 'p1', stand_fraction_estimate=1.)])
    assert error.value.reason == 'empty_resources'


def test_rice_implement_choices_execute_on_native_tools():
    for implement in ('puddler', 'spreader', 'sprayer'):
        _, a = setup(RICE)
        m = menus(a)['PaddyMachineryApp__attach_implement']
        machine = next(x for x in m.args if x.name == 'machine_id')
        assert list(machine.options.values()) == ['tractor']
        assert a.tools_map[m.tool_name](machine_id='tractor', implement=implement)['status'] == 'ok'
        assert a.tools_map['PaddyMachineryApp__detach_implement'](machine_id='tractor')['status'] == 'ok'


def test_rice_dependent_values_follow_selected_plot():
    _, a = setup(RICE)
    steps = [observation('read_water_sensors', 'p1', surface_water_mm=2),
             observation('read_water_sensors', 'p2', surface_water_mm=90)]
    a._facts = {'steps': steps}; a.tool_menus = menus(a, steps)
    menu = a.tool_menus['PaddyOpsApp__drain']; asked = []
    assert dependent_menu(a.tools_map[menu.tool_name])
    def ask(kind, state, qs):
        result = {}
        for qid, q in qs.items():
            asked.append((qid, list(q['criteria'])))
            pick = 'p1' if qid == 'arg__plot_id' else list(q['criteria'])[-1]
            result[qid] = {'choice': pick, 'confidence': 1}
        return result
    a._ask = ask
    args, _ = a._dependent_values(menu, {'task': 'Manage the farm.'})
    assert asked[0][0] == 'arg__plot_id'
    assert args == {'plot_id': 'p1', 'water_mm': 2}
