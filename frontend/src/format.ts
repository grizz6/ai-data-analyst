/** "p < 0.001" or "p = 0.042", matching how the backend words its insights. */
export function formatP(p: number | null): string {
  if (p === null) return "p n/a";
  return p < 0.001 ? "p < 0.001" : `p = ${p.toFixed(3)}`;
}

/** A statistic for display: thousands separators and at most two decimals ("9,419.35", "92"). */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  const text = value.toLocaleString("en-US", { maximumFractionDigits: 2 });
  // A tiny negative rounds to "-0", which reads like an error.
  return text === "-0" ? "0" : text;
}

/** Plain-language name for a pandas dtype ("int64" -> "Whole number"). */
export function friendlyType(dtype: string): string {
  if (dtype.startsWith("datetime")) return "Date";
  if (dtype === "bool" || dtype === "boolean") return "Yes / no";
  if (/^u?int|^U?Int/.test(dtype)) return "Whole number";
  if (/^float|^Float/.test(dtype)) return "Number";
  return "Text";
}
