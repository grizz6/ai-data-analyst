import { formatNumber, formatP } from "../format";
import type { AnalysisResult } from "../types";
import Hint from "./Hint";

interface Props {
  duplicates: AnalysisResult["duplicates"];
  missing: AnalysisResult["missing_dependencies"];
}

/** Duplicate rows, and whether each column's gaps depend on the other columns. */
export default function QualityExtras({ duplicates, missing }: Props) {
  return (
    <div className="grid-2 quality-extras">
      <section aria-label="Duplicate rows">
        <h3>
          Duplicate rows <Hint text="Rows identical to another row in every column, numbered as in the file." />
        </h3>
        {!duplicates || duplicates.count === 0 ? (
          <p className="empty-good">
            <span aria-hidden="true">✓</span> No exact duplicates.
          </p>
        ) : (
          <>
            <p>
              <strong>{duplicates.count.toLocaleString()}</strong> extra copies ({formatNumber(duplicates.share)}% of
              rows). They are left out of every figure.
            </p>
            <div className="scroll-table">
              <table className="data" aria-label="Duplicate groups">
                <thead>
                  <tr>
                    <th>Rows</th>
                    <th>Values</th>
                  </tr>
                </thead>
                <tbody>
                  {duplicates.groups.map((g) => (
                    <tr key={g.rows.join("-")}>
                      <td>{g.rows.join(", ")}</td>
                      <td className="muted">
                        {Object.entries(g.values)
                          .map(([k, v]) => `${k}: ${v ?? "–"}`)
                          .join(" · ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <section aria-label="Why values are missing">
        <h3>
          Why values are missing{" "}
          <Hint text="For each column with gaps: other columns that differ between rows where it's missing and rows where it isn't. Gaps that depend on other columns aren't random, so dropping those rows would skew the rest." />
        </h3>
        {missing.length === 0 ? (
          <p className="empty-good">
            <span aria-hidden="true">✓</span> No column is missing more than 1% of its values.
          </p>
        ) : (
          <ul className="insight-list" aria-label="Missing-value patterns">
            {missing.map((m) => (
              <li key={m.column}>
                <strong>{m.column}</strong>{" "}
                <span className="muted">
                  {formatNumber(m.missing_share)}% missing ({m.missing.toLocaleString()} rows)
                </span>
                {m.related.length === 0 ? (
                  <div className="muted small">Looks random: no other column differs where it's missing.</div>
                ) : (
                  <ul className="related-list">
                    {m.related.map((r) => (
                      <li key={r.column}>
                        {r.detail} <span className="muted">({formatP(r.p_value)})</span>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
