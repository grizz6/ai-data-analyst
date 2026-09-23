import numpy as np
import pandas as pd
import pytest

from app.services.cleaning import clean_dataframe, prepare_dataframe
from app.services.pipeline import compute_analysis
from app.services.quality import check_quality
from app.services.semantics import label_variants, parse_numeric_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$1,200", 1200.0),
        ("1,234,567.89", 1234567.89),
        (" 12.5 ", 12.5),
        ("45%", 45.0),
        ("(300)", -300.0),
        ("-$75", -75.0),
        ("€20", 20.0),
    ],
)
def test_numeric_text_formats_are_parsed(raw, expected):
    series = pd.Series([raw] * 9 + ["$1"])
    assert parse_numeric_text(series).iloc[0] == pytest.approx(expected)


def test_placeholders_become_missing_not_zero():
    series = pd.Series(["$10", "$20", "N/A", "$30", "$40", "$50", "$60", "$70", "$80", "$90", "$100"])
    parsed = parse_numeric_text(series)
    assert parsed.isna().tolist() == [False, False, True] + [False] * 8


@pytest.mark.parametrize(
    "values",
    [
        ["West", "East", "North"] * 5,  # real text
        ["00123", "00456", "00789"] * 5,  # codes with leading zeros must keep them
        ["2024-01-05", "2024-02-05", "2024-03-05"] * 5,  # dates
        ["$10", "ten", "twenty", "thirty"] * 5,  # mostly words
    ],
)
def test_text_that_is_not_numbers_is_left_alone(values):
    assert parse_numeric_text(pd.Series(values)) is None


def test_numeric_text_is_converted_and_logged():
    prices = ["$1,200", "$950", "$1,050"] * 4
    prices[5] = "unknown"
    df = pd.DataFrame({"row": range(12), "price": prices})
    prepared, actions = prepare_dataframe(df)

    assert pd.api.types.is_float_dtype(prepared["price"])
    assert prepared["price"].isna().sum() == 1  # "unknown" is missing, not zero
    [action] = [a for a in actions if a.action == "convert_numeric_text"]
    assert action.column == "price"
    assert "1 value(s) that weren't numbers became missing" in action.description


def test_too_much_non_numeric_text_blocks_conversion():
    df = pd.DataFrame({"row": range(12), "price": ["$1,200", "$950", "$1,050", "unknown"] * 3})
    cleaned, _ = clean_dataframe(df)
    assert cleaned["price"].dtype == object


def test_label_variants_group_case_and_spacing_under_the_common_spelling():
    series = pd.Series(["West", "West", "West", "west ", "WEST", "East", "East", " east", "North"])
    assert label_variants(series) == {"West": ["West", "west ", "WEST"], "East": ["East", " east"]}


def test_different_words_are_not_treated_as_variants():
    assert label_variants(pd.Series(["NY", "New York", "NY", "New York"])) == {}


def test_labels_are_unified_in_cleaning():
    df = pd.DataFrame(
        {"row": range(9), "region": ["West", "West", "West", "west ", "WEST", "East", "East", " east", "North"]}
    )
    cleaned, actions = clean_dataframe(df)

    assert sorted(cleaned["region"].unique()) == ["East", "North", "West"]
    [action] = [a for a in actions if a.action == "unify_labels"]
    assert action.rows_affected == 3


def test_quality_report_flags_both_problems():
    df = pd.DataFrame(
        {
            "price": ["$1,200", "$950", "$1,050", "$990"] * 5,
            "region": ["West", "west", "East", "East"] * 5,
        }
    )
    categories = {(i.category, i.column) for i in check_quality(df)}
    assert {("type", "price"), ("labels", "region")} <= categories


def test_converted_column_gets_statistics_end_to_end():
    rng = np.random.default_rng(1)
    amounts = rng.integers(500, 1500, size=40)
    df = pd.DataFrame(
        {
            "region": (["West", "west ", "East", "EAST"] * 10),
            "amount": [f"${a:,}" for a in amounts],
        }
    )
    result = compute_analysis(df.to_csv(index=False).encode(), "messy.csv")

    [summary] = result.numeric_summaries
    assert summary.column == "amount"
    assert summary.mean == pytest.approx(float(amounts.mean()), abs=1e-4)
    [regions] = result.categorical_summaries
    assert {v["value"] for v in regions.top_values} == {"West", "East"}
