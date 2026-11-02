"""Thinking controls must reach the wire and remain auditable through CLI runs."""
import json
import sys
from unittest.mock import Mock

import pytest
from openai.types.chat import ChatCompletion
from fairy.agents.llm.base_llm import BaseLLM


def completion():
    return ChatCompletion.model_validate({
        'id':'test', 'object':'chat.completion', 'created':0, 'model':'fake',
        'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'done'}}],
    })


def expected_body(provider, value):
    if provider == 'deepseek':
        return {'thinking': {'type': 'enabled' if value else 'disabled'}}
    if provider == 'vllm':
        return {'chat_template_kwargs': {'enable_thinking':value}}
    return {'enable_thinking': value}


@pytest.mark.parametrize('provider',['deepseek','qwen'])
@pytest.mark.parametrize('value',[None, True, False, 'true', 'false'])
def test_provider_wire_override(provider,value):
    client=BaseLLM.llm_builder({'provider':provider,'model':'fake','api_key':'test-key','enable_thinking':value})
    client.api_client.chat.completions.create=Mock(return_value=completion())
    client.chat_completion([{'role':'user','content':'done'}],tools=[])
    request=client.api_client.chat.completions.create.call_args.kwargs
    normalized=None if value is None else value in (True,'true')
    assert client.to_dict()['enable_thinking'] is normalized
    if normalized is None:
        assert 'extra_body' not in request
    else:
        assert request['extra_body']==expected_body(provider,normalized)
    assert request['max_tokens']==2048


@pytest.mark.parametrize('provider',['deepseek','qwen'])
@pytest.mark.parametrize('value',['typo',1,[],{}])
def test_invalid_switch_is_rejected(provider,value):
    with pytest.raises(ValueError,match='enable_thinking'):
        BaseLLM.llm_builder({'provider':provider,'model':'fake','api_key':'test-key','enable_thinking':value})


def test_unsupported_provider_does_not_silently_ignore_switch():
    with pytest.raises(ValueError,match='enable_thinking is not supported'):
        BaseLLM.llm_builder({'provider':'openai','model':'fake','enable_thinking':False})


@pytest.mark.parametrize('provider',['deepseek','qwen','vllm'])
@pytest.mark.parametrize('value',[None,True,False])
def test_cli_to_wire_and_run_report(monkeypatch,tmp_path,provider,value):
    from fairy.cli import main
    original=BaseLLM.llm_builder
    requests=[]
    def build(cfg):
        client=original({**cfg,'api_key':'test-key'})
        def create(**kwargs):
            requests.append(kwargs)
            return completion()
        client.api_client.chat.completions.create=create
        return client
    monkeypatch.setattr(BaseLLM,'llm_builder',build)
    monkeypatch.chdir(tmp_path)
    sid='scenario_farm_world_field_prep'
    args=['fairy','-s',sid,'--agent','--provider',provider,'--model','fake',
          '--output-dir',str(tmp_path/'out'),'--max-tool-calls','1']
    if value is not None: args+=['--enable-thinking',str(value).lower()]
    monkeypatch.setattr(sys,'argv',args)
    main()
    report=json.loads((tmp_path/'out'/f'{sid}.run_report.json').read_text())
    assert report['llm_config']['enable_thinking_override'] is value
    assert requests
    if value is None: assert 'extra_body' not in requests[0]
    else: assert requests[0]['extra_body']==expected_body(provider,value)
    rows=[json.loads(x) for x in (tmp_path/'out'/f'{sid}.runtime_log.jsonl').read_text().splitlines()]
    assert next(x for x in rows if x['record_type']=='llm_call_start')['enable_thinking_override'] is value


@pytest.mark.parametrize('value',[None,True,False])
def test_runner_config_and_subprocess_flag(tmp_path,value):
    from scripts.iclr_validation_runner import _parse_args,_build_cell_command,CellSpec
    config=tmp_path/'config.json'
    config.write_text(json.dumps({'phase':'test','output_root':str(tmp_path/'out'),
        'families':'farm_baseline_react','scenarios':'scenario_farm_world_field_prep',
        'provider':'deepseek','enable_thinking':value}))
    args=_parse_args(['--config',str(config)])
    assert args.enable_thinking is value
    cell=CellSpec('farm_baseline_react','scenario_farm_world_field_prep',1)
    cmd=_build_cell_command(cell,'fake','deepseek',tmp_path,enable_thinking=args.enable_thinking)
    if value is None: assert '--enable-thinking' not in cmd
    else: assert cmd[cmd.index('--enable-thinking')+1]==str(value).lower()
    assert _parse_args(['--config',str(config),'--enable-thinking','false']).enable_thinking is False
    with pytest.raises(SystemExit):
        _parse_args(['--config',str(config),'--enable-thinking','typo'])
