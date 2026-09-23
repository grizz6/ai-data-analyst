from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models.schemas import AnalysisResult
from app.services.analysis import format_p

_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES)),
    autoescape=select_autoescape(["html"]),
)


def format_number(value) -> str:
    """Readable figure for tables: thousands separators, at most 4 decimals, no trailing zeros."""
    if value is None:
        return ""
    if isinstance(value, int) or float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.4f}".rstrip("0").rstrip(".")


_env.filters["num"] = format_number
_env.filters["pval"] = format_p


def render_html_report(result: AnalysisResult) -> str:
    template = _env.get_template("report.html")
    return template.render(
        result=result,
        chart_notes={e["chart_id"]: e["explanation"] for e in result.llama.chart_explanations},
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
