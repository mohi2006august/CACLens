"""CACLens metrics API (FastAPI). Run: uv run uvicorn api.main:app --reload"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from functools import lru_cache
from typing import Annotated, Any

import duckdb
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api import qa
from api.analytics import cohorts, dashboard, optimiser
from api.analytics.alerts import AlertConfig, detect_alerts, read_alerts
from api.analytics.common import data_bounds, default_range, semantic_layer
from api.config import get_settings
from api.log import configure_logging, get_logger
from api.semantic import GRAINS, Grain, MetricQuery, QueryFilter, SemanticError, SemanticLayer
from api.warehouse import WarehouseNotReady, connect, serving_path, table_exists

configure_logging()
log = get_logger(__name__)

app = FastAPI(
    title="CACLens API",
    version="0.1.0",
    description="Channel-level CAC, LTV:CAC and payback metrics with plain-English Q&A.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(SemanticError)
async def _semantic_error(_: Request, exc: SemanticError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(WarehouseNotReady)
async def _not_ready(_: Request, exc: WarehouseNotReady) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@contextmanager
def _db() -> Iterator[duckdb.DuckDBPyConnection]:
    with connect() as conn:
        yield conn


def get_layer() -> SemanticLayer:
    return semantic_layer()


Layer = Annotated[SemanticLayer, Depends(get_layer)]
Attribution = Annotated[str, Query(alias="attribution", description="Attribution model")]
FullyLoaded = Annotated[bool, Query(description="Include allocated people and tool costs")]


def _range(conn: duckdb.DuckDBPyConnection, start: date | None, end: date | None,
           days: int = 90) -> tuple[date, date]:
    default_start, default_end = default_range(data_bounds(conn), days)
    return start or default_start, end or default_end


def _check_model(layer: SemanticLayer, model: str) -> str:
    allowed = layer.dimensions["attribution_model"].values
    if model not in allowed:
        raise HTTPException(400, f"attribution must be one of: {', '.join(allowed)}")
    return model


# --- health & catalogue -------------------------------------------------------------


@app.get("/v1/health")
def health() -> dict[str, Any]:
    path = serving_path()
    if not path.exists():
        return {"status": "no_data", "warehouse": None}
    with _db() as conn:
        bounds = data_bounds(conn)
        alerts_ready = table_exists(conn, "app", "alerts")
    return {
        "status": "ok",
        "snapshot": path.name,
        "data_from": bounds.first_day.isoformat() if bounds.first_day else None,
        "data_through": bounds.last_day.isoformat() if bounds.last_day else None,
        "revenue_through": bounds.last_complete_revenue_month.isoformat()
        if bounds.last_complete_revenue_month else None,
        "alerts_ready": alerts_ready,
        "qa_planner": "claude" if qa.claude_configured() else "rules",
    }


@app.get("/v1/metrics")
def list_metrics(layer: Layer) -> dict[str, Any]:
    catalog = layer.catalog()
    with _db() as conn:
        bounds = data_bounds(conn)
        values: dict[str, list[str]] = {}
        if table_exists(conn, "marts", "fct_acquisition_daily"):
            for dim in ("channel", "campaign"):
                values[dim] = [r[0] for r in conn.execute(
                    f"select distinct {dim} from marts.fct_acquisition_daily "
                    "where paid_spend > 0 or new_customers > 0 order by 1"
                ).fetchall()]
    for dim in catalog["dimensions"]:
        if dim["name"] in values:
            dim["values"] = values[dim["name"]]
    catalog["data_through"] = bounds.last_day.isoformat() if bounds.last_day else None
    return catalog


# --- generic metric queries ---------------------------------------------------------


@lru_cache(maxsize=256)
def _cached_query(snapshot: str, payload: str) -> str:
    """Semantic queries are cached per published snapshot (SYSTEM_ARCHITECTURE §6)."""
    del snapshot  # part of the cache key only
    query = MetricQuery.model_validate_json(payload)
    with _db() as conn:
        result = semantic_layer().query(conn, query)
    return json.dumps(
        {"columns": result.columns, "rows": result.rows, "sql": result.sql,
         "query": result.query},
        default=str,
    )


def _run(query: MetricQuery) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(_cached_query(serving_path().name, query.model_dump_json()))
    return out


@app.post("/v1/metrics/query")
def query_metrics(query: MetricQuery) -> dict[str, Any]:
    return _run(query)


def _parse_filter(raw: str) -> QueryFilter:
    parts = raw.split(":", 2)
    if len(parts) == 2:
        dim, value = parts
        return QueryFilter(dimension=dim, op="eq", value=value)
    if len(parts) == 3:
        dim, op, value = parts
        if op in ("in", "not_in"):
            return QueryFilter(dimension=dim, op=op, value=value.split(","))
        return QueryFilter(dimension=dim, op=op, value=value)  # type: ignore[arg-type]
    raise HTTPException(400, "filter must be dimension:value or dimension:op:value")


@app.get("/v1/metrics/payback")
def payback(
    layer: Layer,
    cohort: Annotated[str | None, Query(description="e.g. 2026-Q1, 2026-03 or 2026")] = None,
    by: Annotated[str | None, Query(pattern="^channel$")] = "channel",
    channel: str | None = None,
    fully_loaded: FullyLoaded = False,
    attribution: Attribution = "position_based",
) -> dict[str, Any]:
    """FR-04 cohort payback curves: cumulative gross margin per customer vs CAC."""
    _check_model(layer, attribution)
    with _db() as conn:
        bounds = data_bounds(conn)
        if bounds.last_complete_revenue_month is None:
            raise HTTPException(503, "No revenue data yet.")
        try:
            rng = cohorts.parse_cohort(cohort) if cohort else cohorts.CohortRange(
                start=bounds.last_complete_revenue_month.replace(
                    year=bounds.last_complete_revenue_month.year - 1),
                end=bounds.last_complete_revenue_month,
                label="last 12 months",
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return cohorts.payback_curves(
            layer, conn, rng, bounds.last_complete_revenue_month, by_channel=by == "channel",
            channel=channel, attribution_model=attribution, fully_loaded=fully_loaded,
        )


@app.get("/v1/metrics/{metric}")
def metric_series(
    metric: str,
    by: Annotated[str | None, Query(description="Comma-separated dimensions")] = None,
    period: Annotated[Grain | None, Query(description=f"Grain: {', '.join(GRAINS)}")] = None,
    start: date | None = None,
    end: date | None = None,
    filter: Annotated[list[str] | None, Query(description="dim:value or dim:op:value")] = None,
    fully_loaded: FullyLoaded = False,
    attribution: Attribution = "position_based",
) -> dict[str, Any]:
    """e.g. /v1/metrics/cac?by=channel&period=month (TECHNICAL.md §4)."""
    metric = semantic_layer().variant(metric, fully_loaded)
    with _db() as conn:
        s, e = _range(conn, start, end, days=365 if period else 90)
    query = MetricQuery(
        metrics=[metric],
        dimensions=[d.strip() for d in by.split(",") if d.strip()] if by else [],
        grain=period,
        start=s,
        end=e,
        filters=[_parse_filter(f) for f in filter or []],
        attribution_model=attribution,
    )
    return _run(query)


# --- screens ------------------------------------------------------------------------


@app.get("/v1/overview")
def overview(
    layer: Layer,
    start: date | None = None,
    end: date | None = None,
    fully_loaded: FullyLoaded = False,
    attribution: Attribution = "position_based",
) -> dict[str, Any]:
    _check_model(layer, attribution)
    with _db() as conn:
        s, e = _range(conn, start, end)
        return dashboard.overview(layer, conn, s, e, fully_loaded, attribution)


@app.get("/v1/channels/{channel}")
def channel_detail(
    channel: str,
    layer: Layer,
    start: date | None = None,
    end: date | None = None,
    fully_loaded: FullyLoaded = False,
    attribution: Attribution = "position_based",
) -> dict[str, Any]:
    _check_model(layer, attribution)
    with _db() as conn:
        s, e = _range(conn, start, end)
        return dashboard.channel_detail(layer, conn, channel, s, e, fully_loaded, attribution)


@app.get("/v1/cohorts")
def cohort_grid(
    layer: Layer,
    start: date | None = None,
    end: date | None = None,
    channel: str | None = None,
    attribution: Attribution = "position_based",
) -> dict[str, Any]:
    _check_model(layer, attribution)
    with _db() as conn:
        bounds = data_bounds(conn)
        last = bounds.last_complete_revenue_month
        if last is None:
            raise HTTPException(503, "No revenue data yet.")
        first = start or last.replace(year=last.year - 1)
        return cohorts.cohort_grid(layer, conn, first, end or last, channel, attribution)


@app.get("/v1/attribution/compare")
def attribution_compare(
    layer: Layer,
    metric: Annotated[str, Query(pattern="^(cac|cac_fully_loaded|new_customers|ltv_cac|"
                                         "payback_months)$")] = "cac",
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    """FR-05 side-by-side attribution models with channel ranks per model."""
    with _db() as conn:
        s, e = _range(conn, start, end)
        return dashboard.attribution_compare(layer, conn, s, e, metric)


@app.get("/v1/alerts")
def alerts(
    layer: Layer,
    status: Annotated[str | None, Query(pattern="^(open|resolved)$")] = None,
    channel: str | None = None,
) -> dict[str, Any]:
    """FR-06 CAC spike alerts with driver decomposition."""
    with _db() as conn:
        if table_exists(conn, "app", "alerts"):
            items = read_alerts(conn)
            source = "published"
        else:
            bounds = data_bounds(conn)
            if bounds.last_day is None:
                return {"alerts": [], "source": "none"}
            items = [a.to_dict() for a in detect_alerts(layer, conn, bounds.last_day,
                                                        alert_config())]
            source = "computed"
    if status:
        items = [a for a in items if a["status"] == status]
    if channel:
        items = [a for a in items if a["channel"] == channel]
    return {"alerts": items, "source": source}


def alert_config() -> AlertConfig:
    s = get_settings()
    return AlertConfig(window_days=s.alert_window_days, baseline_days=s.alert_baseline_days,
                       threshold_pct=s.alert_threshold_pct,
                       min_customers=float(s.alert_min_customers))


@app.get("/v1/optimiser")
def budget_optimiser(
    layer: Layer,
    budget: Annotated[float | None, Query(gt=0, description="Monthly paid budget")] = None,
    months: Annotated[int, Query(ge=3, le=24)] = 12,
    attribution: Attribution = "position_based",
) -> dict[str, Any]:
    """FR-08 marginal-CAC based budget reallocation."""
    _check_model(layer, attribution)
    with _db() as conn:
        bounds = data_bounds(conn)
        if bounds.last_day is None:
            raise HTTPException(503, "No data yet.")
        return optimiser.optimise(layer, conn, bounds.last_day, budget, months, attribution)


@app.get("/v1/data-quality")
def data_quality(layer: Layer) -> dict[str, Any]:
    with _db() as conn:
        bounds = data_bounds(conn)
        return dashboard.data_quality(layer, conn, bounds.last_day or date.today())


# --- Q&A ----------------------------------------------------------------------------


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    fully_loaded: bool = False
    attribution: str = "position_based"


@app.post("/v1/ask")
def ask(body: AskRequest, layer: Layer) -> dict[str, Any]:
    """FR-07 natural-language question -> answer + chart + the queries used."""
    _check_model(layer, body.attribution)
    answer = qa.ask(body.question, fully_loaded=body.fully_loaded,
                    attribution_model=body.attribution)
    log.info("qa_answered", planner=answer.planner, queries=len(answer.queries))
    return answer.to_dict()

