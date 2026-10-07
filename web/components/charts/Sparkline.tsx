import { currency } from "@/lib/format";

/** Trend glyph: de-emphasis line with the current period in the accent. */
export function Sparkline({ values, label }: { values: (number | null)[]; label: string }) {
  const pts = values.map((v, i) => ({ i, v })).filter((p): p is { i: number; v: number } => p.v !== null);
  if (pts.length < 2) return <span className="muted">—</span>;
  const w = 88;
  const h = 26;
  const min = Math.min(...pts.map((p) => p.v));
  const max = Math.max(...pts.map((p) => p.v));
  const span = max - min || 1;
  const x = (i: number) => 3 + (i / Math.max(1, values.length - 1)) * (w - 6);
  const y = (v: number) => h - 4 - ((v - min) / span) * (h - 8);
  const d = pts.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
  const last = pts[pts.length - 1]!;
  const first = pts[0]!;
  return (
    <span title={`${label}: ${currency(first.v)} → ${currency(last.v)}`}>
      <svg width={w} height={h} aria-hidden="true" style={{ verticalAlign: "middle" }}>
        <path d={d} fill="none" stroke="var(--ink-3)" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={x(last.i)} cy={y(last.v)} r={3} fill="var(--accent)" stroke="var(--surface)" strokeWidth={1.5} />
      </svg>
      <span className="sr-only">
        {label} trend from {currency(first.v)} to {currency(last.v)}
      </span>
    </span>
  );
}
