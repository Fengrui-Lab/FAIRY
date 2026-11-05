import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from fairy.contracts.request_probe import probe_request


@pytest.fixture
def server():
    records=[];reply={'status':200,'body':{}}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            records.append({'path':self.path,'payload':json.loads(self.rfile.read(int(self.headers['Content-Length']))),'authorization':self.headers.get('Authorization')})
            self.send_response(reply['status']);self.send_header('Content-Type','application/json')
            if reply['status']==307:self.send_header('Location','/redirected')
            self.end_headers();self.wfile.write(json.dumps(reply['body']).encode())
        def log_message(self,*args):pass
    http=ThreadingHTTPServer(('127.0.0.1',0),Handler);t=threading.Thread(target=http.serve_forever,daemon=True);t.start()
    yield f'http://127.0.0.1:{http.server_port}/v1',records,reply
    http.shutdown();http.server_close();t.join()


def decision_job(url):
    return {'service':{'provider':'system-one-compatible','model_id':'test','endpoint':url},'timeout_seconds':2,
        'state':{'a':1},'questions':{'q':{'type':'choice','criteria':{'a':'a','b':'b'}}}}


def test_decision_single_request(server):
    url,records,reply=server
    reply['body']={'model':'test','answers':{'q':{'choice':'a','probabilities':{'a':.8,'b':.2},'confidence':.8}},'usage':{'input_tokens':5,'output_tokens':0}}
    result=probe_request(decision_job(url))
    assert result['status']=='passed' and result['http_request_count']==1 and result['tools_executed']==0
    assert len(records)==1 and records[0]['path']=='/v1/systemone'


@pytest.mark.parametrize('status',[401,500,307])
def test_no_retry_no_redirect(server,status):
    url,records,reply=server;reply['status']=status
    result=probe_request(decision_job(url))
    assert result['status']=='failed' and len(records)==1


def test_chat_parameters_single_request_and_validation(server,monkeypatch):
    url,records,reply=server;monkeypatch.setenv('TEST_PROBE_KEY','secret-token')
    reply['body']={'id':'chat','object':'chat.completion','created':0,'model':'test','choices':[{'index':0,'message':{'role':'assistant','content':None,'tool_calls':[{'id':'call','type':'function','function':{'name':'report','arguments':'{"value":7}'}}]},'finish_reason':'tool_calls'}],'usage':{'prompt_tokens':5,'completion_tokens':3,'total_tokens':8}}
    job={'service':{'provider':'vllm','model_id':'test','endpoint':url,'api_key_env':'TEST_PROBE_KEY','temperature':.1,'max_output_tokens':4096,'enable_thinking':False},'timeout_seconds':2,'messages':[{'role':'user','content':'report 7'}],
      'tools':[{'type':'function','function':{'name':'report','parameters':{'type':'object','properties':{'value':{'type':'integer'}},'required':['value']}}}]}
    r=probe_request(job);assert r['status']=='passed'
    assert records[0]['payload']['max_tokens']==4096
    assert records[0]['payload']['temperature']==.1
    assert records[0]['payload']['chat_template_kwargs']['enable_thinking'] is False
    assert records[0]['authorization']=='Bearer secret-token'
    reply['status']=307;probe_request(job);assert len(records)==2
    reply['status']=200;reply['body']['choices'][0]['message']['tool_calls']*=2
    assert probe_request(job)['error_category']=='protocol'


def test_requires_explicit_timeout(server):
    job=decision_job(server[0]);job['timeout_seconds']=float('inf')
    with pytest.raises(ValueError):probe_request(job)
    assert not server[1]
