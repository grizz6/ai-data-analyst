from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import rate_limit
from app.config import settings
from app.frontend import mount_frontend
from app.routers import analysis

# Multipart wraps the file in boundaries and part headers; allow for that on top of the cap.
MULTIPART_OVERHEAD_BYTES = 64 * 1024

app = FastAPI(title=settings.app_name, version="0.1.0")


# Registered before CORS so CORS wraps it and a 413 still reaches the browser readable.
@app.middleware("http")
async def reject_oversized_uploads(request: Request, call_next):
    """Refuse an oversized upload from its Content-Length, before the body is read.

    FastAPI parses the whole multipart body before the endpoint runs, so the
    size check has to happen here to save the server from receiving it.
    """
    if request.method == "POST" and request.url.path == "/api/upload":
        declared = request.headers.get("content-length")
        if declared and declared.isdigit():
            if int(declared) > settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES:
                return JSONResponse(status_code=413, content={"detail": analysis.too_large_detail()})
    return await call_next(request)


# Also inside CORS, so a 429 is readable by the browser. Checked before the
# upload body is read, so a blocked visitor's file never reaches the server.
@app.middleware("http")
async def limit_request_rate(request: Request, call_next):
    if request.method == "POST":
        path = request.url.path
        if path == "/api/upload":
            limiter, limit, what = rate_limit.uploads, settings.uploads_per_hour, "uploads"
        elif path.startswith("/api/sessions/") and path.endswith("/ask"):
            limiter, limit, what = rate_limit.questions, settings.questions_per_hour, "questions"
        else:
            return await call_next(request)
        visitor = request.client.host if request.client else "unknown"
        wait = limiter.check(visitor, limit)
        if wait is not None:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": rate_limit.retry_after_header(wait)},
                content={
                    "detail": f"Too many {what}: the limit is {limit} per hour. "
                    f"Try again in {rate_limit.describe_wait(wait)}."
                },
            )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analysis.router)

# With a built frontend present, this one process serves the whole app. Without
# it (development, or an API-only deploy), "/" just points at the API docs.
if not mount_frontend(app, Path(settings.frontend_dist)):

    @app.get("/")
    async def root():
        return {"message": settings.app_name, "docs": "/docs"}
