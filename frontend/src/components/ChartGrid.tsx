import Plotly from "plotly.js-cartesian-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import { themedData, themedLayout } from "../chartTheme";
import type { ChartSpec, Explanation } from "../types";

// The default react-plotly.js import bundles all of Plotly (3D, maps, and more).
// Every chart here is 2D, so the smaller cartesian build is enough.
const Plot = createPlotlyComponent(Plotly);

// Tall charts and grids of three or more small charts need the full row to be readable.
const WIDE_HEIGHT = 420;

interface Props {
  charts: ChartSpec[];
  explanation?: Explanation;
}

export default function ChartGrid({ charts, explanation }: Props) {
  const notes = new Map((explanation?.chart_explanations ?? []).map((e) => [e.chart_id, e.explanation]));

  if (!charts.length) {
    return <p style={{ color: "var(--muted)" }}>No charts could be generated for this dataset.</p>;
  }

  return (
    <div className="chart-grid">
      {charts.map((chart) => {
        const figure = chart.plotly_json as { data: Record<string, unknown>[]; layout?: Record<string, unknown> };
        const wide = Number(figure.layout?.height ?? 0) > WIDE_HEIGHT || "xaxis3" in (figure.layout ?? {});
        return (
          <div key={chart.id} className={wide ? "chart-card wide" : "chart-card"}>
            <h3>{chart.title}</h3>
            <Plot
              data={themedData(figure.data) as Plotly.Data[]}
              layout={themedLayout(figure.layout) as Partial<Plotly.Layout>}
              config={{ displayModeBar: false, responsive: true }}
              style={{ width: "100%" }}
            />
            {notes.get(chart.id) && <p className="chart-explain">{notes.get(chart.id)}</p>}
          </div>
        );
      })}
    </div>
  );
}
