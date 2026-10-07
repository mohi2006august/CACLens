from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest

from api.qa.agent import ClaudeAgent
from api.qa.answer import AskContext, format_value
from api.qa.rules import plan_question, resolve_period
from api.semantic import SemanticLayer
from tests.conftest import acq_row, daterange, make_marts

AS_OF = date(2026, 9, 30)
CTX = AskContext(as_of=AS_OF, first_day=date(2025, 1, 1), revenue_through=date(2026, 9, 1))


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("last month", date(2026, 8, 1), date(2026, 8, 31)),
        ("this quarter", date(2026, 7, 1), date(2026, 9, 30)),
        ("last quarter", date(2026, 4, 1), date(2026, 6, 30)),
        ("in march", date(2026, 3, 1), date(2026, 3, 31)),
        ("in november", date(2025, 11, 1), date(2025, 11, 30)),  # most recent past November
        ("q1 2026", date(2026, 1, 1), date(2026, 3, 31)),
        ("last 30 days", date(2026, 9, 1), date(2026, 9, 30)),
        ("this year", date(2026, 1, 1), date(2026, 9, 30)),
        ("in 2025", date(2025, 1, 1), date(2025, 12, 31)),
        ("", date(2026, 7, 3), date(2026, 9, 30)),
    ],
)
def test_resolve_period(text: str, start: date, end: date) -> None:
    period = resolve_period(text, AS_OF)
    assert (period.start, period.end) == (start, end)


def test_plan_understands_channels_metrics_and_intent(layer: SemanticLayer) -> None:
    plan = plan_question("Why did paid social CAC jump in March?", CTX, layer)
    assert plan.intent == "explain"
    assert plan.filters == [{"dimension": "channel", "op": "in",
                             "value": ["meta_ads", "linkedin_ads"]}]

    plan = plan_question("Fully loaded LTV:CAC by channel this year", CTX, layer)
    assert plan.metrics == ["ltv_cac_fully_loaded"] and plan.dimensions == ["channel"]

    plan = plan_question("Which channel's CAC grew most this quarter and why?", CTX, layer)
    assert plan.intent == "growth"


def test_format_value() -> None:
    assert format_value(1234.4, "currency") == "$1,234"
    assert format_value(0.1234, "percent") == "12.3%"
    assert format_value(3.25, "ratio") == "3.2x"
    assert format_value(None, "currency") == "n/a"


# --- Claude agent with a fake client ------------------------------------------------


@dataclass
class Block:
    type: str
    text: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    id: str = ""


@dataclass
class Response:
    stop_reason: str
    content: list[Block]


class FakeMessages:
    def __init__(self, responses: list[Response]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Response:
        self.requests.append(kwargs)
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[Response]) -> None:
        self.beta = type("Beta", (), {})()
        self.beta.messages = FakeMessages(responses)


def _conn() -> Any:
    rows = [acq_row(day, "meta_ads", paid_spend=1000.0, clicks=500.0, leads=50.0,
                    new_customers=2.0) for day in daterange(date(2026, 3, 1), 31)]
    return make_marts(rows)


def test_agent_runs_tools_through_the_semantic_layer(layer: SemanticLayer) -> None:
    query = {"metrics": ["cac"], "dimensions": ["channel"], "grain": None,
             "start": "2026-03-01", "end": "2026-03-31", "filters": [],
             "attribution_model": "position_based", "order_by": [], "limit": None}
    client = FakeClient([
        Response("tool_use", [Block("text", text="Checking."),
                              Block("tool_use", name="query_metric", input=query, id="t1")]),
        Response("end_turn", [Block("text", text="Meta Ads CAC was $500 in March 2026.")]),
    ])
    agent = ClaudeAgent(layer, "claude-opus-5-5", client=client)
    answer = agent.ask(_conn(), "What was Meta CAC in March?", CTX)

    assert answer.answer == "Meta Ads CAC was $500 in March 2026."
    assert answer.planner == "claude"
    assert answer.queries[0]["tool"] == "query_metric" and answer.queries[0]["ok"]
    assert answer.chart and answer.chart["type"] == "bar"
    assert answer.chart["rows"][0]["cac"] == pytest.approx(500.0)

    first, second = client.beta.messages.requests
    assert first["model"] == "claude-opus-5-5"
    assert first["fallbacks"] == "default"
    assert {t["name"] for t in first["tools"]} == {"query_metric", "explain_cac_change",
                                                   "list_dimension_values"}
    assert "sql" not in str([t["name"] for t in first["tools"]]).lower()
    tool_result = second["messages"][-1]["content"][0]
    assert tool_result["tool_use_id"] == "t1" and tool_result["is_error"] is False


def test_agent_returns_tool_errors_to_the_model(layer: SemanticLayer) -> None:
    bad = {"metrics": ["cac"], "dimensions": ["months_since_acquisition"], "grain": None,
           "start": None, "end": None, "filters": [], "attribution_model": "position_based",
           "order_by": [], "limit": None}
    client = FakeClient([
        Response("tool_use", [Block("tool_use", name="query_metric", input=bad, id="t1")]),
        Response("end_turn", [Block("text", text="That breakdown is not available.")]),
    ])
    answer = ClaudeAgent(layer, "m", client=client).ask(_conn(), "CAC by cohort age?", CTX)
    result = client.beta.messages.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "not available" in result["content"]
    assert answer.queries[0]["ok"] is False


def test_agent_handles_refusals(layer: SemanticLayer) -> None:
    client = FakeClient([Response("refusal", [])])
    answer = ClaudeAgent(layer, "m", client=client).ask(_conn(), "something", CTX)
    assert "can't help" in answer.answer
