import numpy as np
import pandas as pd

from app.services.ml import cluster

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


def test_report_includes_the_groups(client):
    data = blobs(40).assign(segment="x").to_csv(index=False).encode()
    upload = client.post("/api/upload", files={"file": ("blobs.csv", data, "text/csv")})
    html = client.get(f"/api/sessions/{upload.json()['session_id']}/report").text
    assert "<h2>Groups of similar rows</h2>" in html and "fall into 3 groups" in html
    assert "Groups of similar rows (PCA map)" in html
