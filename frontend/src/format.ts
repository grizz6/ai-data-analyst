/** "p < 0.001" or "p = 0.042", matching how the backend words its insights. */
export function formatP(p: number | null): string {
  if (p === null) return "p n/a";
  return p < 0.001 ? "p < 0.001" : `p = ${p.toFixed(3)}`;
}
