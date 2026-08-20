# AI Data Analyst Agent

A web application where anyone can upload a CSV or Excel dataset and receive automated data analysis: quality checks, cleaning, statistics, charts, rule-based insights, and (when configured) natural-language explanations from **Meta Llama 4 Scout**.

**Design choice:** Python and Pandas perform all calculations. Llama only explains, summarizes, answers questions, and writes reports — it never computes metrics, which keeps every number auditable and non-hallucinated.

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

Sessions are stored in memory (`session_store.py`) for simplicity — a production deployment would swap in Redis/a database plus object storage.

### Frontend (`frontend/`)

React + Vite + Plotly.js, proxying `/api` to the backend during development.

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

Open [http://localhost:5173](http://localhost:5173) and upload `sample-data/sales_sample.csv`. API docs at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## Llama integration (when you have an API key)

```bash
export ADA_LLAMA_API_KEY="your-key-here"
# optional: export ADA_LLAMA_API_BASE="https://your-llama-endpoint"
```
Implement the HTTP client in `backend/app/services/llama.py` at the marked `TODO` blocks, passing structured facts from `build_ask_context()` — never ask the model to calculate numbers.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/upload` | Upload file, run full pipeline |
| `GET` | `/api/sessions/{id}` | Retrieve analysis result |
| `POST` | `/api/sessions/{id}/ask` | Ask a question about the data |
| `GET` | `/api/sessions/{id}/report` | Download HTML report |
| `GET` | `/api/health` | Health + Llama configured flag |

## Code used

Backend: **Python**, **FastAPI**, **Pandas**, **Plotly**, **Jinja2**. Frontend: **React**, **Vite**, **Plotly.js**.

## The algorithms

- **Missing-value / constant-column detection** (`quality.py`) — per column, `isna().mean()` gives the null rate (flagged at ≥50% warning, ≥90% error, >0% info); `nunique(dropna=True) == 1` flags constant columns.
- **IQR outlier detection** (`quality.py`) — for each numeric column, computes Q1/Q3 quartiles, `IQR = Q3 − Q1`, and flags any value outside `[Q1 − 1.5·IQR, Q3 + 1.5·IQR]` as a potential outlier — the standard Tukey fence method.
- **Correlation ranking** (`analysis.py: top_correlations`) — computes the full pairwise Pearson correlation matrix (`DataFrame.corr()`), keeps pairs with `|r| ≥ 0.5`, and returns the top N sorted by absolute correlation strength.
- **Trend detection, two methods** (`analysis.py: detect_trends`):
  - *Time-based*: for the first detected datetime column, splits each numeric column's values (sorted by date) into a first half and second half, compares their means, and reports percent change — labeled "up"/"down" past a ±5% threshold, else "stable".
  - *Row-order proxy* (used when there's no reliable date column): applies a rolling mean (window of 5) over each numeric column and compares the last rolling value to the first — a >10% rise/fall is reported as an upward/downward pattern.
- **Rule-based insight generation** (`insights.py`) — turns the structured facts above (quality issues, correlations, trends) into plain-English narrative bullets without any model call, so the "explanation" layer is deterministic and traceable back to a specific number.
