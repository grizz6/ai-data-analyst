import { lazy, Suspense } from "react";
import { formatNumber } from "../format";
import type { ChartSpec, ClusterAnalysis } from "../types";
import Hint from "./Hint";
import Tile from "./Tile";

const ChartGrid = lazy(() => import("./ChartGrid"));

interface Props {
  clustering: ClusterAnalysis | null;
  charts: ChartSpec[];
}

export default function ClusteringPanel({ clustering, charts }: Props) {
  if (!clustering) return <p className="muted">Grouping needs at least two numeric columns and 50 rows.</p>;
  const pcaTwo = clustering.pca_explained.slice(0, 2).reduce((a, b) => a + b, 0);
  return (
    <>
      <div className="stats">
        <Tile label="Groups (k)" value={String(clustering.k)} />
        <Tile
          label="Silhouette"
          value={clustering.silhouette.toFixed(2)}
          tone={clustering.clear ? "good" : "attention"}
          hint="How well rows sit in their own group, from −1 to 1. Under 0.25 means no real grouping."
        />
        <Tile label="Rows used" value={clustering.rows_used.toLocaleString()} />
        <Tile label="Columns used" value={String(clustering.features.length)} hint={clustering.features.join(", ")} />
        <Tile
          label="PCA map shows"
          value={`${Math.round(pcaTwo * 100)}%`}
          hint="Share of the variation the two map axes capture"
        />
      </div>

      {clustering.clear && (
        <div className="scroll-table">
          <table className="data">
            <thead>
              <tr>
                <th>Group</th>
                <th className="num">Rows</th>
                <th>
                  Stands out for <Hint text="Columns furthest from the overall average, in standard deviations (SD)" />
                </th>
              </tr>
            </thead>
            <tbody>
              {clustering.clusters.map((c) => (
                <tr key={c.cluster}>
                  <td>Group {c.cluster}</td>
                  <td className="num">{c.size.toLocaleString()}</td>
                  <td>
                    {c.distinctive
                      .map((d) => {
                        const sd = Number(d.sd_from_average);
                        return `${d.column} ${sd > 0 ? "high" : "low"} (avg ${formatNumber(Number(d.mean))}, ${sd > 0 ? "+" : ""}${sd.toFixed(1)} SD)`;
                      })
                      .join(" · ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Suspense fallback={<p className="muted">Loading charts…</p>}>
        <ChartGrid charts={charts.length ? charts : clustering.chart ? [clustering.chart] : []} />
      </Suspense>
    </>
  );
}
