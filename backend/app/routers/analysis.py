import logging
import uuid

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.models.schemas import AnalysisResult, QuestionRequest, QuestionResponse
from app.services import llama, report
from app.services.ingestion import DatasetError
from app.services.pipeline import run_full_analysis
from app.session_store import get, save

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


@router.post("/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    sheet: str | None = Query(default=None, description="Excel only: which sheet to analyze."),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")

    suffix = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Use CSV or Excel (.csv, .xlsx, .xls).",
        )

    content = await read_capped(file, settings.max_upload_bytes)
    if not content:
        raise HTTPException(status_code=400, detail="The file is empty.")

    try:
        result = await run_full_analysis(content, file.filename, sheet)
    except DatasetError as exc:
        # Our own messages about the file itself, written for the user.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Anything else is a bug. The exception text can hold paths or data
        # values, so it goes to the log under a reference, not to the client.
        reference = uuid.uuid4().hex[:8]
        logger.exception("Analysis failed for %r (reference %s)", file.filename, reference)
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed because of a server error. Reference: {reference}.",
        ) from exc

    save(result)
    return result.model_dump(mode="json")


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    result = session_or_404(session_id)
    return result.model_dump(mode="json")


@router.post("/sessions/{session_id}/ask", response_model=QuestionResponse)
async def ask_question(session_id: str, body: QuestionRequest):
    result = session_or_404(session_id)
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    return await llama.answer_question(result, body.question.strip())


@router.get("/sessions/{session_id}/report", response_class=HTMLResponse)
async def download_report(session_id: str):
    result = session_or_404(session_id)
    # Serializing every chart into the template takes real CPU on big results.
    html = await run_in_threadpool(report.render_html_report, result)
    return HTMLResponse(
        content=html,
        headers={
            "Content-Disposition": f'attachment; filename="report-{session_id[:8]}.html"'
        },
    )


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "llm_configured": llama.is_llama_configured(),
        "llm_model": settings.llm_model if llama.is_llama_configured() else None,
        "max_upload_mb": settings.max_upload_mb,
    }
