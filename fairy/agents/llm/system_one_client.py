"""HTTP System One adapter. No TypeSafe SDK or model runtime is required."""
from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from .base_llm import BaseLLM
from .decision_response import (
    DecisionAnswer, DecisionBatch, DecisionProtocolError, DecisionResponse, DecisionUsage,
    aggregate_usage, normalize_response, validate_questions,
)


def api_root(endpoint: str) -> str:
    """Only accept an explicit, credential-free API root ending in /v1."""
    url = urlsplit(endpoint)
    if (url.scheme not in ("http", "https") or not url.hostname or url.username
            or url.password or url.query or url.fragment
            or not url.path.rstrip("/").endswith("/v1")):
        raise ValueError("endpoint must be an HTTP(S) API root ending in /v1, without credentials/query/fragment")
    return endpoint.rstrip("/")


def api_key_from_env(name: str | None) -> str | None:
    if name is None:
        return None
    key = os.getenv(name)
    if not key:
        raise ValueError("configured API key environment variable is unset or empty")
    return key


class DecisionServiceError(RuntimeError):
    """A sanitized service error (no URL, headers or response body)."""

    def __init__(self, message: str, *, status_code: int | None = None,
                 completed_batches: list[DecisionBatch] | None = None,
                 failed_batch: DecisionBatch | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.completed_batches = completed_batches or []
        self.failed_batch = failed_batch


class SystemOneCompatibleClient(BaseLLM):
    llm_class = "SystemOneCompatibleClient"

    def __init__(self, model, temperature=0.1, api_key=None, **kwargs):
        super().__init__(model, temperature, **kwargs)
        self.provider = "system-one-compatible"
        self.base_url = api_root(kwargs.get("base_url") or "")
        self.max_questions = kwargs.get("max_questions_per_request")
        if self.max_questions is not None and (
            isinstance(self.max_questions, bool) or not isinstance(self.max_questions, int) or self.max_questions < 1
        ):
            raise ValueError("max_questions_per_request must be a positive integer")
        self.api_key_env = kwargs.get("api_key_env")
        key = api_key if api_key is not None else api_key_from_env(self.api_key_env)
        if self.request_timeout is None:
            self.request_timeout = 60.0
        self._client = httpx.Client(
            timeout=self.request_timeout,
            headers={"Authorization": f"Bearer {key}"} if key else {},
            follow_redirects=False,
            transport=kwargs.get("transport"),  # injection point for offline contract tests
        )

    def close(self) -> None:
        self._client.close()

    def system_one(self, state: Any, questions: dict[str, Any]) -> DecisionResponse:
        validate_questions(questions)
        # All providers can consume text; JSON state is rendered losslessly, never shortened.
        rendered = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, allow_nan=False, default=str)
        answers: dict[str, DecisionAnswer] = {}
        pending = []
        for qid, question in questions.items():
            if len(question["criteria"]) == 1:
                option = next(iter(question["criteria"]))
                answers[qid] = DecisionAnswer(option, {option: 1.0}, 1.0, deterministic=True)
            else:
                pending.append((qid, question))
        batches: list[DecisionBatch] = []
        limit = self.max_questions or max(1, len(pending))
        for start in range(0, len(pending), limit):
            subset = dict(pending[start:start + limit])
            started = time.perf_counter()
            def failure(message: str, status_code: int | None = None) -> DecisionServiceError:
                return DecisionServiceError(
                    message, status_code=status_code, completed_batches=list(batches),
                    failed_batch=DecisionBatch(
                        list(subset), DecisionUsage(), wall_time_seconds=round(time.perf_counter() - started, 6),
                        status="error",
                    ),
                )
            try:
                response = self._client.post(
                    self.base_url + "/systemone",
                    json={"model": self.model, "state": rendered, "questions": subset},
                )
            except httpx.TimeoutException:
                raise failure("System One request timed out") from None
            except httpx.HTTPError:
                raise failure("System One transport error") from None
            if response.status_code != 200:
                raise failure(
                    f"System One returned HTTP {response.status_code}; check service limits and configuration",
                    status_code=response.status_code,
                ) from None
            try:
                result = normalize_response(response.json(), subset)
            except DecisionProtocolError as exc:
                raise failure(f"System One protocol error: {exc}") from None
            except (ValueError, TypeError):
                raise failure(
                    "System One returned invalid JSON",
                ) from None
            batch = DecisionBatch(
                list(subset), result.usage, result.model,
                result.request_id or response.headers.get("x-request-id"),
                round(time.perf_counter() - started, 6),
            )
            batches.append(batch)
            if len({b.model for b in batches}) > 1:
                raise DecisionServiceError("System One model identity changed between batches", completed_batches=batches)
            answers.update(result.choices)
        return DecisionResponse(
            {qid: answers[qid] for qid in questions}, aggregate_usage(batches),
            model=batches[0].model if batches else None,
            request_id=batches[0].request_id if len(batches) == 1 else None,
            batches=batches,
        )

    def chat_completion(self, messages, tools=None):
        raise NotImplementedError("Use --controller farm_jev for a System One service")

    def to_dict(self):
        return {
            "llm_class": self.llm_class, "provider": self.provider, "model": self.model,
            "base_url": self.base_url, "max_questions_per_request": self.max_questions,
        }
