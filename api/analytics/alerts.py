"""FR-06 CAC spike detection with driver decomposition.

Every day, each paid channel's cost per outcome over a trailing window is compared with
the window before it. Two outcomes are watched:

- `cost_per_qualified_lead` (3-day window vs the 28 days before): qualified leads are
  known at form fill, so a lead-quality or CPC regression shows the day it starts. This
  is the early warning that keeps alert lead time under 3 days.
- `cac` (14 days vs 56, p < 0.001, 3 flagged days): a strict backstop for large,
  sustained regressions that lead quality cannot show (e.g. a sales-side conversion
  collapse). Customers lag leads by the sales cycle and are few per window, so at
  small-channel volumes it rarely confirms in time; the early warning does the work.

(Cost per opportunity was watched too, but it caught regressions ~10 days after the
qualified-lead alert and caused most false alarms; see `uv run caclens alerts-backtest`
and BRAIN.md.)

A day is flagged when the cost rose beyond the threshold *and* the drop in outcomes per
dollar is statistically significant. Outcomes are over-dispersed (budgets, weekdays and
outcomes landing in a different week from their spend move them more than Poisson
noise), so the test is negative binomial, with the dispersion measured on same-length
windows over the prior half year. Consecutive flagged days form one episode, explained
by the CPC x CVR decomposition at its peak; CAC must stay flagged for 3 days before it
alerts. An alert stays open until the cost recovers against the baseline it fired on.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

import duckdb

from api.analytics.decomposition import Funnel, Outcome, decompose
from api.log import get_logger
from api.semantic import MetricQuery, QueryFilter, SemanticLayer

log = get_logger(__name__)

FUNNEL_METRICS = ["paid_spend", "fully_loaded_spend", "clicks", "leads", "qualified_leads",
                  "opportunities", "new_customers"]
MAX_DISPERSION = 10.0
DISPERSION_LOOKBACK_DAYS = 182


@dataclass(frozen=True)
class WatchedMetric:
    name: str
    fully_loaded_name: str
    label: str
    outcome: Outcome
    # An episode must reach this many flagged days before it alerts. Slow metrics ask for
    # persistence: a daily scan of overlapping windows crosses any p-value now and then.
    min_flagged_days: int = 1
    # Overrides of the config defaults for this metric (None = use the config).
    window_days: int | None = None
    baseline_days: int | None = None
    max_p_value: float | None = None


WATCHED = (
    WatchedMetric("cost_per_qualified_lead", "cost_per_qualified_lead",
                  "cost per qualified lead", "qualified_leads",
                  window_days=3, baseline_days=28, max_p_value=0.001),
    WatchedMetric("cac", "cac_fully_loaded", "CAC", "new_customers", min_flagged_days=3,
                  max_p_value=0.001),
)


@dataclass(frozen=True)
class AlertConfig:
    window_days: int = 14
    baseline_days: int = 56
    threshold_pct: float = 0.30
    min_customers: float = 5.0
    max_p_value: float = 0.01
    lookback_days: int = 365
    merge_gap_days: int = 7
    fully_loaded: bool = False
    attribution_model: str = "position_based"


@dataclass
class Alert:
    id: str
    channel: str
    metric: str
    severity: str
    status: str
    first_detected_on: date
    last_detected_on: date
    peak_on: date
    window_start: date
    window_end: date
    current_value: float
    baseline_value: float
    change_pct: float
    current_count: float
    baseline_count: float
    p_value: float
    summary: str
    drivers: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        for key in ("first_detected_on", "last_detected_on", "peak_on", "window_start",
                    "window_end"):
            out[key] = out[key].isoformat()
        return out


class _Series:
    """Prefix sums of a channel's daily funnel for O(1) window totals."""

    def __init__(self, start: date, days: int) -> None:
        self.start = start
        self.daily: list[Funnel] = [Funnel.zero()] * days
        self.prefix: list[Funnel] = [Funnel.zero()] * (days + 1)

    def set(self, day: date, funnel: Funnel) -> None:
        self.daily[(day - self.start).days] = funnel

    def finalize(self) -> None:
        running = Funnel.zero()
        for i, funnel in enumerate(self.daily):
            running = running + funnel
            self.prefix[i + 1] = running

    def window(self, first: date, last: date) -> Funnel:
        i = max(0, (first - self.start).days)
        j = (last - self.start).days + 1
        return self.prefix[j] - self.prefix[i] if j > i else Funnel.zero()


def poisson_cdf(observed: float, expected: float) -> float:
    """P(X <= observed) for X ~ Poisson(expected); fractional credits are floored."""
    if expected <= 0:
        return 1.0
    k = math.floor(observed)
    term = total = math.exp(-expected)
    for i in range(1, k + 1):
        term *= expected / i
        total += term
    return min(1.0, total)


def nb_cdf(observed: float, expected: float, dispersion: float) -> float:
    """P(X <= observed) for a negative binomial with this mean and variance mean x dispersion.

    Dispersion 1 is Poisson; larger values widen the distribution, so the same drop is
    less surprising when the series is naturally noisy.
    """
    if dispersion <= 1.0001:
        return poisson_cdf(observed, expected)
    if expected <= 0:
        return 1.0
    r = expected / (dispersion - 1)  # NB "size"
    p = 1 / dispersion  # success probability
    k = math.floor(observed)
    term = math.exp(r * math.log(p))  # P(X = 0)
    total = term
    for i in range(1, k + 1):
        term *= (i - 1 + r) / i * (1 - p)
        total += term
    return min(1.0, total)


def dispersion(s: _Series, outcome: Outcome, window: int, last: date, fully_loaded: bool,
               lookback_days: int = DISPERSION_LOOKBACK_DAYS) -> float:
    """Pearson dispersion of rolling `window`-day outcome totals around spend x rate (>= 1).

    Measured on windows of the same length as the test (not single days) over the prior
    half year, so it captures what makes window totals noisy: weekday mix, budget changes
    and outcomes that land in a different week from the spend that bought them.
    """
    first = max(s.start, last - timedelta(days=lookback_days - 1))
    total = s.window(first, last)
    spend, count = total.spend(fully_loaded), total.outcome(outcome)
    if spend <= 0 or count <= 0:
        return 1.0
    rate = count / spend
    chi2, n = 0.0, 0
    end = first + timedelta(days=window - 1)
    while end <= last:
        w = s.window(end - timedelta(days=window - 1), end)
        expected = w.spend(fully_loaded) * rate
        if expected > 0:
            chi2 += (w.outcome(outcome) - expected) ** 2 / expected
            n += 1
        end += timedelta(days=1)
    if n < 2:
        return 1.0
    return min(MAX_DISPERSION, max(1.0, chi2 / n))


def _load_series(layer: SemanticLayer, conn: duckdb.DuckDBPyConnection, start: date,
                 end: date, cfg: AlertConfig) -> dict[str, _Series]:
    result = layer.query(
        conn,
        MetricQuery(
            metrics=FUNNEL_METRICS,
            dimensions=["channel"],
            grain="day",
            start=start,
            end=end,
            filters=[QueryFilter(dimension="is_paid_channel", op="eq", value=True)],
            attribution_model=cfg.attribution_model,
        ),
    )
    days = (end - start).days + 1
    series: dict[str, _Series] = {}
    for row in result.rows:
        series.setdefault(row["channel"], _Series(start, days)).set(
            row["period"], Funnel.from_row(row)
        )
    for s in series.values():
        s.finalize()
    return series


Flag = tuple[date, float, float, Funnel, Funnel]


def _windows(watched: WatchedMetric, cfg: AlertConfig) -> tuple[int, int, float]:
    return (watched.window_days or cfg.window_days,
            watched.baseline_days or cfg.baseline_days,
            watched.max_p_value if watched.max_p_value is not None else cfg.max_p_value)


def _scan(s: _Series, watched: WatchedMetric, first_eval: date, as_of: date,
          cfg: AlertConfig) -> list[Flag]:
    window, baseline, max_p = _windows(watched, cfg)
    flagged: list[Flag] = []
    day = first_eval
    while day <= as_of:
        cur_first = day - timedelta(days=window - 1)
        base_last = cur_first - timedelta(days=1)
        base_first = base_last - timedelta(days=baseline - 1)
        cur, base = s.window(cur_first, day), s.window(base_first, base_last)
        n_cur, n_base = cur.outcome(watched.outcome), base.outcome(watched.outcome)
        # Compare counts on a per-day basis so window lengths can differ.
        enough = (n_cur >= cfg.min_customers
                  and n_base * window / baseline >= cfg.min_customers)
        cost_cur = cur.cost_per(watched.outcome, cfg.fully_loaded)
        cost_base = base.cost_per(watched.outcome, cfg.fully_loaded)
        if enough and cost_cur and cost_base:
            change = cost_cur / cost_base - 1
            if change >= cfg.threshold_pct:
                phi = dispersion(s, watched.outcome, window, base_last, cfg.fully_loaded)
                p_value = nb_cdf(n_cur, cur.spend(cfg.fully_loaded) / cost_base, phi)
                if p_value < max_p:
                    flagged.append((day, change, p_value, cur, base))
        day += timedelta(days=1)
    return flagged


def _still_elevated(s: _Series, watched: WatchedMetric, reference: Funnel, as_of: date,
                    cfg: AlertConfig) -> bool:
    """Open until the cost recovers against the baseline from when the alert fired.

    A short trailing baseline absorbs a lasting regression within weeks, so "no longer
    flagged" must not be read as "fixed".
    """
    window = _windows(watched, cfg)[0]
    now = s.window(as_of - timedelta(days=window - 1), as_of).cost_per(
        watched.outcome, cfg.fully_loaded)
    before = reference.cost_per(watched.outcome, cfg.fully_loaded)
    return bool(now and before and now >= before * (1 + cfg.threshold_pct))


def _episodes(flagged: list[Flag], gap: int) -> list[list[Flag]]:
    episodes: list[list[Flag]] = []
    for item in flagged:
        if episodes and (item[0] - episodes[-1][-1][0]).days <= gap:
            episodes[-1].append(item)
        else:
            episodes.append([item])
    return episodes


def detect_alerts(layer: SemanticLayer, conn: duckdb.DuckDBPyConnection, as_of: date,
                  cfg: AlertConfig) -> list[Alert]:
    first_eval = as_of - timedelta(days=cfg.lookback_days)
    span = max(sum(_windows(w, cfg)[:2]) for w in WATCHED)
    start = first_eval - timedelta(days=span)
    series = _load_series(layer, conn, start, as_of, cfg)
    alerts: list[Alert] = []
    for channel, s in sorted(series.items()):
        label = channel.replace("_", " ").title()
        for watched in WATCHED:
            metric = watched.fully_loaded_name if cfg.fully_loaded else watched.name
            episodes = [e for e in _episodes(_scan(s, watched, first_eval, as_of, cfg),
                                             cfg.merge_gap_days)
                        if len(e) >= watched.min_flagged_days]
            for index, episode in enumerate(episodes):
                # Raised on the day the episode became persistent enough to alert.
                raised_on = episode[watched.min_flagged_days - 1][0]
                peak_day, peak_change, p_value, cur, base = max(episode, key=lambda e: e[1])
                dec = decompose(base, cur, cfg.fully_loaded, f"{label} {watched.label}",
                                watched.outcome)
                last_day = episode[-1][0]
                is_latest = index == len(episodes) - 1
                reference = episode[watched.min_flagged_days - 1][4]
                open_ = is_latest and _still_elevated(s, watched, reference, as_of, cfg)
                alerts.append(
                    Alert(
                        id=f"{metric}:{channel}:{raised_on.isoformat()}",
                        channel=channel,
                        metric=metric,
                        severity="critical" if peak_change >= 2 * cfg.threshold_pct
                        else "warning",
                        status="open" if open_ else "resolved",
                        first_detected_on=raised_on,
                        last_detected_on=last_day,
                        peak_on=peak_day,
                        window_start=peak_day - timedelta(days=_windows(watched, cfg)[0] - 1),
                        window_end=peak_day,
                        current_value=cur.cost_per(watched.outcome, cfg.fully_loaded) or 0.0,
                        baseline_value=base.cost_per(watched.outcome, cfg.fully_loaded) or 0.0,
                        change_pct=peak_change,
                        current_count=cur.outcome(watched.outcome),
                        baseline_count=base.outcome(watched.outcome),
                        p_value=p_value,
                        summary=dec.summary,
                        drivers=[asdict(d) for d in dec.drivers],
                    )
                )
    alerts.sort(key=lambda a: a.first_detected_on, reverse=True)
    log.info("alerts_detected", as_of=as_of.isoformat(), count=len(alerts))
    return alerts


ALERTS_DDL = """
create or replace table app.alerts (
    id varchar primary key,
    channel varchar,
    metric varchar,
    severity varchar,
    status varchar,
    first_detected_on date,
    last_detected_on date,
    peak_on date,
    window_start date,
    window_end date,
    current_value double,
    baseline_value double,
    change_pct double,
    current_count double,
    baseline_count double,
    p_value double,
    summary varchar,
    drivers varchar
)
"""


def save_alerts(conn: duckdb.DuckDBPyConnection, alerts: list[Alert]) -> None:
    conn.execute("create schema if not exists app")
    conn.execute(ALERTS_DDL)
    for a in alerts:
        conn.execute(
            "insert into app.alerts values "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                a.id, a.channel, a.metric, a.severity, a.status, a.first_detected_on,
                a.last_detected_on, a.peak_on, a.window_start, a.window_end, a.current_value,
                a.baseline_value, a.change_pct, a.current_count, a.baseline_count, a.p_value,
                a.summary, json.dumps(a.drivers),
            ],
        )


def read_alerts(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    cursor = conn.execute("select * from app.alerts order by first_detected_on desc")
    names = [d[0] for d in cursor.description]
    out: list[dict[str, Any]] = []
    for row in cursor.fetchall():
        item = dict(zip(names, row, strict=True))
        item["drivers"] = json.loads(item["drivers"] or "[]")
        for key, value in item.items():
            if isinstance(value, date):
                item[key] = value.isoformat()
        out.append(item)
    return out
