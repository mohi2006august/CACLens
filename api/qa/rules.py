"""Offline Q&A planner: keyword rules -> semantic-layer queries -> templated answer.

Used when no Anthropic credentials are configured and as the baseline in the Q&A eval.
It understands metric names, channel/segment/model mentions, common time phrases and
three intents: plain lookups, "why did CAC change" and "which channel's CAC grew most".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import duckdb

from api.analytics.common import add_months, month_start, previous_period
from api.qa.answer import Answer, AskContext, finalize, format_value
from api.qa.tools import ToolCall, execute_tool
from api.semantic import SemanticLayer

# Ordered: the first matching phrase wins, so specific phrases come first.
METRIC_PATTERNS: list[tuple[str, str]] = [
    (r"ltv\s*(:|/|to)\s*cac|ltv-to-cac|ltv cac ratio", "ltv_cac"),
    (r"payback", "payback_months"),
    (r"\bltv\b|lifetime value", "ltv"),
    (r"unattributed|no source|without (a )?source", "unattributed_share"),
    (r"lagged cac|lagged", "cac_lagged"),
    (r"paid cac", "paid_cac"),
    (r"\bcac\b|acquisition cost|cost (per|to acquire a?) ?(new )?customer", "cac"),
    (r"\bcpc\b|cost per click", "cpc"),
    (r"\bctr\b|click[- ]through", "ctr"),
    (r"cost per lead|\bcpl\b", "cost_per_lead"),
    (r"click[- ]to[- ]lead|lead (conversion|cvr)|clicks? (convert|turn) (in)?to leads",
     "lead_cvr"),
    (r"lead[- ]to[- ]customer|customer (conversion|cvr)|conversion rate|close rate|win rate",
     "customer_cvr"),
    (r"opportunit", "opportunities"),
    (r"churn", "monthly_churn"),
    (r"\barpa\b|average revenue per (account|customer)", "arpa"),
    (r"gross margin", "gross_margin_pct"),
    (r"refund|chargeback", "refunds_and_chargebacks"),
    (r"revenue", "net_revenue"),
    (r"people cost|salar|payroll", "people_cost"),
    (r"tool cost|software cost", "tool_cost"),
    (r"total cost|fully loaded (spend|cost)", "fully_loaded_spend"),
    (r"spend|spent|budget|cost", "paid_spend"),
    (r"\bleads?\b", "leads"),
    (r"clicks", "clicks"),
    (r"impressions", "impressions"),
    (r"customers|signups|sign-ups|deals won|acquired", "new_customers"),
]

CHANNEL_PATTERNS: list[tuple[str, list[str]]] = [
    (r"paid social", ["meta_ads", "linkedin_ads"]),
    (r"paid search|google|adwords|search ads", ["google_search"]),
    (r"\bmeta\b|facebook|instagram", ["meta_ads"]),
    (r"linkedin", ["linkedin_ads"]),
    (r"organic|seo", ["organic_search"]),
    (r"referral|partner", ["referral"]),
    (r"\bemail|newsletter", ["email"]),
    (r"\bdirect\b", ["direct"]),
]

SEGMENT_PATTERNS: list[tuple[str, str]] = [
    (r"\bsmb\b|small business", "smb"),
    (r"mid[- ]?market", "mid_market"),
    (r"enterprise", "enterprise"),
]

MODEL_PATTERNS: list[tuple[str, str]] = [
    (r"first[- ]touch", "first_touch"),
    (r"last[- ]touch", "last_touch"),
    (r"\blinear\b", "linear"),
    (r"time[- ]decay", "time_decay"),
    (r"position[- ]based|u[- ]shaped", "position_based"),
]

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


@dataclass
class Period:
    start: date
    end: date
    label: str
    unit: str  # day | month | quarter | year | range


@dataclass
class Plan:
    intent: str  # lookup | explain | growth
    metrics: list[str]
    dimensions: list[str] = field(default_factory=list)
    grain: str | None = None
    filters: list[dict[str, Any]] = field(default_factory=list)
    period: Period | None = None
    attribution_model: str = "position_based"
    order_desc: bool | None = None
    fully_loaded: bool = False

    def query_input(self) -> dict[str, Any]:
        assert self.period is not None
        order = []
        if self.order_desc is not None and self.dimensions and not self.grain:
            order = [{"field": self.metrics[0], "descending": self.order_desc}]
        return {
            "metrics": self.metrics,
            "dimensions": self.dimensions,
            "grain": self.grain,
            "start": self.period.start.isoformat(),
            "end": self.period.end.isoformat(),
            "filters": self.filters,
            "attribution_model": self.attribution_model,
            "order_by": order,
            "limit": None,
        }


def _quarter_start(day: date) -> date:
    return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


def _month_end(day: date) -> date:
    return add_months(month_start(day), 1) - timedelta(days=1)


def resolve_period(text: str, as_of: date) -> Period:
    t = text.lower()
    if m := re.search(r"(last|past|previous) (\d+) days", t):
        n = int(m.group(2))
        return Period(as_of - timedelta(days=n - 1), as_of, f"the last {n} days", "range")
    if m := re.search(r"(last|past|previous) (\d+) months", t):
        n = int(m.group(2))
        return Period(add_months(month_start(as_of), -(n - 1)), as_of, f"the last {n} months",
                      "range")
    if re.search(r"(last|past|previous) (week|7 days)", t):
        return Period(as_of - timedelta(days=6), as_of, "the last 7 days", "range")
    if re.search(r"this month|month to date|mtd", t):
        return Period(month_start(as_of), as_of, f"{as_of:%B %Y} to date", "month")
    if re.search(r"(last|previous) month", t):
        start = add_months(month_start(as_of), -1)
        return Period(start, _month_end(start), f"{start:%B %Y}", "month")
    if re.search(r"this quarter|quarter to date|qtd", t):
        start = _quarter_start(as_of)
        return Period(start, as_of, f"Q{(start.month - 1) // 3 + 1} {start.year}", "quarter")
    if re.search(r"(last|previous) quarter", t):
        start = add_months(_quarter_start(as_of), -3)
        return Period(start, add_months(start, 3) - timedelta(days=1),
                      f"Q{(start.month - 1) // 3 + 1} {start.year}", "quarter")
    if m := re.search(r"\bq([1-4])(?:\s*(?:of\s*)?(20\d\d))?\b", t):
        q = int(m.group(1))
        year = int(m.group(2)) if m.group(2) else as_of.year
        start = date(year, 3 * q - 2, 1)
        if not m.group(2) and start > as_of:
            start = date(year - 1, 3 * q - 2, 1)
        end = min(add_months(start, 3) - timedelta(days=1), as_of)
        return Period(start, end, f"Q{q} {start.year}", "quarter")
    if re.search(r"this year|year to date|ytd", t):
        return Period(date(as_of.year, 1, 1), as_of, f"{as_of.year} to date", "year")
    if re.search(r"(last|previous) year", t):
        y = as_of.year - 1
        return Period(date(y, 1, 1), date(y, 12, 31), str(y), "year")
    month_names = "|".join(sorted(MONTHS, key=len, reverse=True))
    if m := re.search(rf"\b({month_names})\b(?:\s+(20\d\d))?", t):
        month = MONTHS[m.group(1)]
        year = int(m.group(2)) if m.group(2) else as_of.year
        start = date(year, month, 1)
        if not m.group(2) and start > as_of:
            start = date(year - 1, month, 1)
        return Period(start, min(_month_end(start), as_of), f"{start:%B %Y}", "month")
    if m := re.search(r"\b(20\d\d)\b", t):
        y = int(m.group(1))
        return Period(date(y, 1, 1), min(date(y, 12, 31), as_of), str(y), "year")
    return Period(as_of - timedelta(days=89), as_of, "the last 90 days", "range")


def baseline_for(period: Period) -> Period:
    if period.unit == "month":
        start = add_months(period.start, -1)
        return Period(start, _month_end(start), f"{start:%B %Y}", "month")
    if period.unit == "quarter":
        start = add_months(period.start, -3)
        end = start + (period.end - period.start)
        return Period(start, end, f"Q{(start.month - 1) // 3 + 1} {start.year}", "quarter")
    start, end = previous_period(period.start, period.end)
    return Period(start, end, "the previous period", "range")


def plan_question(question: str, ctx: AskContext, layer: SemanticLayer) -> Plan:
    q = question.lower()
    fully_loaded = bool(re.search(r"fully[- ]loaded|including salar|incl\.? salar", q)) or (
        ctx.fully_loaded and "paid" not in q
    )
    metrics: list[str] = []
    for pattern, metric in METRIC_PATTERNS:
        if re.search(pattern, q) and metric not in metrics:
            metrics.append(metric)
            break
    if not metrics:
        metrics = ["cac"]
    if fully_loaded:
        metrics = [layer.variant(m, True) for m in metrics]

    model = ctx.attribution_model
    for pattern, name in MODEL_PATTERNS:
        if re.search(pattern, q):
            model = name
            break

    dims: list[str] = []
    if re.search(r"attribution models|by model|each model|across models|compare models|"
                 r"different models|model comparison", q):
        dims.append("attribution_model")
    by_channel = re.search(
        r"(by|per|each|every|across|which|what) (marketing )?channels?|channel mix|"
        r"channels? (has|have|had|is|are|was|were|with|grew|rose|increased|performed)", q)
    by_segment = re.search(r"(by|per|each|across|which|what) segments?", q)
    by_campaign = re.search(r"(by|per|each|across|which|what|top) campaigns?", q)
    by_cohort = re.search(r"by cohort|per cohort|each cohort|cohorts", q)
    if by_channel:
        dims.append("channel")
    if by_segment:
        dims.append("segment")
    if by_campaign:
        dims.append("campaign")
    if by_cohort and not dims:
        dims.append("cohort_month")

    filters: list[dict[str, Any]] = []
    if not by_channel:
        for pattern, channels in CHANNEL_PATTERNS:
            if re.search(pattern, q):
                filters.append(
                    {"dimension": "channel", "op": "eq", "value": channels[0]}
                    if len(channels) == 1
                    else {"dimension": "channel", "op": "in", "value": channels}
                )
                break
    if not by_segment:
        for pattern, segment in SEGMENT_PATTERNS:
            if re.search(pattern, q):
                filters.append({"dimension": "segment", "op": "eq", "value": segment})
                break

    grain = None
    if re.search(r"monthly|by month|per month|each month|month over month|month-over-month|"
                 r"trend|over time", q):
        grain = "month"
    elif re.search(r"weekly|by week|per week|each week", q):
        grain = "week"
    elif re.search(r"quarterly|by quarter|per quarter|each quarter", q):
        grain = "quarter"
    elif re.search(r"daily|by day|per day|each day", q):
        grain = "day"
    if grain in ("day", "week") and any(
        m in ("ltv", "ltv_cac", "payback_months", "monthly_churn", "arpa", "net_revenue")
        for m in metrics
    ):
        grain = "month"

    order_desc: bool | None = None
    if re.search(r"highest|most|best|biggest|largest|top|max", q):
        order_desc = not metrics[0].startswith(("cac", "payback", "cpc", "cost_per", "paid_cac"))
        if re.search(r"highest|most|biggest|largest|max", q):
            order_desc = True
    if re.search(r"lowest|least|cheapest|worst|smallest|min\b|fastest", q):
        order_desc = False

    period = resolve_period(q, ctx.as_of)
    intent = "lookup"
    is_cac = metrics[0].startswith(("cac", "paid_cac"))
    if is_cac and re.search(r"(grew|grow|increased|rose|jumped|spiked|worsened) (the )?most|"
                            r"biggest (increase|jump|change)", q):
        intent = "growth"
    elif is_cac and re.search(r"\bwhy\b|what drove|driver|explain|cause", q):
        intent = "explain"

    return Plan(intent=intent, metrics=metrics, dimensions=dims, grain=grain, filters=filters,
                period=period, attribution_model=model, order_desc=order_desc,
                fully_loaded=fully_loaded)


def _label(layer: SemanticLayer, metric: str) -> str:
    return layer.metrics[metric].label


def _fmt(layer: SemanticLayer, metric: str, value: float | None) -> str:
    return format_value(value, layer.metrics[metric].format)


def _model_label(model: str) -> str:
    return model.replace("_", "-")


class RulePlanner:
    def __init__(self, layer: SemanticLayer) -> None:
        self.layer = layer

    def ask(self, conn: duckdb.DuckDBPyConnection, question: str, ctx: AskContext) -> Answer:
        plan = plan_question(question, ctx, self.layer)
        answer = Answer(question=question, answer="", planner="rules")
        if plan.intent == "growth":
            answer.answer = self._growth(conn, plan, answer)
        elif plan.intent == "explain":
            answer.answer = self._explain(conn, plan, answer, self._channel_filter(plan))
        else:
            answer.answer = self._lookup(conn, plan, answer)
        return finalize(self.layer, answer)

    @staticmethod
    def _channel_filter(plan: Plan) -> str | None:
        for f in plan.filters:
            if f["dimension"] == "channel" and f["op"] == "eq":
                return str(f["value"])
        return None

    def _call(self, conn: duckdb.DuckDBPyConnection, answer: Answer, name: str,
              raw: dict[str, Any]) -> ToolCall:
        call = execute_tool(self.layer, conn, name, raw)
        answer.calls.append(call)
        return call

    def _lookup(self, conn: duckdb.DuckDBPyConnection, plan: Plan, answer: Answer) -> str:
        assert plan.period is not None
        call = self._call(conn, answer, "query_metric", plan.query_input())
        if not call.ok or call.result is None:
            return f"I couldn't run that query: {call.output.get('error')}"
        metric = plan.metrics[0]
        rows = [r for r in call.result.rows if r.get(metric) is not None]
        where = f"for {plan.period.label} ({_model_label(plan.attribution_model)} attribution)"
        label = _label(self.layer, metric)
        if not rows:
            return f"There is no {label} data {where}."
        if not plan.dimensions and not plan.grain:
            return f"{label} was {_fmt(self.layer, metric, rows[0][metric])} {where}."
        if plan.grain and not plan.dimensions:
            first, last = rows[0], rows[-1]
            peak = max(rows, key=lambda r: r[metric])
            return (
                f"{label} by {plan.grain} {where}: {_fmt(self.layer, metric, first[metric])} in "
                f"{first['period']:%b %Y} and {_fmt(self.layer, metric, last[metric])} in "
                f"{last['period']:%b %Y}; the peak was "
                f"{_fmt(self.layer, metric, peak[metric])} in {peak['period']:%b %Y}."
            )
        dim = plan.dimensions[0]
        if plan.grain:
            latest = max(r["period"] for r in rows)
            rows = [r for r in rows if r["period"] == latest]
        reverse = plan.order_desc if plan.order_desc is not None else True
        ranked = sorted(rows, key=lambda r: r[metric], reverse=reverse)
        parts = ", ".join(
            f"{r[dim]} {_fmt(self.layer, metric, r[metric])}" for r in ranked[:5]
        )
        lead = ranked[0]
        if plan.order_desc is not None:
            word = "highest" if reverse else "lowest"
            return (
                f"{lead[dim]} has the {word} {label} {where} at "
                f"{_fmt(self.layer, metric, lead[metric])}. By {dim}: {parts}."
            )
        return f"{label} by {dim} {where}: {parts}."

    def _explain(self, conn: duckdb.DuckDBPyConnection, plan: Plan, answer: Answer,
                 channel: str | None) -> str:
        assert plan.period is not None
        base = baseline_for(plan.period)
        call = self._call(conn, answer, "explain_cac_change", {
            "channel": channel,
            "current_start": plan.period.start.isoformat(),
            "current_end": plan.period.end.isoformat(),
            "baseline_start": base.start.isoformat(),
            "baseline_end": base.end.isoformat(),
            "fully_loaded": plan.fully_loaded,
            "attribution_model": plan.attribution_model,
        })
        if not call.ok:
            return f"I couldn't explain that change: {call.output.get('error')}"
        out = call.output
        if out.get("cac_change_pct") is None or not out.get("drivers"):
            return out.get("summary", "Not enough data to explain the change.")
        who = channel or "Paid"
        drivers = "; ".join(
            f"{d['label']} {d['change_pct'] * 100:+.0f}% (CAC effect {d['cac_effect_pct'] * 100:+.0f}%)"
            for d in out["drivers"]
        )
        return (
            f"{who} CAC moved {out['cac_change_pct'] * 100:+.0f}% in {plan.period.label} vs "
            f"{base.label}: ${out['cac_current']:,.0f} vs ${out['cac_baseline']:,.0f} "
            f"({_model_label(plan.attribution_model)} attribution). "
            f"Drivers: {drivers}. The biggest factor was {out['drivers'][0]['label']}."
        )

    def _growth(self, conn: duckdb.DuckDBPyConnection, plan: Plan, answer: Answer) -> str:
        assert plan.period is not None
        metric = plan.metrics[0]
        base = baseline_for(plan.period)
        rows: dict[str, dict[str, float | None]] = {}
        for key, period in (("current", plan.period), ("baseline", base)):
            call = self._call(conn, answer, "query_metric", {
                **plan.query_input(),
                "dimensions": ["channel"],
                "start": period.start.isoformat(),
                "end": period.end.isoformat(),
                "filters": [{"dimension": "is_paid_channel", "op": "eq", "value": True}],
                "order_by": [],
            })
            if not call.ok or call.result is None:
                return f"I couldn't run that query: {call.output.get('error')}"
            for r in call.result.rows:
                rows.setdefault(r["channel"], {})[key] = r[metric]
        changes = {
            c: v["current"] / v["baseline"] - 1
            for c, v in rows.items()
            if v.get("current") and v.get("baseline")
        }
        if not changes:
            return "Not enough paid-channel data to compare the two periods."
        top = max(changes, key=lambda c: changes[c])
        explanation = self._explain(conn, plan, answer, top)
        return (
            f"{top} had the largest {_label(self.layer, metric)} increase in "
            f"{plan.period.label} vs {base.label} ({changes[top] * 100:+.0f}%). {explanation}"
        )
