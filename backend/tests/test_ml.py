import numpy as np
import pandas as pd
import pytest

from app.config import settings
from app.services.ml import ModelRequestError, cluster, predict

rng = np.random.default_rng(11)


def blobs(n_per=150) -> pd.DataFrame:
    centres = [(0, 0, 0), (8, 8, 0), (0, 8, 8)]
    rows = [rng.normal(c, 0.6, (n_per, 3)) for c in centres]
    return pd.DataFrame(np.vstack(rows), columns=["a", "b", "c"])


def test_clear_groups_are_found():
    result = cluster(blobs())
    assert result.clear and result.k == 3
    assert result.silhouette > 0.6
    assert sorted(p.size for p in result.clusters) == [150, 150, 150]
    assert result.chart.id == "clusters_pca"
    assert "fall into 3 groups" in result.summary


def test_no_structure_is_reported_as_such():
    noise = pd.DataFrame(rng.uniform(0, 1, (400, 4)), columns=list("wxyz"))
    result = cluster(noise)
    assert not result.clear
    assert result.summary.startswith("No clear groups")


def test_clustering_needs_enough_rows_and_columns():
    assert cluster(pd.DataFrame({"a": range(20), "b": range(20)})) is None  # too few rows
    assert cluster(pd.DataFrame({"a": rng.normal(size=200)})) is None  # one column


@pytest.fixture(scope="module")
def shop() -> pd.DataFrame:
    n = 400
    x = rng.uniform(0, 10, n)
    tier = rng.choice(["bronze", "silver", "gold"], n)
    return pd.DataFrame(
        {
            "x": x,
            "noise": rng.normal(size=n),
            "tier": tier,
            "spend": 3 * x + np.select([tier == "gold", tier == "silver"], [20, 10], 0) + rng.normal(0, 1, n),
            "churned": np.where(x > 5, "yes", "no"),
            "joined": pd.date_range("2020-01-01", periods=n),
        }
    )


def test_regression_beats_the_baseline_and_finds_the_drivers(shop):
    report = predict(shop.drop(columns="churned"), "spend")
    assert report.task == "regression" and report.primary_metric == "R²"
    assert report.beats_baseline
    best = next(s for s in report.scores if s.name == report.best_model)
    assert best.primary > 0.95
    assert {i.feature for i in report.importances[:2]} == {"x", "tier"}  # one-hot tier added back up
    assert "joined" in report.dropped_features
    assert [s.name for s in report.scores][0].startswith("Baseline")


def test_classification_with_a_text_target(shop):
    report = predict(shop.drop(columns="spend"), "churned")
    assert report.task == "classification" and report.primary_metric == "accuracy"
    assert report.beats_baseline
    assert report.importances[0].feature == "x"
    assert max(s.primary for s in report.scores) > 0.9


def test_unpredictable_target_is_called_out():
    df = pd.DataFrame({"a": rng.normal(size=300), "b": rng.normal(size=300), "y": rng.normal(size=300)})
    report = predict(df, "y")
    assert not report.beats_baseline
    assert report.summary.startswith("None of the models predicts 'y' reliably")


def test_rare_classes_are_set_aside_with_a_note():
    df = pd.DataFrame({"x": rng.normal(size=200), "label": ["a"] * 100 + ["b"] * 97 + ["c"] * 3})
    report = predict(df, "label")
    assert any("under 5 rows were left out" in note for note in report.notes)


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
    session_id = upload.json()["session_id"]
    res = client.post(f"/api/sessions/{session_id}/model", json={"target": "sales"})
    assert res.status_code == 200
    assert res.json()["task"] == "regression" and res.json()["beats_baseline"] is True

    assert client.post(f"/api/sessions/{session_id}/model", json={"target": "nope"}).status_code == 400
    monkeypatch.setattr(settings, "models_per_hour", 2)
    assert client.post(f"/api/sessions/{session_id}/model", json={"target": "units"}).status_code == 429


def test_report_includes_the_groups(client):
    data = blobs(40).assign(segment="x").to_csv(index=False).encode()
    upload = client.post("/api/upload", files={"file": ("blobs.csv", data, "text/csv")})
    html = client.get(f"/api/sessions/{upload.json()['session_id']}/report").text
    assert "<h2>Groups of similar rows</h2>" in html and "fall into 3 groups" in html
    assert "Groups of similar rows (PCA map)" in html
