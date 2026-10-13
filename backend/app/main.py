import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import keep_awake, rate_limit, security
from app.config import settings
from app.frontend import mount_frontend
from app.routers import analysis

# Multipart wraps the file in boundaries and part headers; allow for that on top of the cap.
MULTIPART_OVERHEAD_BYTES = 64 * 1024
# Every request other than an upload is a small JSON body (a question, a chart choice).
MAX_JSON_BODY_BYTES = 64 * 1024

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    url = keep_awake.keep_awake_url()
    task = None
    if url:
        logger.info("keep-awake: requesting %s every %g minutes", url, settings.keep_awake_minutes)
        task = asyncio.create_task(keep_awake.keep_awake(url, settings.keep_awake_minutes * 60))
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs" if settings.api_docs else None,
    redoc_url="/redoc" if settings.api_docs else None,
    openapi_url="/openapi.json" if settings.api_docs else None,
)


# Registered before CORS so CORS wraps it and a 413 still reaches the browser readable.
@app.middleware("http")
async def reject_oversized_uploads(request: Request, call_next):
    """Refuse an oversized upload from its Content-Length, before the body is read.

    FastAPI parses the whole multipart body before the endpoint runs, so the
    size check has to happen here to save the server from receiving it.
    """
    if request.method in ("POST", "PUT", "PATCH"):
        is_upload = request.url.path == "/api/upload"
        limit = settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES if is_upload else MAX_JSON_BODY_BYTES
        declared = request.headers.get("content-length")
        if declared and declared.isdigit():
            if int(declared) > limit:
                detail = analysis.too_large_detail() if is_upload else "Request body is too large."
                return JSONResponse(status_code=413, content={"detail": detail})
        elif not is_upload:
            # Without a length the body could be any size; every client this app has sends one.
            return JSONResponse(status_code=411, content={"detail": "Content-Length is required."})
    return await call_next(request)


# Also inside CORS, so a 429 is readable by the browser. Checked before the
# upload body is read, so a blocked visitor's file never reaches the server.
@app.middleware("http")
async def limit_request_rate(request: Request, call_next):
    if request.method == "POST":
        path = request.url.path
        if path == "/api/upload":
            limiter, limit, what = rate_limit.uploads, settings.uploads_per_hour, "uploads"
        elif path.startswith("/api/sessions/") and path.endswith("/plan"):
            limiter, limit, what = rate_limit.plans, settings.plans_per_hour, "plans"
        else:
            return await call_next(request)
        visitor = rate_limit.visitor_address(
            request.client.host if request.client else None,
            request.headers.get("x-forwarded-for"),
            settings.trusted_proxy_hops,
            request.headers.get(settings.client_ip_header) if settings.client_ip_header else None,
        )
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


class SecurityHeaders:
    """Outermost layer, so every response gets the headers: errors, static files, the 413s above."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                security.add_security_headers(scope["path"], message)
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Added last, so it wraps everything else.
app.add_middleware(SecurityHeaders)

app.include_router(analysis.router)

# With a built frontend present, this one process serves the whole app. Without
# it (development, or an API-only deploy), "/" just points at the API docs.
if not mount_frontend(app, Path(settings.frontend_dist)):

    @app.get("/")
    async def root():
        return {"message": settings.app_name, "docs": "/docs"}
