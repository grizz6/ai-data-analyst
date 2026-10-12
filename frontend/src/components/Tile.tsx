import Hint from "./Hint";

interface Props {
  label: string;
  value: string;
  tone?: "good" | "attention";
  hint?: string;
}

/** One number with its label: the dashboard's basic unit. */
export default function Tile({ label, value, tone, hint }: Props) {
  return (
    <div className={tone ? `stat ${tone}` : "stat"}>
      <div className="label">
        {label} {hint && <Hint text={hint} />}
      </div>
      <div className="value">{value}</div>
    </div>
  );
}
