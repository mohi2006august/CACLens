"""Shared helpers for the analytics services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import duckdb

from api.config import get_settings
from api.semantic import SemanticLayer, load_semantic_layer
from api.warehouse import table_exists


def semantic_layer() -> SemanticLayer:
    return load_semantic_layer(get_settings().semantic_path)


@dataclass(frozen=True)
class DataBounds:
    first_day: date | None
    last_day: date | None
    last_complete_revenue_month: date | None


def data_bounds(conn: duckdb.DuckDBPyConnection) -> DataBounds:
    """Time coverage of the marts (metadata, not a metric)."""
    first_day = last_day = revenue_month = None
    if table_exists(conn, "marts", "fct_acquisition_daily"):
        first_day, last_day = conn.execute(
            "select min(date_day), max(date_day) from marts.fct_acquisition_daily "
            "where paid_spend > 0 or new_customers > 0"
        ).fetchone() or (None, None)
    if table_exists(conn, "marts", "fct_customer_revenue_monthly"):
        row = conn.execute(
            "select max(revenue_month) from marts.fct_customer_revenue_monthly"
        ).fetchone()
        revenue_month = row[0] if row else None
    return DataBounds(first_day, last_day, revenue_month)


def previous_period(start: date, end: date) -> tuple[date, date]:
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=length - 1), prev_end


def default_range(bounds: DataBounds, days: int = 90) -> tuple[date, date]:
    end = bounds.last_day or date.today()
    return end - timedelta(days=days - 1), end


def month_start(day: date) -> date:
    return day.replace(day=1)


def add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    return date(day.year + index // 12, index % 12 + 1, 1)


def channel_meta(conn: duckdb.DuckDBPyConnection) -> dict[str, dict[str, Any]]:
    if not table_exists(conn, "marts", "dim_channels"):
        return {}
    rows = conn.execute(
        "select channel, channel_label, channel_group, is_paid, sort_order "
        "from marts.dim_channels order by sort_order"
    ).fetchall()
    return {
        r[0]: {"channel": r[0], "label": r[1], "group": r[2], "is_paid": r[3], "sort_order": r[4]}
        for r in rows
    }


def pct_change(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None or baseline == 0:
        return None
    return current / baseline - 1
