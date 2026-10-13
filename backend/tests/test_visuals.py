import numpy as np
import pandas as pd

from app.services.pipeline import compute_analysis

rng = np.random.default_rng(4)


def ids(result, tab):
    return [c.id for c in result.visuals.get(tab, [])]


def test_sample_file_gets_charts_on_every_relevant_tab(sample_csv_bytes):
    result = compute_analysis(sample_csv_bytes, "sales.csv")
    assert ids(result, "overview") == ["column_types", "row_completeness"]
    assert {"histograms", "category_counts", "box_plots", "rows_over_time"} <= set(ids(result, "explore"))
    rel = ids(result, "relationships")
    assert {"corr_pearson", "corr_spearman", "scatter_matrix", "cramers_v"} <= set(rel)
    # Group comparisons and crosstabs are explored pair by pair, not drawn here.
    assert not any(i.startswith("group_") or i == "crosstab" for i in rel)


def test_gaps_are_mapped_and_counted():
    df = pd.DataFrame({"a": rng.normal(size=100), "b": rng.normal(size=100)})
    df.loc[::4, "b"] = np.nan
    result = compute_analysis(df.to_csv(index=False).encode(), "gaps.csv")
    quality = {c.id: c for c in result.visuals["quality"]}
    assert {"missing_by_column", "missing_map"} <= set(quality)
    bars = quality["missing_by_column"].plotly_json["data"][0]
    assert dict(zip(bars["y"], bars["x"], strict=True))["b"] == 25.0


def test_identifiers_are_counted_but_not_charted():
    df = pd.DataFrame({"order_id": range(1000, 1050), "amount": rng.normal(100, 5, 50)})
    result = compute_analysis(df.to_csv(index=False).encode(), "orders.csv")
    pie = result.visuals["overview"][0].plotly_json["data"][0]
    assert dict(zip(pie["labels"], pie["values"], strict=True)) == {"numbers": 1, "identifiers": 1}
    hist = next(c for c in result.visuals["explore"] if c.id == "histograms")
    assert "order_id" not in str(hist.plotly_json["layout"])


def test_scatter_matrix_uses_plain_scatter_traces():
    # The app ships Plotly's cartesian build, which has no splom trace.
    df = pd.DataFrame(rng.normal(size=(120, 3)), columns=["p", "q", "r"])
    df["kind"] = ["x", "y", "z"] * 40
    result = compute_analysis(df.to_csv(index=False).encode(), "pairs.csv")
    matrix = next(c for c in result.visuals["relationships"] if c.id == "scatter_matrix")
    traces = matrix.plotly_json["data"]
    assert {t["type"] for t in traces} == {"scatter"}
    assert len(traces) == 3 * 3  # three pairs, one trace per category
    assert sum(bool(t.get("showlegend")) for t in traces) == 3


def test_quality_charts_are_skipped_when_there_is_nothing_to_show():
    df = pd.DataFrame({"a": np.arange(60.0), "b": np.arange(60.0) * 2})
    result = compute_analysis(df.to_csv(index=False).encode(), "clean.csv")
    assert "quality" not in result.visuals
