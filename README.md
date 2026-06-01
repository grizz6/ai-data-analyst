# AI Data Analyst Agent

A web application where anyone can upload a CSV or Excel dataset and receive automated data analysis: quality checks, cleaning, statistics, charts, rule-based insights, and (when configured) natural-language explanations from **Meta Llama 4 Scout**.

**Important design choice:** Python and Pandas perform all calculations. Llama only explains, summarizes, answers questions, and writes reports — it never computes metrics.

## Architecture

```
┌─────────────┐     upload      ┌──────────────────────────────────────────┐
│  React UI   │ ──────────────► │  FastAPI backend                         │
│  (Vite)     │ ◄────────────── │  ingestion → quality → clean → analyze   │
└─────────────┘   JSON + charts │  → charts → insights → llama (stub)      │
                                └──────────────────────────────────────────┘
```

### Backend pipeline (`backend/app/services/`)

| Step | Module | What it does |
|------|--------|----------------|
| 1 | `ingestion.py` | Load CSV/Excel into a Pandas DataFrame |
| 2 | `quality.py` | Missing values, duplicates, constants, IQR outliers |
| 3 | `cleaning.py` | Drop duplicates, drop ultra-sparse columns, impute median/mode, parse dates |
| 4 | `profiling.py` | Per-column dtype, null %, uniqueness, samples |
| 5 | `analysis.py` | `describe()` stats, correlations, trend detection |
| 6 | `charts.py` | Plotly histograms, bars, scatter, heatmap, time series, box plots |
| 7 | `insights.py` | Rule-based narrative facts (not LLM) |
| 8 | `llama.py` | **Stub** — explanations & Q&A when `ADA_LLAMA_API_KEY` is set |
| 9 | `report.py` | Downloadable HTML report (Jinja2) |

Sessions are stored in memory (`session_store.py`) for simplicity. For production, use Redis or a database plus object storage for files.

### Frontend (`frontend/`)

React + Vite + Plotly.js. Proxies `/api` to the backend during development.

## Quick start

**Terminal 1 — backend**

```bash
chmod +x scripts/run-backend.sh
./scripts/run-backend.sh
```

**Terminal 2 — frontend**

```bash
chmod +x scripts/run-frontend.sh
./scripts/run-frontend.sh
```

Open [http://localhost:5173](http://localhost:5173) and upload `sample-data/sales_sample.csv`.

API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## Llama integration (when you have an API key)

Set environment variables before starting the backend:

```bash
export ADA_LLAMA_API_KEY="your-key-here"
# optional:
# export ADA_LLAMA_API_BASE="https://your-llama-endpoint"
```

Implement the HTTP client in `backend/app/services/llama.py` at the marked `TODO` blocks. Pass structured facts from `build_ask_context()` — never ask the model to calculate numbers.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/upload` | Upload file, run full pipeline |
| `GET` | `/api/sessions/{id}` | Retrieve analysis result |
| `POST` | `/api/sessions/{id}/ask` | Ask a question about the data |
| `GET` | `/api/sessions/{id}/report` | Download HTML report |
| `GET` | `/api/health` | Health + Llama configured flag |

## Project goal

Enable non-analysts to upload business data and immediately see:

- Whether the data is trustworthy (quality panel)
- What was fixed automatically (cleaning log)
- Visual and statistical summaries
- Plain-English narrative (Llama, once wired)
- Interactive Q&A and a shareable report

The separation between **deterministic analytics** (Pandas) and **interpretation** (Llama) keeps results auditable and reduces hallucinated numbers.
