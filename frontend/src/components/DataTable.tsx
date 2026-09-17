interface Props {
  rows: Record<string, unknown>[];
  title?: string;
}

export default function DataTable({ rows, title }: Props) {
  if (!rows.length) return null;

  const columns = Object.keys(rows[0]);

  return (
    <>
      {title ? <h2>{title}</h2> : null}
      <div className="scroll-table">
        <table className="data">
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {columns.map((col) => (
                  <td key={col}>{String(row[col] ?? "")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
