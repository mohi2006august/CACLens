"""End-to-end refresh: load raw -> dbt build -> alerts -> publish serving snapshot.

Dagster runs the same steps as assets (pipelines/definitions.py); this module backs
the `caclens refresh` CLI for running without the Dagster UI.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import duckdb

from api.analytics.alerts import AlertConfig, detect_alerts, save_alerts
from api.analytics.common import data_bounds
from api.config import REPO_ROOT, Settings, get_settings
from api.log import get_logger
from api.semantic import load_semantic_layer
from pipelines.demo import load_demo
from pipelines.load import load_sources
from pipelines.publish import publish_snapshot

log = get_logger(__name__)


class DbtBuildFailed(RuntimeError):
    """dbt models or tests failed; metrics are not published."""


def alert_config(settings: Settings) -> AlertConfig:
    return AlertConfig(
        window_days=settings.alert_window_days,
        baseline_days=settings.alert_baseline_days,
        threshold_pct=settings.alert_threshold_pct,
        min_customers=float(settings.alert_min_customers),
    )


def load_raw(settings: Settings, demo: bool | None = None, scale: float = 1.0,
             seed: int = 42) -> dict[str, object]:
    use_demo = settings.demo if demo is None else demo
    if use_demo:
        return {"demo": load_demo(settings.warehouse_path, scale=scale, seed=seed)}
    return dict(load_sources(settings.warehouse_path))


def run_dbt(settings: Settings, args: Sequence[str] = ("build",)) -> None:
    from dbt.cli.main import dbtRunner  # imported lazily: dbt is slow to import

    os.environ["WAREHOUSE_URL"] = str(settings.warehouse_path)
    cli_args = [*args, "--project-dir", str(REPO_ROOT), "--profiles-dir", str(REPO_ROOT)]
    result = dbtRunner().invoke(cli_args)
    if not result.success:
        log.error("dbt_failed", args=list(args), error=str(result.exception or ""))
        raise DbtBuildFailed(f"dbt {' '.join(args)} failed; metric publishing paused")
    log.info("dbt_succeeded", args=list(args))


def compute_alerts(settings: Settings, as_of: date | None = None) -> int:
    layer = load_semantic_layer(settings.semantic_path)
    with duckdb.connect(str(settings.warehouse_path)) as conn:
        as_of = as_of or data_bounds(conn).last_day
        if as_of is None:
            return 0
        alerts = detect_alerts(layer, conn, as_of, alert_config(settings))
        save_alerts(conn, alerts)
    return len(alerts)


def publish(settings: Settings) -> Path:
    return publish_snapshot(settings.warehouse_path, settings.serving_dir)


def refresh(demo: bool | None = None, scale: float = 1.0, seed: int = 42,
            settings: Settings | None = None) -> dict[str, object]:
    settings = settings or get_settings()
    loaded = load_raw(settings, demo, scale, seed)
    run_dbt(settings)
    n_alerts = compute_alerts(settings)
    snapshot = publish(settings)
    summary = {"loaded": loaded, "alerts": n_alerts, "snapshot": snapshot.name}
    log.info("refresh_finished", alerts=n_alerts, snapshot=snapshot.name)
    return summary
