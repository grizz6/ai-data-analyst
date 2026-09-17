# AI Data Analyst Agent

## About

A FastAPI backend that takes an uploaded CSV or Excel file and returns a full automated analysis: data-quality checks, cleaning, summary statistics, correlations, trend detection, Plotly charts, plain-English insights, and a downloadable HTML report.

**Design choice:** Pandas computes every number. The language model layer (planned: Meta Llama 4 Scout) is only allowed to explain and summarize results it's handed, never to calculate them, so every figure in the output can be traced back to code.

**Status:**

| Part | State |
|---|---|
| Analysis pipeline (ingest → quality → clean → profile → analyze → charts → insights → report) | Working |
| REST API + interactive docs at `/docs` | Working |
| Llama explanations and Q&A | **Placeholder.** Returns templated text; the HTTP client is a `TODO` in `llama.py` |
| React frontend | **Not in this repo.** `scripts/run-frontend.sh` expects a `frontend/` folder that hasn't been committed |

---

## Architecture

```
upload (.csv/.xlsx/.xls)
        │
        ▼
┌──────────────────────────── FastAPI backend ────────────────────────────┐
│ ingestion → quality → cleaning → profiling → analysis → charts          │
│          → insights (rule-based) → llama (placeholder) → session store  │
└─────────────────────────────────────────────────────────────────────────┘
        │
        ▼
JSON result  +  Plotly chart specs  +  HTML report download
```

### Pipeline (`backend/app/services/`)

| Step | Module | What it does |
|------|--------|----------------|
| 1 | `ingestion.py` | Reads CSV (detects UTF-8, Windows-1252, or Latin-1 text and comma, semicolon, tab, or pipe delimiters) or Excel (first sheet with data, or a named sheet) into a DataFrame and strips whitespace from column names |
| 1b | `semantics.py` | Spots identifier columns (`order_id`, `customerId`, `sku`, `zip`, or a 1, 2, 3... row counter) so they're profiled but kept out of statistics, outlier checks, imputation, and charts |
| 2 | `quality.py` | Flags duplicates, missing values, constant columns, and IQR outliers, each with a severity |
| 3 | `cleaning.py` | Two steps. First drops duplicate rows and ≥90%-empty columns and parses date-like columns; statistics are computed on that. Then fills gaps (median for numbers, mode for text, never dates or IDs) for the cleaned preview only, so filled values never skew a figure |
| 4 | `profiling.py` | Per-column dtype, null %, uniqueness, sample values |
| 5 | `analysis.py` | `describe()` stats, top categories, strongest correlations, trends |
| 6 | `charts.py` | Up to 8 Plotly charts: histogram, bar, scatter, correlation heatmap, time-series line (averaged into daily, weekly, monthly, quarterly, or yearly buckets so it stays under 366 points), box plot |
| 7 | `insights.py` | Turns the results above into plain-English bullets with no model call |
| 8 | `llama.py` | Placeholder explanations and Q&A; builds the structured context a real model would get |
| 9 | `report.py` | Renders `templates/report.html` with Jinja2 |

`pipeline.py` chains all of these for a single upload. Results are held in an in-memory dict (`session_store.py`), so they disappear when the server restarts.

---

## Quick start

Developed on Python 3.12 (the pinned NumPy needs 3.10 or newer).

```bash
./scripts/run-backend.sh
```

On first run the script creates `backend/.venv` and installs `requirements.txt`, then starts Uvicorn on `http://127.0.0.1:8000`.

Open **http://127.0.0.1:8000/docs**, expand `POST /api/upload`, and upload `sample-data/sales_sample.csv` (31 rows of weekly sales by region and product). The response includes a `session_id` you can pass to the other endpoints.

### Configuration

Settings come from environment variables with the `ADA_` prefix, or from `backend/.env` (copy `backend/.env.example`). See `backend/app/config.py`.

| Variable | Default | Effect |
|---|---|---|
| `ADA_MAX_UPLOAD_MB` | `10` | Upload size limit. Oversized uploads get a 413, from the `Content-Length` header before the body is read, or mid-read if no length was sent |
| `ADA_MISSING_THRESHOLD_DROP` | `0.9` | Columns at or above this missing fraction are dropped during cleaning |
| `ADA_LLM_API_KEY` | empty | Key for the explanation model. Empty means rule-based summaries |
| `ADA_LLM_BASE_URL` | `https://api.groq.com/openai/v1` | Any OpenAI-compatible chat completions endpoint |
| `ADA_LLM_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | Model name at that endpoint |

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/upload` | Upload a file and run the full pipeline. For Excel, `?sheet=NAME` picks a sheet; otherwise the first sheet with data is used |
| `GET` | `/api/sessions/{id}` | Fetch a stored analysis result |
| `POST` | `/api/sessions/{id}/ask` | Ask a question about the data (returns the key findings until an LLM key is set) |
| `GET` | `/api/sessions/{id}/report` | Download the HTML report |
| `GET` | `/api/health` | Status, upload limit, and whether an LLM key is set |

Problems with the file itself (empty, unreadable, bad sheet name) return 400 with a plain explanation. Unexpected server errors return 500 with a short reference code; the details go to the server log only.

---

## The algorithms

- **Missing values and constant columns** (`quality.py`): `isna().mean()` gives each column's null rate. Anything above 0% is `info`, 50% or more is a `warning`, and 90% or more is an `error`. A column with exactly one distinct non-null value is flagged as constant.
- **IQR outliers** (`quality.py`): for each numeric column with at least 4 values, compute Q1, Q3, and `IQR = Q3 − Q1`, then count values outside `[Q1 − 1.5·IQR, Q3 + 1.5·IQR]` (Tukey's fences).
- **Correlation ranking** (`analysis.py: top_correlations`): Pearson correlation across all numeric pairs, keeping pairs with `|r| ≥ 0.5` and returning the 10 strongest.
- **Trend detection** (`analysis.py: detect_trends`), two methods:
  - *Date-based:* sort by the first datetime column, then compare the mean of the first half against the second half for up to 3 numeric columns. More than +5% is "up", below −5% is "down", anything between is "stable".
  - *Row-order proxy:* only when the file has no datetime column. For up to 5 numeric columns with at least 10 values, compare the mean of the first 5 rows to the mean of the last 5. A rise or fall of more than 10% is reported with its percentage.
- **Rule-based insights** (`insights.py`): converts dataset size, quality counts, numeric summaries, top categories, correlations (≥0.7 = "strong", otherwise "moderate"), trends, and column maximums into sentences, so the narrative is deterministic.

## Built with

Python, FastAPI, Uvicorn, Pandas, NumPy, Plotly, Jinja2, Pydantic, openpyxl.
