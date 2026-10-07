"use client";

import { useId, useMemo, useState, type KeyboardEvent, type PointerEvent } from "react";

import type { MetricFormat } from "@/lib/api";
import { axisFormat, byFormat, monthLabel } from "@/lib/format";
import { linear, niceTicks, toTime } from "./scale";
import { useWidth } from "./useWidth";

export interface LineSeries {
  key: string;
  label: string;
  color: string;
  points: { x: string | number; y: number | null }[];
}

interface Props {
  title: string;
  summary: string;
  series: LineSeries[];
  yFormat: MetricFormat;
  xType?: "date" | "number";
  xLabel?: (x: string | number) => string;
  xAxisTitle?: string;
  height?: number;
  reference?: { y: number; label: string };
}

const M = { top: 12, right: 16, bottom: 28, left: 56 };

export function LineChart({
  title,
  summary,
  series,
  yFormat,
  xType = "date",
  xLabel,
  xAxisTitle,
  height = 240,
  reference,
}: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const summaryId = useId();
  const [active, setActive] = useState<number | null>(null);
  const fmtX = xLabel ?? ((x: string | number) => (typeof x === "string" ? monthLabel(x) : String(x)));

  const xs = useMemo(() => {
    const all = new Map<number, string | number>();
    for (const s of series) for (const p of s.points) all.set(toTime(p.x), p.x);
    return [...all.entries()].sort((a, b) => a[0] - b[0]);
  }, [series]);

  const ys = series.flatMap((s) => s.points.map((p) => p.y).filter((y): y is number => y !== null));
  if (reference) ys.push(reference.y);
  const yMax = ys.length ? Math.max(...ys) : 1;
  const yMin = Math.min(0, ...(ys.length ? ys : [0]));
  const ticks = niceTicks(yMin, yMax * 1.05, 4);
  const yTop = ticks[ticks.length - 1] ?? yMax;
  const yBottom = ticks[0] ?? 0;

  const innerW = Math.max(120, width - M.left - M.right);
  const innerH = height - M.top - M.bottom;
  const xDomain: [number, number] = [xs[0]?.[0] ?? 0, xs[xs.length - 1]?.[0] ?? 1];
  const x = linear(xDomain, [M.left, M.left + innerW]);
  const y = linear([yBottom, yTop], [M.top + innerH, M.top]);

  const paths = series.map((s) => {
    let d = "";
    let pen = false;
    const pts = [...s.points].sort((a, b) => toTime(a.x) - toTime(b.x));
    for (const p of pts) {
      if (p.y === null) {
        pen = false;
        continue;
      }
      d += `${pen ? "L" : "M"}${x(toTime(p.x)).toFixed(1)},${y(p.y).toFixed(1)}`;
      pen = true;
    }
    const last = [...pts].reverse().find((p) => p.y !== null);
    return { s, d, last };
  });

  const labelEvery = Math.max(1, Math.ceil(xs.length / Math.max(2, Math.floor(innerW / 90))));

  function nearest(clientX: number, rect: DOMRect) {
    const px = ((clientX - rect.left) / rect.width) * width;
    let best = 0;
    let bestDist = Infinity;
    xs.forEach(([t], i) => {
      const dist = Math.abs(x(t) - px);
      if (dist < bestDist) {
        best = i;
        bestDist = dist;
      }
    });
    return best;
  }

  function onMove(e: PointerEvent<SVGRectElement>) {
    const svg = e.currentTarget.ownerSVGElement;
    if (svg) setActive(nearest(e.clientX, svg.getBoundingClientRect()));
  }

  function onKey(e: KeyboardEvent<SVGRectElement>) {
    if (e.key === "ArrowRight") setActive((i) => Math.min(xs.length - 1, (i ?? -1) + 1));
    if (e.key === "ArrowLeft") setActive((i) => Math.max(0, (i ?? xs.length) - 1));
    if (e.key === "Escape") setActive(null);
  }

  const activeX = active !== null ? xs[active] : undefined;
  const tooltipLeft = activeX ? Math.min(width - 170, Math.max(0, x(activeX[0]) + 12)) : 0;

  return (
    <div className="chart" ref={ref}>
      {series.length > 1 && (
        <ul className="legend" aria-label="Legend">
          {series.map((s) => (
            <li key={s.key}>
              <span className="line-key" style={{ background: s.color }} aria-hidden />
              {s.label}
            </li>
          ))}
        </ul>
      )}
      <svg width={width} height={height} role="img" aria-label={title} aria-describedby={summaryId}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.left} x2={M.left + innerW} y1={y(t)} y2={y(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="tick-num">
              {axisFormat(t, yFormat)}
            </text>
          </g>
        ))}
        <line
          x1={M.left}
          x2={M.left + innerW}
          y1={y(Math.max(0, yBottom))}
          y2={y(Math.max(0, yBottom))}
          stroke="var(--axis)"
        />
        {xs.map(([t, raw], i) =>
          i % labelEvery === 0 || i === xs.length - 1 ? (
            <text key={t} x={x(t)} y={height - 8} textAnchor="middle">
              {fmtX(raw)}
            </text>
          ) : null,
        )}
        {xAxisTitle && (
          <text x={M.left + innerW} y={height - 8} textAnchor="end" className="sr-only">
            {xAxisTitle}
          </text>
        )}
        {reference && (
          <g>
            <line
              x1={M.left}
              x2={M.left + innerW}
              y1={y(reference.y)}
              y2={y(reference.y)}
              stroke="var(--ink-3)"
              strokeWidth={1}
            />
            <text x={M.left + innerW} y={y(reference.y) - 6} textAnchor="end">
              {reference.label}
            </text>
          </g>
        )}
        {paths.map(({ s, d }) => (
          <path key={s.key} d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {paths.map(({ s, last }) =>
          last && last.y !== null ? (
            <circle
              key={s.key}
              cx={x(toTime(last.x))}
              cy={y(last.y)}
              r={4}
              fill={s.color}
              stroke="var(--surface)"
              strokeWidth={2}
            />
          ) : null,
        )}
        {activeX && (
          <line
            x1={x(activeX[0])}
            x2={x(activeX[0])}
            y1={M.top}
            y2={M.top + innerH}
            stroke="var(--axis)"
            strokeWidth={1}
          />
        )}
        {activeX &&
          series.map((s) => {
            const p = s.points.find((pt) => toTime(pt.x) === activeX[0]);
            return p && p.y !== null ? (
              <circle key={s.key} cx={x(activeX[0])} cy={y(p.y)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
            ) : null;
          })}
        <rect
          x={M.left}
          y={M.top}
          width={innerW}
          height={innerH}
          fill="transparent"
          tabIndex={0}
          aria-label={`${title}: use left and right arrow keys to read values`}
          onPointerMove={onMove}
          onPointerLeave={() => setActive(null)}
          onFocus={() => setActive((i) => i ?? xs.length - 1)}
          onBlur={() => setActive(null)}
          onKeyDown={onKey}
        />
      </svg>
      {activeX && (
        <div className="tooltip" style={{ left: tooltipLeft, top: 24 }} role="status">
          <div className="tooltip-title">{fmtX(activeX[1])}</div>
          {series.map((s) => {
            const p = s.points.find((pt) => toTime(pt.x) === activeX[0]);
            return (
              <div className="tooltip-row" key={s.key}>
                <span>
                  <span className="line-key" style={{ background: s.color }} aria-hidden />
                  {s.label}
                </span>
                <strong>{byFormat(p?.y ?? null, yFormat)}</strong>
              </div>
            );
          })}
        </div>
      )}
      <p id={summaryId} className="sr-only">
        {summary}
      </p>
      <details className="table-fallback">
        <summary>Data table</summary>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">{xType === "date" ? "Period" : (xAxisTitle ?? "x")}</th>
                {series.map((s) => (
                  <th scope="col" className="r" key={s.key}>
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {xs.map(([t, raw]) => (
                <tr key={t}>
                  <td>{fmtX(raw)}</td>
                  {series.map((s) => (
                    <td className="r" key={s.key}>
                      {byFormat(s.points.find((p) => toTime(p.x) === t)?.y ?? null, yFormat)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
