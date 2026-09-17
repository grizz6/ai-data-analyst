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
from app.services import llama
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
    return asyncio.run(llama.explain_analysis(result, client=fake.client(**kwargs)))


def test_without_a_key_the_model_is_never_called(result, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")
    fake = FakeModel(AssertionError("should not be called"))

    explanation = explain(result, fake)

    assert fake.requests == []
    assert (explanation.source, explanation.configured) == ("rule_based", False)


def test_grounded_reply_is_used(result, configured):
    explanation = explain(result, FakeModel(completion(grounded_explanation(result))))

    assert explanation.source == "llm"
    assert explanation.model == "test-model"
    assert explanation.fallback_reason is None
    assert "correlation 0.98" in explanation.analysis_summary
    assert [n["chart_id"] for n in explanation.chart_explanations] == [result.charts[0].id]


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

    explanation = explain(result, FakeModel(completion(reply)))

    assert explanation.source == "rule_based"
    assert explanation.configured is True
    assert "37" in explanation.fallback_reason


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
    explanation = explain(result, FakeModel(completion(content)))
    assert explanation.source == "rule_based"
    assert reason in explanation.fallback_reason


def test_server_error_is_retried_then_succeeds(result, configured):
    fake = FakeModel(httpx.Response(503), completion(grounded_explanation(result)))

    explanation = explain(result, fake)

    assert explanation.source == "llm"
    assert len(fake.requests) == 2
    assert fake.sleeps == [0.5]


def test_retry_after_header_is_honored(result, configured):
    fake = FakeModel(httpx.Response(429, headers={"Retry-After": "3"}), completion(grounded_explanation(result)))
    explain(result, fake)
    assert fake.sleeps == [3.0]


def test_repeated_timeouts_give_up_after_the_retry_budget(result, configured):
    fake = FakeModel(httpx.ReadTimeout("slow"))

    explanation = explain(result, fake, max_retries=2)

    assert len(fake.requests) == 3
    assert fake.sleeps == [0.5, 1.0]
    assert explanation.source == "rule_based"
    assert "timed out" in explanation.fallback_reason
    assert "3 attempts" in explanation.fallback_reason


def test_auth_error_is_not_retried(result, configured):
    fake = FakeModel(httpx.Response(401))

    explanation = explain(result, fake)

    assert len(fake.requests) == 1
    assert "HTTP 401" in explanation.fallback_reason


def ask(result, fake: FakeModel, question: str):
    return asyncio.run(llama.answer_question(result, question, client=fake.client()))


def test_grounded_answer_is_used_and_numbers_from_the_question_are_allowed(result, configured):
    fake = FakeModel(completion({"answer": "West leads. The top 3 regions are West, East, and North."}))

    response = ask(result, fake, "What are the top 3 regions?")

    assert response.source == "llm"
    assert response.answer.startswith("West leads")


def test_answer_with_an_invented_number_falls_back(result, configured):
    fake = FakeModel(completion({"answer": "West sold 58,000 in total."}))

    response = ask(result, fake, "How much did West sell?")

    assert response.source == "rule_based"
    assert response.answer.startswith("The language model couldn't answer just now")
    assert "58,000" in response.fallback_reason


def test_ask_endpoint_uses_the_model_when_configured(client, sample_csv_bytes, configured, monkeypatch):
    fake = FakeModel(
        completion({"dataset_overview": "31 rows.", "analysis_summary": "Sales track units.", "recommendations": []}),
        completion({"answer": "Sales and units rise and fall together."}),
    )
    monkeypatch.setattr(llama, "make_client", fake.client)

    upload = client.post("/api/upload", files={"file": ("s.csv", sample_csv_bytes, "text/csv")}).json()
    assert upload["llama"]["source"] == "llm"

    answer = client.post(f"/api/sessions/{upload['session_id']}/ask", json={"question": "Link?"}).json()
    assert answer == {
        "answer": "Sales and units rise and fall together.",
        "configured": True,
        "source": "llm",
        "fallback_reason": None,
    }
    assert client.get("/api/health").json()["llm_configured"] is True
