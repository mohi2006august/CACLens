"""FR-06 alert backtest: lead time to known regressions and the false-alarm rate.

The detector is replayed for every day of history (each day sees only data up to that
day, because every window ends on the evaluation day), then scored against the
incidents listed in `evals/alert_incidents.yml`:

- lead time: days from an incident's start to the first alert on that channel
- false alarms: alert episodes that match no incident, per channel-year evaluated

On your own data, `suggest_incidents` lists candidate regressions from history (months
where a paid channel's CAC or cost per qualified lead ran well above its recent norm) as
a starting point for labelling real incidents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import yaml

from api.analytics.alerts import Alert, AlertConfig, detect_alerts
from api.analytics.common import add_months, data_bounds
from api.config import REPO_ROOT
from api.semantic import MetricQuery, QueryFilter, SemanticLayer

INCIDENTS_PATH = REPO_ROOT / "evals" / "alert_incidents.yml"
# An alert this long after an incident ends still counts as catching it.
MATCH_GRACE = timedelta(days=30)


@dataclass(frozen=True)
class Incident:
    channel: str
    start: date
    end: date
    description: str = ""


@dataclass
class IncidentResult:
    incident: Incident
    first_alert_on: date | None
    lead_time_days: int | None
    first_by_metric: dict[str, date] = field(default_factory=dict)


@dataclass
class BacktestResult:
    incidents: list[IncidentResult]
    false_alarms: list[Alert]
    channel_years: float
    target_lead_time_days: int
    max_false_alarms_per_channel_year: float

    @property
    def false_alarm_rate(self) -> float:
        return len(self.false_alarms) / self.channel_years if self.channel_years else 0.0

    @property
    def passed(self) -> bool:
        lead_ok = all(
            r.lead_time_days is not None and r.lead_time_days < self.target_lead_time_days
            for r in self.incidents
        )
        return lead_ok and self.false_alarm_rate <= self.max_false_alarms_per_channel_year

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "target_lead_time_days": self.target_lead_time_days,
            "incidents": [
                {
                    "channel": r.incident.channel,
                    "start": r.incident.start.isoformat(),
                    "first_alert_on": r.first_alert_on.isoformat() if r.first_alert_on else None,
                    "lead_time_days": r.lead_time_days,
                    "first_by_metric": {m: d.isoformat() for m, d in r.first_by_metric.items()},
                }
                for r in self.incidents
            ],
            "false_alarms": [
                {"channel": a.channel, "metric": a.metric, "first_detected_on":
                 a.first_detected_on.isoformat(), "change_pct": a.change_pct}
                for a in self.false_alarms
            ],
            "false_alarms_per_channel_year": self.false_alarm_rate,
            "channel_years": self.channel_years,
        }


def load_spec(path: Path = INCIDENTS_PATH) -> tuple[date | None, list[Incident], int, float]:
    """`as_of` is optional: without it the backtest runs to the latest data."""
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    incidents = [
        Incident(i["channel"], date.fromisoformat(str(i["start"])),
                 date.fromisoformat(str(i["end"])), str(i.get("description") or "").strip())
        for i in spec.get("incidents") or []
    ]
    as_of = date.fromisoformat(str(spec["as_of"])) if spec.get("as_of") else None
    return (as_of, incidents, int(spec.get("target_lead_time_days", 3)),
            float(spec.get("max_false_alarms_per_channel_year", 1)))


def _matches(alert: Alert, incident: Incident) -> bool:
    return (alert.channel == incident.channel
            and incident.start <= alert.first_detected_on <= incident.end + MATCH_GRACE)


def backtest(layer: SemanticLayer, conn: duckdb.DuckDBPyConnection, cfg: AlertConfig,
             path: Path = INCIDENTS_PATH) -> BacktestResult:
    spec_as_of, incidents, target, max_fa = load_spec(path)
    bounds = data_bounds(conn)
    as_of = spec_as_of or bounds.last_day
    if as_of is None:
        raise ValueError("no data to backtest: build the warehouse first")
    first_day = bounds.first_day or as_of
    # Evaluate every day that has a full baseline behind it.
    warmup = timedelta(days=cfg.window_days + cfg.baseline_days)
    lookback = max(1, (as_of - (first_day + warmup)).days)
    cfg = AlertConfig(**{**cfg.__dict__, "lookback_days": lookback})
    alerts = detect_alerts(layer, conn, as_of, cfg)

    results = []
    for incident in incidents:
        hits = sorted((a for a in alerts if _matches(a, incident)),
                      key=lambda a: a.first_detected_on)
        by_metric: dict[str, date] = {}
        for a in hits:
            by_metric.setdefault(a.metric, a.first_detected_on)
        first = hits[0].first_detected_on if hits else None
        results.append(IncidentResult(
            incident, first, (first - incident.start).days if first else None, by_metric))
    false_alarms = [a for a in alerts if not any(_matches(a, i) for i in incidents)]
    channels = {a.channel for a in alerts} | {i.channel for i in incidents}
    paid_channels = max(len(channels), 3)
    return BacktestResult(results, false_alarms, paid_channels * lookback / 365, target, max_fa)


@dataclass(frozen=True)
class Candidate:
    channel: str
    start: date
    end: date
    metric: str
    change_pct: float


def suggest_incidents(layer: SemanticLayer, conn: duckdb.DuckDBPyConnection,
                      threshold: float = 0.3, min_customers: float = 5.0) -> list[Candidate]:
    """Months where a paid channel's CAC or cost per qualified lead ran `threshold`+ above
    the median of its previous three months. Consecutive months merge into one candidate.
    """
    result = layer.query(conn, MetricQuery(
        metrics=["cac", "cost_per_qualified_lead", "new_customers"],
        dimensions=["channel"], grain="month",
        filters=[QueryFilter(dimension="is_paid_channel", op="eq", value=True)],
    ))
    by_channel: dict[str, list[dict[str, Any]]] = {}
    for row in result.rows:
        by_channel.setdefault(row["channel"], []).append(row)
    candidates: list[Candidate] = []
    for channel, rows in sorted(by_channel.items()):
        rows.sort(key=lambda r: r["period"])
        flagged: list[tuple[date, str, float]] = []
        for i in range(3, len(rows)):
            if (rows[i]["new_customers"] or 0) < min_customers:
                continue
            for metric in ("cost_per_qualified_lead", "cac"):
                prior = sorted(r[metric] for r in rows[i - 3:i] if r[metric])
                value = rows[i][metric]
                if len(prior) == 3 and value and value >= prior[1] * (1 + threshold):
                    flagged.append((rows[i]["period"], metric, value / prior[1] - 1))
                    break
        for month, metric, change in flagged:
            last = candidates[-1] if candidates else None
            if last and last.channel == channel and month == add_months(last.end.replace(day=1), 1):
                candidates[-1] = Candidate(channel, last.start, add_months(month, 1)
                                           - timedelta(days=1), last.metric,
                                           max(last.change_pct, change))
            else:
                candidates.append(Candidate(channel, month, add_months(month, 1)
                                            - timedelta(days=1), metric, change))
    return candidates


def format_suggestions(candidates: list[Candidate]) -> str:
    lines = [
        "# Candidate incidents: months where a paid channel's CAC or cost per qualified lead",
        "# ran 30%+ above its prior 3-month median. Keep only the real regressions (budget",
        "# tests and seasonality are not incidents), set `start` to the day the cause began,",
        "# save as e.g. evals/alert_incidents.local.yml, then run:",
        "#   uv run caclens alerts-backtest --incidents evals/alert_incidents.local.yml",
        "target_lead_time_days: 3",
        "max_false_alarms_per_channel_year: 1",
        "incidents:" if candidates else "incidents: []",
    ]
    for c in candidates:
        label = "CAC" if c.metric == "cac" else "cost per qualified lead"
        lines += [
            f"  - channel: {c.channel}",
            f"    start: {c.start.isoformat()}",
            f"    end: {c.end.isoformat()}",
            f'    description: "candidate: {label} {c.change_pct:+.0%} vs prior 3-month median"',
        ]
    return "\n".join(lines)


def format_report(result: BacktestResult) -> str:
    lines = []
    for r in result.incidents:
        lead = f"{r.lead_time_days} days" if r.lead_time_days is not None else "missed"
        lines.append(f"{r.incident.channel} from {r.incident.start}: first alert "
                     f"{r.first_alert_on or '-'} (lead time {lead})")
        for metric, day in sorted(r.first_by_metric.items(), key=lambda kv: kv[1]):
            lines.append(f"    {metric:<28} {day}  (+{(day - r.incident.start).days} days)")
    lines.append(f"false alarms: {len(result.false_alarms)} over {result.channel_years:.1f} "
                 f"channel-years = {result.false_alarm_rate:.2f}/channel-year")
    for a in result.false_alarms:
        lines.append(f"    {a.channel} {a.metric} {a.first_detected_on} ({a.change_pct:+.0%})")
    lines.append(f"target: lead time < {result.target_lead_time_days} days, "
                 f"<= {result.max_false_alarms_per_channel_year:g} false alarms/channel-year "
                 f"-> {'PASS' if result.passed else 'FAIL'}")
    return "\n".join(lines)
