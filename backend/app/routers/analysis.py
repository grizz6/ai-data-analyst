import functools
import logging
import re
import uuid
from pathlib import Path
from typing import Annotated, BinaryIO

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from starlette.concurrency import run_in_threadpool

from app import security
from app.config import settings
from app.models.schemas import AnalysisResult, PlanRequest, PlanResponse
from app.services import advice, eda, explanation, report
from app.services.ingestion import DatasetError
from app.services.pipeline import run_full_analysis
from app.session_store import delete, get, save
from app.workload import BusyError, busy_detail

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["analysis"])

ALLOWED_SUFFIXES = {".csv", ".xlsx", ".xls"}
READ_CHUNK_BYTES = 1024 * 1024


def session_or_404(session_id: str) -> AnalysisResult:
    result = get(session_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "This analysis wasn't found. Results are kept for "
                f"{settings.session_ttl_minutes} minutes after last use; upload the file again."
            ),
        )
    return result


def too_large_detail() -> str:
    return f"File exceeds the {settings.max_upload_mb} MB upload limit."


async def read_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload in chunks, stopping as soon as it passes max_bytes.

    Never holds more than max_bytes plus one chunk in memory, even when the
    client sent no Content-Length for the middleware to check.
    """
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(READ_CHUNK_BYTES):
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(status_code=413, detail=too_large_detail())
        chunks.append(chunk)
    return b"".join(chunks)


# The report's own charts carry every data point and the dashboard never draws them;
# leaving them out keeps the response small enough to load without freezing the page.
DASHBOARD_EXCLUDE = {"charts"}


@router.post("/upload", response_model=AnalysisResult, response_model_exclude=DASHBOARD_EXCLUDE)
async def upload_dataset(
    file: Annotated[UploadFile, File()],
    sheet: Annotated[str | None, Query(description="Excel only: which sheet to analyze.")] = None,
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")

    filename = file.filename
    # The browser gzips a CSV before sending it as "name.csv.gz"; the analysis
    # reads either form, and shows the name the visitor chose.
    if filename.lower().endswith(".csv.gz"):
        filename = filename[: -len(".gz")]
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Use CSV or Excel (.csv, .csv.gz, .xlsx, .xls).",
        )

    # The framework has already spooled the upload to a temporary file, so large
    # files are analyzed from there rather than copied into memory.
    source: bytes | BinaryIO
    if file.size is None:
        source = await read_capped(file, settings.max_upload_bytes)
        size = len(source)
    else:
        source, size = file.file, file.size
        if size > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail=too_large_detail())
    if size == 0:
        raise HTTPException(status_code=400, detail="The file is empty.")

    try:
        result = await run_full_analysis(source, filename, sheet)
    except DatasetError as exc:
        # Our own messages about the file itself, written for the user.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BusyError as exc:
        raise HTTPException(status_code=503, detail=busy_detail(), headers={"Retry-After": "30"}) from exc
    except Exception as exc:
        # Anything else is a bug. The exception text can hold paths or data
        # values, so it goes to the log under a reference, not to the client.
        reference = uuid.uuid4().hex[:8]
        logger.exception("Analysis failed for %r (reference %s)", filename, reference)
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed because of a server error. Reference: {reference}.",
        ) from exc

    save(result)
    return result


@router.get("/sessions/{session_id}", response_model=AnalysisResult, response_model_exclude=DASHBOARD_EXCLUDE)
async def get_session(session_id: str):
    return session_or_404(session_id)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str) -> Response:
    """Remove an analysis and everything stored with it now, rather than at expiry."""
    if not delete(session_id):
        raise HTTPException(status_code=404, detail="This analysis wasn't found; it may already be deleted or expired.")
    return Response(status_code=204)


@router.post("/sessions/{session_id}/plan", response_model=PlanResponse)
async def plan_for_goal(session_id: str, body: PlanRequest):
    """Order the analyses that fit this file into a plan for a business goal."""
    result = session_or_404(session_id)
    if not body.goal.strip():
        raise HTTPException(status_code=400, detail="Describe the goal first.")
    return await advice.plan_for_goal(result, body.goal)


@router.get("/sessions/{session_id}/dictionary.csv")
async def download_dictionary(session_id: str):
    """One row per column: type, completeness, range, most common value and notes."""
    result = session_or_404(session_id)
    body = await run_in_threadpool(eda.data_dictionary_csv, result)
    name = cleaned_filename(result.filename).removesuffix("-cleaned.csv") + "-dictionary.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/sessions/{session_id}/report", response_class=HTMLResponse)
async def download_report(
    session_id: str,
    print_view: Annotated[
        bool,
        Query(alias="print", description="Show a print-ready page that opens the print dialog, to save as PDF."),
    ] = False,
):
    result = session_or_404(session_id)
    nonce = security.new_nonce() if print_view else ""
    # Serializing every chart into the template takes real CPU on big results.
    html = await run_in_threadpool(lambda: report.render_html_report(result, for_print=print_view, nonce=nonce))
    if print_view:
        return HTMLResponse(content=html, headers={"Content-Security-Policy": security.report_csp(nonce)})
    return HTMLResponse(
        content=html,
        headers={
            "Content-Disposition": f'attachment; filename="report-{session_id[:8]}.html"'
        },
    )


@router.get("/sessions/{session_id}/cleaned.csv")
async def download_cleaned_data(session_id: str):
    result = session_or_404(session_id)
    if result.cleaned_csv is None:
        raise HTTPException(status_code=404, detail="No cleaned data is stored for this analysis.")
    return Response(
        content=result.cleaned_csv,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{cleaned_filename(result.filename)}"'},
    )


def cleaned_filename(original: str) -> str:
    """'Q3 sales (final).xlsx' -> 'Q3-sales-final-cleaned.csv', safe inside a header."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(original).stem).strip("-.") or "data"
    return f"{stem}-cleaned.csv"


@functools.cache
def _plotly_js() -> bytes:
    from plotly.offline import get_plotlyjs

    return get_plotlyjs().encode("utf-8")


@router.get("/vendor/plotly.min.js", include_in_schema=False)
async def plotly_js():
    """Plotly for the printable report, served from here so the page makes no third-party requests."""
    return Response(
        content=_plotly_js(),
        media_type="text/javascript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/sample.csv", response_class=FileResponse)
async def sample_data():
    """The example dataset, so a visitor can try the app without a file of their own."""
    path = Path(settings.sample_data_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No sample file is installed on this server.")
    return FileResponse(path, media_type="text/csv; charset=utf-8", filename="sales_sample.csv")


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "llm_configured": explanation.is_llm_configured(),
        "llm_model": settings.llm_model if explanation.is_llm_configured() else None,
        "max_upload_mb": settings.max_upload_mb,
        "max_csv_mb": settings.max_csv_mb,
        "max_excel_mb": settings.max_excel_mb,
        "max_analysis_rows": settings.max_analysis_rows,
    }
