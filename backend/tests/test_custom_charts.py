import sqlite3

import pytest

from app.models.schemas import CustomChartRequest
from app.services.custom_charts import ChartRequestError, build_custom_chart, load_chart_data
from app.session_store import SessionStore


@pytest.fixture
def session_id(client, sample_csv_bytes) -> str:
    return client.post("/api/upload", files={"file": ("sales.csv", sample_csv_bytes, "text/csv")}).json()["session_id"]


def chart(client, session_id, **body):
    return client.post(f"/api/sessions/{session_id}/charts", json=body)


@pytest.mark.parametrize(
    "body, title",
    [
        ({"chart_type": "histogram", "x": "units"}, "Distribution of units"),
        ({"chart_type": "bar", "x": "region"}, "Count by region"),
        ({"chart_type": "bar", "x": "region", "y": "sales", "aggregate": "sum"}, "Total sales by region"),
        ({"chart_type": "scatter", "x": "units", "y": "sales"}, "units vs sales"),
        ({"chart_type": "line", "x": "date", "y": "units", "aggregate": "mean"}, "Average units over date (daily)"),
        ({"chart_type": "box", "y": "sales"}, "Spread of sales"),
        ({"chart_type": "box", "x": "product", "y": "sales"}, "Spread of sales by product"),
    ],
)
def test_each_chart_type_builds(client, session_id, body, title):
    res = chart(client, session_id, **body)
    assert res.status_code == 200, res.text
    spec = res.json()
    assert spec["title"] == title
    assert spec["chart_type"] == body["chart_type"]
    assert spec["plotly_json"]["data"]


def test_bar_totals_are_computed_by_pandas(client, session_id, sample_csv_bytes):
    import io

    import pandas as pd

    expected = pd.read_csv(io.BytesIO(sample_csv_bytes)).groupby("region")["sales"].sum()
    spec = chart(client, session_id, chart_type="bar", x="region", y="sales", aggregate="sum").json()
    bars = spec["plotly_json"]["data"][0]
    assert dict(zip(bars["x"], bars["y"], strict=True)) == expected.to_dict()
    assert bars["y"] == sorted(bars["y"], reverse=True)


@pytest.mark.parametrize(
    "body, message",
    [
        ({"chart_type": "histogram", "x": "region"}, "isn't numeric"),
        ({"chart_type": "scatter", "x": "units", "y": "units"}, "two different columns"),
        ({"chart_type": "bar", "x": "region", "aggregate": "mean"}, "Choose a numeric column"),
        ({"chart_type": "bar", "x": "date"}, "use a line chart"),
        ({"chart_type": "box", "x": "units", "y": "sales"}, "text column"),
        ({"chart_type": "line", "y": "sales", "aggregate": "sum"}, "x axis"),
        ({"chart_type": "histogram", "x": "no_such_column"}, "isn't in the data"),
    ],
)
def test_bad_combinations_get_a_plain_400(client, session_id, body, message):
    res = chart(client, session_id, **body)
    assert res.status_code == 400
    assert message in res.json()["detail"]


def test_unknown_chart_type_is_422(client, session_id):
    assert chart(client, session_id, chart_type="pie", x="region").status_code == 422


def test_unknown_session_is_404(client):
    assert chart(client, "nope", chart_type="histogram", x="units").status_code == 404


def test_charts_never_show_filled_in_values():
    from app.services.pipeline import compute_analysis

    csv = b"region,sales\nWest,10\nEast,\nWest,30\nEast,50\nNorth,20\n"
    result = compute_analysis(csv, "gaps.csv")
    df = load_chart_data(result, result.chart_csv)
    assert df["sales"].isna().sum() == 1  # the gap is still a gap, not the median

    spec = build_custom_chart(df, CustomChartRequest(chart_type="bar", x="region", y="sales", aggregate="mean"))
    bars = dict(zip(spec.plotly_json["data"][0]["x"], spec.plotly_json["data"][0]["y"], strict=True))
    assert bars["East"] == 50


def test_identifier_columns_cannot_be_charted():
    from app.services.pipeline import compute_analysis

    csv = "order_id,amount\n" + "".join(f"{1000 + i},{i * 3}\n" for i in range(30))
    result = compute_analysis(csv.encode(), "orders.csv")
    df = load_chart_data(result, result.chart_csv)
    with pytest.raises(ChartRequestError, match="identifier"):
        build_custom_chart(df, CustomChartRequest(chart_type="histogram", x="order_id"))


def test_text_that_looks_numeric_stays_text():
    from app.services.pipeline import compute_analysis

    csv = "".join(["team,score\n"] + [f"{t},{i}\n" for i, t in enumerate(["007", "010", "007", "abc"] * 5)])
    result = compute_analysis(csv.encode(), "teams.csv")
    df = load_chart_data(result, result.chart_csv)
    spec = build_custom_chart(df, CustomChartRequest(chart_type="bar", x="team"))
    assert set(spec.plotly_json["data"][0]["x"]) == {"007", "010", "abc"}


def test_older_databases_gain_the_chart_column(tmp_path, result_for_store):
    path = tmp_path / "old.sqlite3"
    db = sqlite3.connect(path)
    db.execute(
        """CREATE TABLE sessions (id TEXT PRIMARY KEY, filename TEXT NOT NULL, created_at REAL NOT NULL,
           last_used REAL NOT NULL, use_seq INTEGER NOT NULL, result_json TEXT NOT NULL, cleaned_csv BLOB)"""
    )
    db.commit()
    db.close()

    store = SessionStore(path=path, ttl_seconds=600, max_sessions=5)
    store.save(result_for_store)
    assert store.get(result_for_store.session_id).chart_csv == result_for_store.chart_csv
    store.close()
