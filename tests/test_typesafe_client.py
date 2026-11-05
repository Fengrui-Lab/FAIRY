"""The SDK remains the transport; the wrapper only forwards explicit options."""
import json
import pytest
typesafe_sdk = pytest.importorskip("typesafe_sdk")
httpx2 = pytest.importorskip("httpx2")
from typesafe_sdk.constants import DEFAULT_TIMEOUT,DEFAULT_BASE_URL
from fairy.agents.llm.typesafe_client import TypeSafeJevClient
from fairy.contracts.cli import probe

Q={'probe':{'type':'choice','instructions':'Choose a','criteria':{'a':'a','b':'b'}}}

@pytest.fixture
def sdk(monkeypatch):
    seen=[];options=[];mode={'status':200,'probabilities':{'a':.8,'b':.199}}
    real=typesafe_sdk.TypeSafeClient
    def handler(req):
        seen.append(req)
        if mode['status']!=200:
            return httpx2.Response(mode['status'],headers={'x-typesafe-request-id':'test'},json={'detail':'test error'})
        body=json.loads(req.content)
        return httpx2.Response(200,headers={'x-typesafe-request-id':'test'},json={'model':body['model'],
            'answers':{k:{'type':'choice','choice':'a','confidence':.3,'probabilities':mode['probabilities']} for k in body['questions']},
            'usage':{'input_tokens':10,'output_tokens':1}})
    def factory(**kwargs):
        options.append(kwargs.copy());return real(**kwargs,transport=httpx2.MockTransport(handler))
    monkeypatch.setattr(typesafe_sdk,'TypeSafeClient',factory)
    monkeypatch.setenv('TYPESAFE_API_KEY','test-only-key')
    monkeypatch.delenv('FAIRY_LLM_REQUEST_TIMEOUT_S',raising=False)
    monkeypatch.delenv('TYPESAFE_BASE_URL',raising=False)
    return seen,options,mode


def test_defaults_are_not_overridden(sdk):
    seen,options,_=sdk
    c=TypeSafeJevClient('jev-1.14.0',0)
    try:
        assert options==[{'model':'jev-1.14.0'}]
        assert c.request_timeout==DEFAULT_TIMEOUT and c.sdk_max_retries==typesafe_sdk.RetryPolicy().max_retries
        assert c.base_url==DEFAULT_BASE_URL
    finally:c.close()


@pytest.mark.parametrize('probabilities',[{'a':.8,'b':.199},{'a':.8,'b':.201}])
def test_explicit_options_and_raw_probabilities(sdk,probabilities):
    seen,options,mode=sdk;mode['probabilities']=probabilities
    c=TypeSafeJevClient('jev-1.14.0',.1,timeout=60,max_retries=0,base_url='http://local.test',api_key_env='TYPESAFE_API_KEY')
    try:
        result=c.system_one({},Q)
        assert result.choices['probe'].probabilities==probabilities
        assert result.choices['probe'].confidence==.3
        assert len(seen)==1 and str(seen[0].url)=='http://local.test/v1/systemone'
        assert seen[0].headers['authorization']=='Bearer test-only-key'
        assert seen[0].extensions['timeout']['read']==60
        assert options[0]['retry'].max_retries==0
        assert set(json.loads(seen[0].content))=={'model','state','questions'}
    finally:c.close()


def test_positive_retry_count_is_supported(sdk):
    _,options,_=sdk;c=TypeSafeJevClient('jev-1.14.0',0,max_retries=3)
    try:assert options[0]['retry'].max_retries==3 and c.sdk_max_retries==3
    finally:c.close()


def test_existing_timeout_environment(sdk,monkeypatch):
    _,options,_=sdk;monkeypatch.setenv('FAIRY_LLM_REQUEST_TIMEOUT_S','37')
    c=TypeSafeJevClient('jev-1.14.0',0)
    try:assert options[0]['timeout']==37
    finally:c.close()


@pytest.mark.parametrize('status',[429,500])
def test_explicit_zero_sdk_retry(sdk,status):
    seen,_,mode=sdk;mode['status']=status
    c=TypeSafeJevClient('jev-1.14.0',0,max_retries=0)
    try:
        with pytest.raises(Exception):c.system_one({},Q)
        assert len(seen)==1
    finally:c.close()


@pytest.mark.parametrize('retry',[-1,True,1.5])
def test_invalid_retry(sdk,retry):
    with pytest.raises(ValueError):TypeSafeJevClient('test',0,max_retries=retry)


def test_service_probe_reports_effective_settings(sdk):
    result=probe({'provider':'typesafe','model_id':'jev-1.14.0','timeout':37,'endpoint':'http://local.test'})
    assert result['status']=='passed' and result['returned_model']=='jev-1.14.0'
    assert result['timeout_seconds']==37 and result['max_retries']==0
    assert result['usage']['total_tokens']==11 and result['endpoint']=='http://local.test'
    assert 'test-only-key' not in json.dumps(result)
    assert len(sdk[0])==1


def test_custom_endpoint_does_not_inherit_cloud_key(sdk):
    seen, options, _ = sdk
    c = TypeSafeJevClient('vllm-sr/d3', 0, base_url='http://local.test', max_retries=0)
    try:
        c.system_one('中文 English', Q)
        assert seen[0].headers['authorization'] == 'Bearer local-no-auth'
        assert json.loads(seen[0].content)['state'] == '中文 English'
    finally:
        c.close()


def test_explicit_credential_env_is_required(sdk, monkeypatch):
    monkeypatch.delenv('D3_TEST_KEY', raising=False)
    with pytest.raises(ValueError, match='Missing service credential'):
        TypeSafeJevClient('vllm-sr/d3', 0, base_url='http://local.test', api_key_env='D3_TEST_KEY')


def test_singletons_and_multiple_questions_use_sdk_unchanged(monkeypatch):
    requests=[]
    real=typesafe_sdk.TypeSafeClient
    def handler(request):
        payload=json.loads(request.content); requests.append(payload)
        return httpx2.Response(200,json={'model':payload['model'],'usage':{'input_tokens':3,'output_tokens':0},
            'answers':{k:{'type':'choice','choice':next(iter(q['criteria'])),
                'confidence':1.,'probabilities':{o:float(i==0) for i,o in enumerate(q['criteria'])}}
                for k,q in payload['questions'].items()}})
    monkeypatch.setattr(typesafe_sdk,'TypeSafeClient',lambda **kw:real(**kw,transport=httpx2.MockTransport(handler)))
    questions={**Q,'singleton':{'type':'choice','instructions':'唯一选项','criteria':{'only':'only'}}}
    for model in ['vllm-sr/d3','jev-1.14.0']:
        c=TypeSafeJevClient(model,0,base_url='http://local.test',max_retries=0)
        try:
            r=c.system_one('中文 English',questions)
            assert not r.choices['singleton'].deterministic
            assert r.usage.output_tokens==0 and r.usage.cached_tokens is None
        finally:c.close()
    assert len(requests)==2
    assert requests[0]['questions']==requests[1]['questions']==questions
    assert requests[0]['state']==requests[1]['state']=='中文 English'
