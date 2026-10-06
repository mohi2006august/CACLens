"""FR-08 budget optimiser: marginal CAC curves -> recommended reallocation.

Each paid channel gets a diminishing-returns response curve fitted on monthly data,

    customers = a * spend ** b          (0 < b < 1)

so marginal CAC = d spend / d customers = spend ** (1 - b) / (a * b), which rises as
spend grows. The budget is allocated greedily to whichever channel currently has the
lowest marginal CAC, within guard rails around today's spend (curves are only
trustworthy near the spend levels we have observed).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import duckdb

from api.analytics.common import add_months, month_start
from api.semantic import MetricQuery, QueryFilter, SemanticLayer

PRIOR_ELASTICITY = 0.7
MIN_B, MAX_B = 0.3, 0.95


@dataclass(frozen=True)
class ResponseCurve:
    a: float
    b: float
    r2: float | None
    n: int
    fitted: bool

    def customers(self, spend: float) -> float:
        return self.a * spend**self.b if spend > 0 else 0.0

    def marginal_cac(self, spend: float) -> float | None:
        if spend <= 0:
            return None
        return float(spend ** (1 - self.b) / (self.a * self.b))


def fit_curve(points: list[tuple[float, float]]) -> ResponseCurve:
    """Log-log OLS with shrinkage to a prior elasticity when the data is thin."""
    usable = [(s, c) for s, c in points if s > 0 and c > 0]
    if not usable:
        return ResponseCurve(a=0.0, b=PRIOR_ELASTICITY, r2=None, n=0, fitted=False)
    xs = [math.log(s) for s, _ in usable]
    ys = [math.log(c) for _, c in usable]
    n = len(usable)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    b, r2, fitted = PRIOR_ELASTICITY, None, False
    if n >= 6 and sxx > 1e-3:
        sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
        b_ols = sxy / sxx
        syy = sum((y - mean_y) ** 2 for y in ys)
        r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else 0.0
        # Weight the data by how much spend actually varied and how well it fits.
        weight = min(1.0, sxx / 0.5) * max(0.0, r2)
        b = min(MAX_B, max(MIN_B, weight * b_ols + (1 - weight) * PRIOR_ELASTICITY))
        fitted = weight > 0.2
    # Calibrate the level so the curve passes through the average observed point.
    a = math.exp(mean_y - b * mean_x)
    return ResponseCurve(a=a, b=b, r2=r2, n=n, fitted=fitted)


def optimise(
    layer: SemanticLayer,
    conn: duckdb.DuckDBPyConnection,
    as_of: date,
    budget: float | None = None,
    months: int = 12,
    attribution_model: str = "position_based",
    min_ratio: float = 0.5,
    max_ratio: float = 1.5,
    steps: int = 400,
) -> dict[str, Any]:
    # Use complete months only: the as-of month counts if as_of is its last day.
    month_is_complete = (as_of + timedelta(days=1)).month != as_of.month
    last_complete = month_start(as_of) if month_is_complete else add_months(month_start(as_of), -1)
    first = add_months(last_complete, -(months - 1))
    end_day = add_months(last_complete, 1).toordinal() - 1
    result = layer.query(
        conn,
        MetricQuery(
            metrics=["paid_spend", "new_customers"],
            dimensions=["channel"],
            grain="month",
            start=first,
            end=date.fromordinal(end_day),
            filters=[QueryFilter(dimension="is_paid_channel", op="eq", value=True)],
            attribution_model=attribution_model,
        ),
    )
    by_channel: dict[str, list[dict[str, Any]]] = {}
    for row in result.rows:
        by_channel.setdefault(row["channel"], []).append(row)

    channels = []
    for channel, rows in sorted(by_channel.items()):
        rows.sort(key=lambda r: r["period"])
        points = [(r["paid_spend"] or 0.0, r["new_customers"] or 0.0) for r in rows]
        curve = fit_curve(points)
        recent = rows[-3:]
        current = sum(r["paid_spend"] or 0 for r in recent) / len(recent)
        if current <= 0 or curve.a <= 0:
            continue
        channels.append({"channel": channel, "curve": curve, "current": current})

    if not channels:
        return {"channels": [], "budget": 0.0, "message": "No paid channel spend to optimise."}

    total_current = sum(c["current"] for c in channels)
    total_budget = budget if budget and budget > 0 else total_current
    lower = {c["channel"]: c["current"] * min_ratio for c in channels}
    upper = {c["channel"]: c["current"] * max_ratio * max(1.0, total_budget / total_current)
             for c in channels}
    alloc = dict(lower)
    remaining = total_budget - sum(alloc.values())
    if remaining < 0:  # budget below the floor: scale floors down proportionally
        scale = total_budget / sum(lower.values())
        alloc = {k: v * scale for k, v in lower.items()}
        remaining = 0.0
    step = total_budget / steps
    curves = {c["channel"]: c["curve"] for c in channels}
    while remaining > 1e-6:
        amount = min(step, remaining)
        best, best_gain = None, 0.0
        for name, curve in curves.items():
            if alloc[name] + amount > upper[name] + 1e-9:
                continue
            gain = curve.customers(alloc[name] + amount) - curve.customers(alloc[name])
            if gain > best_gain:
                best, best_gain = name, gain
        if best is None:
            break
        alloc[best] += amount
        remaining -= amount

    out = []
    for c in channels:
        name, curve, current = c["channel"], c["curve"], c["current"]
        recommended = alloc[name]
        cur_customers = curve.customers(current)
        rec_customers = curve.customers(recommended)
        out.append(
            {
                "channel": name,
                "current_spend": current,
                "recommended_spend": recommended,
                "change_pct": recommended / current - 1,
                "current_customers": cur_customers,
                "recommended_customers": rec_customers,
                "current_cac": current / cur_customers if cur_customers else None,
                "recommended_cac": recommended / rec_customers if rec_customers else None,
                "marginal_cac_current": curve.marginal_cac(current),
                "marginal_cac_recommended": curve.marginal_cac(recommended),
                "elasticity": curve.b,
                "fit_r2": curve.r2,
                "fitted_from_data": curve.fitted,
                "curve": [
                    {
                        "spend": current * f,
                        "customers": curve.customers(current * f),
                        "marginal_cac": curve.marginal_cac(current * f),
                    }
                    for f in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
                ],
            }
        )
    cur_total = sum(o["current_customers"] for o in out)
    rec_total = sum(o["recommended_customers"] for o in out)
    return {
        "budget": total_budget,
        "current_budget": total_current,
        "months_used": months,
        "attribution_model": attribution_model,
        "current_customers": cur_total,
        "recommended_customers": rec_total,
        "customer_lift_pct": rec_total / cur_total - 1 if cur_total else None,
        "blended_cac_current": total_current / cur_total if cur_total else None,
        "blended_cac_recommended": total_budget / rec_total if rec_total else None,
        "channels": out,
        "query": result.sql,
        "caveat": "Response curves are fitted on observed monthly spend; recommendations "
        "are bounded to 50-150% of current spend per channel. Validate with an "
        "incrementality test before large shifts.",
    }
