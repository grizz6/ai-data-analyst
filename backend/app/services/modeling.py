"""Predict a column from the others with a broad set of models, honestly evaluated.

The rows are split once: 80% to train, 20% held out as a test set that no
model sees until the end. Each model is cross-validated on the training
rows, refit on all of them, then scored on both the training and the test
rows, so overfitting (high train, low test) shows. The best model is the
one with the highest cross-validation score; the test set only reports how
it does on new rows.

Families compared (scikit-learn):
- baseline: most common value / average, the bar to beat
- linear: logistic regression; linear, ridge and lasso regression
- neighbours: k-nearest neighbours
- bayes: Gaussian naive Bayes
- tree: a single decision tree
- bagging: random forest, bagged trees, extra trees
- boosting: gradient boosting, AdaBoost
- kernel: support vector machine

Imputation, scaling and one-hot encoding are part of every model's
pipeline, so they're fitted on training folds only.
"""

import math
import time
import warnings
from typing import Literal

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app.models.schemas import ChartSpec, FeatureImportance, ModelReport, ModelScore, TargetSuggestion
from app.services.semantics import is_categorical, name_words
from app.utils.json_compat import plotly_figure_to_dict

Task = Literal["classification", "regression"]

SEED = 0
# Sized so a full comparison stays within a few minutes on a slow free server.
MODEL_MAX_ROWS = 2_500
TEST_SHARE = 0.2
MIN_MODEL_ROWS = 30
MAX_CLASSES = 20
MIN_CLASS_ROWS = 5
MAX_ONE_HOT_LEVELS = 20
MAX_FEATURES = 30
FOLDS = 3
OVERFIT_GAP = 0.1
TREES = 40
IMPORTANCE_REPEATS = 3
IMPORTANCE_MAX_ROWS = 500
CHART_MAX_POINTS = 1_500

TARGET_WORDS = {
    "target", "label", "class", "outcome", "result", "churn", "churned", "default", "fraud", "survived",
    "status", "y", "price", "sales", "revenue", "amount", "total", "profit", "cost", "score", "rating",
    "salary", "income", "value", "quantity", "demand", "risk", "grade", "approved", "converted", "spend",
    "spending",
}  # fmt: skip


class ModelRequestError(ValueError):
    """The chosen target can't be modelled. The message is for the user."""


# ---------------------------------------------------------------------------
# Which column to predict
# ---------------------------------------------------------------------------


def suggest_targets(df: pd.DataFrame, limit: int = 5) -> list[TargetSuggestion]:
    """Columns worth predicting, likeliest first: target-like names, then the last usable column."""
    usable = [str(c) for c in df.columns if _target_task(df[c]) is not None]
    scored = []
    for position, col in enumerate(usable):
        words = {w.lower() for w in name_words(col)}
        named = bool(words & TARGET_WORDS)
        last = position == len(usable) - 1
        reason = "name suggests an outcome" if named else "last column" if last else "can be predicted"
        scored.append((not named, not last, position, col, reason))
    scored.sort()
    return [
        TargetSuggestion(column=col, task=_target_task(df[col]) or "regression", reason=reason)
        for *_, col, reason in scored[:limit]
    ]


def _target_task(series: pd.Series) -> Task | None:
    present = series.dropna()
    if len(present) < MIN_MODEL_ROWS or present.nunique() < 2 or pd.api.types.is_datetime64_any_dtype(series):
        return None
    if pd.api.types.is_bool_dtype(series):
        return "classification"
    if pd.api.types.is_numeric_dtype(series):
        if pd.api.types.is_integer_dtype(series) and present.nunique() <= 10:
            return "classification"
        return "regression"
    if is_categorical(series) and present.nunique() <= MAX_CLASSES:
        return "classification"
    return None


# ---------------------------------------------------------------------------
# Training and evaluation
# ---------------------------------------------------------------------------


def predict(df: pd.DataFrame, target: str) -> ModelReport:
    from sklearn.model_selection import train_test_split

    if target not in df.columns:
        raise ModelRequestError(f"'{target}' isn't a column that can be predicted (identifier columns can't).")
    notes: list[str] = []
    data = df.loc[df[target].notna()]
    if len(data) < len(df):
        notes.append(f"{len(df) - len(data):,} rows without '{target}' left out.")
    if len(data) > MODEL_MAX_ROWS:
        data = data.sample(n=MODEL_MAX_ROWS, random_state=SEED)
        notes.append(f"Random {MODEL_MAX_ROWS:,} rows used.")

    task = _task(data[target])
    y = data[target]
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
            notes.append(f"{len(rare)} value(s) of '{target}' with under {MIN_CLASS_ROWS} rows left out.")
        if y.nunique() < 2:
            raise ModelRequestError(f"'{target}' needs at least two values with {MIN_CLASS_ROWS}+ rows each.")
    if len(data) < MIN_MODEL_ROWS:
        raise ModelRequestError(f"Prediction needs at least {MIN_MODEL_ROWS} rows with a value for '{target}'.")

    numeric, categorical, dropped = _features(data, target)
    if not numeric and not categorical:
        raise ModelRequestError("There are no other usable columns to predict it from.")
    X = data[numeric + categorical]

    stratify = y if task == "classification" else None
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SHARE, random_state=SEED, stratify=stratify
    )
    folds = min(FOLDS, int(y_train.value_counts().min())) if task == "classification" else FOLDS
    folds = max(2, folds)

    models = _models(task, numeric, categorical, len(X_train))
    scores, fitted = _evaluate(models, task, X_train, X_test, y_train, y_test, folds)

    baseline = scores[0]
    best = max(scores[1:], key=lambda s: s.cv_mean)
    best_model = fitted[best.name]
    beats = best.cv_mean - best.cv_std > baseline.cv_mean
    importances = _permutation_importance(best_model, X_test, y_test, task)
    metrics, charts = _evaluation_charts(task, scores, fitted, best.name, X_test, y_test)
    charts.insert(1, _learning_curve(best_model, best.name, X_train, y_train, task))
    if importances:
        charts.append(_importance_chart(importances, best.name))
    if dropped:
        listed = ", ".join(dropped[:8]) + ("…" if len(dropped) > 8 else "")
        notes.append(f"Not used as inputs: {listed}.")

    report = ModelReport(
        target=target,
        task=task,
        primary_metric="accuracy" if task == "classification" else "R²",
        secondary_metric="macro F1" if task == "classification" else "MAE",
        rows_used=len(data),
        train_rows=len(X_train),
        test_rows=len(X_test),
        features=numeric + categorical,
        dropped_features=dropped,
        folds=folds,
        scores=scores,
        best_model=best.name,
        beats_baseline=beats,
        best_test_metrics=metrics,
        importances=importances,
        charts=charts,
        notes=notes,
        summary="",
    )
    report.summary = _summary(report, baseline, best)
    return report


def _task(y: pd.Series) -> Task:
    if pd.api.types.is_bool_dtype(y) or not pd.api.types.is_numeric_dtype(y):
        return "classification"
    if pd.api.types.is_integer_dtype(y) and y.nunique() <= 10:
        return "classification"
    return "regression"


def _features(data: pd.DataFrame, target: str) -> tuple[list[str], list[str], list[str]]:
    numeric: list[str] = []
    categorical: list[str] = []
    dropped: list[str] = []
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


def _models(task: Task, numeric: list[str], categorical: list[str], train_rows: int) -> dict[str, tuple[str, object]]:
    from sklearn.compose import ColumnTransformer
    from sklearn.dummy import DummyClassifier, DummyRegressor
    from sklearn.ensemble import (
        AdaBoostClassifier,
        AdaBoostRegressor,
        BaggingClassifier,
        BaggingRegressor,
        ExtraTreesClassifier,
        ExtraTreesRegressor,
        HistGradientBoostingClassifier,
        HistGradientBoostingRegressor,
        RandomForestClassifier,
        RandomForestRegressor,
    )
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Lasso, LinearRegression, LogisticRegression, Ridge
    from sklearn.naive_bayes import GaussianNB
    from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    from sklearn.svm import SVC, SVR
    from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

    def prep(scale: bool) -> ColumnTransformer:
        num_steps: list = [("impute", SimpleImputer(strategy="median"))]
        if scale:
            num_steps.append(("scale", StandardScaler()))
        cat = Pipeline(
            [
                ("impute", SimpleImputer(strategy="most_frequent")),
                ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
            ]
        )
        return ColumnTransformer([("num", Pipeline(num_steps), numeric), ("cat", cat, categorical)])

    def pipe(model, scale: bool = True) -> Pipeline:
        return Pipeline([("prep", prep(scale)), ("model", model)])

    k = max(3, min(25, int(math.sqrt(train_rows)) | 1))
    if task == "classification":
        return {
            "Baseline (most common)": ("baseline", DummyClassifier(strategy="most_frequent")),
            "Logistic regression": ("linear", pipe(LogisticRegression(max_iter=2000))),
            "K-nearest neighbours": ("neighbours", pipe(KNeighborsClassifier(n_neighbors=k))),
            "Naive Bayes": ("bayes", pipe(GaussianNB())),
            "Decision tree": ("tree", pipe(DecisionTreeClassifier(max_depth=8, random_state=SEED), scale=False)),
            "Random forest": (
                "bagging",
                pipe(RandomForestClassifier(n_estimators=TREES, max_depth=12, random_state=SEED), scale=False),
            ),
            "Bagged trees": (
                "bagging",
                pipe(BaggingClassifier(n_estimators=20, random_state=SEED), scale=False),
            ),
            "Extra trees": (
                "bagging",
                pipe(ExtraTreesClassifier(n_estimators=TREES, max_depth=12, random_state=SEED), scale=False),
            ),
            "Gradient boosting": (
                "boosting",
                pipe(
                    HistGradientBoostingClassifier(
                        max_iter=100, early_stopping=True, n_iter_no_change=5, random_state=SEED
                    ),
                    scale=False,
                ),
            ),
            "AdaBoost": ("boosting", pipe(AdaBoostClassifier(n_estimators=60, random_state=SEED), scale=False)),
            "Support vector machine": ("kernel", pipe(SVC(probability=False, random_state=SEED))),
        }
    return {
        "Baseline (average)": ("baseline", DummyRegressor(strategy="mean")),
        "Linear regression": ("linear", pipe(LinearRegression())),
        "Ridge regression": ("linear", pipe(Ridge(alpha=1.0))),
        "Lasso regression": ("linear", pipe(Lasso(alpha=0.01, max_iter=5000))),
        "K-nearest neighbours": ("neighbours", pipe(KNeighborsRegressor(n_neighbors=k))),
        "Decision tree": ("tree", pipe(DecisionTreeRegressor(max_depth=8, random_state=SEED), scale=False)),
        "Random forest": (
            "bagging",
            pipe(RandomForestRegressor(n_estimators=TREES, max_depth=12, random_state=SEED), scale=False),
        ),
        "Bagged trees": ("bagging", pipe(BaggingRegressor(n_estimators=20, random_state=SEED), scale=False)),
        "Extra trees": (
            "bagging",
            pipe(ExtraTreesRegressor(n_estimators=TREES, max_depth=12, random_state=SEED), scale=False),
        ),
        "Gradient boosting": (
            "boosting",
            pipe(
                HistGradientBoostingRegressor(max_iter=100, early_stopping=True, n_iter_no_change=5, random_state=SEED),
                scale=False,
            ),
        ),
        "AdaBoost": ("boosting", pipe(AdaBoostRegressor(n_estimators=60, random_state=SEED), scale=False)),
        "Support vector machine": ("kernel", pipe(SVR())),
    }


def _evaluate(models, task: Task, X_train, X_test, y_train, y_test, folds: int):
    from sklearn.base import clone
    from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, r2_score, roc_auc_score
    from sklearn.model_selection import KFold, StratifiedKFold, cross_val_score

    if task == "classification":
        cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=SEED)
        metric = "accuracy"
    else:
        cv = KFold(n_splits=folds, shuffle=True, random_state=SEED)
        metric = "r2"

    def primary(y_true, y_pred) -> float:
        return float(accuracy_score(y_true, y_pred) if task == "classification" else r2_score(y_true, y_pred))

    scores, fitted = [], {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for name, (family, model) in models.items():
            start = time.perf_counter()
            cv_scores = cross_val_score(clone(model), X_train, y_train, cv=cv, scoring=metric)
            final = clone(model).fit(X_train, y_train)
            elapsed = time.perf_counter() - start
            test_pred = final.predict(X_test)
            train_score = primary(y_train, final.predict(X_train))
            test_score = primary(y_test, test_pred)
            if task == "classification":
                secondary = float(f1_score(y_test, test_pred, average="macro", zero_division=0))
                auc = None
                class_scores = _class_scores(final, X_test)
                if class_scores is not None and family != "baseline":
                    try:
                        if len(final.classes_) == 2:
                            auc = float(roc_auc_score(y_test == final.classes_[1], class_scores[:, 1]))
                        else:
                            auc = float(roc_auc_score(y_test, class_scores, multi_class="ovr", labels=final.classes_))
                    except ValueError:
                        auc = None
            else:
                secondary = float(mean_absolute_error(y_test, test_pred))
                auc = None
            scores.append(
                ModelScore(
                    name=name,
                    family=family,
                    cv_mean=round(float(np.mean(cv_scores)), 4),
                    cv_std=round(float(np.std(cv_scores)), 4),
                    train_score=round(train_score, 4),
                    test_score=round(test_score, 4),
                    test_secondary=round(secondary, 4),
                    test_auc=None if auc is None else round(auc, 4),
                    fit_seconds=round(elapsed, 2),
                    overfit=family != "baseline" and train_score - test_score > OVERFIT_GAP,
                )
            )
            fitted[name] = final
    return scores, fitted


def _class_scores(model, X) -> np.ndarray | None:
    """Per-class scores for ROC curves: probabilities, or decision values turned into two columns."""
    if hasattr(model, "predict_proba"):
        try:
            return np.asarray(model.predict_proba(X))
        except (AttributeError, NotImplementedError):
            pass
    if hasattr(model, "decision_function"):
        values = np.asarray(model.decision_function(X))
        return np.column_stack([-values, values]) if values.ndim == 1 else values
    return None


def _permutation_importance(model, X_test, y_test, task: Task) -> list[FeatureImportance]:
    from sklearn.inspection import permutation_importance

    if len(X_test) > IMPORTANCE_MAX_ROWS:
        X_test = X_test.sample(n=IMPORTANCE_MAX_ROWS, random_state=SEED)
        y_test = y_test.loc[X_test.index]
    scoring = "accuracy" if task == "classification" else "r2"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = permutation_importance(
            model, X_test, y_test, scoring=scoring, n_repeats=IMPORTANCE_REPEATS, random_state=SEED
        )
    ranked = sorted(
        zip(X_test.columns, result.importances_mean, result.importances_std, strict=True),
        key=lambda item: item[1],
        reverse=True,
    )
    return [
        FeatureImportance(feature=str(col), importance=round(float(mean), 4), spread=round(float(std), 4))
        for col, mean, std in ranked[:12]
    ]


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


def _spec(fig: go.Figure, chart_id: str, title: str, chart_type: str) -> ChartSpec:
    fig.update_layout(title=title)
    return ChartSpec(id=chart_id, title=title, chart_type=chart_type, plotly_json=plotly_figure_to_dict(fig))


def _comparison_chart(scores: list[ModelScore], metric: str) -> ChartSpec:
    ordered = sorted(scores, key=lambda s: s.cv_mean)
    names = [s.name for s in ordered]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=names,
            x=[s.cv_mean for s in ordered],
            orientation="h",
            name="cross-validation",
            error_x={"type": "data", "array": [s.cv_std for s in ordered]},
        )
    )
    fig.add_trace(
        go.Scatter(
            y=names,
            x=[s.test_score for s in ordered],
            mode="markers",
            name="test",
            marker={"size": 10, "symbol": "diamond"},
        )
    )
    fig.add_trace(
        go.Scatter(
            y=names,
            x=[s.train_score for s in ordered],
            mode="markers",
            name="train",
            marker={"size": 8, "symbol": "circle-open"},
        )
    )
    fig.update_layout(xaxis_title=metric, legend={"orientation": "h"}, height=max(320, 32 * len(names)))
    return _spec(fig, "model_comparison", f"Models compared ({metric})", "bar")


def _learning_curve(model, name: str, X_train, y_train, task: Task) -> ChartSpec:
    from sklearn.model_selection import learning_curve

    scoring = "accuracy" if task == "classification" else "r2"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sizes, train, valid = learning_curve(
            model,
            X_train,
            y_train,
            train_sizes=np.linspace(0.25, 1.0, 4),
            cv=3,
            scoring=scoring,
            shuffle=True,
            random_state=SEED,
        )
    fig = go.Figure()
    for label, values in (("train", train), ("validation", valid)):
        mean, std = values.mean(axis=1), values.std(axis=1)
        fig.add_trace(
            go.Scatter(
                x=sizes,
                y=mean,
                mode="lines+markers",
                name=label,
                error_y={"type": "data", "array": std, "visible": True},
            )
        )
    fig.update_layout(xaxis_title="training rows", yaxis_title=scoring.replace("r2", "R²"), legend={"orientation": "h"})
    return _spec(fig, "learning_curve", f"Learning curve: {name}", "line")


def _importance_chart(importances: list[FeatureImportance], name: str) -> ChartSpec:
    ordered = list(reversed(importances))
    fig = go.Figure(
        go.Bar(
            y=[i.feature for i in ordered],
            x=[i.importance for i in ordered],
            orientation="h",
            error_x={"type": "data", "array": [i.spread for i in ordered]},
        )
    )
    fig.update_layout(xaxis_title="drop in test score when shuffled", height=max(300, 28 * len(ordered)))
    return _spec(fig, "permutation_importance", f"What matters most: {name}", "bar")


def _evaluation_charts(
    task: Task, scores, fitted, best: str, X_test, y_test
) -> tuple[dict[str, float], list[ChartSpec]]:
    charts = [_comparison_chart(scores, "accuracy" if task == "classification" else "R²")]
    model = fitted[best]
    pred = model.predict(X_test)
    if task == "classification":
        return _classification_charts(charts, scores, fitted, best, X_test, y_test, pred)
    return _regression_charts(charts, best, y_test, pred)


def _classification_charts(charts, scores, fitted, best, X_test, y_test, pred):
    from sklearn.metrics import (
        auc,
        average_precision_score,
        confusion_matrix,
        precision_recall_curve,
        precision_score,
        recall_score,
        roc_curve,
    )

    model = fitted[best]
    labels = [str(c) for c in model.classes_]
    matrix = confusion_matrix(y_test, pred, labels=model.classes_)
    fig = px.imshow(
        matrix, x=labels, y=labels, text_auto=True, color_continuous_scale="Blues",
        labels={"x": "predicted", "y": "actual", "color": "rows"},
    )  # fmt: skip
    charts.append(_spec(fig, "confusion_matrix", f"Confusion matrix (test rows): {best}", "heatmap"))

    metrics = {
        "accuracy": round(float((pred == y_test).mean()), 4),
        "precision (macro)": round(float(precision_score(y_test, pred, average="macro", zero_division=0)), 4),
        "recall (macro)": round(float(recall_score(y_test, pred, average="macro", zero_division=0)), 4),
    }
    best_score = next(s for s in scores if s.name == best)
    if best_score.test_auc is not None:
        metrics["ROC AUC"] = best_score.test_auc

    if len(labels) == 2:
        positive = model.classes_[1]
        truth = (y_test == positive).to_numpy()
        roc = go.Figure()
        ranked = sorted((s for s in scores if s.test_auc is not None), key=lambda s: s.test_auc or 0, reverse=True)[:5]
        for s in ranked:
            values = _class_scores(fitted[s.name], X_test)
            if values is None:
                continue
            fpr, tpr, _ = roc_curve(truth, values[:, 1])
            roc.add_trace(go.Scatter(x=fpr, y=tpr, mode="lines", name=f"{s.name} (AUC {auc(fpr, tpr):.2f})"))
        roc.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines", line={"dash": "dot"}, name="chance"))
        roc.update_layout(
            xaxis_title="false positive rate", yaxis_title="true positive rate", legend={"orientation": "h"}
        )
        charts.append(_spec(roc, "roc_curves", f"ROC curves (test rows, positive = {positive})", "line"))

        values = _class_scores(model, X_test)
        if values is not None:
            precision, recall, _ = precision_recall_curve(truth, values[:, 1])
            pr = go.Figure(go.Scatter(x=recall, y=precision, mode="lines", name=best))
            pr.add_hline(y=float(truth.mean()), line_dash="dot")
            pr.update_layout(xaxis_title="recall", yaxis_title="precision", showlegend=False)
            metrics["average precision"] = round(float(average_precision_score(truth, values[:, 1])), 4)
            charts.append(_spec(pr, "precision_recall", f"Precision–recall: {best}", "line"))
    return metrics, charts


def _regression_charts(charts, best, y_test, pred):
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    actual = np.asarray(y_test, dtype=float)
    residual = actual - pred
    keep: np.ndarray = np.arange(len(actual))
    if len(keep) > CHART_MAX_POINTS:
        keep = np.random.default_rng(SEED).choice(len(actual), CHART_MAX_POINTS, replace=False)

    low, high = float(min(actual.min(), pred.min())), float(max(actual.max(), pred.max()))
    fig = go.Figure(go.Scatter(x=actual[keep], y=pred[keep], mode="markers", opacity=0.6, name="test rows"))
    fig.add_trace(go.Scatter(x=[low, high], y=[low, high], mode="lines", line={"dash": "dot"}, name="perfect"))
    fig.update_layout(xaxis_title="actual", yaxis_title="predicted", showlegend=False)
    charts.append(_spec(fig, "predicted_vs_actual", f"Predicted vs actual (test rows): {best}", "scatter"))

    fig = go.Figure(go.Scatter(x=pred[keep], y=residual[keep], mode="markers", opacity=0.6))
    fig.add_hline(y=0, line_dash="dot")
    fig.update_layout(xaxis_title="predicted", yaxis_title="actual − predicted")
    charts.append(_spec(fig, "residuals", f"Residuals (test rows): {best}", "scatter"))

    fig = go.Figure(go.Histogram(x=residual, nbinsx=30))
    fig.update_layout(xaxis_title="actual − predicted", yaxis_title="rows")
    charts.append(_spec(fig, "residual_histogram", "Residual distribution", "histogram"))

    metrics = {
        "R²": round(float(r2_score(actual, pred)), 4),
        "MAE": round(float(mean_absolute_error(actual, pred)), 4),
        "RMSE": round(float(math.sqrt(mean_squared_error(actual, pred))), 4),
    }
    return metrics, charts


def _summary(r: ModelReport, baseline: ModelScore, best: ModelScore) -> str:
    if r.task == "classification":
        score = f"{best.test_score:.0%} test accuracy vs {baseline.test_score:.0%} baseline"
    else:
        score = f"test R² {best.test_score:.2f} vs {baseline.test_score:.2f} baseline"
    if not r.beats_baseline:
        return f"No model beats the baseline reliably for '{r.target}' (best: {r.best_model}, {score})."
    overfit = " Overfits: train score well above test." if best.overfit else ""
    return f"Best for '{r.target}': {r.best_model}, {score}.{overfit}"
