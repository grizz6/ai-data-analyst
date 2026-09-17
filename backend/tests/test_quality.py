import pandas as pd

from app.services.quality import check_quality
from tests.builders import with_nulls, with_outliers


def issues_for(issues, category, column=None):
    return [i for i in issues if i.category == category and (column is None or i.column == column)]


def test_missingness_severity_follows_thresholds():
    n = 100
    df = pd.DataFrame(
        {
            "mostly_empty": with_nulls(n, 91),
            "half_empty": with_nulls(n, 55),
            "few_gaps": with_nulls(n, 10),
            "complete": with_nulls(n, 0),
        }
    )
    issues = check_quality(df)

    assert [i.severity for i in issues_for(issues, "missing", "mostly_empty")] == ["error"]
    assert [i.severity for i in issues_for(issues, "missing", "half_empty")] == ["warning"]
    assert [i.severity for i in issues_for(issues, "missing", "few_gaps")] == ["info"]
    assert issues_for(issues, "missing", "complete") == []


def test_constant_column_is_flagged():
    df = pd.DataFrame({"country": ["US"] * 10, "value": range(10)})
    issues = check_quality(df)
    assert [i.column for i in issues_for(issues, "constant")] == ["country"]


def test_exactly_the_planted_outliers_are_counted():
    df = pd.DataFrame({"amount": with_outliers(97, [500.0, 600.0, -300.0])})
    [issue] = issues_for(check_quality(df), "outliers", "amount")
    assert issue.details["outlier_count"] == 3


def test_duplicate_rows_are_counted():
    df = pd.DataFrame({"a": [1, 1, 1, 2], "b": ["x", "x", "x", "y"]})
    [issue] = issues_for(check_quality(df), "duplicates")
    assert issue.details["duplicate_rows"] == 2


def test_empty_dataset_is_an_error():
    issues = check_quality(pd.DataFrame({"a": []}))
    assert [(i.category, i.severity) for i in issues] == [("empty", "error")]
