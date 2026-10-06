"""FR-07 Claude Q&A agent: tool use over the semantic layer, never raw SQL."""

from __future__ import annotations

import json
import os
from typing import Any

import anthropic
import duckdb

from api.log import get_logger
from api.qa.answer import Answer, AskContext, finalize
from api.qa.tools import execute_tool, tool_definitions
from api.semantic import SemanticLayer

log = get_logger(__name__)

MAX_TURNS = 8
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """You are CACLens, the analytics assistant for a B2B SaaS company. You answer \
questions about customer acquisition cost (CAC), LTV, LTV:CAC, payback, funnel conversion and \
spend by channel, segment, campaign and cohort.

How to work:
- Get every number from the tools. Never estimate, recall or invent figures. If the tools \
cannot answer the question, say what is missing.
- query_metric is the only way to read data, and only metrics and dimensions from the catalog \
below exist. Prefer one well-shaped query (e.g. dimensions=["channel"], grain="month") over \
many small ones.
- For "why did CAC change" questions, find the period with query_metric if needed, then call \
explain_cac_change with the current period and a comparable baseline (usually the previous \
period of the same length) and report the driving factors.
- Resolve relative dates ("last quarter", "in March", "this year") against the as-of date in \
the context block. A month without a year means its most recent occurrence on or before the \
as-of date. Use whole calendar months/quarters.
- "Paid social" means meta_ads and linkedin_ads; "paid search" means google_search. Channel \
values: google_search, meta_ads, linkedin_ads, organic_search, referral, email, direct, \
unattributed (customers with no known touchpoint), unallocated (costs without a channel).
- CAC means paid-media CAC (metric `cac`) unless the user says fully loaded (`cac_fully_loaded`, \
which adds allocated salaries and tools). Use the default attribution model from the context \
unless the user names one; to compare models, group by attribution_model.
- LTV, churn and ARPA come from monthly revenue data, available only through the revenue \
date in the context block.

Answer format: lead with the direct answer in one or two sentences, then the supporting \
numbers. Keep it under about 120 words. Name the period and the attribution model. Format \
currency like $1,234, rates as percentages and LTV:CAC like 3.2x. Do not show SQL or tool \
names; the app shows the queries separately.

<catalog>
{catalog}
</catalog>"""


def build_catalog(layer: SemanticLayer) -> str:
    lines = ["Metrics:"]
    for m in layer.metrics.values():
        dims = ", ".join(layer.metric_dimensions(m.name))
        lines.append(
            f"- {m.name} ({m.label}; {m.format}): {m.description} Formula: {m.formula}. "
            f"Dimensions: {dims}. Finest grain: {layer.metric_min_grain(m.name)}."
        )
    lines.append("Dimensions:")
    for d in layer.dimensions.values():
        values = f" Values: {', '.join(d.values)}." if d.values else ""
        lines.append(f"- {d.name} ({d.type}): {d.description}{values}")
    return "\n".join(lines)


def context_block(ctx: AskContext) -> str:
    return (
        "<context>\n"
        f"As-of date (latest acquisition data): {ctx.as_of.isoformat()}\n"
        f"Acquisition data starts: {ctx.first_day.isoformat() if ctx.first_day else 'unknown'}\n"
        "Revenue/LTV data through month: "
        f"{ctx.revenue_through.isoformat() if ctx.revenue_through else 'unknown'}\n"
        f"Default attribution model: {ctx.attribution_model}\n"
        f"Dashboard fully-loaded toggle: {'on' if ctx.fully_loaded else 'off'}\n"
        "</context>"
    )


class ClaudeAgent:
    def __init__(self, layer: SemanticLayer, model: str, client: Any = None,
                 api_key: str | None = None) -> None:
        self.layer = layer
        self.model = model
        self.client = client or anthropic.Anthropic(api_key=api_key)
        self.effort = os.environ.get("CACLENS_QA_EFFORT", "medium")
        self.system = [
            {
                "type": "text",
                "text": SYSTEM_PROMPT.format(catalog=build_catalog(layer)),
                "cache_control": {"type": "ephemeral"},
            }
        ]
        self.tools = tool_definitions(layer)

    def ask(self, conn: duckdb.DuckDBPyConnection, question: str, ctx: AskContext) -> Answer:
        answer = Answer(question=question, answer="", planner="claude", model=self.model)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": f"{context_block(ctx)}\n\n{question}"}
        ]
        for _turn in range(MAX_TURNS):
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=self.system,
                tools=self.tools,
                messages=messages,
                output_config={"effort": self.effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
            if response.stop_reason == "refusal":
                answer.answer = "I can't help with that request. Try a question about CAC, " \
                    "LTV, payback, spend or conversion."
                return finalize(self.layer, answer)
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                text = "".join(b.text for b in response.content if b.type == "text").strip()
                answer.answer = text or "I could not produce an answer from the available data."
                return finalize(self.layer, answer)

            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in tool_uses:
                call = execute_tool(self.layer, conn, block.name, dict(block.input))
                answer.calls.append(call)
                log.info("qa_tool_call", tool=block.name, ok=call.ok)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(call.output, default=str),
                        "is_error": not call.ok,
                    }
                )
            messages.append({"role": "user", "content": results})

        answer.answer = "I ran out of steps before finishing. Try a narrower question."
        return finalize(self.layer, answer)
