"""Minimal client for any OpenAI-compatible chat completions API.

One call shape is all this app needs (a system prompt, a user message, a
JSON object back), so this is plain httpx rather than a vendor SDK or an
orchestration framework. Swapping providers is a base URL and model change.
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
# Providers answer 404 for a model they've retired; the next model in the list is tried instead.
MODEL_GONE_STATUS = 404
MAX_RETRY_AFTER_SECONDS = 10.0
# OpenAI's open-weight models reason before answering; "low" keeps that quick for short JSON replies.
REASONING_MODEL_PREFIX = "openai/gpt-oss"


class LLMError(Exception):
    """The model call failed or returned something unusable. Callers fall back."""


class _ModelGone(Exception):
    """The provider doesn't have this model (any more)."""


@dataclass
class ChatResult:
    data: dict
    model: str
    latency_ms: int
    attempts: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        fallback_models: list[str] | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.models = [model, *[m for m in (fallback_models or []) if m and m != model]]
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._transport = transport
        self._sleep = sleep

    async def chat_json(self, system: str, user: str, *, temperature: float = 0.2) -> ChatResult:
        """Send one chat request and return the reply parsed as a JSON object.

        Retries timeouts, connection errors, 429 and 5xx with exponential
        backoff (honoring Retry-After up to 10 s). A 404 means the provider
        retired the model, so the next fallback model is tried. Any other 4xx
        fails at once, since sending the same request again won't change the answer.
        """
        gone: list[str] = []
        for model in self.models:
            try:
                return await self._chat_one(model, system, user, temperature)
            except _ModelGone:
                gone.append(model)
        raise LLMError(f"HTTP 404: model not available ({', '.join(gone)})")

    async def _chat_one(self, model: str, system: str, user: str, temperature: float) -> ChatResult:
        payload: dict = {
            "model": model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if model.startswith(REASONING_MODEL_PREFIX):
            payload["reasoning_effort"] = "low"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        started = time.perf_counter()
        last_error = "no attempt made"

        async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self._transport) as http:
            for attempt in range(1, self.max_retries + 2):
                try:
                    response = await http.post(
                        f"{self.base_url}/chat/completions", json=payload, headers=headers
                    )
                except httpx.TimeoutException:
                    last_error = f"timed out after {self.timeout_seconds:g} s"
                    delay = self._backoff(attempt)
                except httpx.TransportError as exc:
                    last_error = f"connection failed ({type(exc).__name__})"
                    delay = self._backoff(attempt)
                else:
                    if response.status_code == 200:
                        return self._parse(response, model, attempt, started)
                    if response.status_code == MODEL_GONE_STATUS:
                        raise _ModelGone(model)
                    last_error = f"HTTP {response.status_code}"
                    if response.status_code not in RETRYABLE_STATUS:
                        raise LLMError(last_error)
                    delay = self._retry_after(response) or self._backoff(attempt)

                if attempt <= self.max_retries:
                    await self._sleep(delay)

        raise LLMError(f"{last_error} ({self.max_retries + 1} attempts)")

    def _parse(self, response: httpx.Response, model: str, attempts: int, started: float) -> ChatResult:
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("reply was not valid JSON") from exc
        if not isinstance(data, dict):
            raise LLMError("reply was JSON but not an object")

        usage = body.get("usage") or {}
        return ChatResult(
            data=data,
            model=body.get("model") or model,
            latency_ms=round((time.perf_counter() - started) * 1000),
            attempts=attempts,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )

    @staticmethod
    def _backoff(attempt: int) -> float:
        return 0.5 * 2 ** (attempt - 1)

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("retry-after", "")
        try:
            return min(float(value), MAX_RETRY_AFTER_SECONDS)
        except ValueError:
            return None
