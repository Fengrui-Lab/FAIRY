"""One physical request through FAIRY's actual clients, never farm actions."""
import math
import time
from dataclasses import asdict

import httpx
import jsonschema

from fairy.agents.llm.base_llm import BaseLLM
from fairy.agents.llm.system_one_client import SystemOneCompatibleClient, api_key_from_env


def probe_request(job):
    service = job['service']
    timeout = job['timeout_seconds']
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Explicit positive timeout_seconds required')
    provider = service['provider']
    result = dict(status='failed', contract_ok=False, http_request_count=0,
                  provider=provider, requested_model=service['model_id'], returned_model=None,
                  tools_executed=0, usage=None, timeout_seconds=timeout)
    started = time.perf_counter()
    client = None
    transport = None
    try:
        if provider == 'typesafe':
            from fairy.agents.llm.typesafe_client import TypeSafeJevClient
            client = TypeSafeJevClient(service['model_id'], 0.0, base_url=service.get('endpoint'),
                api_key_env=service.get('api_key_env'), timeout=timeout, max_retries=0)
            result['http_request_count'] = 1
            response = client.system_one(job['state'], job['questions'])
            result.update(response=asdict(response), usage=response.usage.tokens(),
                          returned_model=response.model, max_retries=client.sdk_max_retries)
        elif provider == 'system-one-compatible':
            # No question limit: exactly one batch (or zero for local singletons).
            client = SystemOneCompatibleClient(service['model_id'], base_url=service['endpoint'],
                api_key_env=service.get('api_key_env'), timeout=timeout)
            result['http_request_count'] = int(any(len(q['criteria']) > 1 for q in job['questions'].values()))
            response = client.system_one(job['state'], job['questions'])
            result.update(response=asdict(response), usage=response.usage.tokens(),
                          returned_model=response.model, http_request_count=len(response.batches))
        elif provider in ('vllm', 'openai-compatible', 'deepseek'):
            transport = httpx.Client(timeout=timeout, follow_redirects=False)
            config = {k: service[k] for k in ('temperature', 'max_output_tokens', 'enable_thinking',
                      'output_token_parameter', 'send_temperature', 'reasoning_effort') if k in service}
            config.update(provider=provider, model=service['model_id'], base_url=service['endpoint'],
                          api_key=api_key_from_env(service.get('api_key_env')) or 'EMPTY',
                          timeout=timeout, max_retries=0, parallel_tool_calls=False, http_client=transport)
            client = BaseLLM.llm_builder(config)
            result['http_request_count'] = 1
            response = client.chat_completion(job['messages'], tools=job.get('tools'))
            raw = response.model_dump(mode='json')
            result.update(response=raw, usage=raw.get('usage'), returned_model=raw.get('model'))
            choices = raw.get('choices') or []
            if len(choices) != 1:
                raise ValueError('Expected exactly one choice')
            if job.get('tools'):
                calls = choices[0]['message'].get('tool_calls') or []
                if len(calls) != 1:
                    raise ValueError('Expected exactly one tool call')
                functions = {t['function']['name']: t['function'] for t in job['tools']}
                function = calls[0]['function']
                import json
                arguments = json.loads(function['arguments'])
                jsonschema.validate(arguments, functions[function['name']]['parameters'])
        else:
            raise ValueError('Unsupported probe provider')
        if result['http_request_count'] and result['returned_model'] != service['model_id']:
            raise ValueError('Returned model differs from configured model')
        result.update(status='passed', contract_ok=True)
    except Exception as exc:
        status = getattr(exc, 'status_code', None)
        name = type(exc).__name__
        message = str(exc).lower()
        category = ('timeout' if 'timeout' in name.lower() or 'timed out' in message
                    else 'authentication' if status in (401, 403)
                    else 'transport' if isinstance(exc, httpx.TransportError) or 'connection' in name.lower()
                    else 'protocol')
        result.update(error_category=category, error_type=name, status_code=status)
    finally:
        if client:
            client.api_client.close() if provider in ('vllm', 'openai-compatible', 'deepseek') else client.close()
        if transport:
            transport.close()
    result['request_seconds'] = time.perf_counter() - started
    return result
