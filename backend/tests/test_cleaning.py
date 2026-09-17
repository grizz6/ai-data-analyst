import pandas as pd

from app.services.cleaning import clean_dataframe
from app.services.pipeline import compute_analysis
from tests.builders import with_nulls


def actions_by_type(actions, action):
    return [a for a in actions if a.action == action]


def test_duplicate_rows_are_removed():
    df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
    cleaned, actions = clean_dataframe(df)
    assert len(cleaned) == 2
    assert actions_by_type(actions, "drop_duplicates")[0].rows_affected == 1


def test_mostly_empty_column_is_dropped():
    df = pd.DataFrame({"sparse": with_nulls(20, 19), "dense": range(20)})
    cleaned, actions = clean_dataframe(df)
    assert "sparse" not in cleaned.columns
    assert [a.column for a in actions_by_type(actions, "drop_column")] == ["sparse"]


def test_numeric_gaps_are_filled_with_median():
    df = pd.DataFrame({"v": [1.0, None, 3.0, 100.0]})
    cleaned, actions = clean_dataframe(df)
    assert cleaned["v"].tolist() == [1.0, 3.0, 3.0, 100.0]
    assert actions_by_type(actions, "impute_median")[0].rows_affected == 1


def test_text_gaps_are_filled_with_mode():
    df = pd.DataFrame({"row": [1, 2, 3, 4], "region": ["West", "West", None, "East"]})
    cleaned, _ = clean_dataframe(df)
    assert cleaned["region"].tolist() == ["West", "West", "West", "East"]


def test_missing_dates_stay_missing_instead_of_taking_the_most_common_date():
    df = pd.DataFrame(
        {
            "order_date": ["2024-01-01", "2024-01-01", None, "2024-01-15", None],
            "v": [1, 2, 3, 4, 5],
        }
    )
    cleaned, actions = clean_dataframe(df)

    assert pd.api.types.is_datetime64_any_dtype(cleaned["order_date"])
    assert cleaned["order_date"].isna().sum() == 2
    assert not any(a.column == "order_date" and a.action.startswith("impute") for a in actions)


def test_date_column_with_many_gaps_is_still_parsed():
    # 40% missing, but every recorded value is a valid date.
    dates = ["2024-02-01", None, "2024-02-03", None, "2024-02-05"] * 4
    cleaned, _ = clean_dataframe(pd.DataFrame({"ship_date": dates, "v": range(20)}))
    assert pd.api.types.is_datetime64_any_dtype(cleaned["ship_date"])


def test_statistics_use_recorded_values_and_the_preview_uses_filled_ones():
    amounts = [10.0, 20.0, 30.0, 40.0, 1000.0] + [None] * 5
    df = pd.DataFrame({"region": list("ABCDEFGHIJ"), "amount": amounts})
    result = compute_analysis(df.to_csv(index=False).encode(), "gaps.csv")

    [summary] = result.numeric_summaries
    assert summary.count == 5
    assert summary.mean == 220.0  # the median fill would have dragged this to 125
    assert next(c for c in result.columns if c.name == "amount").null_count == 5
    assert [row["amount"] for row in result.cleaned_preview_rows][-5:] == [30.0] * 5


def test_date_named_column_is_parsed():
    df = pd.DataFrame({"order_date": ["2024-01-01", "2024-01-08", "2024-01-15"], "v": [1, 2, 3]})
    cleaned, actions = clean_dataframe(df)
    assert pd.api.types.is_datetime64_any_dtype(cleaned["order_date"])
    assert [a.column for a in actions_by_type(actions, "parse_datetime")] == ["order_date"]
