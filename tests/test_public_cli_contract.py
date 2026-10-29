import json
from types import SimpleNamespace

import pytest
from fairy.agents.llm.base_llm import BaseLLM
from fairy.contracts.cli import capabilities, probe


@pytest.mark.parametrize('provider',['vllm','openai-compatible'])
def test_compatible_parameter_policy(provider,monkeypatch):
    module=__import__('fairy.agents.llm.'+('vllm_client' if provider=='vllm' else 'openai_compatible_client'),fromlist=['OpenAI'])
    calls=[]
    api=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw:calls.append(kw))))
    monkeypatch.setattr(module,'OpenAI',lambda **kw:api)
    client=BaseLLM.llm_builder(dict(provider=provider,model='actual-model',api_key='fixture',
        base_url='http://localhost:1/v1',output_token_parameter='max_completion_tokens',
        send_temperature=False,reasoning_effort='high',max_output_tokens=123,enable_thinking=False))
    client.chat_completion([],tools=[])
    assert client.provider==provider
    request=calls[0]
    assert request['model']=='actual-model' and request['max_completion_tokens']==123
    assert 'max_tokens' not in request and 'temperature' not in request
    assert request['reasoning_effort']=='high'
    assert request['extra_body']['chat_template_kwargs']['enable_thinking'] is False


def test_unsupported_options_rejected():
    with pytest.raises(ValueError,match='compatible'):
        BaseLLM.llm_builder({'provider':'typesafe','model':'unused','send_temperature':False})
    with pytest.raises(ValueError,match='token'):
        BaseLLM.llm_builder({'provider':'vllm','output_token_parameter':'invented'})


def test_capabilities_without_model_clients(monkeypatch):
    monkeypatch.setattr(BaseLLM,'llm_builder',lambda *_:pytest.fail('No model client during discovery'))
    result=capabilities()
    assert result['contract_version']==1
    assert 'farm_llm_snapshot' in result['controllers'] and 'farm_qwen_snapshot' in result['controllers']
    assert result['identity']['dependencies']['httpx']


def test_typesafe_probe_custom_environment(monkeypatch):
    import sys
    calls=[]
    class Client:
        def __init__(self,**kwargs):
            import os
            calls.append((kwargs,os.environ['TYPESAFE_API_KEY']))
        def system_one(self,**kwargs):
            return {'model':'actual-returned','choices':{'probe':{'choice':'a','probabilities':{'a':.9,'b':.1},'confidence':.9}}}
    monkeypatch.setitem(sys.modules,'typesafe_sdk',SimpleNamespace(TypeSafeClient=Client))
    monkeypatch.setenv('CUSTOM_TYPESAFE','fixture-key')
    result=probe({'provider':'typesafe','model_id':'served','api_key_env':'CUSTOM_TYPESAFE'})
    assert result['status']=='passed'
    assert calls[0][1]=='fixture-key'


def test_native_scenario_description_never_runs_model_or_oracle(monkeypatch):
    from fairy.contracts.cli import describe_scenario
    from fairy.controllers.engine import Engine
    monkeypatch.setattr(BaseLLM,'llm_builder',lambda *_:pytest.fail('model call'))
    monkeypatch.setattr(Engine,'run_scenario_oracle',lambda *_args,**_kwargs:pytest.fail('oracle execution'))
    sid='scenario_l1_hb_wetcold_high_residue_planting_execution'
    d=describe_scenario({'scenario_id':sid,'seed':0,'kwargs':{'detailed_briefing':True}})
    assert d['task'] and d['task_source']=='event_briefing'
    assert d['validation_hook_available']
    assert d['checkpoint_label']
    assert any(k.endswith('.json') for k in d['identity']['files'])


def test_fingerprint_tracks_checkpoint_data(tmp_path,monkeypatch):
    import fairy.contracts.cli as cli
    package=tmp_path/'fairy';(package/'contracts').mkdir(parents=True)
    (package/'scenarios').mkdir()
    checkpoint=package/'scenarios'/'state.json';checkpoint.write_text('{"state":1}')
    monkeypatch.setattr(cli,'__file__',str(package/'contracts'/'cli.py'))
    first=cli.fingerprint()['source_hash']
    checkpoint.write_text('{"state":2}')
    assert cli.fingerprint()['source_hash']!=first
