"""Flow-based Rice menus preserve Choice routing; no real model calls."""
import copy
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from test_jev_new_tools import setup
from fairy.agents.jev.menu import build_arg_menu, build_tool_menus, arg_descriptions, task_numbers

RICE = 'scenario_rice_l3_normal'


def water_menu(agent, plot='p1', task='Manage the field.'):
    tool = agent.tools_map['PaddyOpsApp__irrigate']
    return build_arg_menu(tool, next(a for a in tool.args if a.name == 'water_mm'),
        descriptions=arg_descriptions(tool.function_description), numbers=task_numbers(task),
        num_ridges=0, arguments={'plot_id': plot}, task_text=task)


def world_of(scene):
    return next(a for a in scene.apps if type(a).__name__ == 'PaddyWorldApp')


def test_native_task_small_and_large_doses_without_model_or_task_hint():
    _, agent = setup(RICE)
    p1 = water_menu(agent); p2 = water_menu(agent, 'p2')
    assert min(p1.options.values()) == 3.6
    assert min(p2.options.values()) == 2.4
    assert {3.6, 7.2, 18., 36., 50.4, 72., 1728., 10800.} <= set(p1.options.values())
    assert 50 not in p1.options.values()  # Not copied from a previous Qwen answer.
    assert len(p1.options) <= 255 and len(p2.options) <= 255
    assert 'WAIT_STEPS' in p1.source and 'effective flow=72' in p1.source
    menus = build_tool_menus(agent.tools_map, task_text='Manage the field.', num_ridges=0)
    union = next(a for a in menus['PaddyOpsApp__irrigate'].args if a.name == 'water_mm')
    assert len(union.options) <= 255


def test_quota_clips_but_does_not_set_low_dose_spacing():
    s, agent = setup(RICE); world = world_of(s); channel = world.channel('supply')
    initial = set(water_menu(agent).options.values())
    channel.withdrawn_m3 = 6000
    later = set(water_menu(agent).options.values())
    assert min(later) == min(initial) == 3.6
    assert {v for v in initial if v < 100} == {v for v in later if v < 100}
    assert max(later) == 5400
    channel.quota_m3 = channel.withdrawn_m3 + 1 / .9  # Public residual budget: 1 mm.
    assert set(water_menu(agent).options.values()) == {1.}


def test_flow_efficiency_blockage_area_and_window_are_public_sources():
    s, agent = setup(RICE); world = world_of(s); channel = world.channel('supply')
    channel.flow_m3_hour = 40
    assert min(water_menu(agent).options.values()) == 1.8
    channel.efficiency = .45
    assert min(water_menu(agent).options.values()) == .9
    channel.blockage_fraction = .5
    assert min(water_menu(agent).options.values()) == .45
    channel.open_hour = 6; channel.close_hour = 20
    assert max(water_menu(agent).options.values()) == 126  # 9 mm/h * 14h.
    assert min(water_menu(agent, 'p2').options.values()) == .3


def test_explicit_task_duration_and_numbers_are_used_in_dependent_request():
    _, agent = setup(RICE)
    task = 'Work for 5 minutes, then inspect.'
    menu = water_menu(agent, task=task)
    assert .6 in menu.options.values()  # 72 mm/h * 5/60 h / 10.
    assert 5 in menu.options.values()  # Existing manos plain task-number rule.
    agent.tool_menus = build_tool_menus(agent.tools_map, task_text=task, num_ridges=0)
    calls = []
    def choose(kind, state, questions):
        calls.extend(questions)
        return {qid: {'choice': 'p1' if qid == 'arg__plot_id' else '0.6', 'confidence': 1}
                for qid in questions}
    agent._ask = choose
    args, _ = agent._dependent_values(agent.tool_menus['PaddyOpsApp__irrigate'], {'task': task})
    assert args == {'plot_id': 'p1', 'water_mm': .6}
    assert calls == ['arg__plot_id', 'arg__water_mm']


def test_menu_does_not_query_hidden_water_or_change_clock(monkeypatch):
    s, agent = setup(RICE); world = world_of(s)
    before = copy.deepcopy(world.get_state()); clock = (world.time_manager.start_time, world.time_manager.offset)
    def forbidden(*args, **kwargs): raise AssertionError('No physics/observation queries allowed')
    with monkeypatch.context() as protected:
        protected.setattr(world, 'advance_physics_time', forbidden)
        for backend in world.backends.values(): protected.setattr(backend.water, 'ledger', forbidden)
        water_menu(agent)
    assert world.get_state() == before
    assert clock == (world.time_manager.start_time, world.time_manager.offset)


@pytest.mark.parametrize('plot,water', [('p1', 3.6), ('p2', 2.4)])
def test_generated_doses_reach_native_irrigation(plot, water):
    _, agent = setup(RICE)
    assert water in water_menu(agent, plot).options.values()
    receipt = agent.tools_map['PaddyOpsApp__irrigate'](plot_id=plot, water_mm=water)
    assert receipt['status'] == 'ok'
    assert receipt['delivered_mm'] == pytest.approx(water)
    assert receipt['withdrawn_m3'] == pytest.approx(4)
    assert receipt['duration_s'] == 180


@pytest.mark.parametrize('hybrid', [False, True])
def test_cli_choice_to_typed_water_with_no_extra_duration_decision(tmp_path, hybrid):
    calls = []; errors = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append({'path': self.path, 'body': body})
            try:
                if self.path == '/v1/systemone':
                    answers = {}
                    picks = {'next_action': 'PaddyOpsApp__irrigate', 'arg__plot_id': 'p1', 'arg__water_mm': '3.6'}
                    for qid, q in body['questions'].items():
                        pick = picks[qid]; assert pick in q['criteria']
                        answers[qid] = {'choice': pick, 'confidence': .1 if hybrid else .9,
                                        'probabilities': {k: float(k == pick) for k in q['criteria']}}
                    response = {'model': 'offline-jev', 'answers': answers, 'usage': {'input_tokens': 10, 'output_tokens': 1}}
                elif self.path == '/v1/chat/completions':
                    response = {'id': 'fixture', 'model': 'offline-llm', 'choices': [{'index': 0, 'finish_reason': 'tool_calls',
                        'message': {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'c1', 'type': 'function',
                            'function': {'name': 'PaddyOpsApp__irrigate', 'arguments': json.dumps({'plot_id': 'p1', 'water_mm': 7.2})}}]}}],
                        'usage': {'prompt_tokens': 10, 'completion_tokens': 1, 'total_tokens': 11}}
                else: raise AssertionError(self.path)
                self.send_response(200)
            except Exception as exc:
                errors.append(str(exc)); response = {'error': str(exc)}; self.send_response(400)
            data = json.dumps(response).encode()
            self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data)))
            self.end_headers(); self.wfile.write(data)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    root = Path(__file__).resolve().parents[1]; url = f'http://127.0.0.1:{server.server_port}/v1'
    argv = [str(root/'.venv/bin/fairy-cli'), '--scenario', RICE, '--agent', '--controller', 'farm_jev',
            '--provider', 'system-one-compatible', '--model', 'offline-jev', '--endpoint', url,
            '--max-tool-calls', '1', '--timeout-seconds', '60', '--request-max-retries', '0',
            '--output-dir', str(tmp_path), '--task-id', 'rice-flow-offline',
            '--scenario-kwargs', json.dumps({'seed': 0, 'detailed_briefing': True})]
    if hybrid:
        argv += ['--fallback-provider', 'openai-compatible', '--fallback-model', 'offline-llm',
                 '--fallback-endpoint', url, '--fallback-api-key-env', 'OFFLINE_KEY', '--fallback-confidence', '.4']
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ('API_KEY','TOKEN','PROXY'))}
    env.update(OFFLINE_KEY='fixture', FAIRY_AGENT_LLM_CALL_RETRIES='0')
    try:
        proc = subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=90)
        (tmp_path/'cli.log').write_text(proc.stdout + proc.stderr)
        (tmp_path/'requests.json').write_text(json.dumps(calls, indent=2))
        assert proc.returncode == 0, proc.stderr
        assert not errors
        decision = [c for c in calls if c['path'] == '/v1/systemone']
        llm = [c for c in calls if c['path'] == '/v1/chat/completions']
        assert [list(c['body']['questions']) for c in decision] == [['next_action'], ['arg__plot_id'], ['arg__water_mm']]
        assert len(llm) == int(hybrid)
        workflow = json.loads((tmp_path/(RICE+'.agent_workflow.json')).read_text())
        executed = [s for s in workflow.values() if s.get('op_type') in ('TOOL', 'TOOL_ERROR')]
        assert len(executed) == 1 and executed[0]['op_type'] == 'TOOL'
        assert executed[0]['tool_args']['water_mm'] == (7.2 if hybrid else 3.6)
        assert executed[0]['content']['status'] == 'ok'
    finally:
        server.shutdown(); server.server_close(); thread.join()
