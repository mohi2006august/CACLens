"use client";

import { useId, useState } from "react";

import type { MetricFormat } from "@/lib/api";
import { axisFormat, byFormat } from "@/lib/format";
import { linear, niceTicks } from "./scale";
import { useWidth } from "./useWidth";

export interface BarRow {
  key: string;
  label: string;
  value: number | null;
  note?: string;
}

interface Props {
  title: string;
  summary: string;
  rows: BarRow[];
  format: MetricFormat;
  color?: string;
}

const BAR = 18;
const ROW = 32;
const LABEL_W = 140;
const VALUE_W = 72;

/** Horizontal bars: one series, one colour; value at the tip; 4px rounded data-end. */
export function BarChart({ title, summary, rows, format, color = "var(--series-1)" }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const summaryId = useId();
  const [hover, setHover] = useState<string | null>(null);
  const values = rows.map((r) => r.value ?? 0);
  const ticks = niceTicks(0, Math.max(1, ...values), 4);
  const max = ticks[ticks.length - 1] ?? 1;
  const plotW = Math.max(80, width - LABEL_W - VALUE_W);
  const x = linear([0, max], [LABEL_W, LABEL_W + plotW]);
  const height = rows.length * ROW + 24;

  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={height} role="img" aria-label={title} aria-describedby={summaryId}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={0} y2={rows.length * ROW} stroke="var(--grid)" />
            <text x={x(t)} y={height - 6} textAnchor="middle" className="tick-num">
              {axisFormat(t, format)}
            </text>
          </g>
        ))}
        <line x1={LABEL_W} x2={LABEL_W} y1={0} y2={rows.length * ROW} stroke="var(--axis)" />
        {rows.map((r, i) => {
          const y0 = i * ROW + (ROW - BAR) / 2;
          const w = Math.max(0, x(r.value ?? 0) - LABEL_W);
          const radius = Math.min(4, w / 2);
          const d =
            w > 0
              ? `M${LABEL_W},${y0} h${w - radius} a${radius},${radius} 0 0 1 ${radius},${radius} v${BAR - 2 * radius} a${radius},${radius} 0 0 1 ${-radius},${radius} h${-(w - radius)} z`
              : "";
          return (
            <g
              key={r.key}
              tabIndex={0}
              role="img"
              aria-label={`${r.label}: ${byFormat(r.value, format)}`}
              onPointerEnter={() => setHover(r.key)}
              onPointerLeave={() => setHover(null)}
              onFocus={() => setHover(r.key)}
              onBlur={() => setHover(null)}
            >
              <rect x={0} y={i * ROW} width={width} height={ROW} fill="transparent" />
              <text x={LABEL_W - 10} y={i * ROW + ROW / 2} dy="0.32em" textAnchor="end" style={{ fill: "var(--ink-2)", fontSize: 12 }}>
                {r.label}
              </text>
              {d && <path d={d} fill={color} opacity={hover && hover !== r.key ? 0.55 : 1} />}
              <text
                x={LABEL_W + w + 8}
                y={i * ROW + ROW / 2}
                dy="0.32em"
                className="tick-num"
                style={{ fill: "var(--ink)", fontSize: 12 }}
              >
                {byFormat(r.value, format)}
              </text>
            </g>
          );
        })}
      </svg>
      {hover && (
        <div className="tooltip" style={{ left: LABEL_W, top: rows.findIndex((r) => r.key === hover) * ROW + ROW }} role="status">
          {rows
            .filter((r) => r.key === hover)
            .map((r) => (
              <div key={r.key}>
                <div className="tooltip-row">
                  <span>{r.label}</span>
                  <strong>{byFormat(r.value, format)}</strong>
                </div>
                {r.note && <div className="tooltip-title">{r.note}</div>}
              </div>
            ))}
        </div>
      )}
      <p id={summaryId} className="sr-only">
        {summary}
      </p>
      <details className="table-fallback">
        <summary>Data table</summary>
        <table className="data">
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td>{r.label}</td>
                <td className="r">{byFormat(r.value, format)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
