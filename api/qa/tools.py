"""FR-07 tools the Q&A agent may call. They only reach data through the semantic layer;
there is deliberately no tool that accepts SQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import duckdb
from pydantic import BaseModel, Field, ValidationError

from api.analytics.decomposition import Funnel, decompose
from api.semantic import (
    GRAINS,
    MetricQuery,
    OrderBy,
    QueryFilter,
    QueryResult,
    SemanticError,
    SemanticLayer,
)

MAX_ROWS_TO_MODEL = 60
DIMENSION_VALUE_DIMS = ("channel", "campaign", "segment")


class ExplainInput(BaseModel):
    channels: list[str] | None = None
    current_start: date
    current_end: date
    baseline_start: date
    baseline_end: date
    fully_loaded: bool = False
    attribution_model: str = "position_based"


class DimensionValuesInput(BaseModel):
    dimension: str = Field(pattern="^(channel|campaign|segment)$")


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    ok: bool
    output: dict[str, Any]
    sql: list[str] = field(default_factory=list)
    result: QueryResult | None = None


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def tool_definitions(layer: SemanticLayer) -> list[dict[str, Any]]:
    metric_names = sorted(layer.metrics)
    dim_names = list(layer.dimensions)
    models = list(layer.dimensions["attribution_model"].values)
    scalar = {"anyOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}]}
    return [
        {
            "name": "query_metric",
            "description": (
                "Query one or more metrics from the CACLens semantic layer. Returns rows with "
                "the requested dimensions (and `period` when a grain is set). Use filters to "
                "restrict channels, segments, campaigns or cohorts. Dates are inclusive "
                "YYYY-MM-DD. Every number you report must come from a call like this."
            ),
            "strict": True,
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["metrics", "dimensions", "grain", "start", "end", "filters",
                             "attribution_model", "order_by", "limit"],
                "properties": {
                    "metrics": {"type": "array", "items": {"type": "string", "enum": metric_names}},
                    "dimensions": {"type": "array", "items": {"type": "string", "enum": dim_names}},
                    "grain": _nullable({"type": "string", "enum": list(GRAINS)}),
                    "start": _nullable({"type": "string", "format": "date"}),
                    "end": _nullable({"type": "string", "format": "date"}),
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["dimension", "op", "value"],
                            "properties": {
                                "dimension": {"type": "string", "enum": dim_names},
                                "op": {"type": "string",
                                       "enum": ["eq", "neq", "in", "not_in", "gt", "gte", "lt",
                                                "lte"]},
                                "value": {"anyOf": [scalar, {"type": "array", "items": scalar}]},
                            },
                        },
                    },
                    "attribution_model": {"type": "string", "enum": models},
                    "order_by": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["field", "descending"],
                            "properties": {"field": {"type": "string"},
                                           "descending": {"type": "boolean"}},
                        },
                    },
                    "limit": _nullable({"type": "integer"}),
                },
            },
        },
        {
            "name": "explain_cac_change",
            "description": (
                "Explain why CAC changed between a baseline and a current period by "
                "decomposing it into CPC, click-to-lead CVR, lead-to-customer CVR (and, when "
                "fully_loaded, people/tool overhead). Use for 'why' questions about CAC. "
                "channels null means all paid channels together; pass several channels "
                "(e.g. meta_ads and linkedin_ads for paid social) to explain them combined."
            ),
            "strict": True,
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["channels", "current_start", "current_end", "baseline_start",
                             "baseline_end", "fully_loaded", "attribution_model"],
                "properties": {
                    "channels": _nullable({"type": "array", "items": {"type": "string"}}),
                    "current_start": {"type": "string", "format": "date"},
                    "current_end": {"type": "string", "format": "date"},
                    "baseline_start": {"type": "string", "format": "date"},
                    "baseline_end": {"type": "string", "format": "date"},
                    "fully_loaded": {"type": "boolean"},
                    "attribution_model": {"type": "string", "enum": models},
                },
            },
        },
        {
            "name": "list_dimension_values",
            "description": "List the values that exist in the data for channel, campaign or segment.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["dimension"],
                "properties": {
                    "dimension": {"type": "string", "enum": list(DIMENSION_VALUE_DIMS)},
                },
            },
        },
    ]


def _rows_for_model(result: QueryResult) -> list[dict[str, Any]]:
    rows = []
    for row in result.rows[:MAX_ROWS_TO_MODEL]:
        rows.append({
            k: (round(v, 4) if isinstance(v, float) else v.isoformat() if isinstance(v, date) else v)
            for k, v in row.items()
        })
    return rows


def run_query_metric(layer: SemanticLayer, conn: duckdb.DuckDBPyConnection,
                     raw: dict[str, Any]) -> ToolCall:
    try:
        query = MetricQuery(
            metrics=raw.get("metrics") or [],
            dimensions=raw.get("dimensions") or [],
            grain=raw.get("grain"),
            start=raw.get("start"),
            end=raw.get("end"),
            filters=[QueryFilter(**f) for f in raw.get("filters") or []],
            attribution_model=raw.get("attribution_model") or "position_based",
            order_by=[OrderBy(**o) for o in raw.get("order_by") or []],
            limit=raw.get("limit"),
        )
        result = layer.query(conn, query)
    except (ValidationError, SemanticError, TypeError, ValueError) as exc:
        return ToolCall("query_metric", raw, False, {"error": str(exc)})
    output = {
        "columns": result.columns,
        "rows": _rows_for_model(result),
        "row_count": len(result.rows),
        "truncated": len(result.rows) > MAX_ROWS_TO_MODEL,
        "formats": {m: layer.metrics[m].format for m in query.metrics},
    }
    return ToolCall("query_metric", raw, True, output, [result.sql], result)


def run_explain(layer: SemanticLayer, conn: duckdb.DuckDBPyConnection,
                raw: dict[str, Any]) -> ToolCall:
    try:
        args = ExplainInput(**raw)
        filters = [QueryFilter(dimension="is_paid_channel", op="eq", value=True)]
        if args.channels:
            filters = [QueryFilter(dimension="channel", op="in", value=list(args.channels))]
        metrics = ["paid_spend", "fully_loaded_spend", "clicks", "leads", "new_customers"]
        funnels, sql = [], []
        for start, end in ((args.baseline_start, args.baseline_end),
                           (args.current_start, args.current_end)):
            result = layer.query(conn, MetricQuery(metrics=metrics, start=start, end=end,
                                                   filters=filters,
                                                   attribution_model=args.attribution_model))
            funnels.append(Funnel.from_row(result.rows[0] if result.rows else None))
            sql.append(result.sql)
    except (ValidationError, SemanticError, TypeError, ValueError) as exc:
        return ToolCall("explain_cac_change", raw, False, {"error": str(exc)})
    subject = f"{' + '.join(args.channels)} CAC" if args.channels else "Paid CAC"
    dec = decompose(funnels[0], funnels[1], args.fully_loaded, subject=subject)
    output = {
        **dec.to_dict(),
        "baseline_funnel": funnels[0].__dict__,
        "current_funnel": funnels[1].__dict__,
    }
    return ToolCall("explain_cac_change", raw, True, output, sql)


def run_dimension_values(conn: duckdb.DuckDBPyConnection, raw: dict[str, Any]) -> ToolCall:
    try:
        args = DimensionValuesInput(**raw)
    except ValidationError as exc:
        return ToolCall("list_dimension_values", raw, False, {"error": str(exc)})
    # The column name comes from a closed enum, never from free text.
    values = [r[0] for r in conn.execute(
        f"select distinct {args.dimension} from marts.fct_acquisition_daily "
        f"where new_customers > 0 or paid_spend > 0 order by 1"
    ).fetchall()]
    return ToolCall("list_dimension_values", raw, True, {"values": values})


def execute_tool(layer: SemanticLayer, conn: duckdb.DuckDBPyConnection, name: str,
                 raw: dict[str, Any]) -> ToolCall:
    if name == "query_metric":
        return run_query_metric(layer, conn, raw)
    if name == "explain_cac_change":
        return run_explain(layer, conn, raw)
    if name == "list_dimension_values":
        return run_dimension_values(conn, raw)
    return ToolCall(name, raw, False, {"error": f"unknown tool {name}"})
