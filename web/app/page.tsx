import Link from "next/link";
import { Suspense } from "react";

import { ChannelTable } from "@/components/ChannelTable";
import { Controls } from "@/components/Controls";
import { LineChart } from "@/components/charts/LineChart";
import { Term } from "@/components/Term";
import { AlertLine, ErrorState, KpiTile, PageHead } from "@/components/ui";
import { api, type Health, type Overview, type Row } from "@/lib/api";
import { channelColor, channelLabel } from "@/lib/channels";
import { currency, modelLabel, pct, rangeLabel } from "@/lib/format";
import { resolveView, type SearchParams } from "@/lib/range";

export default async function OverviewPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  let health: Health;
  let data: Overview;
  let trend: { rows: Row[] };
  const view = { ...resolveView(sp) };
  try {
    health = await api<Health>("/v1/health");
    Object.assign(view, resolveView(sp, health.data_through));
    const cacMetric = view.fullyLoaded ? "cac_fully_loaded" : "cac";
    const endDate = view.end ?? health.data_through ?? undefined;
    const trendStart = endDate ? `${Number(endDate.slice(0, 4)) - 1}${endDate.slice(4, 7)}-01` : undefined;
    [data, trend] = await Promise.all([
      api<Overview>("/v1/overview", {
        start: view.start,
        end: view.end,
        fully_loaded: view.fullyLoaded,
        attribution: view.attribution,
      }),
      api<{ rows: Row[] }>(`/v1/metrics/${cacMetric}`, {
        by: "channel",
        period: "month",
        start: trendStart,
        end: endDate,
        attribution: view.attribution,
        filter: "is_paid_channel:eq:true",
      }),
    ]);
  } catch (error) {
    return (
      <>
        <PageHead title="Overview" />
        <ErrorState error={error} />
      </>
    );
  }

  const k = data.kpis;
  const unattributed = k.unattributed_share?.value ?? 0;
  const openAlerts = data.channels.flatMap((c) => c.alerts);
  const cacKey = view.fullyLoaded ? "cac_fully_loaded" : "cac";
  const paidChannels = [...new Set(trend.rows.map((r) => String(r.channel)))].filter((c) =>
    ["google_search", "meta_ads", "linkedin_ads"].includes(c),
  );
  const series = paidChannels.map((c) => ({
    key: c,
    label: channelLabel(c),
    color: channelColor(c),
    points: trend.rows
      .filter((r) => r.channel === c)
      .map((r) => ({ x: String(r.period), y: typeof r[cacKey] === "number" ? (r[cacKey] as number) : null })),
  }));
  const latest = series.map((s) => `${s.label} ${currency(s.points[s.points.length - 1]?.y ?? null)}`).join(", ");

  return (
    <>
      <PageHead
        title="Overview"
        subtitle={`${rangeLabel(data.period.start, data.period.end)} · ${modelLabel(data.attribution_model)} attribution · ${
          data.fully_loaded ? "fully loaded (incl. salaries & tools)" : "paid media only"
        }`}
      />
      <Suspense fallback={null}>
        <Controls />
      </Suspense>

      {unattributed >= 0.1 && (
        <div className="banner" role="status">
          <span aria-hidden>⚠</span>
          <span>
            <strong>{pct(unattributed, 0)} of new customers have no source</strong>: their purchases can’t be credited to a
            channel, so channel CAC is overstated. Fix UTMs and CRM capture. <Link href="/data-quality">See data quality →</Link>
          </span>
        </div>
      )}

      {openAlerts.length > 0 && (
        <section className="card" style={{ marginBottom: 16 }} aria-label="Open alerts">
          <div className="stack" style={{ gap: 8 }}>
            {openAlerts.map((a) => (
              <AlertLine key={a.id} alert={a} />
            ))}
          </div>
        </section>
      )}

      <section className="grid grid-kpi" aria-label="Key metrics" style={{ marginBottom: 16 }}>
        <KpiTile hero label="Blended CAC" metric={k.blended_cac!.metric} value={k.blended_cac!.value} change={k.blended_cac!.change_pct} format="currency" upIsGood={false} />
        <KpiTile label="Paid CAC" metric="paid_cac" value={k.paid_cac!.value} change={k.paid_cac!.change_pct} format="currency" upIsGood={false} />
        <KpiTile label="LTV:CAC" metric={k.ltv_cac!.metric} value={k.ltv_cac!.value} change={k.ltv_cac!.change_pct} format="ratio" upIsGood />
        <KpiTile label="CAC payback" metric={k.payback_months!.metric} value={k.payback_months!.value} change={k.payback_months!.change_pct} format="months" upIsGood={false} />
        <KpiTile label="New customers" metric="new_customers" value={k.new_customers!.value} change={k.new_customers!.change_pct} format="number" upIsGood />
        <KpiTile label={data.fully_loaded ? "Fully loaded spend" : "Paid spend"} metric={k.spend!.metric} value={k.spend!.value} change={k.spend!.change_pct} format="currency" upIsGood={false} />
      </section>

      <section className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <div>
            <h2>Channels</h2>
            <p>Click a channel for its funnel, CAC drivers and campaigns.</p>
          </div>
        </div>
        <ChannelTable channels={data.channels} fullyLoaded={data.fully_loaded} query={view.query} />
      </section>

      <section className="card">
        <div className="card-head">
          <div>
            <h2>
              <Term metric={cacKey}>{data.fully_loaded ? "Fully loaded CAC" : "CAC"}</Term> by month, paid channels
            </h2>
            <p>Last 12 months · {modelLabel(data.attribution_model)} attribution</p>
          </div>
        </div>
        <LineChart
          title="CAC by month for paid channels"
          summary={`Monthly CAC for paid channels. Latest month: ${latest}.`}
          series={series}
          yFormat="currency"
        />
      </section>
    </>
  );
}
