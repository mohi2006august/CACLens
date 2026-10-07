import type { Metadata } from "next";

import { BarChart } from "@/components/charts/BarChart";
import { LineChart } from "@/components/charts/LineChart";
import { Term } from "@/components/Term";
import { ErrorState, PageHead } from "@/components/ui";
import { api, type DataQuality } from "@/lib/api";
import { dayLabel, number, pct } from "@/lib/format";

export const metadata: Metadata = { title: "Data quality" };

const MATCH_LABELS: Record<string, string> = {
  crm_id: "CRM id in Stripe metadata",
  email: "Hashed email",
  domain: "Company domain",
  unmatched: "No match (unattributed)",
};

function staleness(loaded: string | null, dataThrough: string): { label: string; cls: string } {
  if (!loaded) return { label: "Never loaded", cls: "pill-critical" };
  const hours = (Date.parse(`${dataThrough}T23:59:59Z`) - Date.parse(`${loaded}Z`)) / 3_600_000;
  if (hours > 72) return { label: "Stale", cls: "pill-critical" };
  if (hours > 36) return { label: "Late", cls: "pill-warning" };
  return { label: "Fresh", cls: "pill-good" };
}

export default async function DataQualityPage() {
  let data: DataQuality;
  try {
    data = await api<DataQuality>("/v1/data-quality");
  } catch (error) {
    return (
      <>
        <PageHead title="Data quality" />
        <ErrorState error={error} />
      </>
    );
  }
  const total = data.identity_matches.reduce((s, m) => s + m.customers, 0) || 1;
  return (
    <>
      <PageHead title="Data quality" subtitle="Freshness per source, identity stitching coverage and the unattributed share." />
      <div className="grid grid-2" style={{ marginBottom: 16 }}>
        <section className="card">
          <div className="card-head">
            <div>
              <h2>Identity stitching</h2>
              <p>How each paying customer was linked to its CRM journey.</p>
            </div>
          </div>
          <BarChart
            title="Customers by identity match method"
            summary={data.identity_matches.map((m) => `${MATCH_LABELS[m.match_method] ?? m.match_method}: ${m.customers}`).join(", ")}
            rows={data.identity_matches.map((m) => ({
              key: m.match_method,
              label: MATCH_LABELS[m.match_method] ?? m.match_method,
              value: m.customers,
              note: pct(m.customers / total, 0),
            }))}
            format="number"
          />
        </section>
        <section className="card">
          <div className="card-head">
            <div>
              <h2>
                <Term metric="unattributed_share">Unattributed share</Term> by month
              </h2>
              <p>Customers with no known source touchpoint. Lower is better.</p>
            </div>
          </div>
          <LineChart
            title="Unattributed share of new customers by month"
            summary={`Unattributed share over the last 12 months, latest ${pct(data.unattributed_trend.at(-1)?.unattributed_share ?? null)}.`}
            series={[
              {
                key: "unattributed",
                label: "Unattributed share",
                color: "var(--series-1)",
                points: data.unattributed_trend.map((r) => ({ x: r.period, y: r.unattributed_share })),
              },
            ]}
            yFormat="percent"
            height={200}
          />
        </section>
      </div>
      <section className="card">
        <div className="card-head">
          <div>
            <h2>Source freshness</h2>
            <p>Warn after 36 hours, error after 72 (cost files: 45 and 75 days). Data through {dayLabel(data.data_through)}.</p>
          </div>
        </div>
        <table className="data">
          <thead>
            <tr>
              <th>Raw table</th>
              <th>Source</th>
              <th className="r">Rows</th>
              <th>Last loaded</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {data.freshness.map((f) => {
              const costFile = f.group === "costs";
              const s = costFile ? { label: "Monthly file", cls: "pill-neutral" } : staleness(f.last_loaded_at, data.data_through);
              return (
                <tr key={f.table}>
                  <td className="mono">raw.{f.table}</td>
                  <td className="secondary">{f.group}</td>
                  <td className="r">{number(f.rows)}</td>
                  <td className="num">{f.last_loaded_at ? f.last_loaded_at.replace("T", " ").slice(0, 16) : "—"}</td>
                  <td>
                    <span className={`pill ${s.cls}`}>{s.label}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </>
  );
}
