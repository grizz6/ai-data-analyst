"""Machine learning on the prepared data: clustering for everyone, prediction on request.

- Clustering runs with every analysis: K-means on the standardized numeric
  columns, with the number of groups chosen by silhouette score, and a PCA
  map to draw them. When no grouping is clearly better than chance, it says
  so instead of presenting arbitrary clusters.
- Prediction runs when someone picks a target column: a naive baseline,
  k-nearest neighbours, a linear model and a random forest, compared with
  k-fold cross-validation. Imputation, scaling and one-hot encoding are part
  of each model's pipeline, so they are fitted inside every fold and the
  scores aren't flattered by the rows they're tested on.

Row counts are capped so this stays quick on a small server.
"""

import math
import warnings
from typing import Literal

import numpy as np
import pandas as pd
import plotly.express as px

from app.models.schemas import (
    ChartSpec,
    ClusterAnalysis,
    ClusterProfile,
    FeatureImportance,
    ModelReport,
    ModelScore,
)
from app.services.semantics import is_categorical
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

MODEL_MAX_ROWS = 5_000
FOREST_TREES = 50
MIN_MODEL_ROWS = 30
MAX_CLASSES = 20
MIN_CLASS_ROWS = 5
MAX_ONE_HOT_LEVELS = 20
FOLDS = 5


class ModelRequestError(ValueError):
    """The chosen target can't be modelled. The message is for the user."""


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
    for k in K_RANGE:
        if k >= len(scaled):
            break
        model = KMeans(n_clusters=k, n_init=3, random_state=SEED).fit(scaled)
        with sklearn.config_context(working_memory=SKLEARN_WORKING_MEMORY_MB):
            score = float(silhouette_score(scaled[check], model.labels_[check]))
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


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------


def predict(df: pd.DataFrame, target: str) -> ModelReport:
    from sklearn.compose import ColumnTransformer
    from sklearn.dummy import DummyClassifier, DummyRegressor
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.model_selection import KFold, StratifiedKFold, cross_validate
    from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    if target not in df.columns:
        raise ModelRequestError(f"'{target}' isn't a column that can be predicted (identifier columns can't).")
    notes: list[str] = []
    data = df.loc[df[target].notna()]
    if len(data) < len(df):
        notes.append(f"{len(df) - len(data):,} rows without a value for '{target}' were left out.")
    if len(data) > MODEL_MAX_ROWS:
        data = data.sample(n=MODEL_MAX_ROWS, random_state=SEED)
        notes.append(f"Trained on a random {MODEL_MAX_ROWS:,} rows to keep this quick.")

    y = data[target]
    task = _task(y)
    if task == "classification":
        y = y.astype(str)
        counts = y.value_counts()
        if len(counts) > MAX_CLASSES:
            raise ModelRequestError(
                f"'{target}' has {len(counts)} different values; prediction works for up to {MAX_CLASSES} "
                "categories, or for a numeric column."
            )
        rare = counts[counts < MIN_CLASS_ROWS].index
        if len(rare):
            keep = ~y.isin(rare)
            data, y = data.loc[keep], y.loc[keep]
            notes.append(f"{len(rare)} value(s) of '{target}' with under {MIN_CLASS_ROWS} rows were left out.")
        if y.nunique() < 2:
            raise ModelRequestError(f"'{target}' needs at least two values with {MIN_CLASS_ROWS}+ rows each.")
    if len(data) < MIN_MODEL_ROWS:
        raise ModelRequestError(f"Prediction needs at least {MIN_MODEL_ROWS} rows with a value for '{target}'.")

    numeric, categorical, dropped = _model_features(data, target)
    if not numeric and not categorical:
        raise ModelRequestError("There are no other usable columns to predict it from.")
    X = data[numeric + categorical]

    def preprocess(scale: bool) -> ColumnTransformer:
        num_steps: list = [("impute", SimpleImputer(strategy="median"))]
        if scale:
            num_steps.append(("scale", StandardScaler()))
        return ColumnTransformer(
            [
                ("num", Pipeline(num_steps), numeric),
                (
                    "cat",
                    Pipeline(
                        [
                            ("impute", SimpleImputer(strategy="most_frequent")),
                            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                        ]
                    ),
                    categorical,
                ),
            ]
        )

    if task == "classification":
        folds = min(FOLDS, int(y.value_counts().min()))
        cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=SEED)
        scoring = {"primary": "accuracy", "secondary": "f1_macro"}
        models = {
            "Baseline (most common value)": DummyClassifier(strategy="most_frequent"),
            "K-nearest neighbours": Pipeline(
                [("prep", preprocess(True)), ("model", KNeighborsClassifier(n_neighbors=_k(len(data))))]
            ),
            "Logistic regression": Pipeline([("prep", preprocess(True)), ("model", LogisticRegression(max_iter=2000))]),
            "Random forest": Pipeline(
                [
                    ("prep", preprocess(False)),
                    ("model", RandomForestClassifier(n_estimators=FOREST_TREES, max_depth=12, random_state=SEED)),
                ]
            ),
        }
        labels = ("accuracy", "macro F1")
    else:
        folds = FOLDS
        cv = KFold(n_splits=folds, shuffle=True, random_state=SEED)
        scoring = {"primary": "r2", "secondary": "neg_mean_absolute_error"}
        models = {
            "Baseline (average)": DummyRegressor(strategy="mean"),
            "K-nearest neighbours": Pipeline(
                [("prep", preprocess(True)), ("model", KNeighborsRegressor(n_neighbors=_k(len(data))))]
            ),
            "Linear regression (ridge)": Pipeline([("prep", preprocess(True)), ("model", Ridge(alpha=1.0))]),
            "Random forest": Pipeline(
                [
                    ("prep", preprocess(False)),
                    ("model", RandomForestRegressor(n_estimators=FOREST_TREES, max_depth=12, random_state=SEED)),
                ]
            ),
        }
        labels = ("R²", "mean absolute error")

    scores = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for name, model in models.items():
            result = cross_validate(model, X, y, cv=cv, scoring=scoring)
            secondary = float(np.mean(result["test_secondary"]))
            scores.append(
                ModelScore(
                    name=name,
                    primary=round(float(np.mean(result["test_primary"])), 4),
                    primary_std=round(float(np.std(result["test_primary"])), 4),
                    secondary=round(-secondary if task == "regression" else secondary, 4),
                )
            )
        forest = models["Random forest"].fit(X, y)

    baseline, *candidates = scores
    best = max(candidates, key=lambda s: s.primary)
    beats = best.primary - best.primary_std > baseline.primary
    importances = _importances(forest, numeric, categorical)
    if dropped:
        listed = ", ".join(dropped[:8]) + ("…" if len(dropped) > 8 else "")
        notes.append(f"Left out as inputs: {listed} (dates, mostly-empty columns, or text with many different values).")

    report = ModelReport(
        target=target,
        task=task,
        primary_metric=labels[0],
        secondary_metric=labels[1],
        rows_used=len(data),
        features=numeric + categorical,
        dropped_features=dropped,
        folds=folds,
        scores=scores,
        best_model=best.name,
        beats_baseline=beats,
        importances=importances,
        notes=notes,
        summary="",
    )
    report.summary = _model_summary(report, baseline)
    return report


def _task(y: pd.Series) -> Literal["classification", "regression"]:
    if pd.api.types.is_bool_dtype(y) or not pd.api.types.is_numeric_dtype(y):
        return "classification"
    if pd.api.types.is_integer_dtype(y) and y.nunique() <= 10:
        return "classification"
    return "regression"


def _k(rows: int) -> int:
    """Neighbours for KNN: about the square root of the rows in a training fold, kept odd and modest."""
    k = int(math.sqrt(rows * (FOLDS - 1) / FOLDS))
    return max(3, min(25, k | 1))


def _model_features(data: pd.DataFrame, target: str) -> tuple[list[str], list[str], list[str]]:
    numeric, categorical, dropped = [], [], []
    for col in data.columns:
        if col == target:
            continue
        series = data[col]
        if series.notna().mean() < 0.5:
            dropped.append(str(col))
        elif pd.api.types.is_bool_dtype(series):
            categorical.append(str(col))
        elif pd.api.types.is_numeric_dtype(series):
            numeric.append(str(col))
        elif (
            not pd.api.types.is_datetime64_any_dtype(series)
            and is_categorical(series)
            and series.nunique() <= MAX_ONE_HOT_LEVELS
        ):
            categorical.append(str(col))
        else:
            dropped.append(str(col))
    return numeric[:MAX_FEATURES], categorical[:MAX_FEATURES], dropped


def _importances(forest, numeric: list[str], categorical: list[str]) -> list[FeatureImportance]:
    """Random-forest importances, with one-hot columns added back up to the column they came from."""
    prep = forest.named_steps["prep"]
    raw = forest.named_steps["model"].feature_importances_
    totals: dict[str, float] = {}
    names = prep.get_feature_names_out()
    for name, value in zip(names, raw, strict=True):
        kind, column = name.split("__", 1)
        if kind == "cat":
            column = next((c for c in categorical if column == c or column.startswith(f"{c}_")), column)
        totals[column] = totals.get(column, 0.0) + float(value)
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:10]
    return [FeatureImportance(feature=f, importance=round(v, 4)) for f, v in ranked]


def _model_summary(r: ModelReport, baseline: ModelScore) -> str:
    best = next(s for s in r.scores if s.name == r.best_model)
    metric = r.primary_metric
    if r.task == "classification":
        level = f"{best.primary:.0%} {metric} against {baseline.primary:.0%} for always guessing the most common value"
    else:
        level = f"{metric} {best.primary:.2f} (1 is perfect, 0 is no better than the average)"
    top = ", ".join(i.feature for i in r.importances[:3])
    if not r.beats_baseline:
        return (
            f"None of the models predicts '{r.target}' reliably better than the baseline across {r.folds} folds "
            f"(best: {r.best_model}, {level}). The other columns don't carry much information about it."
        )
    return (
        f"'{r.target}' can be predicted from the other columns: the {r.best_model} reaches {level}, "
        f"averaged over {r.folds} cross-validation folds. The columns that matter most are {top}."
    )
