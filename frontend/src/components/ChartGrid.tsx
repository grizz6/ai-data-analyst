import Plotly from "plotly.js-cartesian-dist-min";
import { useEffect, useRef, useState } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import { themedData, themedLayout } from "../chartTheme";
import { useTheme } from "../theme";
import type { ChartSpec, Explanation } from "../types";

// The default react-plotly.js import bundles all of Plotly (3D, maps, and more).
// Every chart here is 2D, so the smaller cartesian build is enough.
const Plot = createPlotlyComponent(Plotly);

// Tall charts and grids of three or more small charts need the full row to be readable.
const WIDE_HEIGHT = 420;
const DEFAULT_HEIGHT = 320;

/*
 * Drawing a Plotly chart blocks the page for tens to hundreds of milliseconds.
 * Drawing a whole tab's worth at once froze the page for seconds on slower
 * machines, so charts are drawn one at a time, only once they come near the
 * screen, with a pause between them for the browser to stay responsive.
 */
const queue: (() => void)[] = [];
let draining = false;

function drain() {
  const next = queue.shift();
  if (!next) {
    draining = false;
    return;
  }
  next();
  setTimeout(drain, 40);
}

function enqueue(job: () => void): () => void {
  queue.push(job);
  if (!draining) {
    draining = true;
    setTimeout(drain, 0);
  }
  return () => {
    const i = queue.indexOf(job);
    if (i >= 0) queue.splice(i, 1);
  };
}

function useDrawWhenNear(height: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (ready) return;
    let cancel: (() => void) | undefined;
    const start = () => {
      cancel ??= enqueue(() => setReady(true));
    };
    if (typeof IntersectionObserver === "undefined" || !ref.current) {
      start();
      return () => cancel?.();
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          observer.disconnect();
          start();
        }
      },
      { rootMargin: `${Math.max(400, height)}px 0px` },
    );
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      cancel?.();
    };
  }, [ready, height]);
  return { ref, ready };
}

function Chart({ chart, note }: { chart: ChartSpec; note?: string }) {
  const theme = useTheme();
  const figure = chart.plotly_json as { data: Record<string, unknown>[]; layout?: Record<string, unknown> };
  const height = Number(figure.layout?.height ?? DEFAULT_HEIGHT);
  const wide = height > WIDE_HEIGHT || "xaxis3" in (figure.layout ?? {});
  const { ref, ready } = useDrawWhenNear(height);
  return (
    <div ref={ref} className={wide ? "chart-card wide" : "chart-card"}>
      <h3>{chart.title}</h3>
      {ready ? (
        <div className="chart-body">
          <Plot
            data={themedData(figure.data, theme) as Plotly.Data[]}
            layout={themedLayout(figure.layout, theme) as Partial<Plotly.Layout>}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: "100%" }}
          />
        </div>
      ) : (
        <div className="chart-skeleton" style={{ height }} aria-label="Drawing chart" role="img" />
      )}
      {note && <p className="chart-explain">{note}</p>}
    </div>
  );
}

interface Props {
  charts: ChartSpec[];
  explanation?: Explanation;
}

export default function ChartGrid({ charts, explanation }: Props) {
  const notes = new Map((explanation?.chart_explanations ?? []).map((e) => [e.chart_id, e.explanation]));

  if (!charts.length) {
    return <p className="muted">No charts could be generated for this dataset.</p>;
  }

  return (
    <div className="chart-grid">
      {charts.map((chart) => (
        <Chart key={chart.id} chart={chart} note={notes.get(chart.id)} />
      ))}
    </div>
  );
}
