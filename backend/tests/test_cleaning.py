import pandas as pd

from app.services.cleaning import clean_dataframe
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


def test_date_named_column_is_parsed():
    df = pd.DataFrame({"order_date": ["2024-01-01", "2024-01-08", "2024-01-15"], "v": [1, 2, 3]})
    cleaned, actions = clean_dataframe(df)
    assert pd.api.types.is_datetime64_any_dtype(cleaned["order_date"])
    assert [a.column for a in actions_by_type(actions, "parse_datetime")] == ["order_date"]
