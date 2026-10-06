"""FR-04 cohort LTV and payback curves.

For a set of acquisition cohorts, the curve at month k is the cumulative gross margin
per acquired customer, using only cohorts old enough to have reached month k. The
cohort's payback month is the first k where that curve reaches the cohort's CAC.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb

from api.analytics.common import add_months
from api.semantic import MetricQuery, QueryFilter, SemanticLayer


@dataclass(frozen=True)
class CohortRange:
    start: date  # first cohort month
    end: date  # last cohort month (inclusive)
    label: str


def parse_cohort(value: str) -> CohortRange:
    """Accepts '2026-Q1', '2026-03' or '2026'."""
    text = value.strip().upper()
    try:
        if "-Q" in text:
            year, quarter = text.split("-Q")
            q = int(quarter)
            if not 1 <= q <= 4:
                raise ValueError
            start = date(int(year), 3 * q - 2, 1)
            return CohortRange(start, add_months(start, 2), f"{year}-Q{q}")
        if len(text) == 7:
            start = date(int(text[:4]), int(text[5:7]), 1)
            return CohortRange(start, start, text)
        if len(text) == 4:
            start = date(int(text), 1, 1)
            return CohortRange(start, date(int(text), 12, 1), text)
    except ValueError:
        pass
    raise ValueError(f"cohort must look like 2026-Q1, 2026-03 or 2026, got '{value}'")


def _cohort_filters(cohort: CohortRange, channel: str | None) -> list[QueryFilter]:
    filters = [
        QueryFilter(dimension="cohort_month", op="gte", value=cohort.start),
        QueryFilter(dimension="cohort_month", op="lte", value=cohort.end),
    ]
    if channel:
        filters.append(QueryFilter(dimension="channel", op="eq", value=channel))
    return filters


def payback_curves(
    layer: SemanticLayer,
    conn: duckdb.DuckDBPyConnection,
    cohort: CohortRange,
    as_of_month: date,
    by_channel: bool = True,
    channel: str | None = None,
    attribution_model: str = "position_based",
    fully_loaded: bool = False,
    max_months: int = 24,
) -> dict[str, Any]:
    group = "channel" if by_channel else None
    dims = ["cohort_month", "months_since_acquisition"] + ([group] if group else [])
    revenue = layer.query(
        conn,
        MetricQuery(
            metrics=["gross_margin_revenue", "cohort_customers", "active_customers"],
            dimensions=dims,
            filters=_cohort_filters(cohort, channel),
            attribution_model=attribution_model,
        ),
    )
    cac_metric = "cac_fully_loaded" if fully_loaded else "cac"
    cac = layer.query(
        conn,
        MetricQuery(
            metrics=[cac_metric, "new_customers"],
            dimensions=[group] if group else [],
            filters=_cohort_filters(cohort, channel),
            attribution_model=attribution_model,
        ),
    )

    # cohort sizes and gross margin per (series, cohort_month, k)
    sizes: dict[tuple[str, date], float] = defaultdict(float)
    margin: dict[tuple[str, date, int], float] = defaultdict(float)
    active: dict[tuple[str, date, int], float] = defaultdict(float)
    for row in revenue.rows:
        key = row[group] if group else "all"
        k = int(row["months_since_acquisition"])
        margin[(key, row["cohort_month"], k)] += row["gross_margin_revenue"] or 0
        active[(key, row["cohort_month"], k)] += row["active_customers"] or 0
        if k == 0:
            sizes[(key, row["cohort_month"])] += row["cohort_customers"] or 0
    cac_by_series = {
        (row[group] if group else "all"): row[cac_metric] for row in cac.rows
    }

    series_keys = sorted({key for key, _ in sizes})
    curves = []
    for key in series_keys:
        cohorts = [(cm, size) for (s, cm), size in sizes.items() if s == key and size > 0]
        points = []
        cumulative = {cm: 0.0 for cm, _ in cohorts}
        payback_month = None
        series_cac = cac_by_series.get(key)
        for k in range(max_months + 1):
            mature = [(cm, size) for cm, size in cohorts if add_months(cm, k) <= as_of_month]
            if not mature:
                break
            for cm, _ in mature:
                cumulative[cm] += margin.get((key, cm, k), 0.0)
            total_size = sum(size for _, size in mature)
            per_customer = sum(cumulative[cm] for cm, _ in mature) / total_size
            retained = sum(active.get((key, cm, k), 0.0) for cm, _ in mature) / total_size
            points.append(
                {
                    "month": k,
                    "cumulative_gross_margin_per_customer": per_customer,
                    "retention": retained,
                    "cohort_customers": total_size,
                    "cac_recovered_pct": per_customer / series_cac if series_cac else None,
                }
            )
            if payback_month is None and series_cac and per_customer >= series_cac:
                payback_month = k
        curves.append(
            {
                "series": key,
                "cac": series_cac,
                "customers": sum(size for _, size in cohorts),
                "payback_month": payback_month,
                "points": points,
            }
        )
    return {
        "cohort": {"label": cohort.label, "start": cohort.start.isoformat(),
                   "end": cohort.end.isoformat()},
        "cac_metric": cac_metric,
        "attribution_model": attribution_model,
        "curves": curves,
        "queries": [revenue.sql, cac.sql],
    }


def cohort_grid(
    layer: SemanticLayer,
    conn: duckdb.DuckDBPyConnection,
    start: date,
    end: date,
    channel: str | None = None,
    attribution_model: str = "position_based",
) -> dict[str, Any]:
    """Retention and cumulative gross margin per customer by cohort month x age."""
    filters = [
        QueryFilter(dimension="cohort_month", op="gte", value=start),
        QueryFilter(dimension="cohort_month", op="lte", value=end),
    ]
    if channel:
        filters.append(QueryFilter(dimension="channel", op="eq", value=channel))
    result = layer.query(
        conn,
        MetricQuery(
            metrics=["cohort_customers", "active_customers", "gross_margin_revenue"],
            dimensions=["cohort_month", "months_since_acquisition"],
            filters=filters,
            attribution_model=attribution_model,
        ),
    )
    by_cohort: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in result.rows:
        by_cohort[row["cohort_month"]].append(row)
    rows = []
    for cm in sorted(by_cohort):
        cells = sorted(by_cohort[cm], key=lambda r: r["months_since_acquisition"])
        size = next((c["cohort_customers"] for c in cells if c["months_since_acquisition"] == 0), 0)
        cumulative = 0.0
        out_cells = []
        for c in cells:
            cumulative += c["gross_margin_revenue"] or 0
            out_cells.append(
                {
                    "month": c["months_since_acquisition"],
                    "retention": (c["active_customers"] or 0) / size if size else None,
                    "cumulative_gross_margin_per_customer": cumulative / size if size else None,
                }
            )
        rows.append({"cohort_month": cm.isoformat(), "customers": size, "cells": out_cells})
    return {"rows": rows, "query": result.sql}
