import type { RecentAnalysis } from "../recent";

interface Props {
  items: RecentAnalysis[];
  disabled: boolean;
  onOpen: (sessionId: string) => void;
}

function timeAgo(at: number): string {
  const minutes = Math.round((Date.now() - at) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours} h ago` : `${Math.round(hours / 24)} d ago`;
}

export default function RecentAnalyses({ items, disabled, onOpen }: Props) {
  if (items.length === 0) return null;
  return (
    <section className="panel" aria-labelledby="recent-heading">
      <h2 id="recent-heading">Recent analyses</h2>
      <p className="muted small">Results are kept on the server for a while after you last open them.</p>
      <ul className="recent-list">
        {items.map((item) => (
          <li key={item.sessionId}>
            <button type="button" className="recent-item" disabled={disabled} onClick={() => onOpen(item.sessionId)}>
              <span className="recent-name">{item.filename}</span>
              <span className="muted small">
                {item.rows.toLocaleString()} rows · {item.columns} columns · {timeAgo(item.openedAt)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
