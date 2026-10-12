# AI Data Analyst

[![CI](https://github.com/grizz6/ai-data-analyst/actions/workflows/ci.yml/badge.svg)](https://github.com/grizz6/ai-data-analyst/actions/workflows/ci.yml)

**Live:** https://ai-data-analyst-xz78.onrender.com

## The problem

Every analysis starts with exploratory data analysis (EDA): what kind of data each column holds, where the gaps and outliers are, how the columns relate, and which analysis the data can support. Done by hand, that means writing the same Pandas and plotting code for every new file before any real question gets answered, and outliers or entry errors that slip through quietly distort everything after.

## What it does

Upload a CSV or Excel file (up to 75 MB) and get the whole exploratory pass in seconds, then the analyses it points to.

- **Every column profiled.** Its type (yes/no, number, count, category, date, identifier, free text), key numbers, and the charts that suit it: histogram, box, violin, Q-Q plot, values over time, and a split by each yes/no column.
- **Outliers explained, not just counted.** Two rules (1.5 × IQR and |z| > 3), marked on the charts, listed by row with a likely cause (placeholder code like 999, impossible negative, a 100× typo, or a genuine extreme), and shown with the mean, spread and correlation with and without them.
- **Yes/no columns compared.** Every other column ranked by how much it differs between the two groups, the starting point for logistic regression.
- **Relationships and structure.** Correlation heatmaps, scatter plots for every pair, group comparisons, statistical tests with adjusted p-values, clustering with a PCA map, and time-series analysis with a forecast whenever the file has a time axis (a date column, or date parts, timestamps, years, steps or meaningful row order).
- **Models on held-out data.** Up to eleven regression or classification models (linear, logistic, ridge, lasso, k-nearest neighbours, naive Bayes, trees, random forest, bagging, boosting, SVM) against a baseline, scored by cross-validation and on a 20% test set, with overfitting flagged.
- **What to run next.** Analyses ranked by how strongly the data supports them, each with the reason and a button that runs it. Describe a business goal in plain words and get a step-by-step plan built from those analyses.
- **Ask, build, export.** Questions about the data, custom charts, the cleaned CSV, and an HTML or PDF report.

## Why the numbers can be trusted

Pandas, SciPy and scikit-learn compute every figure. A language model (Groq, `openai/gpt-oss-120b`) only explains results it is handed, and the code checks every number in its reply against the computed results: any number it didn't receive throws the reply out in favour of rule-based text. Each summary, answer and plan says which one wrote it.

## Run it locally

Python 3.12 and Node 22.

```bash
./scripts/run-backend.sh     # API on http://127.0.0.1:8000 (docs at /docs)
./scripts/run-frontend.sh    # app on http://localhost:5173
```

Or as one container: `docker build -t ai-data-analyst . && docker run -p 8000:8000 ai-data-analyst`.

Settings are `ADA_*` environment variables (see `backend/.env.example` and `backend/app/config.py`). The one most people need is `ADA_LLM_API_KEY`, a free Groq key; without it everything works and the text is rule-based.

## Under the hood

- **Backend:** FastAPI, Pandas, NumPy, SciPy, statsmodels, scikit-learn, Plotly, SQLite for sessions that expire after an hour. Large files are read in chunks and analysed on a 100,000-row sample, which keeps a 75 MB file under 350 MB of memory.
- **Frontend:** React, TypeScript, Vite, Plotly.js. Types are generated from the backend's schemas.
- **Hosting:** Render's free plan, deployed on every push to `main`. The app requests its own address every 10 minutes so the free plan never puts it to sleep.
- **Quality:** 348 backend and 93 frontend tests, many on files with defects planted at known positions; CI runs them with ruff, mypy, ESLint and a Docker build on every push. A manual "Site check" workflow tests the live site end to end.
- **Privacy and abuse limits:** results are reachable only through an unguessable link and deleted after an hour or on request; uploads, questions and model runs are rate-limited per visitor; strict security headers and no third-party requests.

## Limits

- One server: sessions live in a local SQLite file, and a free instance runs one analysis at a time.
- No accounts: anyone with the address can use the site, within the rate limits.
- The number check verifies figures, not wording: a model could still call a drop a rise.
