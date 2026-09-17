from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
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


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analysis.router)


@app.get("/")
async def root():
    return {"message": settings.app_name, "docs": "/docs"}
