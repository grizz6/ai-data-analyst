import pytest

from app.services.grounding import numbers_in, ungrounded_numbers

FACTS = {
    "rows": 31,
    "sales_mean": 12500.0,
    "correlation": 0.9832,
    "trend_change_pct": -3.5,
    "first_date": "2024-01-05T00:00:00",
}


@pytest.mark.parametrize(
    "text",
    [
        "The file has 31 rows.",
        "Average sales were 12,500.",
        "Sales and units are closely linked (correlation 0.98).",
        "Correlation is about 1.",
        "Correlation 0.9832.",
        "Sales fell 3.5% over the period.",
        "Records start on 2024-01-05.",
        "Nothing numeric here at all.",
    ],
)
def test_numbers_taken_from_the_facts_pass(text):
    assert ungrounded_numbers(text, FACTS) == []


@pytest.mark.parametrize(
    ("text", "invented"),
    [
        ("Sales totalled 387,500 across the year.", ["387,500"]),  # 31 × 12,500: arithmetic
        ("Sales are 98% correlated with units.", ["98"]),  # 0.9832 restated as a new figure
        ("Correlation was 0.99.", ["0.99"]),  # rounded the wrong way
        ("There are 32 rows and average sales of 12,500.", ["32"]),
        ("Revenue grew 12% and 7% in two quarters.", ["12", "7"]),
    ],
)
def test_numbers_the_model_made_up_are_caught(text, invented):
    assert ungrounded_numbers(text, FACTS) == invented


def test_digits_inside_words_and_dates_are_not_counted_as_numbers():
    assert numbers_in("Q3 results for v2 on 2024-01-05") == ["2024", "01", "05"]
