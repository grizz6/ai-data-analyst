import asyncio

import numpy as np
import pandas as pd
import pytest

from app.services.pipeline import run_full_analysis
from app.services.semantics import identifier_columns, is_row_counter, looks_like_identifier_name


@pytest.mark.parametrize(
    "name",
    ["id", "ID", "customer_id", "customerId", "userID", "Order ID", "id_number", "uuid", "product_sku", "zip", "api_key"],
)
def test_identifier_names(name):
    assert looks_like_identifier_name(name)


@pytest.mark.parametrize(
    "name",
    ["paid", "valid", "grid_size", "idle_time", "amount", "keyboard_count", "zipper_sales", "bid"],
)
def test_words_that_merely_contain_id_are_not_identifiers(name):
    assert not looks_like_identifier_name(name)


def test_consecutive_whole_numbers_are_a_row_counter():
    assert is_row_counter(pd.Series(range(101, 151)))


@pytest.mark.parametrize(
    "series",
    [
        pd.Series(np.random.default_rng(0).permutation(np.arange(0, 500, 7))[:50]),  # unique, but gaps
        pd.Series(range(10)),  # too short to be sure
        pd.Series([x + 0.5 for x in range(50)]),  # not whole numbers
        pd.Series(list(range(49)) + [3]),  # repeats a value
    ],
)
def test_other_numeric_columns_are_not_row_counters(series):
    assert not is_row_counter(series)


@pytest.fixture
def orders_result():
    rng = np.random.default_rng(3)
    amount = rng.uniform(40, 60, size=40)
    amount[17] = 90.0
    df = pd.DataFrame(
        {
            "order_id": range(1000, 1040),
            "row": range(1, 41),
            "region": ["West", "East"] * 20,
            "amount": amount,
            "quantity": (amount / 10).round(),
        }
    )
    df.loc[5, "order_id"] = None
    csv = df.to_csv(index=False).encode()
    return asyncio.run(run_full_analysis(csv, "orders.csv"))


def test_identifier_columns_on_a_frame():
    df = pd.DataFrame({"order_id": range(30), "row": range(1, 31), "amount": np.linspace(1, 9, 30)})
    assert identifier_columns(df) == ["order_id", "row"]


def test_identifiers_stay_out_of_statistics_and_charts(orders_result):
    ids = {"order_id", "row"}

    assert ids.isdisjoint(s.column for s in orders_result.numeric_summaries)
    assert ids.isdisjoint({p.column_a for p in orders_result.correlations} | {p.column_b for p in orders_result.correlations})
    assert ids.isdisjoint(q.column for q in orders_result.quality_issues if q.category == "outliers")
    assert not any("order_id" in c.title or "row" in c.title.split() for c in orders_result.charts)


def test_identifiers_are_profiled_and_not_imputed(orders_result):
    flags = {c.name: c.is_identifier for c in orders_result.columns}
    assert flags == {"order_id": True, "row": True, "region": False, "amount": False, "quantity": False}
    assert not any(a.column == "order_id" for a in orders_result.cleaning_actions)
    assert next(c for c in orders_result.columns if c.name == "order_id").null_count == 1


def test_extremes_point_at_the_record_id(orders_result):
    highest = next(i for i in orders_result.rule_insights if i.title == "Highest amount")
    assert highest.message == "Maximum amount is 90.0 (order_id 1017)."
    assert any(i.title == "Identifier columns" for i in orders_result.rule_insights)
