import type { Metadata } from "next";

import { LineChart } from "@/components/charts/LineChart";
import { Term } from "@/components/Term";
import { ErrorState, PageHead } from "@/components/ui";
import { api, type Optimiser } from "@/lib/api";
import { channelColor, channelLabel } from "@/lib/channels";
import { currency, currencyCompact, modelLabel, number, signedPct } from "@/lib/format";
import { param, type SearchParams } from "@/lib/range";

export const metadata: Metadata = { title: "Budget optimiser" };

const MULTIPLIERS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];

export default async function OptimiserPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const budget = param(sp, "budget");
  const attribution = param(sp, "attribution") ?? "position_based";
  let data: Optimiser;
  try {
    data = await api<Optimiser>("/v1/optimiser", { budget, attribution });
  } catch (error) {
    return (
      <>
        <PageHead title="Budget optimiser" />
        <ErrorState error={error} />
      </>
    );
  }
  if (!data.channels.length) {
    return (
      <>
        <PageHead title="Budget optimiser" />
        <div className="card">{data.message}</div>
      </>
    );
  }

  const series = data.channels.map((c) => ({
    key: c.channel,
    label: channelLabel(c.channel),
    color: channelColor(c.channel),
    points: c.curve.map((p, i) => ({ x: MULTIPLIERS[i] ?? p.spend / c.current_spend, y: p.marginal_cac })),
  }));

  return (
    <>
      <PageHead
        title="Budget optimiser"
        subtitle={`Moves the monthly paid budget toward the channel whose next dollar buys a customer cheapest · ${modelLabel(
          attribution,
        )} attribution · fitted on the last ${data.months_used} months`}
      />
      <form className="controls" method="get">
        <label className="control">
          Monthly paid budget
          <input type="number" name="budget" min={1000} step={1000} defaultValue={Math.round(budget ? Number(budget) : data.current_budget)} style={{ width: 140 }} />
        </label>
        {attribution !== "position_based" && <input type="hidden" name="attribution" value={attribution} />}
        <button className="btn" type="submit">
          Recalculate
        </button>
        <span className="muted">Current run-rate {currencyCompact(data.current_budget)}/mo</span>
      </form>

      <section className="grid grid-kpi" style={{ marginBottom: 16 }}>
        <div className="card kpi-hero">
          <span className="kpi-label">Expected extra customers / month</span>
          <div className="kpi-value">{signedPct(data.customer_lift_pct, 1)}</div>
          <div className="delta muted">
            {number(data.current_customers)} → {number(data.recommended_customers)}
          </div>
        </div>
        <div className="card">
          <span className="kpi-label">
            <Term metric="paid_cac">Blended paid CAC</Term>
          </span>
          <div className="kpi-value">{currency(data.blended_cac_recommended)}</div>
          <div className="delta muted">from {currency(data.blended_cac_current)}</div>
        </div>
        <div className="card">
          <span className="kpi-label">Budget</span>
          <div className="kpi-value">{currencyCompact(data.budget)}</div>
          <div className="delta muted">per month</div>
        </div>
      </section>

      <section className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h2>Recommended reallocation</h2>
        </div>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Channel</th>
                <th className="r">Current spend</th>
                <th className="r">Recommended</th>
                <th className="r">Change</th>
                <th className="r">Customers</th>
                <th className="r">Marginal CAC now</th>
                <th className="r">Marginal CAC after</th>
                <th className="r">Elasticity</th>
              </tr>
            </thead>
            <tbody>
              {data.channels.map((c) => (
                <tr key={c.channel}>
                  <td>
                    <span className="swatch" style={{ background: channelColor(c.channel) }} aria-hidden />
                    {channelLabel(c.channel)}
                  </td>
                  <td className="r">{currencyCompact(c.current_spend)}</td>
                  <td className="r">{currencyCompact(c.recommended_spend)}</td>
                  <td className="r">
                    <span className={c.change_pct > 0.02 ? "delta-good" : c.change_pct < -0.02 ? "delta-bad" : "muted"}>
                      {c.change_pct > 0 ? "▲ " : c.change_pct < 0 ? "▼ " : ""}
                      {signedPct(c.change_pct)}
                    </span>
                  </td>
                  <td className="r">
                    {number(c.current_customers)} → {number(c.recommended_customers)}
                  </td>
                  <td className="r">{currency(c.marginal_cac_current)}</td>
                  <td className="r">{currency(c.marginal_cac_recommended)}</td>
                  <td className="r" title={c.fitted_from_data ? `fit r² ${c.fit_r2?.toFixed(2)}` : "not enough spend variation: prior used"}>
                    {c.elasticity.toFixed(2)}
                    {!c.fitted_from_data && <span className="muted"> (prior)</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ fontSize: 12 }}>{data.caveat}</p>
      </section>

      <section className="card">
        <div className="card-head">
          <div>
            <h2>Marginal CAC curves</h2>
            <p>Cost of the next customer if each channel’s spend moved to a multiple of today’s level (1.0×).</p>
          </div>
        </div>
        <LineChart
          title="Marginal CAC by spend level"
          summary={data.channels
            .map((c) => `${channelLabel(c.channel)} marginal CAC ${currency(c.marginal_cac_current)} at current spend`)
            .join(". ")}
          series={series}
          yFormat="currency"
          xType="number"
          xLabel={(x) => `${Number(x).toFixed(2).replace(/\.?0+$/, "")}×`}
          xAxisTitle="Spend vs today"
        />
      </section>
    </>
  );
}
