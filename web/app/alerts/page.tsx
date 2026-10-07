import type { Metadata } from "next";
import Link from "next/link";

import { DriversChart } from "@/components/charts/DriversChart";
import { Term } from "@/components/Term";
import { ErrorState, PageHead, SeverityBadge } from "@/components/ui";
import { api, type Alert } from "@/lib/api";
import { channelLabel } from "@/lib/channels";
import { currency, dayLabel, number, signedPct } from "@/lib/format";
import { param, type SearchParams } from "@/lib/range";

export const metadata: Metadata = { title: "Alerts" };

function metricLabel(metric: string) {
  if (metric.startsWith("cost_per_opportunity")) return { label: "Cost per opportunity", term: "cost_per_opportunity", unit: "opportunities" };
  if (metric === "cac_fully_loaded") return { label: "Fully loaded CAC", term: "cac_fully_loaded", unit: "customers" };
  return { label: "CAC", term: "cac", unit: "customers" };
}

export default async function AlertsPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const status = param(sp, "status");
  const channel = param(sp, "channel");
  let alerts: Alert[];
  try {
    alerts = (await api<{ alerts: Alert[] }>("/v1/alerts", { status, channel })).alerts;
  } catch (error) {
    return (
      <>
        <PageHead title="Alerts" />
        <ErrorState error={error} />
      </>
    );
  }
  const filters = [
    { label: "All", href: "/alerts", active: !status && !channel },
    { label: "Open", href: "/alerts?status=open", active: status === "open" },
    { label: "Resolved", href: "/alerts?status=resolved", active: status === "resolved" },
  ];

  return (
    <>
      <PageHead
        title="Alerts"
        subtitle="Daily check: trailing 14-day cost vs the 56 days before, flagged only when the rise is statistically significant (Poisson p < 0.01). Cost per opportunity is the early warning; CAC confirms."
      />
      <nav className="controls" aria-label="Filter alerts">
        <span className="segmented">
          {filters.map((f) => (
            <Link key={f.label} href={f.href} aria-current={f.active ? "true" : undefined}>
              {f.label}
            </Link>
          ))}
        </span>
        {channel && (
          <span className="pill pill-neutral">
            {channelLabel(channel)} <Link href="/alerts" aria-label="Clear channel filter">×</Link>
          </span>
        )}
      </nav>

      {alerts.length === 0 && (
        <div className="card">
          <p className="secondary" style={{ margin: 0 }}>
            No alerts match. CAC has stayed within normal variation.
          </p>
        </div>
      )}

      <div className="stack">
        {alerts.map((a) => {
          const m = metricLabel(a.metric);
          return (
            <article key={a.id} className="card" aria-labelledby={`alert-${a.id}`}>
              <div className="card-head">
                <div>
                  <h2 id={`alert-${a.id}`} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <SeverityBadge severity={a.severity} />
                    {channelLabel(a.channel)} <Term metric={m.term}>{m.label}</Term>{" "}
                    <span className="num">{signedPct(a.change_pct)}</span>
                    <span className={`pill ${a.status === "open" ? "pill-critical" : "pill-neutral"}`}>
                      {a.status === "open" ? "Open" : "Resolved"}
                    </span>
                  </h2>
                  <p>
                    First detected {dayLabel(a.first_detected_on)}
                    {a.last_detected_on !== a.first_detected_on && ` · last ${dayLabel(a.last_detected_on)}`} · peak window{" "}
                    {dayLabel(a.window_start)} – {dayLabel(a.window_end)}
                  </p>
                </div>
                <Link className="btn btn-ghost" href={`/channels/${a.channel}?start=${a.window_start}&end=${a.window_end}`}>
                  Investigate
                </Link>
              </div>
              <div className="grid grid-2">
                <div>
                  <p style={{ marginTop: 0 }}>{a.summary}</p>
                  <table className="data">
                    <tbody>
                      <tr>
                        <td className="muted">Current window</td>
                        <td className="r">{currency(a.current_value)}</td>
                        <td className="r muted">
                          {number(a.current_count)} {m.unit}
                        </td>
                      </tr>
                      <tr>
                        <td className="muted">Baseline</td>
                        <td className="r">{currency(a.baseline_value)}</td>
                        <td className="r muted">
                          {number(a.baseline_count)} {m.unit}
                        </td>
                      </tr>
                      <tr>
                        <td className="muted">Significance</td>
                        <td className="r" colSpan={2}>
                          p = {a.p_value < 0.0001 ? "< 0.0001" : a.p_value.toFixed(4)}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <DriversChart drivers={a.drivers} title={`Drivers of the ${channelLabel(a.channel)} ${m.label} change`} />
              </div>
            </article>
          );
        })}
      </div>
    </>
  );
}
