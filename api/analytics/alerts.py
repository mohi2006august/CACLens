"""FR-06 CAC spike detection with driver decomposition.

Every day, each paid channel's CAC over a trailing window (default 14 days) is
compared with the window before it (default 56 days). A day is flagged when CAC rose
beyond the threshold *and* the drop in customers per dollar is statistically
significant: under the baseline rate, seeing this few customers for the current spend
must have a one-sided Poisson p-value below `max_p_value`. Consecutive flagged days
form one alert episode, explained by the CPC x CVR decomposition at its peak.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

import duckdb

from api.analytics.decomposition import Funnel, decompose
from api.log import get_logger
from api.semantic import MetricQuery, QueryFilter, SemanticLayer

log = get_logger(__name__)

FUNNEL_METRICS = ["paid_spend", "fully_loaded_spend", "clicks", "leads", "new_customers"]


@dataclass(frozen=True)
class AlertConfig:
    window_days: int = 14
    baseline_days: int = 56
    threshold_pct: float = 0.30
    min_customers: float = 5.0
    max_p_value: float = 0.01
    lookback_days: int = 365
    merge_gap_days: int = 3
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
    current_customers: float
    baseline_customers: float
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
        self.prefix: list[Funnel] = [Funnel(0, 0, 0, 0, 0)] * (days + 1)
        self.daily: list[Funnel] = [Funnel(0, 0, 0, 0, 0)] * days

    def set(self, day: date, funnel: Funnel) -> None:
        self.daily[(day - self.start).days] = funnel

    def finalize(self) -> None:
        running = Funnel(0, 0, 0, 0, 0)
        for i, funnel in enumerate(self.daily):
            running = running + funnel
            self.prefix[i + 1] = running

    def window(self, first: date, last: date) -> Funnel:
        i = max(0, (first - self.start).days)
        j = (last - self.start).days + 1
        if j <= i:
            return Funnel(0, 0, 0, 0, 0)
        a, b = self.prefix[i], self.prefix[j]
        return Funnel(
            b.paid_spend - a.paid_spend,
            b.fully_loaded_spend - a.fully_loaded_spend,
            b.clicks - a.clicks,
            b.leads - a.leads,
            b.new_customers - a.new_customers,
        )


def _load_series(
    layer: SemanticLayer, conn: duckdb.DuckDBPyConnection, start: date, end: date,
    cfg: AlertConfig,
) -> dict[str, _Series]:
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
        s = series.setdefault(row["channel"], _Series(start, days))
        s.set(row["period"], Funnel.from_row(row))
    for s in series.values():
        s.finalize()
    return series


def detect_alerts(
    layer: SemanticLayer, conn: duckdb.DuckDBPyConnection, as_of: date, cfg: AlertConfig
) -> list[Alert]:
    first_eval = as_of - timedelta(days=cfg.lookback_days)
    start = first_eval - timedelta(days=cfg.window_days + cfg.baseline_days)
    series = _load_series(layer, conn, start, as_of, cfg)
    metric = "cac_fully_loaded" if cfg.fully_loaded else "cac"
    alerts: list[Alert] = []

    for channel, s in sorted(series.items()):
        flagged: list[tuple[date, float, Funnel, Funnel]] = []
        day = first_eval
        while day <= as_of:
            cur_first = day - timedelta(days=cfg.window_days - 1)
            base_last = cur_first - timedelta(days=1)
            base_first = base_last - timedelta(days=cfg.baseline_days - 1)
            cur, base = s.window(cur_first, day), s.window(base_first, base_last)
            # Compare customers on a per-day basis so window lengths can differ.
            enough = (
                cur.new_customers >= cfg.min_customers
                and base.new_customers * cfg.window_days / cfg.baseline_days >= cfg.min_customers
            )
            cac_cur, cac_base = cur.cac(cfg.fully_loaded), base.cac(cfg.fully_loaded)
            if enough and cac_cur and cac_base:
                change = cac_cur / cac_base - 1
                spend_cur = cur.fully_loaded_spend if cfg.fully_loaded else cur.paid_spend
                expected = spend_cur / cac_base
                if (
                    change >= cfg.threshold_pct
                    and poisson_cdf(cur.new_customers, expected) < cfg.max_p_value
                ):
                    flagged.append((day, change, cur, base))
            day += timedelta(days=1)

        for episode in _episodes(flagged, cfg.merge_gap_days):
            peak_day, peak_change, cur, base = max(episode, key=lambda e: e[1])
            label = channel.replace("_", " ").title()
            dec = decompose(base, cur, cfg.fully_loaded, subject=f"{label} CAC")
            last_day = episode[-1][0]
            alerts.append(
                Alert(
                    id=f"{metric}:{channel}:{episode[0][0].isoformat()}",
                    channel=channel,
                    metric=metric,
                    severity="critical" if peak_change >= 2 * cfg.threshold_pct else "warning",
                    status="open" if last_day >= as_of - timedelta(days=1) else "resolved",
                    first_detected_on=episode[0][0],
                    last_detected_on=last_day,
                    peak_on=peak_day,
                    window_start=peak_day - timedelta(days=cfg.window_days - 1),
                    window_end=peak_day,
                    current_value=cur.cac(cfg.fully_loaded) or 0.0,
                    baseline_value=base.cac(cfg.fully_loaded) or 0.0,
                    change_pct=peak_change,
                    current_customers=cur.new_customers,
                    baseline_customers=base.new_customers,
                    summary=dec.summary,
                    drivers=[asdict(d) for d in dec.drivers],
                )
            )
    alerts.sort(key=lambda a: a.first_detected_on, reverse=True)
    log.info("alerts_detected", as_of=as_of.isoformat(), count=len(alerts))
    return alerts


def poisson_cdf(observed: float, expected: float) -> float:
    """P(X <= observed) for X ~ Poisson(expected); fractional credits are floored."""
    k = math.floor(observed)
    if expected <= 0:
        return 1.0
    term = total = math.exp(-expected)
    for i in range(1, k + 1):
        term *= expected / i
        total += term
    return min(1.0, total)


def _episodes(
    flagged: list[tuple[date, float, Funnel, Funnel]], gap: int
) -> list[list[tuple[date, float, Funnel, Funnel]]]:
    episodes: list[list[tuple[date, float, Funnel, Funnel]]] = []
    for item in flagged:
        if episodes and (item[0] - episodes[-1][-1][0]).days <= gap:
            episodes[-1].append(item)
        else:
            episodes.append([item])
    return episodes


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
    current_customers double,
    baseline_customers double,
    summary varchar,
    drivers varchar
)
"""


def save_alerts(conn: duckdb.DuckDBPyConnection, alerts: list[Alert]) -> None:
    conn.execute("create schema if not exists app")
    conn.execute(ALERTS_DDL)
    for a in alerts:
        conn.execute(
            "insert into app.alerts values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                a.id, a.channel, a.metric, a.severity, a.status, a.first_detected_on,
                a.last_detected_on, a.peak_on, a.window_start, a.window_end, a.current_value,
                a.baseline_value, a.change_pct, a.current_customers, a.baseline_customers,
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
