from types import SimpleNamespace as NS
from unittest.mock import patch
import pytest
from openai.types.chat import ChatCompletion
from fairy.agents.agent.base_agent import BaseAgent
from fairy.agents.llm.deepseek_client import DeepSeekClient

@pytest.mark.parametrize('enabled,expected',[(True,'enabled'),(False,'disabled'),(None,None)])
def test_deepseek_request(enabled,expected):
    with patch('fairy.agents.llm.deepseek_client.OpenAI') as factory:
        client=DeepSeekClient('test',api_key='test',enable_thinking=enabled,timeout=60,max_retries=0)
        client.chat_completion([{'role':'user','content':'test'}])
        request=factory.return_value.chat.completions.create.call_args.kwargs
        assert factory.call_args.kwargs['max_retries']==0
        assert factory.call_args.kwargs['timeout']==60
        assert request.get('extra_body')==({'thinking':{'type':expected}} if expected else None)

@pytest.mark.parametrize('provider,enabled,keep',[('deepseek',True,True),('deepseek',False,False),('vllm',True,False)])
def test_history_and_sidecar(provider,enabled,keep):
    llm=NS(provider=provider,enable_thinking=enabled,parallel_tool_calls=False,model='test')
    agent=BaseAgent('test',llm)
    history=agent._llm_compatible_messages([{'role':'assistant','content':'answer','reasoning_content':'private thought','time':123}])
    assert ('reasoning_content' in history[0])==keep
    response=ChatCompletion.model_validate({'id':'request-1','object':'chat.completion','created':0,'model':'test','choices':[{'index':0,'message':{'role':'assistant','content':None,'reasoning_content':'partial thought'},'finish_reason':'length'}],'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30,'completion_tokens_details':{'reasoning_tokens':20}}})
    agent._record_llm_response(response,response.choices[0].message,.1,'output_truncated')
    record=agent.reasoning_events[0]
    assert record['event_index']==agent.runtime_events[-1]['event_index']
    assert record['response_id']=='request-1' and record['accepted'] is False
    assert record['reasoning_content']=='partial thought'
    assert record['completion_tokens']==20 and record['reasoning_tokens']==20
    assert 'reasoning_content' not in agent.runtime_events[-1]
    response.usage.completion_tokens_details=None
    agent._record_llm_response(response,response.choices[0].message,.1,None)
    assert agent.reasoning_events[-1]['reasoning_tokens'] is None


def test_sidecar_live_redaction(tmp_path,monkeypatch):
    import json
    from fairy.cli import _append_live_progress
    monkeypatch.setenv('FAIRY_REDACT_ENV_NAMES','["TEST_THINKING_SECRET"]')
    monkeypatch.setenv('TEST_THINKING_SECRET','secret-value-123')
    path=tmp_path/'reasoning.jsonl'
    _append_live_progress(path,{'event_index':4,'event_type':'llm_reasoning','reasoning':'secret-value-123','reasoning_tokens':None})
    row=json.loads(path.read_text())
    assert row['record_index']==4 and row['reasoning']=='[REDACTED]' and row['reasoning_tokens'] is None
