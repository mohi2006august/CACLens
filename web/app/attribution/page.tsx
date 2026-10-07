import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { Controls } from "@/components/Controls";
import { Term } from "@/components/Term";
import { ErrorState, PageHead } from "@/components/ui";
import { api, type AttributionCompare, type Health } from "@/lib/api";
import { channelColor } from "@/lib/channels";
import { byFormat, modelLabel, rangeLabel } from "@/lib/format";
import { param, resolveView, type SearchParams } from "@/lib/range";

export const metadata: Metadata = { title: "Attribution" };

const METRICS = [
  { name: "cac", label: "CAC", format: "currency" },
  { name: "cac_fully_loaded", label: "Fully loaded CAC", format: "currency" },
  { name: "new_customers", label: "New customers", format: "number" },
  { name: "ltv_cac", label: "LTV:CAC", format: "ratio" },
  { name: "payback_months", label: "Payback", format: "months" },
] as const;

const MODEL_NOTES: Record<string, string> = {
  first_touch: "All credit to the touch that started the journey. Favours discovery channels.",
  last_touch: "All credit to the final touch before purchase. Favours closers such as email and brand search.",
  linear: "Equal credit to every touch.",
  time_decay: "Credit halves for every 7 days between a touch and the purchase.",
  position_based: "40% first touch, 40% last touch, 20% shared across the middle. The default.",
};

export default async function AttributionPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const metric = METRICS.find((m) => m.name === param(sp, "metric")) ?? METRICS[0];
  let view = resolveView(sp);
  let data: AttributionCompare;
  try {
    const health = await api<Health>("/v1/health");
    view = resolveView(sp, health.data_through);
    data = await api<AttributionCompare>("/v1/attribution/compare", { metric: metric.name, start: view.start, end: view.end });
  } catch (error) {
    return (
      <>
        <PageHead title="Attribution" />
        <ErrorState error={error} />
      </>
    );
  }
  const link = (name: string) => {
    const next = new URLSearchParams(view.query);
    next.set("metric", name);
    return `?${next.toString()}`;
  };

  return (
    <>
      <PageHead
        title="Attribution models"
        subtitle={`${rangeLabel(data.period.start, data.period.end)} · the same customers credited five ways, side by side. No single model is “the truth”.`}
      />
      <Suspense fallback={null}>
        <Controls showFullyLoaded={false} showAttribution={false} />
      </Suspense>
      <nav className="controls" aria-label="Metric">
        <span className="muted">Compare</span>
        <span className="segmented">
          {METRICS.map((m) => (
            <Link key={m.name} href={link(m.name)} aria-current={m.name === metric.name ? "true" : undefined}>
              {m.label}
            </Link>
          ))}
        </span>
      </nav>

      <section className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <div>
            <h2>
              <Term metric={metric.name}>{metric.label}</Term> by channel and model
            </h2>
            <p>The small number is the channel’s rank under that model (1 = best). Highlighted ranks differ from position-based.</p>
          </div>
        </div>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Channel</th>
                {data.models.map((m) => (
                  <th key={m} className="r">
                    {modelLabel(m)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.channel}>
                  <td>
                    <span className="swatch" style={{ background: channelColor(r.channel) }} aria-hidden />
                    {r.label}
                  </td>
                  {data.models.map((m) => {
                    const rank = r.ranks[m];
                    const moved = rank !== undefined && r.ranks.position_based !== undefined && rank !== r.ranks.position_based;
                    const value = r.values[m] ?? null;
                    const empty = value === null || (metric.format !== "number" && value === 0);
                    return (
                      <td key={m} className="r">
                        {empty ? "—" : byFormat(value, metric.format)}
                        {rank !== undefined && !empty && (
                          <span
                            className={`pill ${moved ? "pill-warning" : "pill-neutral"}`}
                            style={{ marginLeft: 6, padding: "0 6px" }}
                            aria-label={`rank ${rank}${moved ? ", differs from position-based" : ""}`}
                          >
                            {rank}
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h2 style={{ marginBottom: 8 }}>How each model splits credit</h2>
        <table className="data">
          <tbody>
            {data.models.map((m) => (
              <tr key={m}>
                <td style={{ width: 160, fontWeight: 600 }}>{modelLabel(m)}</td>
                <td className="secondary">{MODEL_NOTES[m]}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <details style={{ marginTop: 12 }}>
          <summary className="muted">Query used</summary>
          <pre className="code">{data.query}</pre>
        </details>
      </section>
    </>
  );
}
