# One image serving the API and the built frontend on port 8000.
#
#   docker build -t ai-data-analyst .
#   docker run -p 8000:8000 -v ada-data:/app/backend/data ai-data-analyst
#
# The volume keeps stored analyses across container restarts.

# ---- Frontend: type-check and build the React app ----
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Runtime: Python API that also serves the built frontend ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ADA_FRONTEND_DIST=/app/frontend/dist \
    ADA_DATABASE_PATH=/app/backend/data/ada.sqlite3

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Run as an unprivileged user that owns only the data directory.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/backend/data \
    && chown app /app/backend/data
USER app
VOLUME ["/app/backend/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
