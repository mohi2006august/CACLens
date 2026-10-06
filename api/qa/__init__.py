"""FR-07 natural-language Q&A over the semantic layer."""

from __future__ import annotations

import os
from datetime import date

import anthropic

from api.analytics.common import data_bounds, semantic_layer
from api.config import get_settings
from api.log import get_logger
from api.qa.agent import ClaudeAgent
from api.qa.answer import Answer, AskContext
from api.qa.rules import RulePlanner
from api.warehouse import connect

log = get_logger(__name__)


def claude_configured() -> bool:
    planner = os.environ.get("CACLENS_QA_PLANNER", "auto").lower()
    if planner == "rules":
        return False
    if planner == "claude":
        return True
    return bool(get_settings().anthropic_api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def ask(question: str, fully_loaded: bool = False,
        attribution_model: str = "position_based") -> Answer:
    settings = get_settings()
    layer = semantic_layer()
    with connect() as conn:
        bounds = data_bounds(conn)
        ctx = AskContext(
            as_of=bounds.last_day or date.today(),
            first_day=bounds.first_day,
            revenue_through=bounds.last_complete_revenue_month,
            attribution_model=attribution_model,
            fully_loaded=fully_loaded,
        )
        if claude_configured():
            try:
                agent = ClaudeAgent(layer, settings.qa_model, api_key=settings.anthropic_api_key)
                return agent.ask(conn, question, ctx)
            except anthropic.RateLimitError as exc:
                log.warning("qa_claude_rate_limited", error=str(exc))
            except anthropic.APIStatusError as exc:
                log.error("qa_claude_api_error", status=exc.status_code, error=str(exc))
            except anthropic.APIConnectionError as exc:
                log.warning("qa_claude_unreachable", error=str(exc))
        answer = RulePlanner(layer).ask(conn, question, ctx)
        if claude_configured():
            answer.answer += " (Answered by the offline planner because Claude was unavailable.)"
        return answer


__all__ = ["Answer", "AskContext", "ask", "claude_configured"]
