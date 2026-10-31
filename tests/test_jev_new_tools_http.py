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
def test_real_cli_new_scene_routes(tmp_path,scenario,hybrid):
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
     answers[qid]={'choice':pick,'confidence':.1 if hybrid else .9,'probabilities':{n:float(n==pick) for n in opts}}
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
 argv=[str(root/'.venv/bin/fairy-cli'),'--scenario',scenario,'--agent','--controller','farm_jev','--provider','system-one-compatible','--model','offline-decision','--endpoint',endpoint,'--max-tool-calls','1','--timeout-seconds','60','--output-dir',str(tmp_path),'--task-id','offline-new-tools','--scenario-kwargs',json.dumps({'seed':0,'detailed_briefing':True}),'--request-max-retries','0']
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
