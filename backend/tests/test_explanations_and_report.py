import asyncio

import pandas as pd
import pytest

from app.services.llama import explain_analysis
from app.services.pipeline import run_full_analysis
from app.services.report import format_number, render_html_report
from tests.builders import with_outliers


def analyze(df: pd.DataFrame, filename: str = "planted.csv"):
    return asyncio.run(run_full_analysis(df.to_csv(index=False).encode(), filename))


@pytest.fixture
def planted_result():
    amounts = with_outliers(37, [500.0, 600.0, -300.0])
    df = pd.DataFrame(
        {
            "order_id": list(range(40)),
            "region": ["West", "East", "North", "South"] * 10,
            "amount": amounts,
        }
    )
    duplicated = pd.concat([df, df.iloc[:2]], ignore_index=True)
    return analyze(duplicated)


def all_text(explanation) -> str:
    parts = [explanation.dataset_overview, explanation.analysis_summary, *explanation.recommendations]
    parts += [c["explanation"] for c in explanation.chart_explanations]
    return " ".join(parts)


def test_rule_based_explanation_has_no_placeholder_text(planted_result):
    explanation = asyncio.run(explain_analysis(planted_result))
    assert "placeholder" not in all_text(explanation).lower()
    assert explanation.configured is False


def test_recommendations_come_from_the_planted_issues(planted_result):
    recs = " ".join(planted_result.llama.recommendations)
    assert "2 duplicate row(s) were removed" in recs
    assert "3 outlier(s) in 'amount'" in recs


def test_clean_file_gets_an_all_clear_recommendation():
    df = pd.DataFrame({"a": range(20), "b": [x * 2 + 1 for x in range(20)]})
    result = analyze(df)
    assert result.llama.recommendations == [
        "No data quality problems were found, so the figures can be read as they are."
    ]


def test_ask_without_key_returns_findings_not_placeholder(client, sample_csv_bytes):
    session_id = client.post(
        "/api/upload", files={"file": ("sales_sample.csv", sample_csv_bytes, "text/csv")}
    ).json()["session_id"]
    body = client.post(f"/api/sessions/{session_id}/ask", json={"question": "Top region?"}).json()

    assert "placeholder" not in body["answer"].lower()
    assert "Here is what the analysis found" in body["answer"]
    assert "- Summary for sales: Mean 9,419.35" in body["answer"]
    assert body["configured"] is False


def test_report_embeds_every_chart_and_has_no_placeholder_text(planted_result):
    html = render_html_report(planted_result)

    assert "placeholder" not in html.lower()
    assert "cdn.plot.ly" in html
    for i in range(1, len(planted_result.charts) + 1):
        assert f'id="chart-{i}"' in html
    assert "generated from rules, with no language model involved" in html


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, ""), (12500, "12,500"), (12500.0, "12,500"), (1234.56789, "1,234.5679"), (0.5, "0.5"), (-3.25, "-3.25")],
)
def test_format_number(value, expected):
    assert format_number(value) == expected
