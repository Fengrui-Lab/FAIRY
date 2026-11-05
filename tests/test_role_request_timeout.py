from types import SimpleNamespace
import pytest
from fairy.cli import _role_timeout, _fallback_config
from fairy.agents.llm.base_llm import BaseLLM

def test_distinct_request_timeout_in_real_clients(monkeypatch):
 monkeypatch.setenv('FAIRY_LLM_REQUEST_TIMEOUT_S','180')
 monkeypatch.setenv('FAIRY_DECISION_REQUEST_TIMEOUT_S','60')
 monkeypatch.setenv('TYPESAFE_API_KEY','fixture-key')
 chat=BaseLLM.llm_builder(dict(provider='vllm',model='fixture',base_url='http://127.0.0.1:1/v1',api_key='fixture',**_role_timeout('vllm')))
 jev=BaseLLM.llm_builder(dict(provider='typesafe',model='vllm-sr/d3',base_url='http://127.0.0.1:1',**_role_timeout('typesafe')))
 try:
  assert chat.request_timeout==180 and chat.api_client.timeout==180
  assert jev.request_timeout==60
 finally:chat.api_client.close();jev.close()

@pytest.mark.parametrize('value',['0','-1','nan','inf'])
def test_invalid_role_timeout(monkeypatch,value):
 monkeypatch.setenv('FAIRY_DECISION_REQUEST_TIMEOUT_S',value)
 with pytest.raises(ValueError):_role_timeout('typesafe')
