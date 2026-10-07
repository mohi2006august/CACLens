"use client";

import { useId } from "react";

import type { Driver } from "@/lib/api";
import { signedPct } from "@/lib/format";
import { useWidth } from "./useWidth";

const ROW = 34;
const BAR = 16;
const LABEL_W = 190;

/**
 * FR-06 decomposition as diverging bars around zero: how much each factor moved CAC
 * on its own. Raises CAC -> warm pole, lowers CAC -> cool pole; the sign and label
 * always carry the meaning too, never colour alone.
 */
export function DriversChart({ drivers, title, subject = "CAC" }: { drivers: Driver[]; title: string; subject?: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const summaryId = useId();
  if (!drivers.length) return <p className="muted">Not enough funnel data to decompose this change.</p>;

  const maxAbs = Math.max(0.05, ...drivers.map((d) => Math.abs(d.cac_effect_pct)));
  const plotW = Math.max(120, width - LABEL_W - 16);
  const half = plotW / 2;
  const zero = LABEL_W + half;
  const scale = (v: number) => (v / maxAbs) * (half - 48);
  const height = drivers.length * ROW + 8;

  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={height} role="img" aria-label={title} aria-describedby={summaryId}>
        <line x1={zero} x2={zero} y1={0} y2={drivers.length * ROW} stroke="var(--axis)" />
        {drivers.map((d, i) => {
          const w = scale(d.cac_effect_pct);
          const y0 = i * ROW + (ROW - BAR) / 2;
          const raises = d.cac_effect_pct > 0;
          const x0 = raises ? zero : zero + w;
          const abs = Math.abs(w);
          const r = Math.min(4, abs / 2);
          // round only the data end, keep the zero side square
          const path = raises
            ? `M${x0},${y0} h${abs - r} a${r},${r} 0 0 1 ${r},${r} v${BAR - 2 * r} a${r},${r} 0 0 1 ${-r},${r} h${-(abs - r)} z`
            : `M${x0 + abs},${y0} h${-(abs - r)} a${r},${r} 0 0 0 ${-r},${r} v${BAR - 2 * r} a${r},${r} 0 0 0 ${r},${r} h${abs - r} z`;
          return (
            <g key={d.factor}>
              <text x={LABEL_W - 12} y={i * ROW + ROW / 2} dy="0.32em" textAnchor="end" style={{ fill: "var(--ink-2)", fontSize: 12 }}>
                {d.label} {signedPct(d.change_pct)}
              </text>
              {abs > 0.5 && <path d={path} fill={raises ? "var(--raise)" : "var(--lower)"} />}
              <text
                x={raises ? zero + abs + 6 : zero - abs - 6}
                y={i * ROW + ROW / 2}
                dy="0.32em"
                textAnchor={raises ? "start" : "end"}
                className="tick-num"
                style={{ fill: "var(--ink)", fontSize: 12 }}
              >
                {signedPct(d.cac_effect_pct)}
              </text>
            </g>
          );
        })}
      </svg>
      <p id={summaryId} className="sr-only">
        {drivers.map((d) => `${d.label} changed ${signedPct(d.change_pct)} and moved ${subject} ${signedPct(d.cac_effect_pct)}.`).join(" ")}
      </p>
      <ul className="legend" style={{ marginTop: 4 }}>
        <li>
          <span className="swatch" style={{ background: "var(--raise)" }} aria-hidden />
          Raises {subject}
        </li>
        <li>
          <span className="swatch" style={{ background: "var(--lower)" }} aria-hidden />
          Lowers {subject}
        </li>
      </ul>
      <details className="table-fallback">
        <summary>Data table</summary>
        <table className="data">
          <thead>
            <tr>
              <th>Factor</th>
              <th className="r">Baseline</th>
              <th className="r">Current</th>
              <th className="r">Change</th>
              <th className="r">Effect on {subject}</th>
              <th className="r">Share of change</th>
            </tr>
          </thead>
          <tbody>
            {drivers.map((d) => (
              <tr key={d.factor}>
                <td>{d.label}</td>
                <td className="r">{d.baseline.toPrecision(3)}</td>
                <td className="r">{d.current.toPrecision(3)}</td>
                <td className="r">{signedPct(d.change_pct)}</td>
                <td className="r">{signedPct(d.cac_effect_pct)}</td>
                <td className="r">{signedPct(d.share_of_change)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
