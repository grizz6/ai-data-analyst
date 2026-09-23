# AI Data Analyst Agent

[![CI](https://github.com/grizz6/AI-Data-Analyst-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/grizz6/AI-Data-Analyst-Agent/actions/workflows/ci.yml)

## About

Upload a CSV or Excel file and get an analysis you can check: a data-quality report, cleaning, summary statistics, correlations, trends, interactive charts, plain-English insights, and a downloadable HTML report. FastAPI backend, React + TypeScript frontend.

**Design choice:** Pandas computes every number. An optional language model explains results it's handed and is not allowed to calculate. That rule is enforced in code, not just in the prompt: every number in the model's reply is checked against the computed facts, and a reply containing a number that isn't there is thrown away in favor of rule-based text.

**Status:**

| Part | State |
|---|---|
| Analysis pipeline (ingest → quality → clean → profile → analyze → charts → insights → report) | Working |
| REST API + interactive docs at `/docs` | Working |
| React frontend (`frontend/`) | Working |
| LLM explanations and Q&A | **Built, not yet run against a live provider.** OpenAI-compatible client with retries, a grounding check, and fallback, tested against a fake server. Rule-based text until `ADA_LLM_API_KEY` is set |
| Tests and CI | 128 pytest tests. GitHub Actions runs them, plus a frontend type-check and build, on every push |
| Persistence | **Not yet.** Results live in memory (`session_store.py`), expire after 60 minutes without use, are capped at 20 sessions, and disappear on restart |
| Deployment | **Not yet.** Runs locally |

---

## Architecture

```
Browser: React + Vite (frontend/)
        │  upload .csv / .xlsx / .xls
        ▼
┌───────────────────────────── FastAPI backend ─────────────────────────────┐
│ size limit (middleware)                                                   │
│   → ingestion → identifiers → quality → cleaning → profiling              │
│   → analysis → charts → rule-based insights       worker thread (Pandas)  │
│   → explanation: LLM + grounding check,                                   │
│     or rule-based fallback                        event loop (network)    │
│   → in-memory session store                                               │
└───────────────────────────────────────────────────────────────────────────┘
        │
        ▼
JSON result  +  Plotly chart specs  +  HTML report download
```

### Pipeline (`backend/app/services/`)

| Step | Module | What it does |
|------|--------|----------------|
| 1 | `ingestion.py` | Reads CSV (detects UTF-8, Windows-1252, or Latin-1 text and comma, semicolon, tab, or pipe delimiters) or Excel (first sheet with data, or a named sheet) into a DataFrame and strips whitespace from column names |
| 1b | `semantics.py` | Spots identifier columns (`order_id`, `customerId`, `sku`, `zip`, or a 1, 2, 3... row counter) so they're profiled but kept out of statistics, outlier checks, imputation, and charts |
| 2 | `quality.py` | Flags duplicates, missing values, constant columns, IQR outliers, numbers stored as text, and labels written more than one way, each with a severity |
| 3 | `cleaning.py` | Two steps. First drops duplicate rows and ≥90%-empty columns, converts numbers stored as text (`$1,200`, `45%`, `(300)`), merges labels that differ only in case or spacing (`West` / `west `), and parses date-like columns; statistics are computed on that. Then fills gaps (median for numbers, mode for text, never dates or IDs) for the cleaned preview only, so filled values never skew a figure |
| 4 | `profiling.py` | Per-column dtype, missing count and %, distinct values, samples, identifier flag |
| 5 | `analysis.py` | `describe()` stats, top categories, strongest correlations, trends |
| 6 | `charts.py` | Up to 8 Plotly charts: histogram, bar, scatter, correlation heatmap, time-series line (averaged into daily, weekly, monthly, quarterly, or yearly buckets so it stays under 366 points), box plot |
| 7 | `insights.py` | Turns the results above into plain-English bullets with no model call |
| 8 | `explanation.py`, `llm_client.py`, `grounding.py` | Sends the computed facts to the model, rejects any reply containing a number not in those facts, and falls back to rule-based text on any failure |
| 9 | `report.py` | Renders `templates/report.html` with Jinja2, charts included |

`pipeline.py` chains these for one upload. The Pandas work runs in a worker thread so one large file doesn't stall other requests; only the explanation step, which waits on the network, runs on the event loop.

---

## Quick start

Developed on Python 3.12 (the pinned NumPy needs 3.10 or newer) and Node 22.

```bash
./scripts/run-backend.sh
```

On first run the script creates `backend/.venv` and installs `requirements.txt`, then starts Uvicorn on `http://127.0.0.1:8000`. API docs are at **http://127.0.0.1:8000/docs**.

In a second terminal:

```bash
./scripts/run-frontend.sh
```

Open **http://localhost:5173** and drop in `sample-data/sales_sample.csv` (31 rows of weekly sales by region and product).

### Tests

```bash
cd backend
python -m pip install -r requirements-dev.txt
python -m pytest
```

Frontend (Vitest and React Testing Library, in a simulated browser):

```bash
cd frontend
npm test
```

CI also runs `ruff check .` and `mypy` in `backend/` (settings in `backend/pyproject.toml`) and `npm run lint` (ESLint, TypeScript and React Hooks rules, zero warnings allowed) in `frontend/`.

### API types

The frontend's TypeScript types are generated from the backend's Pydantic models, not written by hand. After changing anything in `backend/app/models/schemas.py`, run:

```bash
./scripts/gen-api-types.sh
```

It exports FastAPI's OpenAPI schema and turns it into `frontend/src/generated/api-schema.ts` with `openapi-typescript`. CI regenerates the file and fails if the committed copy is stale.

### Configuration

Settings come from environment variables with the `ADA_` prefix, or from `backend/.env` (copy `backend/.env.example`). See `backend/app/config.py`.

| Variable | Default | Effect |
|---|---|---|
| `ADA_MAX_UPLOAD_MB` | `10` | Upload size limit. Oversized uploads get a 413, from the `Content-Length` header before the body is read, or mid-read if no length was sent |
| `ADA_MAX_EXCEL_UNZIPPED_MB` | `100` | An `.xlsx` is a zip archive; one that would expand past this once opened is refused before parsing, so a small upload can't unpack into gigabytes |
| `ADA_MISSING_THRESHOLD_DROP` | `0.9` | Columns at or above this missing fraction are dropped during cleaning |
| `ADA_SESSION_TTL_MINUTES` | `60` | An analysis is forgotten after this long without being viewed, asked about, or downloaded |
| `ADA_MAX_SESSIONS` | `20` | Most analyses kept in memory at once; the least recently used is dropped first |
| `ADA_LLM_API_KEY` | empty | Key for the explanation model. Empty means rule-based summaries |
| `ADA_LLM_BASE_URL` | `https://api.groq.com/openai/v1` | Any OpenAI-compatible chat completions endpoint |
| `ADA_LLM_MODEL` | `llama-3.3-70b-versatile` | Model name at that endpoint. (Llama 4 Scout was retired on Groq on 2026-07-17.) |

### Turning on the language model

1. Create a free API key at [console.groq.com](https://console.groq.com), or use any provider with an OpenAI-compatible API and set `ADA_LLM_BASE_URL` and `ADA_LLM_MODEL` to match.
2. Put the key in `backend/.env` as `ADA_LLM_API_KEY=...` and restart the backend.
3. `GET /api/health` should report `"llm_configured": true`.

Every explanation and answer says what wrote it. `source` is `"llm"` or `"rule_based"`, `model` names the model, and `fallback_reason` explains any fallback (provider down, timeout, bad JSON, or a number the model made up). The frontend banner and the report's "How this report was made" section show the same thing.

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/upload` | Upload a file and run the full pipeline. For Excel, `?sheet=NAME` picks a sheet; otherwise the first sheet with data is used |
| `GET` | `/api/sessions/{id}` | Fetch a stored analysis result |
| `POST` | `/api/sessions/{id}/ask` | Ask a question about the data. Answered by the model from the computed facts, or with the key findings when no key is set |
| `GET` | `/api/sessions/{id}/report` | Download the HTML report |
| `GET` | `/api/sessions/{id}/cleaned.csv` | Download the full cleaned dataset as CSV (UTF-8 with a byte-order mark so Excel reads accents correctly). Gaps are filled here, as in the cleaned preview |
| `GET` | `/api/health` | Status, upload limit, whether an LLM key is set, and which model |

Problems with the file itself (empty, unreadable, bad sheet name) return 400 with a plain explanation. Unexpected server errors return 500 with a short reference code; the details go to the server log only.

---

## The algorithms

- **Missing values and constant columns** (`quality.py`): `isna().mean()` gives each column's null rate. Anything above 0% is `info`, 50% or more is a `warning`, and 90% or more is an `error`. A column with exactly one distinct non-null value is flagged as constant.
- **IQR outliers** (`quality.py`): for each numeric, non-identifier column with at least 4 values, compute Q1, Q3, and `IQR = Q3 − Q1`, then count values outside `[Q1 − 1.5·IQR, Q3 + 1.5·IQR]` (Tukey's fences).
- **Identifier detection** (`semantics.py`): column names are split into words across snake_case, camelCase, and spaces. Any word `id`, or a last word such as `uuid`, `key`, `sku`, `zip`, or `phone`, marks an identifier, while `paid` or `grid_size` don't match. A whole-number column counting up by one with no gaps or repeats over 20+ rows is a row counter whatever its name.
- **Correlation ranking** (`analysis.py: top_correlations`): Pearson correlation across all numeric pairs, keeping pairs with `|r| ≥ 0.5` and returning the 10 strongest. Each pair carries `n` (rows where both columns have a value) and a two-sided p-value from `scipy.stats.pearsonr`; when `p ≥ 0.05` the insight says the correlation could be chance.
- **Trend detection** (`analysis.py: detect_trends`), two methods:
  - *Date-based:* sort by the first datetime column, then for up to 3 numeric columns compare the mean of the first half against the second half and fit a least-squares line (`scipy.stats.linregress`, slope reported per day, or per month for timelines over 90 days). A column is "up" or "down" only when the halves differ by more than 5% **and** the slope is significant (`p < 0.05`); a big change that could be noise is reported as stable, and says so.
  - *Row-order proxy:* only when the file has no datetime column. For up to 5 numeric columns with at least 10 values, compare the mean of the first 5 rows to the mean of the last 5. A rise or fall of more than 10% with a significant slope over row number (`p < 0.05`) is reported with its percentage, slope, and p-value.
- **Rule-based insights** (`insights.py`): converts dataset size, quality counts, numeric summaries, top categories, correlations (≥0.7 = "strong", otherwise "moderate"), trends, and column maximums into sentences, so the narrative is deterministic. A maximum points at its record by ID, or by its row in the original file.
- **Grounding check** (`grounding.py`): extracts every number from the model's text and requires each to match a number in the facts it was sent, within the rounding its own decimal places imply (`0.98` matches `0.9832`, `0.99` doesn't). Totals, ratios, restated percentages, and invented figures fail. Signs are compared loosely, so "fell 3.5%" matches a change of `-3.5`; the check guarantees magnitudes, not direction words.
- **Model calls** (`llm_client.py`): plain `httpx` in JSON mode with a 30 s timeout. Timeouts, connection errors, 429 and 5xx are retried twice with exponential backoff (honoring `Retry-After` up to 10 s). Other 4xx errors fail at once. Replies are validated with Pydantic before use.

## How it's tested

`backend/tests/` builds datasets with defects planted at known positions and asserts the pipeline finds exactly those: missingness at 91 / 55 / 10%, exactly three values outside Tukey's fences, two columns constructed at r = 0.87, a series rising 30% versus one moving 2%, identifier columns, gaps in dates, several CSV encodings and delimiters, multi-sheet workbooks, and uploads just over the size limit.

The model layer runs against `httpx.MockTransport` instead of a real provider, which scripts every failure: timeouts, 503 then success, 429 with `Retry-After`, 401, prose instead of JSON, missing fields, and replies containing made-up numbers. No test needs an API key or the network, and a fixture keeps tests off a real provider even when `backend/.env` holds a key.

## Known limits

- Results are kept in memory, so a restart loses them.
- Not deployed; no authentication or rate limiting, so it is not safe to expose publicly as is.
- The LLM path has only been exercised against a fake provider.
- The grounding check verifies numbers, not wording: a model could still describe a drop as a rise.
- The box plot puts all numeric columns on one axis, so columns on small scales flatten out next to large ones.

## Built with

**Backend:** Python, FastAPI, Uvicorn, Pandas, NumPy, SciPy, Plotly, Jinja2, Pydantic, httpx, openpyxl, pytest.
**Frontend:** React, TypeScript, Vite, Plotly.js.
**CI:** GitHub Actions.
