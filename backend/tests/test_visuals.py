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
    assert {"corr_pearson", "corr_spearman", "scatter_matrix", "cramers_v", "crosstab"} <= set(rel)
    assert "group_product_sales" in rel
    assert "clustering" not in result.visuals  # 31 rows is too few to group


def test_gaps_are_mapped_and_counted():
    df = pd.DataFrame({"a": rng.normal(size=100), "b": rng.normal(size=100)})
    df.loc[::4, "b"] = np.nan
    result = compute_analysis(df.to_csv(index=False).encode(), "gaps.csv")
    quality = {c.id: c for c in result.visuals["quality"]}
    assert {"missing_by_column", "missing_map"} <= set(quality)
    bars = quality["missing_by_column"].plotly_json["data"][0]
    assert dict(zip(bars["y"], bars["x"], strict=True))["b"] == 25.0


def test_clustering_tab_explains_the_choice_of_k():
    centres = [(0, 0), (6, 6), (0, 6)]
    df = pd.DataFrame(np.vstack([rng.normal(c, 0.5, (60, 2)) for c in centres]), columns=["x", "y"])
    result = compute_analysis(df.to_csv(index=False).encode(), "blobs.csv")
    assert ids(result, "clustering") == [
        "silhouette_by_k",
        "cluster_sizes",
        "cluster_profiles",
        "pca_variance",
        "clusters_pca",
    ]
    assert len(result.clustering.k_scores) == 5 and result.clustering.k == 3
    assert len(result.clustering.centers) == 3


def test_identifiers_are_counted_but_not_charted():
    df = pd.DataFrame({"order_id": range(1000, 1050), "amount": rng.normal(100, 5, 50)})
    result = compute_analysis(df.to_csv(index=False).encode(), "orders.csv")
    pie = result.visuals["overview"][0].plotly_json["data"][0]
    assert dict(zip(pie["labels"], pie["values"], strict=True)) == {"numbers": 1, "identifiers": 1}
    hist = next(c for c in result.visuals["explore"] if c.id == "histograms")
    assert "order_id" not in str(hist.plotly_json["layout"])
