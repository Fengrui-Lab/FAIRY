import json
from test_llm_driven_jev import _run, _events, ASK


def test_argument_and_service_errors_keep_distinct_metadata():
    agent,_,_,jev = _run([None])
    agent._ask_jev('arguments', '{}')
    assert _events(agent,'ask_jev_error')[-1]['failure_scope']=='arguments'
    class Unavailable(Exception):
        status_code=503
    def fail(*args, **kwargs):
        raise Unavailable('backend unavailable')
    jev.system_one=fail
    agent._ask_jev('service',json.dumps(ASK))
    event=_events(agent,'ask_jev_error')[-1]
    assert event['failure_scope']=='service'
    assert event['status_code']==503 and event['error_type']=='Unavailable'
    assert event['source']=='decision'
