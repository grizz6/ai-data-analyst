import numpy as np
import pandas as pd
import pytest

from app.config import settings
from app.services.modeling import ModelRequestError, predict, suggest_targets

rng = np.random.default_rng(21)

CLASSIFIERS = {
    "Logistic regression", "K-nearest neighbours", "Naive Bayes", "Decision tree", "Random forest",
    "Bagged trees", "Extra trees", "Gradient boosting", "AdaBoost", "Support vector machine",
}  # fmt: skip
REGRESSORS = {
    "Linear regression", "Ridge regression", "Lasso regression", "K-nearest neighbours", "Decision tree",
    "Random forest", "Bagged trees", "Extra trees", "Gradient boosting", "AdaBoost", "Support vector machine",
}  # fmt: skip


@pytest.fixture(scope="module")
def shop() -> pd.DataFrame:
    n = 500
    x = rng.uniform(0, 10, n)
    tier = rng.choice(["bronze", "silver", "gold"], n)
    return pd.DataFrame(
        {
            "x": x,
            "noise": rng.normal(size=n),
            "tier": tier,
            "spend": 3 * x + np.select([tier == "gold", tier == "silver"], [20, 10], 0) + rng.normal(0, 1, n),
            "churned": np.where(x + rng.normal(0, 1, n) > 5, "yes", "no"),
            "joined": pd.date_range("2020-01-01", periods=n),
        }
    )


@pytest.fixture(scope="module")
def regression(shop):
    return predict(shop.drop(columns="churned"), "spend")


@pytest.fixture(scope="module")
def classification(shop):
    return predict(shop.drop(columns="spend"), "churned")


def test_every_regression_family_is_compared_against_a_baseline(regression):
    names = [s.name for s in regression.scores]
    assert names[0] == "Baseline (average)" and set(names[1:]) == REGRESSORS
    assert {s.family for s in regression.scores} >= {
        "baseline",
        "linear",
        "neighbours",
        "tree",
        "bagging",
        "boosting",
        "kernel",
    }


def test_train_test_split_and_scores(regression):
    assert regression.train_rows + regression.test_rows == regression.rows_used == 500
    assert regression.test_rows == 100
    best = next(s for s in regression.scores if s.name == regression.best_model)
    assert best.test_score > 0.95 and best.cv_mean > 0.95
    assert regression.beats_baseline
    assert set(regression.best_test_metrics) == {"R²", "MAE", "RMSE"}


def test_best_model_is_chosen_by_cross_validation_not_the_test_set(regression):
    best = next(s for s in regression.scores if s.name == regression.best_model)
    assert best.cv_mean == max(s.cv_mean for s in regression.scores[1:])


def test_regression_charts(regression):
    assert [c.id for c in regression.charts] == [
        "model_comparison", "learning_curve", "predicted_vs_actual", "residuals", "residual_histogram",
        "permutation_importance",
    ]  # fmt: skip
    assert regression.charts[0].plotly_json["data"]


def test_permutation_importance_finds_the_drivers(regression):
    assert {i.feature for i in regression.importances[:2]} == {"x", "tier"}
    assert next(i for i in regression.importances if i.feature == "noise").importance < 0.02
    assert "joined" in regression.dropped_features


def test_classification_suite_with_auc_and_curves(classification):
    names = [s.name for s in classification.scores]
    assert names[0] == "Baseline (most common)" and set(names[1:]) == CLASSIFIERS
    assert classification.task == "classification" and classification.beats_baseline
    assert all(s.test_auc is None for s in classification.scores[:1])
    assert any(s.test_auc and s.test_auc > 0.85 for s in classification.scores)
    ids = [c.id for c in classification.charts]
    assert ids[:3] == ["model_comparison", "learning_curve", "confusion_matrix"]
    assert {"roc_curves", "precision_recall", "permutation_importance"} <= set(ids)
    assert {"accuracy", "precision (macro)", "recall (macro)", "ROC AUC"} <= set(classification.best_test_metrics)


def test_overfitting_is_flagged():
    # Pure noise: deep trees memorize the training rows but can't generalize.
    df = pd.DataFrame({f"f{i}": rng.normal(size=300) for i in range(6)} | {"y": rng.choice(["a", "b"], 300)})
    report = predict(df, "y")
    tree = next(s for s in report.scores if s.name == "Decision tree")
    assert tree.overfit and tree.train_score - tree.test_score > 0.1
    assert not report.beats_baseline
    assert report.summary.startswith("No model beats the baseline")


def test_multiclass_gets_a_confusion_matrix_but_no_binary_curves():
    df = pd.DataFrame({"x": rng.normal(size=300)})
    df["band"] = pd.cut(df["x"], [-np.inf, -0.5, 0.5, np.inf], labels=["low", "mid", "high"]).astype(str)
    report = predict(df, "band")
    ids = [c.id for c in report.charts]
    assert "confusion_matrix" in ids and "roc_curves" not in ids
    best = next(s for s in report.scores if s.name == report.best_model)
    assert best.test_score > 0.9


def test_target_suggestions_prefer_outcome_names_then_the_last_column(shop):
    suggestions = suggest_targets(shop)
    # Both are named like outcomes; the last column comes first.
    assert [s.column for s in suggestions[:2]] == ["churned", "spend"]
    assert suggestions[0].task == "classification" and suggestions[1].task == "regression"
    assert "joined" not in [s.column for s in suggestions]
    plain = pd.DataFrame({"a": rng.normal(size=50), "b": rng.normal(size=50)})
    assert suggest_targets(plain)[0].column == "b" and suggest_targets(plain)[0].reason == "last column"


@pytest.mark.parametrize(
    "frame, target, message",
    [
        (pd.DataFrame({"x": range(100), "y": range(100)}), "nope", "isn't a column"),
        (pd.DataFrame({"x": range(10), "y": np.linspace(0, 1, 10)}), "y", "at least 30 rows"),
        (pd.DataFrame({"x": range(10), "y": range(10)}), "y", "two values with 5\\+ rows each"),
        (pd.DataFrame({"x": range(300), "y": [f"c{i % 40}" for i in range(300)]}), "y", "40 different values"),
        (pd.DataFrame({"y": rng.normal(size=100)}), "y", "no other usable columns"),
    ],
)
def test_targets_that_cant_be_modelled_get_a_plain_reason(frame, target, message):
    with pytest.raises(ModelRequestError, match=message):
        predict(frame, target)


def test_prediction_endpoint(client, sample_csv_bytes, monkeypatch):
    upload = client.post("/api/upload", files={"file": ("s.csv", sample_csv_bytes, "text/csv")})
    body = upload.json()
    assert body["model_targets"][0]["column"] == "sales"
    res = client.post(f"/api/sessions/{body['session_id']}/model", json={"target": "sales"})
    assert res.status_code == 200
    assert res.json()["best_model"] == "Linear regression" and res.json()["charts"]

    assert client.post(f"/api/sessions/{body['session_id']}/model", json={"target": "nope"}).status_code == 400
    monkeypatch.setattr(settings, "models_per_hour", 2)
    assert client.post(f"/api/sessions/{body['session_id']}/model", json={"target": "units"}).status_code == 429
