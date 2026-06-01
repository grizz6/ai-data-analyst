from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from app.config import settings
from app.models.schemas import QuestionRequest, QuestionResponse
from app.services import llama, report
from app.services.pipeline import run_full_analysis
from app.session_store import get, save

router = APIRouter(prefix="/api", tags=["analysis"])

ALLOWED_SUFFIXES = {".csv", ".xlsx", ".xls"}


@router.post("/upload")
async def upload_dataset(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")

    suffix = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Use CSV or Excel (.csv, .xlsx, .xls).",
        )

    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds {settings.max_upload_mb} MB limit.",
        )

    try:
        result = await run_full_analysis(content, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}") from exc

    save(result)
    return result.model_dump(mode="json")


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    result = get(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found.")
    return result.model_dump(mode="json")


@router.post("/sessions/{session_id}/ask", response_model=QuestionResponse)
async def ask_question(session_id: str, body: QuestionRequest):
    result = get(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found.")
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    return await llama.answer_question(result, body.question.strip())


@router.get("/sessions/{session_id}/report", response_class=HTMLResponse)
async def download_report(session_id: str):
    result = get(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found.")
    html = report.render_html_report(result)
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
        "llama_configured": llama.is_llama_configured(),
        "max_upload_mb": settings.max_upload_mb,
    }
