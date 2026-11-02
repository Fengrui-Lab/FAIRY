from argparse import Namespace
from types import SimpleNamespace
from fairy.contracts import service_probe


def test_deepseek_probe_omits_compatible_only_options(monkeypatch):
    captured=[]
    response=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[SimpleNamespace(function=SimpleNamespace(name='report_number',arguments='{"value":7}'))]))],usage=None,model='deepseek-flash')
    client=SimpleNamespace(chat_completion=lambda *a,**k:response,api_client=SimpleNamespace(close=lambda:None))
    def builder(config):
        captured.append(config)
        assert 'send_temperature' not in config and 'output_token_parameter' not in config
        return client
    monkeypatch.setattr(service_probe.BaseLLM,'llm_builder',builder)
    args=Namespace(chat_provider='deepseek',model='deepseek-flash',endpoint='https://api.deepseek.com/v1',api_key_env=None,timeout=60,max_output_tokens=2048,enable_thinking=False,output_token_parameter='max_tokens',send_temperature=True,reasoning_effort=None)
    assert service_probe.check_chat(args)['contract_ok']
