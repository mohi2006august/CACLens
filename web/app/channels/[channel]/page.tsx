import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { Controls } from "@/components/Controls";
import { DriversChart } from "@/components/charts/DriversChart";
import { LineChart } from "@/components/charts/LineChart";
import { Term } from "@/components/Term";
import { AlertLine, ErrorState, KpiTile, PageHead } from "@/components/ui";
import { api, type ChannelDetail, type Health, type Row } from "@/lib/api";
import { channelLabel } from "@/lib/channels";
import { currency, currencyCompact, modelLabel, number, pct, rangeLabel, ratio, months, segmentLabel } from "@/lib/format";
import { resolveView, type SearchParams } from "@/lib/range";

type Props = { params: Promise<{ channel: string }>; searchParams: Promise<SearchParams> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { channel } = await params;
  return { title: channelLabel(channel) };
}

const n = (row: Row, key: string): number | null => (typeof row[key] === "number" ? (row[key] as number) : null);

function change(cur: Row, prev: Row, key: string): number | null {
  const a = n(cur, key);
  const b = n(prev, key);
  return a !== null && b ? a / b - 1 : null;
}

export default async function ChannelPage({ params, searchParams }: Props) {
  const { channel } = await params;
  const sp = await searchParams;
  let data: ChannelDetail;
  let view = resolveView(sp);
  try {
    const health = await api<Health>("/v1/health");
    view = resolveView(sp, health.data_through);
    data = await api<ChannelDetail>(`/v1/channels/${encodeURIComponent(channel)}`, {
      start: view.start,
      end: view.end,
      fully_loaded: view.fullyLoaded,
      attribution: view.attribution,
    });
  } catch (error) {
    return (
      <>
        <PageHead title={channelLabel(channel)} />
        <ErrorState error={error} />
      </>
    );
  }

  const cur = data.funnel.current;
  const prev = data.funnel.previous;
  const cacKey = data.fully_loaded ? "cac_fully_loaded" : "cac";
  const funnelSteps = [
    { key: "impressions", label: "Impressions", rate: null },
    { key: "clicks", label: "Clicks", rate: "ctr" },
    { key: "leads", label: "Leads", rate: "lead_cvr" },
    { key: "qualified_leads", label: "Qualified leads", rate: "qualified_lead_rate" },
    { key: "opportunities", label: "Opportunities", rate: "opportunity_rate" },
    { key: "new_customers", label: "New customers", rate: "customer_cvr" },
  ];
  const isPaid = (n(cur, "paid_spend") ?? 0) > 0;
  const visibleSteps = isPaid ? funnelSteps : funnelSteps.slice(2);
  const maxStep = Math.max(1, ...visibleSteps.map((s) => n(cur, s.key) ?? 0));

  const trendSeries = [
    { key: "cac", label: "CAC", color: "var(--series-1)" },
    { key: "cac_fully_loaded", label: "Fully loaded CAC", color: "var(--series-2)" },
    { key: "cac_lagged", label: "Lagged CAC (1 mo)", color: "var(--series-3)" },
  ]
    .filter((s) => isPaid || s.key === "cac_fully_loaded")
    .map((s) => ({ ...s, points: data.trend.map((r) => ({ x: String(r.period), y: n(r, s.key) })) }));
  const cvrSeries = [
    { key: "lead_cvr", label: "Click to lead CVR", color: "var(--series-1)" },
    { key: "customer_cvr", label: "Lead to customer CVR", color: "var(--series-2)" },
    { key: "qualified_lead_rate", label: "Lead qualification rate", color: "var(--series-3)" },
  ].map((s) => ({ ...s, points: data.trend.map((r) => ({ x: String(r.period), y: n(r, s.key) })) }));

  return (
    <>
      <PageHead
        title={data.label}
        subtitle={`${rangeLabel(data.period.start, data.period.end)} vs ${rangeLabel(
          data.previous_period.start,
          data.previous_period.end,
        )} · ${modelLabel(data.attribution_model)} attribution`}
      >
        <Link href={`/${view.query ? `?${view.query}` : ""}`}>← All channels</Link>
      </PageHead>
      <Suspense fallback={null}>
        <Controls />
      </Suspense>

      {data.alerts.length > 0 && (
        <section className="card" style={{ marginBottom: 16 }} aria-label="Open alerts">
          {data.alerts.map((a) => (
            <AlertLine key={a.id} alert={a} />
          ))}
        </section>
      )}

      <section className="grid grid-kpi" style={{ marginBottom: 16 }} aria-label="Key metrics">
        <KpiTile hero label={data.fully_loaded ? "Fully loaded CAC" : "CAC"} metric={cacKey} value={n(cur, cacKey)} change={change(cur, prev, cacKey)} format="currency" upIsGood={false} />
        {isPaid && <KpiTile label="CPC" metric="cpc" value={n(cur, "cpc")} change={change(cur, prev, "cpc")} format="currency" upIsGood={false} />}
        {isPaid && <KpiTile label="Click to lead" metric="lead_cvr" value={n(cur, "lead_cvr")} change={change(cur, prev, "lead_cvr")} format="percent" upIsGood />}
        <KpiTile label="Lead qualification" metric="qualified_lead_rate" value={n(cur, "qualified_lead_rate")} change={change(cur, prev, "qualified_lead_rate")} format="percent" upIsGood />
        <KpiTile label="Lead to customer" metric="customer_cvr" value={n(cur, "customer_cvr")} change={change(cur, prev, "customer_cvr")} format="percent" upIsGood />
        <KpiTile label="New customers" metric="new_customers" value={n(cur, "new_customers")} change={change(cur, prev, "new_customers")} format="number" upIsGood />
      </section>

      <div className="grid grid-2" style={{ marginBottom: 16 }}>
        <section className="card">
          <div className="card-head">
            <div>
              <h2>Why CAC moved</h2>
              <p>
                <Term metric="cac">CAC</Term> = CPC ÷ (click→lead CVR × lead→customer CVR). Each bar is that factor’s effect on its own.
              </p>
            </div>
          </div>
          <p style={{ marginTop: 0 }}>{data.decomposition.summary}</p>
          <DriversChart drivers={data.decomposition.drivers} title={`${data.label} CAC change by driver`} />
        </section>

        <section className="card">
          <div className="card-head">
            <div>
              <h2>Funnel</h2>
              <p>Volumes this period with step conversion.</p>
            </div>
          </div>
          <table className="data">
            <tbody>
              {visibleSteps.map((s) => {
                const value = n(cur, s.key) ?? 0;
                return (
                  <tr key={s.key}>
                    <td style={{ width: 130 }}>
                      <Term metric={s.key}>{s.label}</Term>
                    </td>
                    <td className="r" style={{ width: 90 }}>
                      {number(value)}
                    </td>
                    <td>
                      <div className="bar-inline" style={{ width: `${Math.max(1, (Math.log10(value + 1) / Math.log10(maxStep + 1)) * 100)}%` }} />
                    </td>
                    <td className="r" style={{ width: 90 }}>
                      {s.rate ? pct(n(cur, s.rate)) : ""}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="muted" style={{ fontSize: 12 }}>
            Bars use a log scale so every stage stays visible. Spend {currencyCompact(n(cur, "paid_spend"))} paid ·{" "}
            {currencyCompact(n(cur, "fully_loaded_spend"))} fully loaded.
          </p>
        </section>
      </div>

      <div className="grid grid-2" style={{ marginBottom: 16 }}>
        <section className="card">
          <div className="card-head">
            <div>
              <h2>CAC trend</h2>
              <p>Last 12 months. Lagged CAC divides last month’s spend by this month’s customers.</p>
            </div>
          </div>
          <LineChart title={`${data.label} CAC by month`} summary={`${data.label} monthly CAC, fully loaded CAC and lagged CAC over the last 12 months.`} series={trendSeries} yFormat="currency" />
        </section>
        <section className="card">
          <div className="card-head">
            <div>
              <h2>Conversion trend</h2>
              <p>The conversion factors behind CAC; qualification moves first when lead quality changes.</p>
            </div>
          </div>
          <LineChart title={`${data.label} conversion rates by month`} summary={`${data.label} monthly click-to-lead and lead-to-customer conversion.`} series={cvrSeries} yFormat="percent" />
        </section>
      </div>

      {data.campaigns.length > 0 && (
        <section className="card" style={{ marginBottom: 16 }}>
          <div className="card-head">
            <h2>Campaigns</h2>
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Campaign</th>
                  <th className="r">Spend</th>
                  <th className="r">Clicks</th>
                  <th className="r">Leads</th>
                  <th className="r">Customers</th>
                  <th className="r"><Term metric="cac">CAC</Term></th>
                  <th className="r"><Term metric="cpc">CPC</Term></th>
                  <th className="r"><Term metric="customer_cvr">Lead→customer</Term></th>
                </tr>
              </thead>
              <tbody>
                {data.campaigns.map((c) => (
                  <tr key={String(c.campaign)}>
                    <td className="mono">{String(c.campaign)}</td>
                    <td className="r">{currencyCompact(n(c, "paid_spend"))}</td>
                    <td className="r">{number(n(c, "clicks"))}</td>
                    <td className="r">{number(n(c, "leads"))}</td>
                    <td className="r">{number(n(c, "new_customers"))}</td>
                    <td className="r">{n(c, "paid_spend") ? currency(n(c, "cac")) : "—"}</td>
                    <td className="r">{n(c, "paid_spend") ? currency(n(c, "cpc")) : "—"}</td>
                    <td className="r">{pct(n(c, "customer_cvr"))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: 12 }}>
            “(unallocated)” holds people and tool costs allocated to the channel but not to a campaign; “(none)” is credit to touches without a campaign tag.
          </p>
        </section>
      )}

      <section className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h2>Segments</h2>
        </div>
        <table className="data">
          <thead>
            <tr>
              <th>Segment</th>
              <th className="r">Customers</th>
              <th className="r"><Term metric={cacKey}>CAC</Term></th>
              <th className="r"><Term metric="ltv">LTV</Term></th>
              <th className="r"><Term metric={data.fully_loaded ? "ltv_cac_fully_loaded" : "ltv_cac"}>LTV:CAC</Term></th>
              <th className="r"><Term metric={data.fully_loaded ? "payback_months_fully_loaded" : "payback_months"}>Payback</Term></th>
            </tr>
          </thead>
          <tbody>
            {data.segments.map((s) => {
              const ltvCac = n(s, data.fully_loaded ? "ltv_cac_fully_loaded" : "ltv_cac");
              const payback = n(s, data.fully_loaded ? "payback_months_fully_loaded" : "payback_months");
              const hasCost = (n(s, cacKey) ?? 0) > 0;
              return (
                <tr key={String(s.segment)}>
                  <td>{segmentLabel(String(s.segment))}</td>
                  <td className="r">{number(n(s, "new_customers"))}</td>
                  <td className="r">{hasCost ? currency(n(s, cacKey)) : "—"}</td>
                  <td className="r">{currency(n(s, "ltv"))}</td>
                  <td className="r">{hasCost ? ratio(ltvCac) : "—"}</td>
                  <td className="r">{hasCost ? months(payback) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="muted" style={{ fontSize: 12 }}>
          Spend is split across segments by each month’s lead mix; see BRAIN.md → Decision log.
        </p>
      </section>

      <details className="card">
        <summary>Queries used</summary>
        {data.queries.map((q, i) => (
          <pre className="code" key={i}>
            {q}
          </pre>
        ))}
      </details>
    </>
  );
}
