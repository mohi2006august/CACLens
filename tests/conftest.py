from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from api.config import REPO_ROOT, get_settings
from api.semantic import SemanticLayer, _literal, load_semantic_layer

ACQ_COLUMNS = {
    "date_day": "DATE", "cohort_month": "DATE", "channel": "VARCHAR", "campaign": "VARCHAR",
    "segment": "VARCHAR", "is_paid_channel": "BOOLEAN", "attribution_model": "VARCHAR",
    "paid_spend": "DOUBLE", "people_cost": "DOUBLE", "tool_cost": "DOUBLE",
    "fully_loaded_spend": "DOUBLE", "impressions": "DOUBLE", "clicks": "DOUBLE",
    "leads": "DOUBLE", "opportunities": "DOUBLE", "new_customers": "DOUBLE",
}
REV_COLUMNS = {
    "revenue_month": "DATE", "cohort_month": "DATE", "months_since_acquisition": "BIGINT",
    "channel": "VARCHAR", "campaign": "VARCHAR", "segment": "VARCHAR",
    "is_paid_channel": "BOOLEAN", "attribution_model": "VARCHAR", "cohort_customers": "DOUBLE",
    "active_customers": "DOUBLE", "starting_customers": "DOUBLE", "churned_customers": "DOUBLE",
    "gross_revenue": "DOUBLE", "refunds_and_chargebacks": "DOUBLE", "net_revenue": "DOUBLE",
    "gross_margin_revenue": "DOUBLE",
}


@pytest.fixture(scope="session")
def layer() -> SemanticLayer:
    return load_semantic_layer(REPO_ROOT / "semantic" / "metrics.yml")


def acq_row(day: date, channel: str = "meta_ads", **values: Any) -> dict[str, Any]:
    row: dict[str, Any] = {c: 0.0 for c, t in ACQ_COLUMNS.items() if t == "DOUBLE"}
    row.update(
        date_day=day, cohort_month=day.replace(day=1), channel=channel, campaign="(none)",
        segment="smb", is_paid_channel=channel in {"meta_ads", "google_search", "linkedin_ads"},
        attribution_model="position_based",
    )
    row.update(values)
    row["fully_loaded_spend"] = row["paid_spend"] + row["people_cost"] + row["tool_cost"]
    return row


def rev_row(month: date, **values: Any) -> dict[str, Any]:
    row: dict[str, Any] = {c: 0.0 for c, t in REV_COLUMNS.items() if t == "DOUBLE"}
    row.update(
        revenue_month=month, cohort_month=month, months_since_acquisition=0, channel="meta_ads",
        campaign="(none)", segment="smb", is_paid_channel=True, attribution_model="position_based",
    )
    row.update(values)
    return row


def make_marts(acq: list[dict[str, Any]], rev: list[dict[str, Any]] | None = None
               ) -> duckdb.DuckDBPyConnection:
    """In-memory warehouse with the two marts the semantic layer reads."""
    conn = duckdb.connect(":memory:")
    conn.execute("create schema marts")
    for table, columns, rows in (
        ("fct_acquisition_daily", ACQ_COLUMNS, acq),
        ("fct_customer_revenue_monthly", REV_COLUMNS, rev or []),
    ):
        conn.execute(f"create table marts.{table} ({', '.join(f'{c} {t}' for c, t in columns.items())})")
        # Literal VALUES (test data only): DuckDB probes for pandas on every bound
        # parameter, which makes thousands of parameters very slow.
        for i in range(0, len(rows), 500):
            values = ", ".join(
                "(" + ", ".join("null" if r[c] is None else _literal(r[c]) for c in columns) + ")"
                for r in rows[i:i + 500]
            )
            conn.execute(f"insert into marts.{table} values {values}")
    return conn


def daterange(start: date, days: int) -> Iterator[date]:
    for i in range(days):
        yield start + timedelta(days=i)


@pytest.fixture(scope="session")
def built_warehouse(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Synthetic data -> dbt build -> alerts -> published snapshot, in a temp dir."""
    from pipelines.refresh import refresh

    root = tmp_path_factory.mktemp("warehouse")
    mp = pytest.MonkeyPatch()
    mp.setenv("WAREHOUSE_URL", str(root / "caclens.duckdb"))
    mp.setenv("CACLENS_SERVING_DIR", str(root / "serving"))
    mp.setenv("CACLENS_QA_PLANNER", "rules")
    get_settings.cache_clear()
    refresh(demo=True, scale=0.6)
    yield root
    mp.undo()
    get_settings.cache_clear()
