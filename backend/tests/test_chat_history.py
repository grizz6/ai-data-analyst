import asyncio
import json

from app.config import settings
from app.models.schemas import ChatTurn
from app.routers.analysis import MAX_CHAT_TURNS
from app.services import explanation
from app.session_store import SessionStore
from tests.test_llm import FakeModel, completion


def upload(client, sample_csv_bytes) -> str:
    res = client.post("/api/upload", files={"file": ("sales.csv", sample_csv_bytes, "text/csv")})
    return res.json()["session_id"]


def test_questions_and_answers_are_kept_with_the_session(client, sample_csv_bytes):
    session_id = upload(client, sample_csv_bytes)
    assert client.get(f"/api/sessions/{session_id}").json()["chat_history"] == []

    for q in ("Which region sells most?", "  And the least?  "):
        assert client.post(f"/api/sessions/{session_id}/ask", json={"question": q}).status_code == 200

    history = client.get(f"/api/sessions/{session_id}").json()["chat_history"]
    assert [t["question"] for t in history] == ["Which region sells most?", "And the least?"]
    assert all(t["source"] == "rule_based" and t["answer"] for t in history)


def test_chat_history_is_in_the_report(client, sample_csv_bytes):
    session_id = upload(client, sample_csv_bytes)
    client.post(f"/api/sessions/{session_id}/ask", json={"question": "What <b>stands</b> out?"})

    html = client.get(f"/api/sessions/{session_id}/report").text
    assert "Questions asked" in html
    assert "What &lt;b&gt;stands&lt;/b&gt; out?" in html  # escaped, not rendered


def test_history_keeps_only_the_newest_turns(result_for_store):
    store = SessionStore(path=":memory:", ttl_seconds=600, max_sessions=5)
    store.save(result_for_store)
    for i in range(MAX_CHAT_TURNS + 3):
        turn = ChatTurn(question=f"q{i}", answer="a")
        store.add_chat_turn(result_for_store.session_id, turn, max_turns=MAX_CHAT_TURNS)

    history = store.get(result_for_store.session_id).chat_history
    assert len(history) == MAX_CHAT_TURNS
    assert history[0].question == "q3"
    # The cleaned CSV stored with the session is untouched by the update.
    assert store.get(result_for_store.session_id).cleaned_csv == result_for_store.cleaned_csv


def test_adding_to_a_missing_session_reports_it():
    store = SessionStore(path=":memory:", ttl_seconds=600, max_sessions=5)
    assert store.add_chat_turn("gone", ChatTurn(question="q", answer="a"), max_turns=5) is False


def test_follow_up_sends_earlier_turns_to_the_model(result_for_store, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    result = result_for_store.model_copy(deep=True)
    result.chat_history = [ChatTurn(question="Which region sold most in the top 3 weeks?", answer="West did.")]
    fake = FakeModel(completion({"answer": "East sold least across the top 3 weeks."}))

    response = asyncio.run(explanation.answer_question(result, "And the least?", client=fake.client()))

    sent = json.loads(json.loads(fake.requests[0].content)["messages"][1]["content"])
    assert sent["earlier_conversation"] == [{"question": result.chat_history[0].question, "answer": "West did."}]
    # "3" appears only in an earlier question, which counts as given.
    assert response.source == "llm"
    assert response.model == "test-model"


def test_numbers_from_earlier_answers_are_not_trusted(result_for_store, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    result = result_for_store.model_copy(deep=True)
    result.chat_history = [ChatTurn(question="Anything odd?", answer="Roughly 4242 things.")]
    fake = FakeModel(completion({"answer": "As said, about 4242."}))

    response = asyncio.run(explanation.answer_question(result, "Repeat that?", client=fake.client()))

    assert response.source == "rule_based"
    assert "4242" in (response.fallback_reason or "")
