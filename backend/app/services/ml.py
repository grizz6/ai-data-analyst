"""Clustering: K-means on the standardized numeric columns for every file.

The number of groups is chosen by silhouette score, and the groups are drawn
on a PCA map. When no grouping is clearly better than chance, it says so
instead of presenting arbitrary clusters. Prediction lives in modeling.py.
"""


import numpy as np
import pandas as pd
import plotly.express as px

from app.models.schemas import ChartSpec, ClusterAnalysis, ClusterProfile
from app.utils.json_compat import plotly_figure_to_dict

SEED = 0
# Kept small for a slow, 512 MB server: the silhouette score builds a distance
# matrix, which at 3,000 rows briefly took 140 MB.
CLUSTER_MAX_ROWS = 10_000
SILHOUETTE_MAX_ROWS = 2_000
SKLEARN_WORKING_MEMORY_MB = 16
MAX_FEATURES = 30
MIN_CLUSTER_ROWS = 50
K_RANGE = range(2, 7)
CLEAR_SILHOUETTE = 0.25
PLOT_MAX_POINTS = 2_000




# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def cluster(df: pd.DataFrame) -> ClusterAnalysis | None:
    import sklearn
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.metrics import silhouette_score

    features = _numeric_features(df)[:MAX_FEATURES]
    if len(features) < 2:
        return None
    data = df[features].astype(float)
    data = data.loc[data.notna().mean(axis=1) >= 0.5]  # rows with most of their values
    if len(data) < MIN_CLUSTER_ROWS:
        return None
    data = data.sample(n=min(len(data), CLUSTER_MAX_ROWS), random_state=SEED)
    filled = data.fillna(data.median())
    scaled = ((filled - filled.mean()) / filled.std(ddof=0).replace(0, 1)).to_numpy()

    rng = np.random.default_rng(SEED)
    check = rng.choice(len(scaled), size=min(len(scaled), SILHOUETTE_MAX_ROWS), replace=False)
    best = None
    k_scores: list[float] = []
    for k in K_RANGE:
        if k >= len(scaled):
            break
        model = KMeans(n_clusters=k, n_init=3, random_state=SEED).fit(scaled)
        with sklearn.config_context(working_memory=SKLEARN_WORKING_MEMORY_MB):
            score = float(silhouette_score(scaled[check], model.labels_[check]))
        k_scores.append(round(score, 4))
        if best is None or score > best[1]:
            best = (k, score, model.labels_)
    if best is None:
        return None
    k, score, labels = best

    pca = PCA(n_components=min(len(features), 5), random_state=SEED).fit(scaled)
    coords = pca.transform(scaled)[:, :2]
    clear = score >= CLEAR_SILHOUETTE
    profiles = _profiles(filled, scaled, labels, features)
    analysis = ClusterAnalysis(
        features=features,
        rows_used=len(scaled),
        k=k,
        silhouette=round(score, 4),
        clear=clear,
        clusters=profiles,
        pca_explained=[round(float(v), 4) for v in pca.explained_variance_ratio_],
        k_scores=k_scores,
        centers=[
            [round(float(v), 3) for v in scaled[labels == cluster_id].mean(axis=0)]
            for cluster_id in sorted(set(labels.tolist()))
        ],
        chart=_cluster_chart(coords, labels, pca.explained_variance_ratio_),
        summary="",
    )
    analysis.summary = _cluster_summary(analysis)
    return analysis


def _numeric_features(df: pd.DataFrame) -> list[str]:
    return [
        str(c)
        for c in df.select_dtypes(include="number").columns
        if not pd.api.types.is_bool_dtype(df[c]) and df[c].nunique() > 1
    ]


def _profiles(
    filled: pd.DataFrame, scaled: np.ndarray, labels: np.ndarray, features: list[str]
) -> list[ClusterProfile]:
    profiles = []
    for cluster_id in sorted(set(labels.tolist())):
        members = labels == cluster_id
        centre = scaled[members].mean(axis=0)
        order = np.argsort(-np.abs(centre))[:3]
        profiles.append(
            ClusterProfile(
                cluster=int(cluster_id) + 1,
                size=int(members.sum()),
                distinctive=[
                    {
                        "column": features[i],
                        "mean": round(float(filled.iloc[members, i].mean()), 4),
                        "sd_from_average": round(float(centre[i]), 2),
                    }
                    for i in order
                ],
            )
        )
    profiles.sort(key=lambda p: p.size, reverse=True)
    return profiles


def _cluster_chart(coords: np.ndarray, labels: np.ndarray, explained: np.ndarray) -> ChartSpec:
    rng = np.random.default_rng(SEED)
    keep = rng.choice(len(coords), size=min(len(coords), PLOT_MAX_POINTS), replace=False)
    frame = pd.DataFrame(
        {
            "PC1": coords[keep, 0],
            "PC2": coords[keep, 1],
            "Group": [f"Group {int(label) + 1}" for label in labels[keep]],
        }
    ).sort_values("Group")
    fig = px.scatter(
        frame,
        x="PC1",
        y="PC2",
        color="Group",
        opacity=0.7,
        labels={
            "PC1": f"Component 1 ({explained[0]:.0%} of variation)",
            "PC2": f"Component 2 ({explained[1]:.0%} of variation)",
        },
    )
    fig.update_layout(title="Groups of similar rows (PCA map)")
    return ChartSpec(
        id="clusters_pca",
        title="Groups of similar rows (PCA map)",
        chart_type="scatter",
        plotly_json=plotly_figure_to_dict(fig),
    )


def _cluster_summary(a: ClusterAnalysis) -> str:
    two = sum(a.pca_explained[:2])
    if not a.clear:
        return (
            f"No clear groups: the best split ({a.k} groups) has a silhouette score of {a.silhouette:.2f}, "
            f"under {CLEAR_SILHOUETTE}, so the rows form one continuous spread rather than distinct types. "
            f"The first two principal components capture {two:.0%} of the variation."
        )
    largest = a.clusters[0]
    traits = ", ".join(
        f"{d['column']} {'high' if d['sd_from_average'] > 0 else 'low'}" for d in largest.distinctive[:2]
    )
    return (
        f"The rows fall into {a.k} groups (silhouette {a.silhouette:.2f}). The largest, {largest.size:,} rows, "
        f"stands out for {traits}. The first two principal components capture {two:.0%} of the variation."
    )
