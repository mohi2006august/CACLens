"""FR-07 Q&A eval: does each planner issue the semantic query an analyst would?

Scores the tool calls, not the prose: an answer built on the wrong metric, filter or
period is wrong however well it reads. Run `uv run caclens eval [--planner claude]`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from api.analytics.common import data_bounds, semantic_layer
from api.config import REPO_ROOT, get_settings
from api.qa.agent import ClaudeAgent
from api.qa.answer import Answer, AskContext
from api.qa.rules import RulePlanner
from api.qa.tools import ToolCall
from api.warehouse import connect

EVAL_PATH = REPO_ROOT / "evals" / "qa_questions.yml"
IGNORED_FILTERS = {"is_paid_channel"}


@dataclass
class Score:
    id: str
    question: str
    passed: bool
    reason: str


def _filter_values(call_input: dict[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in call_input.get("filters") or []:
        values = f["value"] if isinstance(f["value"], list) else [f["value"]]
        out.setdefault(f["dimension"], set()).update(str(v) for v in values)
    model = call_input.get("attribution_model")
    if model and model != "position_based":
        out.setdefault("attribution_model", set()).add(model)
    return out


def _query_matches(call: ToolCall, expect: dict[str, Any], check_dims: bool = True
                   ) -> str | None:
    """None if the query_metric call matches, else the reason it does not."""
    inp = call.input
    if expect["metric"] not in (inp.get("metrics") or []):
        return f"metric {inp.get('metrics')} != {expect['metric']}"
    if check_dims and set(inp.get("dimensions") or []) != set(expect["dimensions"]):
        return f"dimensions {inp.get('dimensions')} != {expect['dimensions']}"
    if (inp.get("grain") or None) != expect["grain"]:
        return f"grain {inp.get('grain')} != {expect['grain']}"
    got = {k: v for k, v in _filter_values(inp).items() if k not in IGNORED_FILTERS}
    want = {k: set(v) for k, v in expect["filters"].items()}
    if got != want:
        return f"filters {got} != {want}"
    if "start" in expect and (inp.get("start"), inp.get("end")) != (expect["start"], expect["end"]):
        return f"period {inp.get('start')}..{inp.get('end')} != {expect['start']}..{expect['end']}"
    return None


def _explain_matches(call: ToolCall, expect: dict[str, Any], channels_required: bool = True
                     ) -> str | None:
    inp = call.input
    want_channels = set(expect["filters"].get("channel", []))
    got_channels = set(inp.get("channels") or [])
    if channels_required and got_channels != want_channels:
        return f"channels {sorted(got_channels)} != {sorted(want_channels)}"
    if bool(inp.get("fully_loaded")) != expect["metric"].startswith("cac_fully_loaded"):
        return "fully_loaded flag mismatch"
    if "start" in expect and (inp.get("current_start"), inp.get("current_end")) != (
        expect["start"], expect["end"]
    ):
        return (f"period {inp.get('current_start')}..{inp.get('current_end')} != "
                f"{expect['start']}..{expect['end']}")
    return None


def score(item: dict[str, Any], answer: Answer) -> Score:
    expect = item["expect"]
    calls = [c for c in answer.calls if c.ok]
    queries = [c for c in calls if c.name == "query_metric"]
    explains = [c for c in calls if c.name == "explain_cac_change"]
    reasons: list[str] = []

    def first_match(candidates: list[ToolCall], check: Any) -> bool:
        for call in candidates:
            reason = check(call)
            if reason is None:
                return True
            reasons.append(reason)
        return False

    if expect["intent"] == "lookup":
        ok = first_match(queries, lambda c: _query_matches(c, expect))
    elif expect["intent"] == "explain":
        ok = first_match(explains, lambda c: _explain_matches(c, expect))
    else:  # growth: compare channels for the period, then explain the winner
        ok = first_match(queries, lambda c: _query_matches(c, expect)) and bool(explains) and \
            first_match(explains, lambda c: _explain_matches(c, expect, channels_required=False))
    if not calls:
        reasons.append("no successful tool calls")
    return Score(item["id"], item["question"], ok, "; ".join(reasons[-2:]) if not ok else "")


def run(planner: str = "rules", limit: int | None = None, path: Path = EVAL_PATH) -> list[Score]:
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    items = spec["questions"][:limit] if limit else spec["questions"]
    layer = semantic_layer()
    settings = get_settings()
    scores: list[Score] = []
    with connect() as conn:
        bounds = data_bounds(conn)
        ctx = AskContext(
            as_of=date.fromisoformat(str(spec["as_of"])),
            first_day=bounds.first_day,
            revenue_through=bounds.last_complete_revenue_month,
        )
        agent: Any = (
            ClaudeAgent(layer, settings.qa_model, api_key=settings.anthropic_api_key)
            if planner == "claude" else RulePlanner(layer)
        )
        for item in items:
            answer = agent.ask(conn, item["question"], ctx)
            scores.append(score(item, answer))
    return scores


def main(planner: str = "rules", limit: int | None = None, verbose: bool = False) -> int:
    scores = run(planner, limit)
    passed = sum(s.passed for s in scores)
    for s in scores:
        if verbose or not s.passed:
            mark = "PASS" if s.passed else "FAIL"
            print(f"{mark} {s.id} {s.question}" + (f"\n     {s.reason}" if s.reason else ""))
    print(f"\n{planner}: {passed}/{len(scores)} passed ({passed / max(len(scores), 1):.0%})")
    return 0
