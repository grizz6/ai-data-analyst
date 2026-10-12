# AI Data Analyst

[![CI](https://github.com/grizz6/ai-data-analyst/actions/workflows/ci.yml/badge.svg)](https://github.com/grizz6/ai-data-analyst/actions/workflows/ci.yml)

**Live:** https://ai-data-analyst-xz78.onrender.com

**Built with:** FastAPI · Pandas · NumPy · SciPy · statsmodels · scikit-learn · Plotly · React · TypeScript · Vite · Groq (`openai/gpt-oss-120b`) · Render · GitHub Actions

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
