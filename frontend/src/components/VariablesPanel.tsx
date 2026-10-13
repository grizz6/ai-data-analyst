import { useState } from "react";
import { formatNumber } from "../format";
import type { VariableProfile } from "../types";
import VariableCard, { KIND_LABELS } from "./VariableCard";

type Filter = "all" | "numbers" | "binary" | "categories" | "dates" | "other" | "flagged";

const FILTERS: [Filter, string, (v: VariableProfile) => boolean][] = [
  ["all", "All", () => true],
  ["numbers", "Numbers", (v) => v.kind === "number" || v.kind === "count"],
  ["binary", "Yes / no", (v) => v.kind === "binary"],
  ["categories", "Categories", (v) => v.kind === "category"],
  ["dates", "Dates", (v) => v.kind === "date"],
  ["other", "IDs & text", (v) => ["identifier", "text", "constant"].includes(v.kind)],
  ["flagged", "Needs a look", (v) => v.flags.length > 0 || (v.outliers?.iqr_count ?? 0) > 0],
];

interface Props {
  variables: VariableProfile[];
  selected: string | null;
  onSelect: (name: string) => void;
}

export default function VariablesPanel({ variables, selected, onSelect }: Props) {
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const test = FILTERS.find(([id]) => id === filter)![2];
  const needle = search.trim().toLowerCase();
  const shown = variables.filter((v) => test(v) && (!needle || v.name.toLowerCase().includes(needle)));
  const current =
    variables.find((v) => v.name === selected) ??
    variables.find((v) => v.kind !== "identifier" && v.kind !== "constant") ??
    variables[0];

  if (!variables.length) return <p className="muted">No columns to profile.</p>;

  return (
    <div className="variables-layout">
      <aside className="variable-picker">
        <input
          type="search"
          className="builder-select"
          aria-label="Find a column"
          placeholder="Find a column…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="filter-chips" role="group" aria-label="Filter columns">
          {FILTERS.map(([id, label, match]) => {
            const count = variables.filter(match).length;
            if (id !== "all" && count === 0) return null;
            return (
              <button
                key={id}
                type="button"
                className={filter === id ? "chip active" : "chip"}
                aria-pressed={filter === id}
                onClick={() => setFilter(id)}
              >
                {label} <span className="muted">{count}</span>
              </button>
            );
          })}
        </div>
        <ul className="variable-list" aria-label="Columns">
          {shown.map((v) => (
            <li key={v.name}>
              <button
                type="button"
                className={v.name === current?.name ? "variable-item active" : "variable-item"}
                aria-current={v.name === current?.name}
                onClick={() => onSelect(v.name)}
              >
                <span className="variable-name">{v.name}</span>
                <span className="variable-meta">
                  {KIND_LABELS[v.kind]}
                  {v.missing_share > 0 && ` · ${formatNumber(v.missing_share)}% missing`}
                  {(v.outliers?.iqr_count ?? 0) > 0 && ` · ${v.outliers!.iqr_count} outliers`}
                </span>
              </button>
            </li>
          ))}
          {shown.length === 0 && <li className="muted small">No column matches.</li>}
        </ul>
      </aside>
      {current && <VariableCard key={current.name} variable={current} />}
    </div>
  );
}
