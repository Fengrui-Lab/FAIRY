"""Real CLI/SDK transport, loopback only; never contacts model services."""
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest

@pytest.mark.parametrize('model',['vllm-sr/d3','jev-1.14.0'])
@pytest.mark.parametrize('mode',['reflex','consult','note','noask'])
def test_hybrid_sdk_cli(tmp_path,model,mode):
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            seen.append((self.path,self.headers.get('Authorization'),body))
            if self.path=='/v1/systemone':
                answers={}
                for qid,q in body['questions'].items():
                    opts=list(q['criteria']);pick='WeatherApp__get_forecast' if qid=='next_action' else opts[0]
                    answers[qid]={'type':'choice','choice':pick,'confidence':.1,'probabilities':{o:float(o==pick) for o in opts}}
                result={'model':model,'answers':answers,'usage':{'input_tokens':10,'output_tokens':0}}
            else:
                chat_calls=sum(p=='/v1/chat/completions' for p,_,_ in seen)
                if mode in ('consult','note') and chat_calls==1:
                    name='ask_jev';args={'state':{'known':'user provided'},'question':'Choose','options':['a','b']}
                else:
                    name='WeatherApp__get_forecast';args={'days':3}
                if mode=='reflex':
                    assert [t['function']['name'] for t in body['tools']]==[name]
                result={'id':'fixture','object':'chat.completion','model':'offline-qwen','choices':[{'index':0,'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':f'c{chat_calls}','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}],'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}}
            data=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    root=Path(__file__).resolve().parents[1];url=f'http://127.0.0.1:{server.server_port}'
    argv=[str(root/'.venv/bin/fairy-cli'),'--scenario','scenario_farm_world_field_prep','--agent','--max-tool-calls','1','--timeout-seconds','30','--output-dir',str(tmp_path),'--task-id','hybrid-sdk-test','--request-max-retries','0','--parallel-tool-calls','false']
    if mode=='reflex':
        argv+=['--controller','farm_jev','--hybrid-mode','reflex','--provider','typesafe','--model',model,'--endpoint',url,'--decision-api-key-env','JEV_TEST_KEY','--fallback-provider','openai-compatible','--fallback-model','offline-qwen','--fallback-endpoint',url+'/v1','--fallback-api-key-env','CHAT_TEST_KEY','--fallback-confidence','.4']
    else:
        argv+=['--controller','farm_llm_jev','--provider','openai-compatible','--model','offline-qwen','--endpoint',url+'/v1','--api-key-env','CHAT_TEST_KEY','--jev-model',model,'--jev-endpoint',url,'--jev-api-key-env','JEV_TEST_KEY','--jev-prompt-note',str(mode=='note').lower()]
    env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ('API_KEY','TOKEN','PROXY'))}
    env.update(JEV_TEST_KEY='jev-fixture',CHAT_TEST_KEY='chat-fixture',FAIRY_AGENT_LLM_CALL_RETRIES='0',FAIRY_LLM_REQUEST_TIMEOUT_S='60')
    try:
        run=subprocess.run(argv,cwd=tmp_path,env=env,capture_output=True,text=True,timeout=60)
        assert run.returncode==0,(run.stdout+run.stderr)[-4000:]
        report=json.loads(next(tmp_path.glob('*.run_report.json')).read_text());t=report['controller_telemetry']
        assert report['metrics']['tool_call_count']==1
        assert sum(p=='/v1/systemone' for p,_,_ in seen)==(0 if mode=='noask' else 1)
        for path,auth,body in seen:
            assert auth=='Bearer '+('jev-fixture' if path=='/v1/systemone' else 'chat-fixture')
            assert body['model']==(model if path=='/v1/systemone' else 'offline-qwen')
        if mode=='reflex': assert t['llm_argument_fills']==1 and t['llm_decisions']==0
        else:
            assert t['ask_jev_calls']==(0 if mode=='noask' else 1)
            assert t['jev_config']['request_timeout']==60 and t['jev_config']['sdk_max_retries']==0
            assert t['jev_prompt_note']==(mode=='note')
            if model=='vllm-sr/d3': assert t['jev_cost_usd'] is None
    finally:
        server.shutdown();server.server_close();thread.join()
