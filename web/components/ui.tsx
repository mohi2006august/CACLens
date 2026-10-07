import Link from "next/link";

import { ApiError, type Alert, type MetricFormat } from "@/lib/api";
import { channelLabel } from "@/lib/channels";
import { byFormat, dayLabel, signedPct } from "@/lib/format";
import { Term } from "./Term";

export function PageHead({ title, subtitle, children }: { title: string; subtitle?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {children}
    </header>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  const message = error instanceof ApiError ? error.message : "Something went wrong loading this view.";
  const notReady = error instanceof ApiError && error.status === 503;
  return (
    <div className="card error-card" role="alert">
      <h2>{notReady ? "No data yet" : "Couldn't load this view"}</h2>
      <p className="secondary">{message}</p>
      {notReady || (error instanceof ApiError && error.status === 0) ? (
        <pre className="code">{`uv run caclens refresh --demo   # build the demo warehouse\nuv run caclens serve            # start the API on :8000`}</pre>
      ) : null}
    </div>
  );
}

/**
 * Stat tile. `upIsGood` decides whether a rise is coloured as good or bad; the sign
 * and the "vs previous period" text always carry the meaning as well.
 */
export function KpiTile({
  label,
  metric,
  value,
  change,
  format,
  upIsGood,
  neutral = false,
  hero = false,
}: {
  label: string;
  metric: string;
  value: number | null;
  change: number | null;
  format: MetricFormat;
  upIsGood: boolean;
  /** Direction is neither good nor bad (e.g. spend): no colour, sign only. */
  neutral?: boolean;
  hero?: boolean;
}) {
  const direction = change === null || Math.abs(change) < 0.005 ? "flat" : change > 0 ? "up" : "down";
  const good = direction === "flat" || neutral ? null : (direction === "up") === upIsGood;
  return (
    <div className={`card ${hero ? "kpi-hero" : ""}`}>
      <span className="kpi-label">
        <Term metric={metric}>{label}</Term>
      </span>
      <div className="kpi-value">{byFormat(value, format)}</div>
      <div className={`delta ${good === null ? "delta-flat" : good ? "delta-good" : "delta-bad"}`}>
        {direction === "up" ? "▲" : direction === "down" ? "▼" : "•"} {signedPct(change)}{" "}
        <span className="muted">vs previous period</span>
      </div>
    </div>
  );
}

export function SeverityBadge({ severity }: { severity: Alert["severity"] }) {
  return (
    <span className={`pill ${severity === "critical" ? "pill-critical" : "pill-warning"}`}>
      <span aria-hidden>{severity === "critical" ? "▲▲" : "▲"}</span>
      {severity === "critical" ? "Critical" : "Warning"}
    </span>
  );
}

export const ALERT_METRICS: Record<string, { label: string; term: string; unit: string; early: boolean }> = {
  cost_per_qualified_lead: { label: "Cost per qualified lead", term: "cost_per_qualified_lead", unit: "qualified leads", early: true },
  cost_per_opportunity: { label: "Cost per opportunity", term: "cost_per_opportunity", unit: "opportunities", early: true },
  cac: { label: "CAC", term: "cac", unit: "customers", early: false },
  cac_fully_loaded: { label: "Fully loaded CAC", term: "cac_fully_loaded", unit: "customers", early: false },
};

export function alertMetric(metric: string) {
  return ALERT_METRICS[metric] ?? { label: metric, term: metric, unit: "outcomes", early: false };
}

export function AlertLine({ alert }: { alert: Alert }) {
  const m = alertMetric(alert.metric);
  const metric = m.early ? `${m.label} (early warning)` : m.label;
  return (
    <span>
      <SeverityBadge severity={alert.severity} /> {channelLabel(alert.channel)} {metric}{" "}
      <strong className="num">{signedPct(alert.change_pct)}</strong>{" "}
      <span className="muted">since {dayLabel(alert.first_detected_on)}</span>{" "}
      <Link href={`/channels/${alert.channel}?start=${alert.window_start}&end=${alert.window_end}`}>Investigate →</Link>
    </span>
  );
}
