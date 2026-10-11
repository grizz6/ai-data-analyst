"""Each test plants a known pattern and checks the statistic finds it, and that noise doesn't."""

import numpy as np
import pandas as pd
import pytest

from app.services.statistics import benjamini_hochberg, compute_statistics

N = 600


@pytest.fixture(scope="module")
def planted() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    x = rng.uniform(0, 4, N)
    region = rng.choice(["North", "South", "East"], N)
    mostly_basic = rng.choice(["basic", "pro"], N, p=[0.9, 0.1])
    mostly_pro = rng.choice(["basic", "pro"], N, p=[0.2, 0.8])
    plan = np.where(region == "North", mostly_basic, mostly_pro)
    spend = np.select([region == "North", region == "South"], [100.0, 200.0], 150.0) + rng.normal(0, 10, N)
    df = pd.DataFrame(
        {
            "normal": rng.normal(50, 5, N),
            "skewed": rng.lognormal(0, 1, N),
            "x": x,
            "curve": np.exp(x),  # monotonic but far from a straight line
            "noise": rng.normal(0, 1, N),
            "region": region,
            "plan": plan,
            "colour": rng.choice(["red", "blue"], N),  # unrelated to everything
            "spend": spend,
        }
    )
    gaps = rng.random(N) < 0.2
    df["email"] = np.where(gaps, None, "a@b.c")
    df["phone_ext"] = np.where(gaps, np.nan, 1.0)  # missing on exactly the same rows
    return df


@pytest.fixture(scope="module")
def tests(planted):
    return compute_statistics(planted)


def find(rows, **match):
    return next(r for r in rows if all(getattr(r, k) == v for k, v in match.items()))


def test_distribution_shape_and_normality(tests):
    normal = find(tests.distributions, column="normal")
    skewed = find(tests.distributions, column="skewed")
    assert normal.shape == "roughly symmetric" and normal.normality_p > 0.05
    assert skewed.shape.startswith("strongly right-skewed") and skewed.normality_p < 0.001
    assert skewed.zscore_outliers > 0


def test_rank_correlation_sees_a_monotonic_curve_that_pearson_understates(tests):
    pair = find(tests.rank_correlations, column_a="x", column_b="curve")
    assert pair.spearman == pytest.approx(1.0)
    assert pair.kendall == pytest.approx(1.0)
    assert pair.pearson < 0.95
    assert pair.p_adjusted < 0.001
    assert not any("noise" in (r.column_a, r.column_b) for r in tests.rank_correlations)


def test_association_between_categories(tests):
    linked = find(tests.categorical_associations, column_a="region", column_b="plan")
    assert linked.cramers_v > 0.5 and linked.p_adjusted < 0.001
    unrelated = [r for r in tests.categorical_associations if "colour" in (r.column_a, r.column_b)]
    assert all(r.cramers_v < 0.15 for r in unrelated)


def test_group_difference_names_the_highest_and_lowest_group(tests):
    diff = find(tests.group_differences, group_column="region", value_column="spend")
    assert diff.eta_squared > 0.9
    assert (diff.highest_group, diff.lowest_group) == ("South", "North")
    assert diff.highest_mean == pytest.approx(200, abs=3)
    assert diff.anova_p < 0.001 and diff.p_adjusted < 0.001
    assert tests.group_differences[0].value_column == "spend"  # strongest effect first


def test_columns_missing_together(tests):
    pattern = find(tests.missing_patterns, column_a="email", column_b="phone_ext")
    assert pattern.correlation == pytest.approx(1.0)
    assert pattern.both_missing > 0


def test_benjamini_hochberg_matches_the_textbook_procedure():
    # Worked example: sorted p 0.01, 0.02, 0.03, 0.5 with m = 4.
    assert benjamini_hochberg([0.03, 0.5, 0.01, 0.02]) == pytest.approx([0.04, 0.5, 0.04, 0.04])
    assert benjamini_hochberg([]) == []


def test_degenerate_inputs_dont_crash():
    empty = compute_statistics(pd.DataFrame({"a": [1.0, 1.0, 1.0], "b": ["x", "x", "x"]}))
    assert empty.distributions == [] and empty.group_differences == []
    assert compute_statistics(pd.DataFrame()).rank_correlations == []


def test_statistics_reach_the_api(client, sample_csv_bytes):
    body = client.post("/api/upload", files={"file": ("s.csv", sample_csv_bytes, "text/csv")}).json()
    stats = body["statistics"]
    assert {d["column"] for d in stats["distributions"]} == {"sales", "units"}
    assert stats["rank_correlations"][0]["column_a"] == "sales"
    assert any(g["group_column"] in ("region", "product") for g in stats["group_differences"])


def test_report_includes_the_statistical_tests(client, sample_csv_bytes):
    upload = client.post("/api/upload", files={"file": ("s.csv", sample_csv_bytes, "text/csv")})
    session_id = upload.json()["session_id"]
    html = client.get(f"/api/sessions/{session_id}/report").text
    assert "<h2>Statistical tests</h2>" in html
    assert "Differences between groups" in html and "Product A" in html
