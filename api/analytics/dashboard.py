"""Screen-level services for the web app: overview, channel detail, attribution
comparison and data quality. Everything metric-shaped goes through the semantic layer.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

import duckdb

from api.analytics.alerts import read_alerts
from api.analytics.common import (
    add_months,
    channel_meta,
    month_start,
    pct_change,
    previous_period,
)
from api.analytics.decomposition import Funnel, decompose
from api.semantic import MetricQuery, OrderBy, QueryFilter, SemanticLayer
from api.warehouse import table_exists


def _single(layer: SemanticLayer, conn: duckdb.DuckDBPyConnection, metrics: list[str],
            start: date, end: date, attribution_model: str,
            filters: list[QueryFilter] | None = None) -> tuple[dict[str, Any], str]:
    result = layer.query(
        conn,
        MetricQuery(metrics=metrics, start=start, end=end, filters=filters or [],
                    attribution_model=attribution_model),
    )
    return (result.rows[0] if result.rows else {}), result.sql


def open_alerts(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    if not table_exists(conn, "app", "alerts"):
        return []
    return [a for a in read_alerts(conn) if a["status"] == "open"]


def overview(layer: SemanticLayer, conn: duckdb.DuckDBPyConnection, start: date, end: date,
             fully_loaded: bool, attribution_model: str) -> dict[str, Any]:
    spend_m, cac_m = layer.variant("paid_spend", fully_loaded), layer.variant("cac", fully_loaded)
    ltv_cac_m = layer.variant("ltv_cac", fully_loaded)
    payback_m = layer.variant("payback_months", fully_loaded)
    kpi_metrics = [spend_m, "new_customers", cac_m, "paid_cac", "ltv", ltv_cac_m, payback_m,
                   "unattributed_share"]
    prev_start, prev_end = previous_period(start, end)
    current, kpi_sql = _single(layer, conn, kpi_metrics, start, end, attribution_model)
    previous, _ = _single(layer, conn, kpi_metrics, prev_start, prev_end, attribution_model)

    table_metrics = [spend_m, "new_customers", cac_m, ltv_cac_m, payback_m]
    rows = layer.query(
        conn,
        MetricQuery(metrics=table_metrics, dimensions=["channel"], start=start, end=end,
                    attribution_model=attribution_model,
                    order_by=[OrderBy(field=spend_m, descending=True)]),
    )
    prev_rows = layer.query(
        conn,
        MetricQuery(metrics=[cac_m], dimensions=["channel"], start=prev_start, end=prev_end,
                    attribution_model=attribution_model),
    )
    prev_cac = {r["channel"]: r[cac_m] for r in prev_rows.rows}

    spark_start = add_months(month_start(end), -5)
    spark = layer.query(
        conn,
        MetricQuery(metrics=[cac_m], dimensions=["channel"], grain="month", start=spark_start,
                    end=end, attribution_model=attribution_model),
    )
    sparklines: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in spark.rows:
        sparklines[r["channel"]].append({"period": r["period"].isoformat(), "value": r[cac_m]})

    meta = channel_meta(conn)
    alerts_by_channel = defaultdict(list)
    for alert in open_alerts(conn):
        alerts_by_channel[alert["channel"]].append(alert)

    channels = []
    for r in rows.rows:
        if not (r[spend_m] or r["new_customers"]):
            continue
        info = meta.get(r["channel"], {})
        channels.append(
            {
                "channel": r["channel"],
                "label": info.get("label", r["channel"]),
                "is_paid": info.get("is_paid", False),
                "spend": r[spend_m],
                "new_customers": r["new_customers"],
                "cac": r[cac_m] if r[spend_m] else None,
                "cac_change_pct": pct_change(r[cac_m], prev_cac.get(r["channel"]))
                if r[spend_m] else None,
                "ltv_cac": r[ltv_cac_m],
                "payback_months": r[payback_m] if r[spend_m] else None,
                "sparkline": sparklines.get(r["channel"], []),
                "alerts": alerts_by_channel.get(r["channel"], []),
            }
        )

    kpis = {
        name: {"value": current.get(metric), "previous": previous.get(metric),
               "change_pct": pct_change(current.get(metric), previous.get(metric)),
               "metric": metric}
        for name, metric in [
            ("spend", spend_m), ("new_customers", "new_customers"), ("blended_cac", cac_m),
            ("paid_cac", "paid_cac"), ("ltv", "ltv"), ("ltv_cac", ltv_cac_m),
            ("payback_months", payback_m), ("unattributed_share", "unattributed_share"),
        ]
    }
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "previous_period": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
        "fully_loaded": fully_loaded,
        "attribution_model": attribution_model,
        "kpis": kpis,
        "channels": channels,
        "queries": [kpi_sql, rows.sql],
    }


FUNNEL = ["impressions", "clicks", "leads", "opportunities", "new_customers", "paid_spend",
          "fully_loaded_spend", "ctr", "cpc", "lead_cvr", "opportunity_rate", "customer_cvr",
          "cac", "cac_fully_loaded"]


def channel_detail(layer: SemanticLayer, conn: duckdb.DuckDBPyConnection, channel: str,
                   start: date, end: date, fully_loaded: bool,
                   attribution_model: str) -> dict[str, Any]:
    flt = [QueryFilter(dimension="channel", op="eq", value=channel)]
    prev_start, prev_end = previous_period(start, end)
    current, funnel_sql = _single(layer, conn, FUNNEL, start, end, attribution_model, flt)
    previous, _ = _single(layer, conn, FUNNEL, prev_start, prev_end, attribution_model, flt)

    trend = layer.query(
        conn,
        MetricQuery(
            metrics=["cac", "cac_fully_loaded", "cac_lagged", "cpc", "lead_cvr", "customer_cvr",
                     "new_customers", "paid_spend"],
            grain="month", start=add_months(month_start(end), -11), end=end,
            filters=flt, attribution_model=attribution_model,
        ),
    )
    cac_m = layer.variant("cac", fully_loaded)
    campaigns = layer.query(
        conn,
        MetricQuery(metrics=["paid_spend", "clicks", "leads", "new_customers", "cac", "cpc",
                             "customer_cvr"],
                    dimensions=["campaign"], start=start, end=end, filters=flt,
                    attribution_model=attribution_model,
                    order_by=[OrderBy(field="paid_spend", descending=True)]),
    )
    segments = layer.query(
        conn,
        MetricQuery(metrics=["new_customers", cac_m, "ltv", layer.variant("ltv_cac", fully_loaded),
                             layer.variant("payback_months", fully_loaded)],
                    dimensions=["segment"], start=start, end=end, filters=flt,
                    attribution_model=attribution_model),
    )
    dec = decompose(Funnel.from_row(previous), Funnel.from_row(current), fully_loaded,
                    subject=f"{channel_meta(conn).get(channel, {}).get('label', channel)} CAC")
    return {
        "channel": channel,
        "label": channel_meta(conn).get(channel, {}).get("label", channel),
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "previous_period": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
        "fully_loaded": fully_loaded,
        "attribution_model": attribution_model,
        "funnel": {"current": current, "previous": previous},
        "trend": [{**r, "period": r["period"].isoformat()} for r in trend.rows],
        "decomposition": dec.to_dict(),
        "campaigns": [r for r in campaigns.rows if r["paid_spend"] or r["new_customers"]],
        "segments": segments.rows,
        "alerts": [a for a in open_alerts(conn) if a["channel"] == channel],
        "queries": [funnel_sql, trend.sql, campaigns.sql],
    }


def attribution_compare(layer: SemanticLayer, conn: duckdb.DuckDBPyConnection, start: date,
                        end: date, metric: str) -> dict[str, Any]:
    result = layer.query(
        conn,
        MetricQuery(metrics=list(dict.fromkeys([metric, "new_customers"])),
                    dimensions=["channel", "attribution_model"],
                    start=start, end=end),
    )
    models = [r[0] for r in conn.execute(
        "select attribution_model from marts.dim_attribution_models order by sort_order"
    ).fetchall()] if table_exists(conn, "marts", "dim_attribution_models") else []
    table: dict[str, dict[str, Any]] = {}
    for r in result.rows:
        if not r["new_customers"]:
            continue
        table.setdefault(r["channel"], {"channel": r["channel"], "values": {}})
        table[r["channel"]]["values"][r["attribution_model"]] = r[metric]
    # Rank channels within each model (1 = best). Lower is better for cost metrics.
    lower_is_better = metric.startswith("cac") or metric.startswith("payback")
    ranks: dict[str, dict[str, int]] = defaultdict(dict)
    for model in models:
        scored = [(c, row["values"].get(model)) for c, row in table.items()
                  if row["values"].get(model)]
        scored.sort(key=lambda x: x[1] if lower_is_better else -x[1])
        for i, (c, _) in enumerate(scored, start=1):
            ranks[c][model] = i
    rows = [{**row, "ranks": ranks.get(c, {})} for c, row in table.items()]
    meta = channel_meta(conn)
    rows.sort(key=lambda r: meta.get(r["channel"], {}).get("sort_order", 99))
    for r in rows:
        r["label"] = meta.get(r["channel"], {}).get("label", r["channel"])
    return {"metric": metric, "models": models, "rows": rows, "query": result.sql,
            "period": {"start": start.isoformat(), "end": end.isoformat()}}


def data_quality(layer: SemanticLayer, conn: duckdb.DuckDBPyConnection, end: date
                 ) -> dict[str, Any]:
    freshness: list[dict[str, Any]] = []
    if table_exists(conn, "marts", "source_freshness"):
        for name, group, count, loaded in conn.execute(
            "select source_table, source_group, row_count, last_loaded_at "
            "from marts.source_freshness order by source_group, source_table"
        ).fetchall():
            freshness.append({"table": name, "group": group, "rows": count,
                              "last_loaded_at": loaded.isoformat() if loaded else None})
    matches: list[dict[str, Any]] = []
    if table_exists(conn, "marts", "customer_journeys"):
        matches = [
            {"match_method": m, "customers": n}
            for m, n in conn.execute(
                "select match_method, count(*) from marts.customer_journeys group by 1 order by 2 desc"
            ).fetchall()
        ]
    unattributed = layer.query(
        conn,
        MetricQuery(metrics=["unattributed_share", "new_customers"], grain="month",
                    start=add_months(month_start(end), -11), end=end),
    )
    return {
        "freshness": freshness,
        "identity_matches": matches,
        "unattributed_trend": [{**r, "period": r["period"].isoformat()} for r in unattributed.rows],
        "data_through": end.isoformat(),
    }
