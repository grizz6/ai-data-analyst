"""What to run next, and plans for a stated goal (rules and a fake model)."""

import asyncio
import json

import numpy as np
import pandas as pd
import pytest

from app.config import settings
from app.services import advice, explanation
from app.services.pipeline import compute_analysis
from tests.test_llm import FakeModel, completion

rng = np.random.default_rng(12)
N = 500


@pytest.fixture(scope="module")
def result():
    tenure = rng.integers(1, 60, N)
    churned = rng.random(N) < 1 / (1 + np.exp(-(1.5 - 0.08 * tenure)))
    spend = rng.gamma(3, 20, N)
    spend[3] = -50
    df = pd.DataFrame(
        {
            "tenure_months": tenure,
            "monthly_spend": spend.round(2),
            "region": rng.choice(["North", "South"], N),
            "churned": np.where(churned, "Yes", "No"),
        }
    )
    return compute_analysis(df.to_csv(index=False).encode(), "churn.csv")


def test_next_steps_give_reasons_from_the_data_and_what_to_check_first(result):
    by_id = {r.id: r for r in result.recommendations}
    churn = by_id["logistic:churned"]
    assert churn.action.tab == "variables" and churn.action.column == "churned"
    assert "tenure_months differs most" in churn.why
    suspicious = by_id["outliers:monthly_spend"]
    assert suspicious.action.tab == "variables" and suspicious.action.column == "monthly_spend"
    assert "-50" in suspicious.why and suspicious.check_first
    spend = by_id["regression:monthly_spend"]
    assert any("skewed" in c for c in spend.check_first)
    assert [r.score for r in result.recommendations] == sorted((r.score for r in result.recommendations), reverse=True)


def test_rule_plan_follows_the_goal_and_fixes_data_first(result):
    plan = advice.rule_plan(result, "Why do customers churn?")
    ids = [s.id for s in plan.steps]
    assert "logistic:churned" in ids
    assert plan.source == "rule_based" and plan.note is None
    first_analysis = next(r.analysis for r in result.recommendations if r.id == ids[0])
    assert first_analysis in ("data_quality", "outliers", "logistic_regression")


def test_rule_plan_says_when_nothing_matches(result):
    plan = advice.rule_plan(result, "zzz qqq")
    assert plan.note and len(plan.steps) == advice.MIN_PLAN_STEPS


def test_plan_endpoint_without_a_key_uses_rules(client):
    df = pd.DataFrame({"x": rng.normal(size=60), "y": rng.normal(size=60), "won": ["yes", "no"] * 30})
    upload = client.post("/api/upload", files={"file": ("deals.csv", df.to_csv(index=False).encode())})
    session = upload.json()["session_id"]
    reply = client.post(f"/api/sessions/{session}/plan", json={"goal": "win more deals"})
    assert reply.status_code == 200
    assert reply.json()["source"] == "rule_based" and reply.json()["steps"]
    assert client.post(f"/api/sessions/{session}/plan", json={"goal": "  "}).status_code == 400


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "test-key")


def plan_with(result, fake):
    return asyncio.run(advice.plan_for_goal(result, "reduce churn", client=fake.client()))


def test_model_plan_keeps_known_steps_in_its_order(result, configured):
    fake = FakeModel(
        completion(
            {
                "steps": [
                    {"id": "outliers:monthly_spend", "why": "Fix the negative spend first."},
                    {"id": "made-up", "why": "Not an option."},
                    {"id": "logistic:churned", "why": "Shows what drives churned, starting with tenure_months."},
                ]
            }
        )
    )
    plan = plan_with(result, fake)
    assert plan.source == "llm" and plan.model == "test-model"
    assert [s.id for s in plan.steps] == ["outliers:monthly_spend", "logistic:churned"]
    assert plan.steps[1].action.column == "churned" and plan.steps[1].check_first == next(
        r.check_first for r in result.recommendations if r.id == "logistic:churned"
    )
    sent = json.loads(json.loads(fake.requests[0].content)["messages"][1]["content"])
    assert sent["goal"] == "reduce churn" and {o["id"] for o in sent["options"]} >= {"logistic:churned"}


def test_model_plan_with_an_invented_number_falls_back_to_rules(result, configured):
    fake = FakeModel(completion({"steps": [{"id": "logistic:churned", "why": "Churn could fall by 4242 customers."}]}))
    plan = plan_with(result, fake)
    assert plan.source == "rule_based" and "4242" in plan.fallback_reason


def test_model_plan_with_only_unknown_steps_falls_back(result, configured):
    fake = FakeModel(completion({"steps": [{"id": "nope", "why": "x"}]}))
    plan = plan_with(result, fake)
    assert plan.source == "rule_based" and "no analysis" in plan.fallback_reason


def test_plan_fallback_keeps_explanation_rules(result, configured, monkeypatch):
    # The plan reuses the explanation's ground rules, so the two can't drift apart.
    assert explanation.GROUND_RULES in advice.PLAN_SYSTEM_PROMPT


def test_outcome_like_columns_are_suggested_first():
    from app.services.targets import suggest_targets

    df = pd.DataFrame({"a": rng.normal(size=60), "churned": ["yes", "no"] * 30, "b": rng.normal(size=60)})
    assert [t.column for t in suggest_targets(df)][:2] == ["churned", "b"]
