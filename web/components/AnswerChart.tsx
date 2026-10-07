"use client";

import type { ChartSpec, MetricFormat } from "@/lib/api";
import { channelColor, channelLabel } from "@/lib/channels";
import { byFormat, modelLabel, segmentLabel } from "@/lib/format";
import { BarChart } from "./charts/BarChart";
import { DriversChart } from "./charts/DriversChart";
import { LineChart } from "./charts/LineChart";

const PALETTE = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)", "var(--series-6)", "var(--series-7)"];

function dimLabel(dim: string | null | undefined, value: unknown): string {
  const v = String(value);
  if (dim === "channel") return channelLabel(v);
  if (dim === "segment") return segmentLabel(v);
  if (dim === "attribution_model") return modelLabel(v);
  return v;
}

/** Renders the chart spec returned by /v1/ask (built from the query the answer used). */
export function AnswerChart({ chart }: { chart: ChartSpec }) {
  if (chart.type === "drivers") {
    return <DriversChart drivers={chart.drivers ?? []} title={chart.title ?? "CAC drivers"} />;
  }
  const metric = chart.metrics?.[0];
  const rows = chart.rows ?? [];
  if (!metric || !rows.length) return null;
  const format = metric.format as MetricFormat;

  if (chart.type === "stat") {
    const value = rows[0]?.[metric.name];
    return (
      <div>
        <span className="kpi-label">{metric.label}</span>
        <div className="kpi-value" style={{ fontSize: 34 }}>
          {byFormat(typeof value === "number" ? value : null, format)}
        </div>
      </div>
    );
  }

  if (chart.type === "line") {
    const seriesDim = chart.series;
    const keys = seriesDim ? [...new Set(rows.map((r) => String(r[seriesDim])))] : [metric.name];
    const series = keys.slice(0, 7).map((key, i) => ({
      key,
      label: seriesDim ? dimLabel(seriesDim, key) : metric.label,
      color: seriesDim === "channel" ? channelColor(key) : PALETTE[i] ?? "var(--series-neutral)",
      points: rows
        .filter((r) => !seriesDim || String(r[seriesDim]) === key)
        .map((r) => ({ x: String(r.period), y: typeof r[metric.name] === "number" ? (r[metric.name] as number) : null })),
    }));
    return <LineChart title={`${metric.label} over time`} summary={`${metric.label} by ${chart.x}`} series={series} yFormat={format} />;
  }

  const x = chart.x ?? "";
  const bars = rows
    .filter((r) => typeof r[metric.name] === "number")
    .map((r) => ({
      key: chart.series ? `${String(r[x])}-${String(r[chart.series])}` : String(r[x]),
      label: chart.series ? `${dimLabel(x, r[x])} · ${dimLabel(chart.series, r[chart.series])}` : dimLabel(x, r[x]),
      value: r[metric.name] as number,
    }))
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
    .slice(0, 20);
  return <BarChart title={`${metric.label} by ${x}`} summary={bars.map((b) => `${b.label}: ${byFormat(b.value, format)}`).join(", ")} rows={bars} format={format} />;
}
