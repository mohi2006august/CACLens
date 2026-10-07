import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { Controls } from "@/components/Controls";
import { LineChart } from "@/components/charts/LineChart";
import { Term } from "@/components/Term";
import { ErrorState, PageHead } from "@/components/ui";
import { api, type CohortGrid, type Health, type Payback } from "@/lib/api";
import { channelColor, channelLabel } from "@/lib/channels";
import { currency, modelLabel, monthLabel, number, pct } from "@/lib/format";
import { param, resolveView, type SearchParams } from "@/lib/range";

export const metadata: Metadata = { title: "Cohorts" };

function quarters(from: string, to: string): string[] {
  const out: string[] = [];
  let y = Number(from.slice(0, 4));
  let q = Math.floor((Number(from.slice(5, 7)) - 1) / 3) + 1;
  const endY = Number(to.slice(0, 4));
  const endQ = Math.floor((Number(to.slice(5, 7)) - 1) / 3) + 1;
  while (y < endY || (y === endY && q <= endQ)) {
    out.push(`${y}-Q${q}`);
    q += 1;
    if (q > 4) {
      q = 1;
      y += 1;
    }
  }
  return out;
}

const SEQ = ["var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)", "var(--seq-6)"];

function cellStyle(value: number | null): React.CSSProperties {
  if (value === null) return {};
  const idx = Math.min(SEQ.length - 1, Math.floor(value * SEQ.length));
  return { background: SEQ[idx], color: idx >= 3 ? "#fff" : "var(--ink)", textAlign: "center" };
}

export default async function CohortsPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const view = resolveView(sp);
  let health: Health;
  let payback: Payback;
  let grid: CohortGrid;
  let options: string[] = [];
  let cohort = param(sp, "cohort");
  try {
    health = await api<Health>("/v1/health");
    options = health.data_from && health.revenue_through ? quarters(health.data_from, health.revenue_through) : [];
    cohort = cohort ?? options[Math.max(0, options.length - 5)];
    [payback, grid] = await Promise.all([
      api<Payback>("/v1/metrics/payback", {
        cohort,
        fully_loaded: view.fullyLoaded,
        attribution: view.attribution,
      }),
      api<CohortGrid>("/v1/cohorts", { attribution: view.attribution }),
    ]);
  } catch (error) {
    return (
      <>
        <PageHead title="Cohorts" />
        <ErrorState error={error} />
      </>
    );
  }

  const curves = payback.curves.filter((c) => (c.cac ?? 0) > 0 && c.customers >= 5 && c.series !== "unattributed");
  const series = curves.map((c) => ({
    key: c.series,
    label: channelLabel(c.series),
    color: channelColor(c.series),
    points: c.points.map((p) => ({ x: p.month, y: p.cac_recovered_pct })),
  }));
  const maxMonth = Math.max(0, ...grid.rows.flatMap((r) => r.cells.map((c) => c.month)));
  const keep = (q: string) => {
    const next = new URLSearchParams(view.query);
    next.set("cohort", q);
    return `?${next.toString()}`;
  };

  return (
    <>
      <PageHead
        title="Cohorts"
        subtitle={`Payback by acquisition cohort · ${modelLabel(payback.attribution_model)} attribution · ${
          view.fullyLoaded ? "fully loaded CAC" : "paid CAC"
        }`}
      />
      <Suspense fallback={null}>
        <Controls showRange={false} />
      </Suspense>
      <nav className="controls" aria-label="Cohort">
        <span className="muted">Cohort</span>
        <span className="segmented">
          {options.map((q) => (
            <Link key={q} href={keep(q)} aria-current={q === cohort ? "true" : undefined}>
              {q}
            </Link>
          ))}
        </span>
      </nav>

      <section className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <div>
            <h2>
              <Term metric="payback_months">Payback curves</Term>, {payback.cohort.label} cohort
            </h2>
            <p>
              Cumulative <Term metric="gross_margin_revenue">gross margin</Term> per acquired customer as a share of that channel’s CAC.
              A curve crossing 100% has paid back.
            </p>
          </div>
        </div>
        <LineChart
          title={`Payback curves for the ${payback.cohort.label} cohort`}
          summary={curves
            .map((c) => `${channelLabel(c.series)}: ${c.payback_month === null ? "not yet paid back" : `pays back in month ${c.payback_month}`}`)
            .join(". ")}
          series={series}
          yFormat="percent"
          xType="number"
          xLabel={(x) => `M${x}`}
          xAxisTitle="Months since acquisition"
          reference={{ y: 1, label: "CAC recovered" }}
        />
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table className="data">
            <thead>
              <tr>
                <th>Channel</th>
                <th className="r">Customers</th>
                <th className="r"><Term metric={payback.cac_metric}>CAC</Term></th>
                <th className="r">Payback month</th>
                <th className="r">GM / customer at M6</th>
                <th className="r">GM / customer at M12</th>
                <th className="r">Retention at M12</th>
              </tr>
            </thead>
            <tbody>
              {curves.map((c) => {
                const at = (m: number) => c.points.find((p) => p.month === m);
                return (
                  <tr key={c.series}>
                    <td>
                      <span className="swatch" style={{ background: channelColor(c.series) }} aria-hidden />
                      {channelLabel(c.series)}
                    </td>
                    <td className="r">{number(c.customers)}</td>
                    <td className="r">{currency(c.cac)}</td>
                    <td className="r">{c.payback_month === null ? "not yet" : `M${c.payback_month}`}</td>
                    <td className="r">{currency(at(6)?.cumulative_gross_margin_per_customer ?? null)}</td>
                    <td className="r">{currency(at(12)?.cumulative_gross_margin_per_customer ?? null)}</td>
                    <td className="r">{pct(at(12)?.retention ?? null, 0)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <div>
            <h2>Retention by cohort</h2>
            <p>Share of each month’s new customers still paying N months later (all channels).</p>
          </div>
          <span className="legend" aria-hidden>
            <span>0%</span>
            {SEQ.map((c) => (
              <span key={c} className="swatch" style={{ background: c, margin: 0 }} />
            ))}
            <span>100%</span>
          </span>
        </div>
        <div className="table-wrap">
          <table className="data" style={{ fontSize: 12 }}>
            <caption className="sr-only">Retention by acquisition month and months since acquisition</caption>
            <thead>
              <tr>
                <th scope="col">Cohort</th>
                <th scope="col" className="r">Customers</th>
                {Array.from({ length: maxMonth + 1 }, (_, m) => (
                  <th scope="col" key={m} className="r">
                    M{m}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grid.rows.map((r) => (
                <tr key={r.cohort_month}>
                  <th scope="row" style={{ fontWeight: 500, color: "var(--ink-2)" }}>
                    {monthLabel(r.cohort_month)}
                  </th>
                  <td className="r">{number(r.customers)}</td>
                  {Array.from({ length: maxMonth + 1 }, (_, m) => {
                    const cell = r.cells.find((c) => c.month === m);
                    return (
                      <td key={m} className="num" style={cellStyle(cell?.retention ?? null)}>
                        {cell?.retention != null ? Math.round(cell.retention * 100) : ""}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
