import type { MetricFormat } from "./api";

const usd0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const usd2 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const int = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const dec1 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

export function currency(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Math.abs(v) >= 100 ? usd0.format(v) : usd2.format(v);
}

/** Compact currency for axes and dense tables: $84k, $1.2M. */
export function currencyCompact(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1_000_000) return `$${dec1.format(v / 1_000_000)}M`;
  if (a >= 10_000) return `$${int.format(v / 1_000)}k`;
  if (a >= 1_000) return `$${dec1.format(v / 1_000)}k`;
  return usd0.format(v);
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function signedPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const s = (v * 100).toFixed(digits);
  return `${v > 0 ? "+" : ""}${s}%`;
}

export function ratio(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(1)}x`;
}

export function months(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(1)} mo`;
}

export function number(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Math.abs(v) >= 100 || Number.isInteger(v) ? int.format(v) : dec1.format(v);
}

export function byFormat(v: number | null | undefined, format: MetricFormat | string): string {
  switch (format) {
    case "currency":
      return currency(v);
    case "percent":
      return pct(v);
    case "ratio":
      return ratio(v);
    case "months":
      return months(v);
    default:
      return number(v);
  }
}

export function axisFormat(v: number, format: MetricFormat | string): string {
  if (format === "currency") return currencyCompact(v);
  if (format === "percent") return `${Math.round(v * 100)}%`;
  if (format === "ratio") return `${dec1.format(v)}x`;
  if (format === "months") return `${dec1.format(v)}`;
  return Math.abs(v) >= 1000 ? `${dec1.format(v / 1000)}k` : dec1.format(v);
}

const monthFmt = new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
const dayFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });

export function monthLabel(iso: string): string {
  return monthFmt.format(new Date(`${iso.slice(0, 10)}T00:00:00Z`));
}

export function dayLabel(iso: string): string {
  return dayFmt.format(new Date(`${iso.slice(0, 10)}T00:00:00Z`));
}

export function rangeLabel(start: string, end: string): string {
  return `${dayLabel(start)} – ${dayLabel(end)}`;
}

export function modelLabel(model: string): string {
  const labels: Record<string, string> = {
    first_touch: "First touch",
    last_touch: "Last touch",
    linear: "Linear",
    time_decay: "Time decay",
    position_based: "Position-based",
  };
  return labels[model] ?? model;
}

export function segmentLabel(segment: string): string {
  const labels: Record<string, string> = {
    smb: "SMB",
    mid_market: "Mid-market",
    enterprise: "Enterprise",
    unknown: "Unknown",
  };
  return labels[segment] ?? segment;
}
