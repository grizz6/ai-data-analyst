import Plotly from "plotly.js-cartesian-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import { themedData, themedLayout } from "../chartTheme";
import type { ChartSpec, Explanation } from "../types";

// The default react-plotly.js import bundles all of Plotly (3D, maps, and more).
// Every chart here is 2D, so the smaller cartesian build is enough.
const Plot = createPlotlyComponent(Plotly);

interface Props {
  charts: ChartSpec[];
  explanation: Explanation;
}

export default function ChartGrid({ charts, explanation }: Props) {
  const notes = new Map(explanation.chart_explanations.map((e) => [e.chart_id, e.explanation]));

  if (!charts.length) {
    return <p style={{ color: "var(--muted)" }}>No charts could be generated for this dataset.</p>;
  }

  return (
    <div className="chart-grid">
      {charts.map((chart) => (
        <div key={chart.id} className="chart-card">
          <h3>{chart.title}</h3>
          <Plot
            data={themedData((chart.plotly_json as { data: Record<string, unknown>[] }).data) as Plotly.Data[]}
            layout={themedLayout((chart.plotly_json as { layout?: Record<string, unknown> }).layout) as Partial<Plotly.Layout>}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: "100%" }}
          />
          {notes.get(chart.id) && (
            <p className="chart-explain">{notes.get(chart.id)}</p>
          )}
        </div>
      ))}
    </div>
  );
}
