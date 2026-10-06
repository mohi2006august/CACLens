"""Answer envelope shared by both planners: text, chart and the queries used."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from api.qa.tools import ToolCall
from api.semantic import SemanticLayer

MAX_CHART_ROWS = 500


@dataclass(frozen=True)
class AskContext:
    as_of: date
    first_day: date | None
    revenue_through: date | None
    attribution_model: str = "position_based"
    fully_loaded: bool = False


@dataclass
class Answer:
    question: str
    answer: str
    planner: str
    model: str | None = None
    chart: dict[str, Any] | None = None
    queries: list[dict[str, Any]] = field(default_factory=list)
    calls: list[ToolCall] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "planner": self.planner,
            "model": self.model,
            "chart": self.chart,
            "queries": self.queries,
        }


def format_value(value: float | None, fmt: str) -> str:
    if value is None:
        return "n/a"
    if fmt == "currency":
        return f"${value:,.0f}" if abs(value) >= 100 else f"${value:,.2f}"
    if fmt == "percent":
        return f"{value * 100:.1f}%"
    if fmt == "ratio":
        return f"{value:.1f}x"
    if fmt == "months":
        return f"{value:.1f} months"
    return f"{value:,.0f}" if abs(value) >= 100 or float(value).is_integer() else f"{value:,.1f}"


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in row.items()}


def chart_for(layer: SemanticLayer, call: ToolCall) -> dict[str, Any] | None:
    if not call.ok:
        return None
    if call.name == "explain_cac_change":
        return {
            "type": "drivers",
            "title": call.output.get("summary"),
            "cac_baseline": call.output.get("cac_baseline"),
            "cac_current": call.output.get("cac_current"),
            "drivers": call.output.get("drivers", []),
        }
    if call.name != "query_metric" or call.result is None:
        return None
    metrics = call.input.get("metrics") or []
    dims = call.input.get("dimensions") or []
    grain = call.input.get("grain")
    metric = metrics[0]
    if grain:
        kind, x, series = "line", "period", (dims[0] if dims else None)
    elif dims:
        kind, x, series = "bar", dims[0], (dims[1] if len(dims) > 1 else None)
    else:
        kind, x, series = "stat", None, None
    return {
        "type": kind,
        "x": x,
        "series": series,
        "metric": metric,
        "metrics": [
            {"name": m, "label": layer.metrics[m].label, "format": layer.metrics[m].format}
            for m in metrics
        ],
        "rows": [_jsonable(r) for r in call.result.rows[:MAX_CHART_ROWS]],
    }


def finalize(layer: SemanticLayer, answer: Answer) -> Answer:
    answer.queries = [
        {"tool": c.name, "input": c.input, "ok": c.ok, "sql": c.sql,
         **({"error": c.output.get("error")} if not c.ok else {})}
        for c in answer.calls
    ]
    for call in reversed(answer.calls):
        chart = chart_for(layer, call)
        if chart:
            answer.chart = chart
            break
    return answer
