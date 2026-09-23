"""Serve the built React app from the same process as the API.

In development the frontend runs on Vite's dev server and proxies /api here.
Once it's built (`npm run build` writes frontend/dist), this module serves it
directly, so the whole app is one process on one port: /api/* is the API,
/assets/* are the built files, and any other path returns index.html so
the single-page app can handle it.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, dist: Path) -> bool:
    """Serve `dist` if it holds a built frontend. Returns whether it did."""
    dist = dist.resolve()
    index = dist / "index.html"
    if not index.is_file():
        return False

    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def single_page_app(path: str) -> FileResponse:
        # Unknown API paths should be a 404, not the app's HTML.
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found.")
        candidate = (dist / path).resolve()
        # Files at the top of dist (favicon and so on), never anything outside it.
        if path and candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)
        return FileResponse(index)

    return True
