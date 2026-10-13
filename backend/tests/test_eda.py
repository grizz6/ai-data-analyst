"""Duplicates, why values are missing, numbers by group, category pairs, the data dictionary and the EDA report."""

import csv
import io

import numpy as np
import pandas as pd
import pytest

from app.services import explanation
from app.services.pipeline import compute_analysis

rng = np.random.default_rng(21)
N = 600


@pytest.fixture(scope="module")
def planted():
    age = rng.normal(40, 10, N).round()
    income = (age * 1200 + rng.normal(0, 8000, N)).round()
    young = age < 30
    income[young & (rng.random(N) < 0.6)] = np.nan  # younger people skip the income question
    segment = rng.choice(["student", "worker", "retired"], N, p=[0.3, 0.5, 0.2])
    spend = np.select([segment == "retired", segment == "student"], [80, 30], 55) + rng.normal(0, 8, N)
    df = pd.DataFrame(
        {
            "age": age,
            "income": income,
            "segment": segment,
            "plan": np.where(segment == "student", "basic", rng.choice(["basic", "pro"], N)),
            "spend": spend.round(2),
            "has_phone": np.where(rng.random(N) < 0.1, np.nan, 1.0),
        }
    )
    df = pd.concat([df, df.iloc[[0, 1]]], ignore_index=True)  # two exact copies
    return compute_analysis(df.to_csv(index=False).encode(), "planted.csv")


def test_exact_duplicates_are_counted_with_their_rows(planted):
    dup = planted.duplicates
    assert dup.count == 2
    assert [g.rows for g in dup.groups] == [[1, N + 1], [2, N + 2]]


def test_gaps_that_depend_on_another_column_are_found(planted):
    income = next(m for m in planted.missing_dependencies if m.column == "income")
    top = income.related[0]
    assert top.column == "age" and top.effect < -0.5 and top.p_value < 0.001
    assert "where income is missing" in top.detail


def test_numbers_are_broken_down_by_every_category(planted):
    spend = next(b for b in planted.breakdowns if b.category == "segment" and b.value == "spend")
    assert [g.label for g in spend.groups] == ["retired", "worker", "student"]
    assert spend.eta_squared > 0.7 and spend.p_value < 0.001
    age = next(b for b in planted.breakdowns if b.category == "segment" and b.value == "age")
    assert age.eta_squared < 0.05


def test_category_pairs_are_cross_tabulated(planted):
    pair = next(c for c in planted.crosstabs if {c.row, c.column} == {"segment", "plan"})
    assert pair.cramers_v > 0.3 and pair.p_value < 0.001
    assert sum(map(sum, pair.counts)) == N  # duplicates removed before exploring


def test_one_value_plus_blanks_is_flagged_as_a_possible_flag(planted):
    phone = next(v for v in planted.variables if v.name == "has_phone")
    assert phone.kind == "constant" and any("blanks may mean 'no'" in f for f in phone.flags)


def test_rule_based_story_says_what_the_data_tells_you(planted):
    story = explanation.rule_based_explanation(planted)
    assert "2 rows are exact duplicates" in story.dataset_overview
    assert "Gaps in 'income' aren't random" in story.analysis_summary
    assert "'spend' differs by 'segment'" in story.analysis_summary


def test_dictionary_and_report(client):
    df = pd.DataFrame({"a": rng.normal(size=60), "=cmd": rng.normal(size=60), "kind": ["x", "y"] * 30})
    upload = client.post("/api/upload", files={"file": ("my data.csv", df.to_csv(index=False).encode())})
    session = upload.json()["session_id"]

    reply = client.get(f"/api/sessions/{session}/dictionary.csv")
    assert reply.status_code == 200
    assert 'filename="my-data-dictionary.csv"' in reply.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(reply.content.decode("utf-8-sig"))))
    assert [r["column"] for r in rows] == ["a", "'=cmd", "kind"]  # a formula-like name can't run in Excel
    assert rows[2]["type"] == "binary" and rows[0]["missing_percent"] == "0.0"

    html = client.get(f"/api/sessions/{session}/report").text
    for heading in ("What this dataset is", "Columns", "Data quality", "Relationships"):
        assert f"<h2>{heading}</h2>" in html
