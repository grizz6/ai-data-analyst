import Plotly from "plotly.js-cartesian-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";

// The default react-plotly.js import bundles all of Plotly (3D, maps, and more).
// Every chart here is 2D, so the smaller cartesian build is enough.
const Plot = createPlotlyComponent(Plotly);
import type { ChartSpec, LlamaExplanation } from "../types";

interface Props {
  charts: ChartSpec[];
  llama: LlamaExplanation;
}

export default function ChartGrid({ charts, llama }: Props) {
  const explanations = new Map(
    llama.chart_explanations.map((e) => [e.chart_id, e.explanation])
  );

  if (!charts.length) {
    return <p style={{ color: "var(--muted)" }}>No charts could be generated for this dataset.</p>;
  }

  return (
    <div className="chart-grid">
      {charts.map((chart) => (
        <div key={chart.id} className="chart-card">
          <h3>{chart.title}</h3>
          <Plot
            data={(chart.plotly_json as { data: object[] }).data}
            layout={{
              ...((chart.plotly_json as { layout?: object }).layout ?? {}),
              // The card heading already shows the title, and Plotly's own would
              // collide with per-panel labels on narrow screens.
              title: undefined,
              paper_bgcolor: "transparent",
              plot_bgcolor: "transparent",
              font: { color: "#e8eef5", size: 11 },
              margin: { t: 36, r: 16, b: 40, l: 48 },
              height: 320,
            }}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: "100%" }}
          />
          {explanations.get(chart.id) && (
            <p className="chart-explain">{explanations.get(chart.id)}</p>
          )}
        </div>
      ))}
    </div>
  );
}
