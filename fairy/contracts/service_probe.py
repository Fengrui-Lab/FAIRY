#!/usr/bin/env python3
"""Explicit, tiny service contract probes. Never deploys models or runs FAIRY tasks.

Run after installing the project: python scripts/check_model_service.py --help
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from fairy.agents.llm.base_llm import BaseLLM, _coerce_optional_bool
from fairy.agents.llm.system_one_client import SystemOneCompatibleClient, api_key_from_env, api_root


def check_decision(args: argparse.Namespace) -> dict:
    criteria = {f"option_{i}": f"Label number {i}" for i in range(args.option_count)}
    questions = {
        f"probe_{i}": {"type": "choice", "instructions": "Choose the label named in the state.", "criteria": criteria}
        for i in range(args.question_count)
    }
    questions["singleton"] = {"type": "choice", "instructions": "Only one answer is allowed.", "criteria": {"only": None}}
    client = SystemOneCompatibleClient(
        args.model, base_url=args.endpoint, api_key_env=args.api_key_env,
        max_questions_per_request=args.max_questions_per_request, timeout=args.timeout,
    )
    try:
        result = client.system_one({"label": "option_0"}, questions)
    finally:
        client.close()
    return {
        "contract_ok": True,
        "semantic_match": all(a.choice == "option_0" for k, a in result.choices.items() if k != "singleton"),
        "provider": client.provider, "requested_model": args.model, "returned_model": result.model,
        "question_count": args.question_count, "option_count": args.option_count,
        "http_request_count": len(result.batches),
        "singleton_handled_locally": result.choices["singleton"].deterministic,
        "provider_confidence_available": all(a.confidence is not None for a in result.choices.values()),
        "usage": result.usage.tokens(),
        "batches": [{"question_ids": b.question_ids, "model": b.model, "request_id": b.request_id,
                     "latency_seconds": b.wall_time_seconds, "usage": b.usage.tokens()} for b in result.batches],
    }


def check_chat(args: argparse.Namespace) -> dict:
    config = {"provider": args.chat_provider, "model": args.model, "base_url": api_root(args.endpoint),
              "temperature": getattr(args,"temperature",0.0), "parallel_tool_calls": False,
              "max_output_tokens": args.max_output_tokens, "timeout": args.timeout}
    if args.api_key_env:
        config["api_key"] = api_key_from_env(args.api_key_env)
    if args.enable_thinking is not None:
        config["enable_thinking"] = args.enable_thinking
    for key in ("output_token_parameter", "send_temperature", "reasoning_effort"):
        value = getattr(args, key, None)
        if key in {"output_token_parameter", "send_temperature"} and args.chat_provider not in {"vllm", "openai-compatible", "llama-api"}:
            continue
        if value is not None: config[key] = value
    config["max_retries"] = 0
    if not args.api_key_env: config["api_key"] = "EMPTY"
    client = BaseLLM.llm_builder(config)
    tools = [{"type": "function", "function": {
        "name": "report_number", "description": "Report the requested number.",
        "parameters": {"type": "object", "properties": {"value": {"type": "integer"}},
                       "required": ["value"], "additionalProperties": False},
    }}]
    try:
        response = client.chat_completion(
            [{"role": "user", "content": "Call report_number exactly once with value 7. Do not answer with text."}], tools=tools
        )
    finally:
        client.api_client.close()
    choices = response.choices or []
    calls = list(choices[0].message.tool_calls or []) if choices else []
    if len(calls) != 1 or calls[0].function.name != "report_number":
        raise ValueError("expected exactly one report_number tool call")
    arguments = json.loads(calls[0].function.arguments)
    if arguments != {"value": 7} or isinstance(arguments["value"], bool):
        raise ValueError("unexpected tool arguments")
    usage = getattr(response, "usage", None)
    return {
        "contract_ok": True, "semantic_match": True, "provider": args.chat_provider,
        "requested_model": args.model, "returned_model": getattr(response, "model", None),
        "tool_calls": 1, "tools_executed": 0, "enable_thinking": args.enable_thinking,
        "max_output_tokens": args.max_output_tokens,
        "usage": {"prompt_tokens": getattr(usage, "prompt_tokens", None),
                  "completion_tokens": getattr(usage, "completion_tokens", None)},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["decision", "chat"], required=True)
    parser.add_argument("--endpoint", required=True, help="API root ending in /v1; no default remote endpoint")
    parser.add_argument("--model", required=True, help="Actual served model ID")
    parser.add_argument("--api-key-env", default=None)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--max-questions-per-request", type=int, default=None)
    parser.add_argument("--question-count", type=int, default=2)
    parser.add_argument("--option-count", type=int, default=2)
    parser.add_argument("--chat-provider", choices=["vllm", "openai-compatible", "deepseek"], default="vllm")
    parser.add_argument("--max-output-tokens", type=int, default=1024)
    parser.add_argument("--enable-thinking", type=_coerce_optional_bool_arg, default=None)
    args = parser.parse_args(argv)
    if args.question_count < 1 or not 2 <= args.option_count <= 255 or args.timeout <= 0:
        parser.error("positive question count/timeout and 2–255 options are required")
    started = time.perf_counter()
    try:
        result = check_decision(args) if args.kind == "decision" else check_chat(args)
        result["status"] = "passed" if result["semantic_match"] else "semantic_probe_failed"
        result["elapsed_seconds"] = round(time.perf_counter() - started, 6)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["semantic_match"] else 1
    except Exception as exc:
        # Upstream SDK exceptions may contain URLs, bodies or secrets: never print them.
        print(json.dumps({"status": "failed", "contract_ok": False, "error_type": type(exc).__name__,
                          "status_code": getattr(exc, "status_code", None),
                          "message": "Check the endpoint, service configuration and server logs; upstream details omitted."}))
        return 1


def _coerce_optional_bool_arg(value: str) -> bool:
    try:
        return _coerce_optional_bool(value, "enable_thinking")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


if __name__ == "__main__":
    sys.exit(main())
