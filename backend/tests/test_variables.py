"""Per-variable profiles: kinds, outliers with their likely causes, and binary comparisons."""

import numpy as np
import pandas as pd
import pytest

from app.services.pipeline import compute_analysis

rng = np.random.default_rng(11)
N = 600


@pytest.fixture(scope="module")
def churn():
    tenure = rng.integers(1, 60, N)
    churned = rng.random(N) < 1 / (1 + np.exp(-(1.5 - 0.08 * tenure)))
    age = rng.normal(40, 8, N).round()
    age[[5, 17, 30]] = [999, -4, 4100]  # placeholder code, sign error, extra zeros
    df = pd.DataFrame(
        {
            "customer_id": np.arange(5000, 5000 + N),
            "tenure_months": tenure,
            "age": age,
            "children": rng.integers(0, 4, N),
            "plan": rng.choice(["basic", "plus", "pro"], N),
            "is_active": rng.integers(0, 2, N),
            "churned": np.where(churned, "Yes", "No"),
            "joined": pd.date_range("2021-01-01", periods=N, freq="D"),
            "note": [f"free text {i}" for i in range(N)],
            "country": "NZ",
        }
    )
    result = compute_analysis(df.to_csv(index=False).encode(), "churn.csv")
    return {v.name: v for v in result.variables}


def test_every_column_gets_a_kind(churn):
    kinds = {name: v.kind for name, v in churn.items()}
    assert kinds == {
        "customer_id": "identifier",
        "tenure_months": "number",
        "age": "number",
        "children": "count",
        "plan": "category",
        "is_active": "binary",
        "churned": "binary",
        "joined": "date",
        "note": "text",
        "country": "constant",
    }


def test_planted_outliers_are_found_with_their_likely_cause(churn):
    outliers = churn["age"].outliers
    causes = {row.value: row.cause for row in outliers.rows}
    assert "placeholder" in causes[999]
    assert "never negative" in causes[-4]
    assert "100x the median" in causes[4100]
    # Rows are numbered from 1 and carry the identifier, so they can be found in the file.
    by_value = {row.value: row for row in outliers.rows}
    assert by_value[4100].row == 31 and by_value[4100].label == "5030"
    assert outliers.mean_all > outliers.mean_without
    assert outliers.z_count >= 2 and outliers.iqr_count >= 3


def test_binary_column_lists_what_differs_between_its_groups(churn):
    churned = churn["churned"]
    assert churned.binary.positive == "Yes"
    top = churned.compared[0]
    assert top.column == "tenure_months" and top.effect < -0.4 and top.p_value < 0.001
    assert "when churned = Yes" in top.detail


def test_numbers_are_split_by_each_binary_column(churn):
    split = next(s for s in churn["tenure_months"].splits if s.binary_column == "churned")
    yes, no = split.groups
    assert yes.label == "churned = Yes" and yes.box.median < no.box.median


def test_numeric_charts_are_sent_as_data(churn):
    tenure = churn["tenure_months"]
    assert sum(tenure.histogram.counts) == N
    assert len(tenure.histogram.edges) == len(tenure.histogram.counts) + 1
    assert len(tenure.density.x) == len(tenure.density.y) > 10
    assert len(tenure.qq.x) == 100
    assert tenure.timeline_label.startswith("average per week")
    # Few whole-number values get one bar each.
    assert len(churn["children"].histogram.counts) == 4


def test_lopsided_binary_columns_are_flagged():
    df = pd.DataFrame({"fraud": [1] * 5 + [0] * 195, "amount": rng.gamma(2, 50, 200)})
    result = compute_analysis(df.to_csv(index=False).encode(), "fraud.csv")
    fraud = next(v for v in result.variables if v.name == "fraud")
    assert fraud.binary.positive == "1" and fraud.binary.positive_share == 2.5
    assert any("Lopsided" in f for f in fraud.flags)


def test_far_out_values_zoom_the_charts_instead_of_squashing_them(churn):
    age = churn["age"]
    low, high = age.view
    assert high < 999 and low > -4  # 999, -4 and 4100 are far out (beyond 3 x IQR)
    assert age.beyond_view == 3
    assert age.histogram.edges[-1] <= high + 1e-9 and sum(age.histogram.counts) == N - 3
    # A column without far-out values isn't zoomed.
    assert churn["tenure_months"].view is None and churn["tenure_months"].beyond_view == 0
