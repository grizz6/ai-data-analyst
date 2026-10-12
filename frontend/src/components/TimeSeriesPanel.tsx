import { lazy, Suspense } from "react";
import { formatP } from "../format";
import type { TimeSeriesAnalysis } from "../types";

const ChartGrid = lazy(() => import("./ChartGrid"));

function Fact({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="fact" title={hint}>
      <span className="fact-label">{label}</span>
      <span className="fact-value">{value}</span>
    </div>
  );
}

export default function TimeSeriesPanel({ series }: { series: TimeSeriesAnalysis[] }) {
  if (series.length === 0) {
    return <p className="muted">This file has no date column with enough dates to analyze over time.</p>;
  }
  return (
    <>
      {series.map((ts) => (
        <section key={ts.column} className="ts-block">
          <h3>
            {ts.column} <span className="muted">over {ts.date_column}</span>
          </h3>
          <p>{ts.summary}</p>
          <div className="facts">
            <Fact label="Periods" value={`${ts.points} ${ts.frequency}`} />
            <Fact
              label="Stable level?"
              value={ts.stationary === null ? "too few periods" : ts.stationary ? `yes (${formatP(ts.adf_p)})` : `not confirmed (${formatP(ts.adf_p)})`}
              hint="Augmented Dickey–Fuller test: does the series return to a stable level?"
            />
            <Fact
              label="Seasonality"
              value={
                ts.seasonal_strength === null
                  ? "not enough history"
                  : `${Math.round(ts.seasonal_strength * 100)}% (every ${ts.seasonal_period})`
              }
              hint="Share of the variation explained by a repeating pattern"
            />
            <Fact
              label="Strongest echo"
              value={ts.strongest_lag === null ? "none" : `lag ${ts.strongest_lag} (${ts.strongest_lag_acf?.toFixed(2)})`}
              hint="Autocorrelation: how much a value resembles the one this many periods earlier"
            />
            <Fact label="Forecast" value={ts.forecast.length ? `${ts.forecast.length} periods` : "none"} hint={ts.forecast_method} />
          </div>
          <Suspense fallback={<p className="muted">Loading charts…</p>}>
            <ChartGrid charts={ts.charts} />
          </Suspense>
        </section>
      ))}
      <p className="muted small">
        Forecast ranges are approximate 95% bands based on the model's past errors. Periods without data are filled
        in between their neighbours for these tests only.
      </p>
    </>
  );
}
