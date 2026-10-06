"""Read-only access to the published serving snapshot of the warehouse.

The pipeline builds into the warehouse file, and only after dbt tests pass does it
publish a snapshot to `data/serving/` (see pipelines/publish.py). The API reads that
snapshot, so a failed build pauses metric publishing instead of serving bad numbers,
and readers never hold a lock on the file the pipeline writes to.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from api.config import Settings, get_settings

CURRENT_POINTER = "CURRENT"


class WarehouseNotReady(RuntimeError):
    """No warehouse has been built yet."""


def serving_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    pointer = settings.serving_dir / CURRENT_POINTER
    if pointer.exists():
        snapshot = settings.serving_dir / pointer.read_text(encoding="utf-8").strip()
        if snapshot.exists():
            return snapshot
    # Development fallback: read the build warehouse directly.
    return settings.warehouse_path


@contextmanager
def connect(settings: Settings | None = None) -> Iterator[duckdb.DuckDBPyConnection]:
    path = serving_path(settings)
    if not path.exists():
        raise WarehouseNotReady(
            "No warehouse found. Run `uv run caclens refresh` (or materialize the Dagster job)."
        )
    conn = duckdb.connect(str(path), read_only=True)
    try:
        yield conn
    finally:
        conn.close()


def table_exists(conn: duckdb.DuckDBPyConnection, schema: str, table: str) -> bool:
    row = conn.execute(
        "select count(*) from information_schema.tables where table_schema = ? and table_name = ?",
        [schema, table],
    ).fetchone()
    return bool(row and row[0])
