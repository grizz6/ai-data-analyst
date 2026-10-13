"""The model layer, tested against a fake OpenAI-compatible server.

httpx.MockTransport stands in for the provider, so these tests need no API
key and no network, and can script any failure: timeouts, 5xx, 401, bad JSON,
or a reply containing numbers the analysis never produced.
"""

import asyncio
import json

import httpx
import pytest

from app.config import settings
from app.services import explanation
from app.services.llm_client import LLMClient
from app.services.pipeline import compute_analysis
from tests.conftest import SAMPLE_CSV


@pytest.fixture(scope="module")
def result():
    return compute_analysis(SAMPLE_CSV.read_bytes(), "sales_sample.csv")


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "test-key")


class FakeModel:
    """Scripted replies, one per call; the last one repeats. Records every request and sleep."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []

    def client(self, max_retries: int = 2) -> LLMClient:
        async def no_sleep(seconds: float) -> None:
            self.sleeps.append(seconds)

        return LLMClient(
            api_key="test-key",
            base_url="https://llm.test/v1",
            model="test-model",
            max_retries=max_retries,
            transport=httpx.MockTransport(self._handle),
            sleep=no_sleep,
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies[min(len(self.requests), len(self.replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply


def completion(content, status: int = 200, headers=None) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    body = {
        "model": "test-model",
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 120},
    }
    return httpx.Response(status, json=body, headers=headers)


def grounded_explanation(result) -> dict:
    return {
        "dataset_overview": "The file has 31 rows and 5 columns of weekly sales, with no quality issues.",
        "analysis_summary": "Sales and units move together very closely (correlation 0.98).",
        "recommendations": ["Use units as an early signal for sales."],
        "chart_explanations": [
            {"chart_id": result.charts[0].id, "explanation": "Most weeks sit in the middle of the range."},
            {"chart_id": "chart_that_does_not_exist", "explanation": "Ignored."},
        ],
    }


def explain(result, fake: FakeModel, **kwargs):
    return asyncio.run(explanation.explain_analysis(result, client=fake.client(**kwargs)))


def test_without_a_key_the_model_is_never_called(result, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")
    fake = FakeModel(AssertionError("should not be called"))

    summary = explain(result, fake)

    assert fake.requests == []
    assert (summary.source, summary.configured) == ("rule_based", False)


def test_grounded_reply_is_used(result, configured):
    summary = explain(result, FakeModel(completion(grounded_explanation(result))))

    assert summary.source == "llm"
    assert summary.model == "test-model"
    assert summary.fallback_reason is None
    assert "correlation 0.98" in summary.analysis_summary
    assert [n["chart_id"] for n in summary.chart_explanations] == [result.charts[0].id]


def test_request_sends_facts_and_forbids_calculation(result, configured):
    fake = FakeModel(completion(grounded_explanation(result)))
    explain(result, fake)

    [request] = fake.requests
    payload = json.loads(request.content)
    assert request.url == "https://llm.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    assert payload["model"] == "test-model"
    assert payload["response_format"] == {"type": "json_object"}
    assert "Never calculate" in payload["messages"][0]["content"]
    facts = json.loads(payload["messages"][1]["content"])["facts"]
    assert facts["correlations"][0]["correlation"] == 0.9832


def test_reply_with_an_invented_number_falls_back(result, configured):
    reply = grounded_explanation(result)
    reply["analysis_summary"] = "Sales grew 37% year over year."

    summary = explain(result, FakeModel(completion(reply)))

    assert summary.source == "rule_based"
    assert summary.configured is True
    assert "37" in summary.fallback_reason


def test_invented_number_in_a_chart_note_also_falls_back(result, configured):
    reply = grounded_explanation(result)
    reply["chart_explanations"][0]["explanation"] = "About 40 weeks sit near the median."

    assert explain(result, FakeModel(completion(reply))).source == "rule_based"


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("Sure! Here is a summary of your data.", "not valid JSON"),
        ('["a", "list"]', "not an object"),
        ({"dataset_overview": "Only one field."}, "missing required fields"),
    ],
)
def test_unusable_replies_fall_back(result, configured, content, reason):
    summary = explain(result, FakeModel(completion(content)))
    assert summary.source == "rule_based"
    assert reason in summary.fallback_reason


def test_server_error_is_retried_then_succeeds(result, configured):
    fake = FakeModel(httpx.Response(503), completion(grounded_explanation(result)))

    summary = explain(result, fake)

    assert summary.source == "llm"
    assert len(fake.requests) == 2
    assert fake.sleeps == [0.5]


def test_retry_after_header_is_honored(result, configured):
    fake = FakeModel(httpx.Response(429, headers={"Retry-After": "3"}), completion(grounded_explanation(result)))
    explain(result, fake)
    assert fake.sleeps == [3.0]


def test_repeated_timeouts_give_up_after_the_retry_budget(result, configured):
    fake = FakeModel(httpx.ReadTimeout("slow"))

    summary = explain(result, fake, max_retries=2)

    assert len(fake.requests) == 3
    assert fake.sleeps == [0.5, 1.0]
    assert summary.source == "rule_based"
    assert "timed out" in summary.fallback_reason
    assert "3 attempts" in summary.fallback_reason


def test_auth_error_is_not_retried(result, configured):
    fake = FakeModel(httpx.Response(401))

    summary = explain(result, fake)

    assert len(fake.requests) == 1
    assert "HTTP 401" in summary.fallback_reason


def test_retired_model_falls_through_to_the_next_one():
    replies = [httpx.Response(404, json={"error": {"code": "model_not_found"}}), completion({"answer": "ok"})]
    seen: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return replies[len(seen) - 1]

    client = LLMClient(
        api_key="k",
        base_url="https://llm.test/v1",
        model="old-model",
        fallback_models=["openai/gpt-oss-20b"],
        transport=httpx.MockTransport(handle),
    )
    reply = asyncio.run(client.chat_json("system", "user"))
    assert reply.data == {"answer": "ok"}
    assert [r["model"] for r in seen] == ["old-model", "openai/gpt-oss-20b"]
    # Reasoning models are asked to keep their reasoning short; others aren't sent the option.
    assert "reasoning_effort" not in seen[0] and seen[1]["reasoning_effort"] == "low"


def test_every_model_retired_falls_back_to_rules(result, configured):
    fake = FakeModel(httpx.Response(404))
    summary = explain(result, fake)
    assert len(fake.requests) == 1  # FakeModel's client has no fallbacks; a 404 isn't retried
    assert summary.source == "rule_based" and "model not available (test-model)" in summary.fallback_reason


def test_default_model_is_one_groq_still_serves():
    assert settings.llm_model == "openai/gpt-oss-120b"
    assert settings.llm_fallback_models == ["openai/gpt-oss-20b"]


def test_upload_uses_the_model_when_configured(client, sample_csv_bytes, configured, monkeypatch):
    fake = FakeModel(
        completion({"dataset_overview": "31 rows.", "analysis_summary": "Sales track units.", "recommendations": []}),
    )
    monkeypatch.setattr(explanation, "make_client", fake.client)

    upload = client.post("/api/upload", files={"file": ("s.csv", sample_csv_bytes, "text/csv")}).json()
    assert upload["explanation"]["source"] == "llm"
    assert upload["explanation"]["analysis_summary"] == "Sales track units."
    assert client.get("/api/health").json()["llm_configured"] is True
