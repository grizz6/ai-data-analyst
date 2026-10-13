"""The analyst's read: verdict, concerns, strengths, limits, and each analysis's readiness and risks."""

import numpy as np
import pandas as pd

from app.services.pipeline import compute_analysis

rng = np.random.default_rng(31)


def analyse(df: pd.DataFrame, name: str = "data.csv"):
    return compute_analysis(df.to_csv(index=False).encode(), name)


def test_clean_data_is_called_ready_and_its_strengths_named():
    n = 1_200
    group = rng.choice(["a", "b", "c"], n)
    df = pd.DataFrame(
        {
            "group": group,
            "value": np.select([group == "a", group == "b"], [10, 20], 30) + rng.normal(0, 2, n),
            "other": rng.normal(50, 5, n),
        }
    )
    review = analyse(df).review
    assert review.readiness == "ready" and review.verdict.startswith("Ready to analyse")
    assert any("1,200 rows" in s for s in review.strengths)
    assert any(s.startswith("A clear signal: group explains") for s in review.strengths)
    assert any(c.startswith("Cause and effect. group explains") for c in review.cannot_conclude)
    assert any("no time axis" in c for c in review.cannot_conclude)


def test_a_column_that_gives_the_outcome_away_is_flagged_as_leakage():
    n = 400
    churned = rng.random(n) < 0.3
    df = pd.DataFrame(
        {
            "days_since_cancel": np.where(churned, rng.integers(1, 30, n), 0),
            "spend": rng.gamma(2, 30, n),
            "churned": np.where(churned, "Yes", "No"),
        }
    )
    result = analyse(df)
    assert result.review.concerns[0].startswith("days_since_cancel almost perfectly separates churned")
    churn = next(r for r in result.recommendations if r.id == "logistic:churned")
    assert churn.readiness == "needs_work"
    assert any(r.startswith("Possible leakage: days_since_cancel") for r in churn.risks)


def test_too_few_outcome_rows_per_predictor_is_called_out():
    n = 120
    df = pd.DataFrame({f"x{i}": rng.normal(size=n) for i in range(8)})
    df["fraud"] = np.where(np.arange(n) < 12, 1, 0)
    df["x0"] = df["x0"] + 3 * df["fraud"]
    fraud = next(r for r in analyse(df).recommendations if r.id == "logistic:fraud")
    assert any("Only 12 rows in the smaller group for 8 candidate predictors" in r for r in fraud.risks)


def test_serious_problems_lead_the_concerns_and_set_the_verdict():
    n = 500
    age = rng.normal(40, 10, n).round()
    income = age * 1_000 + rng.normal(0, 5_000, n)
    income[(age < 32) & (rng.random(n) < 0.7)] = np.nan
    age[[3, 9]] = [999, -5]
    df = pd.DataFrame({"age": age, "income": income, "spend": rng.gamma(2, 20, n)})
    review = analyse(df).review
    assert review.readiness == "not_ready"
    assert review.verdict.startswith("Not ready to analyse:")
    assert "gaps in income aren't random" in review.verdict and "age holds entry errors" in review.verdict
    assert "not at random" in review.concerns[0] or "entry errors" in review.concerns[0]


def test_tiny_files_are_not_ready():
    df = pd.DataFrame({"a": rng.normal(size=20), "b": rng.normal(size=20)})
    review = analyse(df).review
    assert review.readiness == "not_ready" and "only 20 rows" in review.verdict


def test_entry_errors_in_inputs_hold_back_every_model():
    n = 400
    tenure = rng.integers(1, 60, n).astype(float)
    churned = rng.random(n) < 1 / (1 + np.exp(-(1.5 - 0.08 * tenure)))
    age = rng.normal(40, 8, n).round()
    age[[5, 6]] = [999, -4]
    df = pd.DataFrame({"tenure": tenure, "age": age, "churned": np.where(churned, "Yes", "No")})
    churn = next(r for r in analyse(df).recommendations if r.id == "logistic:churned")
    assert churn.readiness == "needs_work"
    assert any(r.startswith("Fix the entry errors in age first") for r in churn.risks)
