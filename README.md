# AI Data Analyst

[![CI](https://github.com/grizz6/ai-data-analyst/actions/workflows/ci.yml/badge.svg)](https://github.com/grizz6/ai-data-analyst/actions/workflows/ci.yml)

**Live:** https://ai-data-analyst-xz78.onrender.com

**Built with:** FastAPI · Pandas · NumPy · SciPy · statsmodels · Plotly · React · TypeScript · Vite · Groq (`openai/gpt-oss-120b`) · Render · GitHub Actions

## The problem

Business goals differ from one analysis to the next, but every one starts the same way: exploratory data analysis (EDA). What kind of data each column holds, where the gaps, duplicates and outliers are, how the columns relate, and what the data could support. Done by hand, that means writing the same Pandas and plotting code for every new file, and entry errors or non-random gaps that slip through quietly distort everything after.

## What it does

Upload a CSV (up to 200 MB, compressed in the browser before it's sent) or an Excel file (up to 15 MB) and get the whole exploratory pass in seconds.

- **The dataset's story.** A short plain-English summary of what the file holds, what it tells you, and what to check before using it.
- **Data quality.** Missing values per column and where they fall, which columns go missing together, whether gaps depend on other columns (income missing mostly for younger rows, say), exact duplicate rows with their row numbers, and every cleaning step applied to the downloadable copy.
- **Every column profiled.** Its type (yes/no, number, count, category, date, identifier, free text), key numbers, and the charts that suit it: histogram, box, violin, Q-Q plot, values over time, and a split by each yes/no column.
- **Outliers explained, not just counted.** Two rules (1.5 × IQR and |z| > 3), marked on the charts, listed by row with a likely cause (placeholder code like 999, impossible negative, a 100× typo, or a genuine extreme), and shown with the mean, spread and correlation with and without them.
- **Relationships.** Correlation heatmaps, scatter plots for every pair, any number broken down by any category, any two categories crossed, yes/no columns compared against everything else, and statistical tests with adjusted p-values.
- **Over time.** Trend, seasonality and autocorrelation whenever the file has a time axis: a date column, or date parts, timestamps, years, steps or meaningful row order.
- **A senior analyst's read.** A verdict on whether the data is ready to analyse, then the concerns ranked by how badly they would mislead: leakage, gaps that aren't random, entry errors, correlations carried by a few outliers, too few rows per predictor, near-duplicate or lopsided columns. It also lists what the data does well and what it can't tell you (cause and effect, trends without a time axis, findings that may be chance after many tests).
- **Next steps.** The analyses this data supports (regression, classification, forecasting, segmentation, group comparisons), each marked ready, needs work first, or weak evidence, with the risks that could make the answer wrong and what to check first. Describe a goal in plain words to get them ordered into a plan.
- **Export.** A data dictionary, the cleaned CSV, and an EDA report as HTML or PDF.

## Why the numbers can be trusted

Pandas, NumPy, SciPy and statsmodels compute every figure. A language model (Groq, `openai/gpt-oss-120b`) only explains results it is handed, and the code checks every number in its reply against the computed results: any number it didn't receive throws the reply out in favour of rule-based text. Each summary and plan says which one wrote it.
