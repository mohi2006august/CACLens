import Link from "next/link";

import type { OverviewChannel } from "@/lib/api";
import { channelColor } from "@/lib/channels";
import { currency, currencyCompact, months, number, ratio, signedPct } from "@/lib/format";
import { Sparkline } from "./charts/Sparkline";
import { Term } from "./Term";

/** DESIGN.md §4 primary screen: channel, spend, customers, CAC, LTV:CAC, payback, trend. */
export function ChannelTable({
  channels,
  fullyLoaded,
  query,
}: {
  channels: OverviewChannel[];
  fullyLoaded: boolean;
  query: string;
}) {
  const cacMetric = fullyLoaded ? "cac_fully_loaded" : "cac";
  return (
    <div className="table-wrap">
      <table className="data">
        <caption className="sr-only">Acquisition metrics by channel</caption>
        <thead>
          <tr>
            <th scope="col">Channel</th>
            <th scope="col" className="r">
              <Term metric={fullyLoaded ? "fully_loaded_spend" : "paid_spend"}>Spend</Term>
            </th>
            <th scope="col" className="r">
              <Term metric="new_customers">Customers</Term>
            </th>
            <th scope="col" className="r">
              <Term metric={cacMetric}>CAC</Term>
            </th>
            <th scope="col" className="r">vs prev</th>
            <th scope="col" className="r">
              <Term metric={fullyLoaded ? "ltv_cac_fully_loaded" : "ltv_cac"}>LTV:CAC</Term>
            </th>
            <th scope="col" className="r">
              <Term metric={fullyLoaded ? "payback_months_fully_loaded" : "payback_months"}>Payback</Term>
            </th>
            <th scope="col">CAC trend (6 mo)</th>
            <th scope="col">
              <span className="sr-only">Alerts</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {channels.map((c) => {
            const href = `/channels/${c.channel}${query ? `?${query}` : ""}`;
            const hasCost = c.cac !== null && c.cac > 0;
            return (
              <tr key={c.channel}>
                <td>
                  <span className="swatch" style={{ background: channelColor(c.channel) }} aria-hidden />
                  {c.channel === "unattributed" || c.channel === "unallocated" ? (
                    <span className="secondary">{c.label}</span>
                  ) : (
                    <Link href={href}>{c.label}</Link>
                  )}
                </td>
                <td className="r">{currencyCompact(c.spend)}</td>
                <td className="r">{number(c.new_customers)}</td>
                <td className="r">{hasCost ? currency(c.cac) : "—"}</td>
                <td className="r">
                  {hasCost && c.cac_change_pct !== null ? (
                    <span className={c.cac_change_pct > 0.1 ? "delta-bad" : c.cac_change_pct < -0.1 ? "delta-good" : "muted"}>
                      {signedPct(c.cac_change_pct)}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="r">{hasCost ? ratio(c.ltv_cac) : "—"}</td>
                <td className="r">{hasCost ? months(c.payback_months) : "—"}</td>
                <td>{hasCost ? <Sparkline values={c.sparkline.map((p) => p.value)} label={`${c.label} CAC`} /> : <span className="muted">—</span>}</td>
                <td>
                  {c.alerts.length > 0 && (
                    <Link href={`/alerts?channel=${c.channel}`} className="pill pill-critical" title={c.alerts[0]?.summary}>
                      <span aria-hidden>⚠</span> {c.alerts.length} alert{c.alerts.length > 1 ? "s" : ""}
                    </Link>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!fullyLoaded && (
        <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          Organic, referral, email and direct have no media spend, so their paid CAC is “—”. Turn on <em>Fully loaded</em> to
          include allocated salaries and tools.
        </p>
      )}
    </div>
  );
}
