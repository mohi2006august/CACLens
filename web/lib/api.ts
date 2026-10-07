// Typed client for the CACLens metrics API. Server components call it at request
// time; the browser only calls /v1/ask (via the Ask page).

export const API_URL =
  process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export type Params = Record<string, string | number | boolean | undefined | null>;

export async function api<T>(path: string, params: Params = {}): Promise<T> {
  const url = new URL(path, API_URL);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
  }
  let res: Response;
  try {
    res = await fetch(url, { cache: "no-store" });
  } catch {
    throw new ApiError(`Cannot reach the CACLens API at ${API_URL}. Start it with: uv run caclens serve`, 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

// --- response shapes ------------------------------------------------------------

export type MetricFormat = "currency" | "percent" | "ratio" | "months" | "number";

export interface CatalogMetric {
  name: string;
  label: string;
  type: string;
  description: string;
  formula: string;
  format: MetricFormat;
  dimensions: string[];
  min_grain: string;
  fully_loaded_variant: string | null;
}

export interface Catalog {
  metrics: CatalogMetric[];
  dimensions: { name: string; label: string; type: string; description: string; values: string[] }[];
  data_through: string | null;
}

export interface Health {
  status: string;
  snapshot?: string;
  data_from?: string | null;
  data_through?: string | null;
  revenue_through?: string | null;
  alerts_ready?: boolean;
  qa_planner?: string;
}

export interface Kpi {
  value: number | null;
  previous: number | null;
  change_pct: number | null;
  metric: string;
}

export interface Alert {
  id: string;
  channel: string;
  metric: string;
  severity: "critical" | "warning";
  status: "open" | "resolved";
  first_detected_on: string;
  last_detected_on: string;
  peak_on: string;
  window_start: string;
  window_end: string;
  current_value: number;
  baseline_value: number;
  change_pct: number;
  current_count: number;
  baseline_count: number;
  p_value: number;
  summary: string;
  drivers: Driver[];
}

export interface Driver {
  factor: string;
  label: string;
  baseline: number;
  current: number;
  change_pct: number;
  cac_effect_pct: number;
  share_of_change: number;
}

export interface OverviewChannel {
  channel: string;
  label: string;
  is_paid: boolean;
  spend: number | null;
  new_customers: number | null;
  cac: number | null;
  cac_change_pct: number | null;
  ltv_cac: number | null;
  payback_months: number | null;
  sparkline: { period: string; value: number | null }[];
  alerts: Alert[];
}

export interface Overview {
  period: { start: string; end: string };
  previous_period: { start: string; end: string };
  fully_loaded: boolean;
  attribution_model: string;
  kpis: Record<string, Kpi>;
  channels: OverviewChannel[];
  queries: string[];
}

export type Row = Record<string, number | string | boolean | null>;

export interface Decomposition {
  cac_baseline: number | null;
  cac_current: number | null;
  cac_change_pct: number | null;
  drivers: Driver[];
  summary: string;
}

export interface ChannelDetail {
  channel: string;
  label: string;
  period: { start: string; end: string };
  previous_period: { start: string; end: string };
  fully_loaded: boolean;
  attribution_model: string;
  funnel: { current: Row; previous: Row };
  trend: Row[];
  decomposition: Decomposition;
  campaigns: Row[];
  segments: Row[];
  alerts: Alert[];
  queries: string[];
}

export interface PaybackCurve {
  series: string;
  cac: number | null;
  customers: number;
  payback_month: number | null;
  points: {
    month: number;
    cumulative_gross_margin_per_customer: number;
    retention: number;
    cohort_customers: number;
    cac_recovered_pct: number | null;
  }[];
}

export interface Payback {
  cohort: { label: string; start: string; end: string };
  cac_metric: string;
  attribution_model: string;
  curves: PaybackCurve[];
  queries: string[];
}

export interface CohortGrid {
  rows: {
    cohort_month: string;
    customers: number;
    cells: { month: number; retention: number | null; cumulative_gross_margin_per_customer: number | null }[];
  }[];
  query: string;
}

export interface AttributionCompare {
  metric: string;
  models: string[];
  rows: { channel: string; label: string; values: Record<string, number | null>; ranks: Record<string, number> }[];
  query: string;
  period: { start: string; end: string };
}

export interface OptimiserChannel {
  channel: string;
  current_spend: number;
  recommended_spend: number;
  change_pct: number;
  current_customers: number;
  recommended_customers: number;
  current_cac: number | null;
  recommended_cac: number | null;
  marginal_cac_current: number | null;
  marginal_cac_recommended: number | null;
  elasticity: number;
  fit_r2: number | null;
  fitted_from_data: boolean;
  curve: { spend: number; customers: number; marginal_cac: number | null }[];
}

export interface Optimiser {
  budget: number;
  current_budget: number;
  months_used: number;
  current_customers: number;
  recommended_customers: number;
  customer_lift_pct: number | null;
  blended_cac_current: number | null;
  blended_cac_recommended: number | null;
  channels: OptimiserChannel[];
  caveat: string;
  message?: string;
}

export interface DataQuality {
  freshness: { table: string; group: string; rows: number; last_loaded_at: string | null }[];
  identity_matches: { match_method: string; customers: number }[];
  unattributed_trend: { period: string; unattributed_share: number | null; new_customers: number | null }[];
  data_through: string;
}

export interface ChartSpec {
  type: "line" | "bar" | "stat" | "drivers";
  x?: string | null;
  series?: string | null;
  metric?: string;
  metrics?: { name: string; label: string; format: MetricFormat }[];
  rows?: Row[];
  title?: string;
  drivers?: Driver[];
  cac_baseline?: number | null;
  cac_current?: number | null;
}

export interface AskResponse {
  question: string;
  answer: string;
  planner: "claude" | "rules";
  model: string | null;
  chart: ChartSpec | null;
  queries: { tool: string; input: Record<string, unknown>; ok: boolean; sql: string[]; error?: string }[];
}
