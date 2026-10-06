"""Incremental extract-load of configured sources into the raw schema with dlt."""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Iterator, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import dlt
import duckdb

from api.config import REPO_ROOT
from api.log import get_logger
from pipelines.schema import RAW_SCHEMA, RAW_TABLES, ensure_raw_tables
from pipelines.sources import SOURCES, SourceSpec, Window
from pipelines.sources.http import utc_now

log = get_logger(__name__)

ADS_LOOKBACK_DAYS = 30  # ad platforms restate recent spend/clicks
CRM_OVERLAP = timedelta(days=3)
BILLING_OVERLAP = timedelta(days=35)  # invoices can be paid weeks after creation
BATCH_SIZE = 1_000


def backfill_start() -> date:
    raw = os.environ.get("CACLENS_BACKFILL_START", "").strip()
    return date.fromisoformat(raw) if raw else date(2024, 1, 1)


def _max_value(conn: duckdb.DuckDBPyConnection, sql: str, params: list[Any]) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def compute_window(conn: duckdb.DuckDBPyConnection, spec: SourceSpec, today: date) -> Window:
    start_default = backfill_start()
    since_default = datetime.combine(start_default, datetime.min.time())
    if spec.group == "ads":
        last_day = _max_value(
            conn,
            f"select max(date_day) from {RAW_SCHEMA}.ad_spend_daily where source_system = ?",
            [spec.name],
        )
        start = max(start_default, last_day - timedelta(days=ADS_LOOKBACK_DAYS)) if last_day \
            else start_default
        return Window(start=start, end=today, since=since_default)

    table = spec.tables[0]
    has_source_col = "source_system" in RAW_TABLES[table].columns
    sql = f"select max(loaded_at) from {RAW_SCHEMA}.{table}"
    params: list[Any] = []
    if has_source_col:
        sql += " where source_system = ?"
        params.append(spec.name)
    last_loaded = _max_value(conn, sql, params)
    overlap = BILLING_OVERLAP if spec.group == "billing" else CRM_OVERLAP
    since = max(since_default, last_loaded - overlap) if last_loaded else since_default
    return Window(start=start_default, end=today, since=since)


def _hints(table: str) -> Any:
    spec = RAW_TABLES[table]
    return dlt.mark.make_hints(
        table_name=table,
        write_disposition="merge",
        primary_key=list(spec.primary_key),
        columns=spec.dlt_columns(),
    )


def _batched(spec: SourceSpec, window: Window) -> Iterator[Any]:
    """Group routed rows into per-table batches tagged with that table's hints."""
    hints = {table: _hints(table) for table in spec.tables}
    buffers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for table, row in spec.extract(window):
        buffers[table].append(row)
        if len(buffers[table]) >= BATCH_SIZE:
            yield dlt.mark.with_hints(buffers.pop(table), hints[table], create_table_variant=True)
    for table, rows in buffers.items():
        if rows:
            yield dlt.mark.with_hints(rows, hints[table], create_table_variant=True)


def run_source(spec: SourceSpec, warehouse_path: Path, today: date | None = None) -> dict[str, int]:
    today = today or utc_now().date()
    with duckdb.connect(str(warehouse_path)) as conn:
        ensure_raw_tables(conn)
        window = compute_window(conn, spec, today)
    log.info("source_load_started", source=spec.name, start=str(window.start),
             since=window.since.isoformat())

    resource = dlt.resource(_batched(spec, window), name=spec.name)
    pipeline = dlt.pipeline(
        pipeline_name=f"caclens_{spec.name}",
        destination=dlt.destinations.duckdb(str(warehouse_path)),
        dataset_name=RAW_SCHEMA,
        pipelines_dir=str(REPO_ROOT / "data" / ".dlt"),
    )
    pipeline.run(resource)
    trace = pipeline.last_trace
    counts: dict[str, int] = {}
    if trace and trace.last_normalize_info:
        counts = {
            table: int(n)
            for table, n in trace.last_normalize_info.row_counts.items()
            if not table.startswith("_dlt")
        }
    log.info("source_load_finished", source=spec.name, **counts)
    return counts


def configured_sources(names: Sequence[str] | None = None) -> list[SourceSpec]:
    selected = [SOURCES[n] for n in names] if names else list(SOURCES.values())
    return [spec for spec in selected if spec.is_configured()]


def load_sources(warehouse_path: Path, names: Sequence[str] | None = None) -> dict[str, dict[str, int]]:
    """Load every configured source (or the named subset). Unconfigured sources are skipped."""
    warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, int]] = {}
    specs = configured_sources(names)
    if not specs:
        log.warning("no_sources_configured", hint="set connector env vars or CACLENS_DEMO=true")
    for spec in specs:
        results[spec.name] = run_source(spec, warehouse_path)
    return results
