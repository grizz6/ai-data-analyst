import { formatNumber, formatP } from "../format";
import type { StatisticalTests } from "../types";

const SIGNIFICANT = 0.05;

function Verdict({ p }: { p: number | null }) {
  if (p === null) return <span className="muted">–</span>;
  return p < SIGNIFICANT ? <span className="badge good">likely real</span> : <span className="badge info">could be chance</span>;
}

function Section({ title, lead, children }: { title: string; lead: string; children: React.ReactNode }) {
  return (
    <section className="stats-section">
      <h3>{title}</h3>
      <p className="panel-lead">{lead}</p>
      <div className="scroll-table">{children}</div>
    </section>
  );
}

export default function StatisticsPanel({ tests }: { tests: StatisticalTests }) {
  const empty =
    tests.distributions.length +
      tests.rank_correlations.length +
      tests.categorical_associations.length +
      tests.group_differences.length +
      tests.missing_patterns.length ===
    0;
  if (empty) return <p className="muted">This file doesn't have the numeric or category columns these tests need.</p>;

  return (
    <>
      <p className="panel-lead">
        Many tests run at once, so some would look significant by chance. Each p-value below is adjusted for that
        (Benjamini–Hochberg); "likely real" means the adjusted p is under 0.05.
      </p>

      {tests.group_differences.length > 0 && (
        <Section
          title="Do numbers differ between groups?"
          lead="Compares a numeric column across the groups of a category (Kruskal–Wallis, with ANOVA alongside). Effect size is the share of variation the groups explain."
        >
          <table className="data">
            <thead>
              <tr>
                <th>Value</th>
                <th>By</th>
                <th>Highest group</th>
                <th>Lowest group</th>
                <th className="num" title="Eta squared: share of the variation explained by the groups">Effect</th>
                <th>Adjusted p</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {tests.group_differences.map((g) => (
                <tr key={`${g.group_column}|${g.value_column}`}>
                  <td>{g.value_column}</td>
                  <td>{g.group_column}</td>
                  <td>
                    {g.highest_group} <span className="muted">({formatNumber(g.highest_mean)})</span>
                  </td>
                  <td>
                    {g.lowest_group} <span className="muted">({formatNumber(g.lowest_mean)})</span>
                  </td>
                  <td className="num">{Math.round(g.eta_squared * 100)}%</td>
                  <td>{formatP(g.p_adjusted)}</td>
                  <td>
                    <Verdict p={g.p_adjusted} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {tests.categorical_associations.length > 0 && (
        <Section
          title="Are categories related?"
          lead="Chi-square test of independence between two category columns. Cramér's V runs from 0 (unrelated) to 1 (one determines the other)."
        >
          <table className="data">
            <thead>
              <tr>
                <th>Columns</th>
                <th className="num">Cramér's V</th>
                <th>Adjusted p</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {tests.categorical_associations.map((a) => (
                <tr key={`${a.column_a}|${a.column_b}`}>
                  <td>
                    {a.column_a} × {a.column_b}
                    {a.sparse && (
                      <span className="badge warning" title="Many combinations are rare, so the p-value is less reliable">
                        sparse
                      </span>
                    )}
                  </td>
                  <td className="num">{a.cramers_v.toFixed(2)}</td>
                  <td>{formatP(a.p_adjusted)}</td>
                  <td>
                    <Verdict p={a.p_adjusted} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {tests.rank_correlations.length > 0 && (
        <Section
          title="Rank correlations"
          lead="Spearman and Kendall measure whether two columns rise and fall together, even along a curve; Pearson only sees straight lines. A rank value well above Pearson means a curved relationship."
        >
          <table className="data">
            <thead>
              <tr>
                <th>Columns</th>
                <th className="num">Spearman</th>
                <th className="num">Kendall</th>
                <th className="num">Pearson</th>
                <th className="num">n</th>
                <th>Adjusted p</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {tests.rank_correlations.map((r) => (
                <tr key={`${r.column_a}|${r.column_b}`}>
                  <td>
                    {r.column_a} ↔ {r.column_b}
                  </td>
                  <td className="num">{r.spearman.toFixed(2)}</td>
                  <td className="num">{r.kendall === null ? "–" : r.kendall.toFixed(2)}</td>
                  <td className="num">{r.pearson === null ? "–" : r.pearson.toFixed(2)}</td>
                  <td className="num">{r.n.toLocaleString()}</td>
                  <td>{formatP(r.p_adjusted)}</td>
                  <td>
                    <Verdict p={r.p_adjusted} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {tests.distributions.length > 0 && (
        <Section
          title="Distribution shape"
          lead="Skewness above 1 or below −1 means a long tail on one side, where the median is a better 'typical' value than the mean. The normality test (D'Agostino–Pearson) flags tiny departures in large files, so read it with the shape."
        >
          <table className="data">
            <thead>
              <tr>
                <th>Column</th>
                <th>Shape</th>
                <th className="num">Skewness</th>
                <th className="num" title="Excess kurtosis: 0 for a normal distribution">Kurtosis</th>
                <th>Normality p</th>
                <th className="num" title="Values more than 3 standard deviations from the mean">Beyond 3 SD</th>
              </tr>
            </thead>
            <tbody>
              {tests.distributions.map((d) => (
                <tr key={d.column}>
                  <td>{d.column}</td>
                  <td>{d.shape}</td>
                  <td className="num">{formatNumber(d.skewness)}</td>
                  <td className="num">{formatNumber(d.kurtosis)}</td>
                  <td>{formatP(d.normality_p)}</td>
                  <td className="num">{d.zscore_outliers.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {tests.missing_patterns.length > 0 && (
        <Section
          title="Values missing together"
          lead="Pairs of columns whose gaps fall on the same rows, which often points to one cause upstream (a form section skipped, an export that failed)."
        >
          <table className="data">
            <thead>
              <tr>
                <th>Columns</th>
                <th className="num">Both missing</th>
                <th className="num">Correlation of gaps</th>
              </tr>
            </thead>
            <tbody>
              {tests.missing_patterns.map((m) => (
                <tr key={`${m.column_a}|${m.column_b}`}>
                  <td>
                    {m.column_a} + {m.column_b}
                  </td>
                  <td className="num">{m.both_missing.toLocaleString()}</td>
                  <td className="num">{m.correlation.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
    </>
  );
}
