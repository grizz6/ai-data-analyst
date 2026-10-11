from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models.schemas import AnalysisResult
from app.services.analysis import format_p

_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES)),
    autoescape=select_autoescape(["html"]),
)


# The same Plotly.js release that the plotly Python package bundles (2.35.2),
# so the charts it serializes draw the same either way.
PLOTLY_CDN_URL = "https://cdn.plot.ly/plotly-cartesian-2.35.2.min.js"
VENDOR_PLOTLY_PATH = "/api/vendor/plotly.min.js"


def format_number(value) -> str:
    """Readable figure for tables: thousands separators, at most 4 decimals, no trailing zeros."""
    if value is None:
        return ""
    if isinstance(value, int) or float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.4f}".rstrip("0").rstrip(".")


_env.filters["num"] = format_number
_env.filters["pval"] = format_p


def render_html_report(result: AnalysisResult, *, for_print: bool = False, nonce: str = "") -> str:
    """The standalone report. for_print gives a light page that opens the print dialog once
    its charts are drawn, which is how the app saves a PDF without a server-side renderer.

    The print view is served by this app, so it loads Plotly from here and marks its
    inline script with the response's CSP nonce. The downloaded file is opened from
    disk, where only a CDN can supply Plotly.
    """
    template = _env.get_template("report.html")
    return template.render(
        result=result,
        # Time-series charts go after the overview charts, in the same grid.
        charts=[*result.charts, *(chart for ts in result.time_series for chart in ts.charts)],
        for_print=for_print,
        nonce=nonce,
        plotly_src=VENDOR_PLOTLY_PATH if for_print else PLOTLY_CDN_URL,
        chart_notes={e["chart_id"]: e["explanation"] for e in result.explanation.chart_explanations},
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    )
