"""Publish a serving snapshot of the marts once a build has passed its tests.

Snapshots are versioned files plus a CURRENT pointer, so the API can keep reading the
previous snapshot while a new one is written (and on Windows, where an open file
cannot be replaced).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb

from api.log import get_logger
from api.warehouse import CURRENT_POINTER

log = get_logger(__name__)

SERVING_SCHEMAS = ("marts", "app")
KEEP_SNAPSHOTS = 3


def publish_snapshot(warehouse_path: Path, serving_dir: Path) -> Path:
    serving_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    target = serving_dir / f"caclens_{stamp}.duckdb"
    # Same (read-write) configuration as the in-process dbt connection; we only read.
    with duckdb.connect(str(warehouse_path)) as conn:
        conn.execute(f"attach '{target.as_posix()}' as serving")
        tables = conn.execute(
            "select table_schema, table_name from information_schema.tables "
            "where table_catalog = current_database() and table_type = 'BASE TABLE' "
            f"and table_schema in ({', '.join('?' for _ in SERVING_SCHEMAS)})",
            list(SERVING_SCHEMAS),
        ).fetchall()
        for schema in {s for s, _ in tables}:
            conn.execute(f"create schema if not exists serving.{schema}")
        for schema, table in tables:
            conn.execute(
                f'create table serving.{schema}."{table}" as select * from {schema}."{table}"'
            )
        conn.execute("detach serving")

    pointer = serving_dir / CURRENT_POINTER
    tmp_pointer = serving_dir / f"{CURRENT_POINTER}.tmp"
    tmp_pointer.write_text(target.name, encoding="utf-8")
    tmp_pointer.replace(pointer)
    log.info("snapshot_published", snapshot=target.name, tables=len(tables))
    _prune(serving_dir, keep=target.name)
    return target


def _prune(serving_dir: Path, keep: str) -> None:
    snapshots = sorted(serving_dir.glob("caclens_*.duckdb"), reverse=True)
    for old in snapshots[KEEP_SNAPSHOTS:]:
        if old.name == keep:
            continue
        try:
            old.unlink()
        except OSError as exc:  # still open by a reader; retry on the next publish
            log.warning("snapshot_prune_skipped", snapshot=old.name, error=str(exc))
