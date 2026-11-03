"""External fairy-cli against loopback-only scripted model services."""
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

@pytest.mark.parametrize('scenario',[
 'scenario_two_farm_full_season_hn84_normal',
 'scenario_rice_l3_normal',
 'scenario_multi_crop_full_season_maize',
])
@pytest.mark.parametrize('hybrid',[False,True])
@pytest.mark.parametrize('provider',['system-one-compatible','typesafe'])
def test_real_cli_new_scene_routes(tmp_path,scenario,hybrid,provider):
 counts={'decision':0,'llm':0}
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_POST(self):
   body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
   if self.path=='/v1/systemone':
    counts['decision']+=1; answers={}
    for qid,q in body['questions'].items():
     opts=list(q['criteria'])
     pick=next((n for n in opts if n.endswith('__get_inventory') or n.endswith('__describe_environment')),opts[0])
     answers[qid]={'type':'choice','choice':pick,'confidence':.1 if hybrid else .9,'probabilities':{n:float(n==pick) for n in opts}}
    result={'model':'offline-decision','answers':answers,'usage':{'input_tokens':10,'output_tokens':2}}
   elif self.path=='/v1/chat/completions':
    counts['llm']+=1
    tools=body['tools'];tool=next(t['function'] for t in tools if t['function']['name'].endswith(('__get_inventory','__describe_environment')) and not t['function']['parameters'].get('required'))
    result={'id':'local','object':'chat.completion','model':'offline-llm','choices':[{'index':0,'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':'c1','type':'function','function':{'name':tool['name'],'arguments':'{}'}}]}}],'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}}
   else:
    self.send_error(404);return
   data=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 root=Path(__file__).resolve().parents[1];endpoint=f'http://127.0.0.1:{server.server_port}/v1'
 argv=[str(root/'.venv/bin/fairy-cli'),'--scenario',scenario,'--agent','--controller','farm_jev','--provider',provider,'--model','offline-decision','--endpoint',endpoint.removesuffix('/v1') if provider=='typesafe' else endpoint,'--max-tool-calls','1','--timeout-seconds','60','--output-dir',str(tmp_path),'--task-id','offline-new-tools','--scenario-kwargs',json.dumps({'seed':0,'detailed_briefing':True}),'--request-max-retries','0']
 if hybrid:argv+=['--fallback-provider','openai-compatible','--fallback-model','offline-llm','--fallback-endpoint',endpoint,'--fallback-api-key-env','OFFLINE_KEY','--fallback-confidence','.4']
 env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ('API_KEY','TOKEN','PROXY'))};env.update(OFFLINE_KEY='fixture',FAIRY_AGENT_LLM_CALL_RETRIES='0')
 (tmp_path/'launch-argv.json').write_text(json.dumps(argv,indent=2))
 try:
  result=subprocess.run(argv,cwd=tmp_path,env=env,capture_output=True,text=True,timeout=90)
  (tmp_path/'cli.log').write_text(result.stdout+result.stderr)
  assert result.returncode==0,(result.stdout+result.stderr)[-4000:]
  report=json.loads(next(tmp_path.glob('*.run_report.json')).read_text())
  assert report['metrics']['tool_call_count']==1
  assert counts['decision']>=1
  assert counts['llm']==(1 if hybrid else 0)
 finally:server.shutdown();server.server_close();thread.join()


@pytest.mark.parametrize('provider', ['system-one-compatible', 'typesafe'])
@pytest.mark.parametrize('enabled', [False, True])
def test_real_cli_robot_range_is_bounded_on_the_wire(tmp_path, provider, enabled):
 """Both SDK routes get a dependent count menu, not the illegal 62+4 choice."""
 requests = []
 class Handler(BaseHTTPRequestHandler):
  def log_message(self, *args): pass
  def do_POST(self):
   body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
   requests.append(body)
   assert self.path == '/v1/systemone'
   answers = {}
   for qid, q in body['questions'].items():
    opts = list(q['criteria'])
    pick = {'next_action': 'Robot0__inspect_emergence', 'arg__start_ridge': 'ridge 62', 'arg__end_ridge': '2 ridges' if enabled else '4 ridges'}[qid]
    assert pick in opts
    answers[qid] = {'type': 'choice', 'choice': pick, 'confidence': .9, 'probabilities': {n: float(n == pick) for n in opts}}
   result = {'model': 'offline-decision', 'answers': answers, 'usage': {'input_tokens': 10, 'output_tokens': 2}}
   data = json.dumps(result).encode()
   self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
 server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
 thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
 root = Path(__file__).resolve().parents[1]
 endpoint = f'http://127.0.0.1:{server.server_port}'
 argv = [str(root/'.venv/bin/fairy-cli'), '--scenario', 'scenario_farm_world_field_prep', '--agent', '--controller', 'farm_jev', '--provider', provider, '--model', 'offline-decision', '--endpoint', endpoint if provider == 'typesafe' else endpoint+'/v1', '--max-tool-calls', '1', '--timeout-seconds', '30', '--output-dir', str(tmp_path), '--task-id', 'offline-range-bound', '--enforced-tool-adaptor', str(enabled).lower(), '--request-max-retries', '0']
 env = {k: v for k, v in os.environ.items() if not any(x in k.upper() for x in ('API_KEY', 'TOKEN', 'PROXY'))}
 try:
  result = subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
  assert result.returncode == 0, (result.stdout+result.stderr)[-4000:]
  expected = [{'next_action'}, {'arg__start_ridge'}, {'arg__end_ridge'}] if enabled else [{'next_action'}, {'arg__start_ridge', 'arg__end_ridge'}]
  assert [set(r['questions']) for r in requests] == expected
  from fairy.agents.jev.execution_guidance import execution_guidance
  for request in requests:
   state = request['state']
   if isinstance(state, str): state = json.loads(state)
   assert ('jev_execution_guidance' in state) == enabled
   if enabled: assert state['jev_execution_guidance'] == execution_guidance()
  if enabled: assert list(requests[2]['questions']['arg__end_ridge']['criteria']) == ['1 ridge', '2 ridges']
  report = json.loads(next(tmp_path.glob('*.run_report.json')).read_text())
  assert report['metrics']['tool_call_count'] == 1
  progress = [json.loads(line) for line in next(tmp_path.glob('*.progress.jsonl')).read_text().splitlines()]
  action = next(e for e in progress if e.get('record_type') == 'jev_action')
  assert action['arguments'] == {'start_ridge': 62, 'end_ridge': 63 if enabled else 65}
  assert report['controller_telemetry']['enforced_tool_adaptor'] is enabled
  assert report['controller_telemetry']['tool_adaptor_profile'] == ('enforced-v1' if enabled else 'manos-compatible-v1')
 finally:
  server.shutdown(); server.server_close(); thread.join()
