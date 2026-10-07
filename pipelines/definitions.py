"""Dagster definitions: `dagster dev` from the repo root loads this module.

Lineage: raw tables (dlt connectors or the demo generator) -> dbt models (with dbt
tests as asset checks) -> CAC alerts -> serving snapshot. The daily schedule
satisfies the PRD's daily refresh; a failing dbt test stops the run before the
snapshot is published, so the API keeps serving the last good numbers.
"""

# No `from __future__ import annotations`: Dagster inspects the context type hints.

from collections.abc import Iterator
from typing import Any

import dagster as dg
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets

from api.config import REPO_ROOT, get_settings
from pipelines.refresh import compute_alerts, load_raw, publish
from pipelines.schema import RAW_SCHEMA, RAW_TABLES

dbt_project = DbtProject(project_dir=REPO_ROOT, profiles_dir=REPO_ROOT)
dbt_project.prepare_if_dev()
if not dbt_project.manifest_path.exists():  # first run outside `dagster dev`
    dbt_project.preparer.prepare(dbt_project)

RAW_GROUPS = {
    "ad_spend_daily": "ads",
    "crm_contacts": "crm",
    "crm_touchpoints": "crm",
    "crm_deals": "crm",
    "stripe_customers": "billing",
    "stripe_invoices": "billing",
    "stripe_refunds": "billing",
    "stripe_disputes": "billing",
    "payroll_costs": "costs",
    "tool_costs": "costs",
}


@dg.multi_asset(
    specs=[
        dg.AssetSpec(
            key=dg.AssetKey([RAW_SCHEMA, name]),
            description=table.description,
            group_name="raw",
            kinds={"duckdb", "dlt"},
            tags={"source_group": RAW_GROUPS[name]},
        )
        for name, table in RAW_TABLES.items()
    ],
    can_subset=False,
)
def raw_tables(context: dg.AssetExecutionContext) -> Iterator[dg.MaterializeResult]:
    """FR-01 load every configured connector (or the synthetic dataset in demo mode)."""
    settings = get_settings()
    loaded: dict[str, Any] = load_raw(settings)
    counts: dict[str, int] = {}
    for result in loaded.values():
        if isinstance(result, dict):
            for table, n in result.items():
                if isinstance(n, int):
                    counts[table] = counts.get(table, 0) + n
    context.log.info(f"loaded {counts} (demo={settings.demo})")
    for name in RAW_TABLES:
        yield dg.MaterializeResult(
            asset_key=dg.AssetKey([RAW_SCHEMA, name]),
            metadata={"rows_loaded": counts.get(name, 0), "demo": settings.demo},
        )


@dbt_assets(manifest=dbt_project.manifest_path, project=dbt_project)
def caclens_dbt_models(context: dg.AssetExecutionContext, dbt: DbtCliResource) -> Iterator[Any]:
    """FR-02..FR-05 journeys, attribution, costs, cohorts and marts, plus their tests."""
    yield from dbt.cli(["build"], context=context).stream()


@dg.asset(
    deps=[dg.AssetKey(["marts", "fct_acquisition_daily"])],
    group_name="serving",
    kinds={"python"},
    description="FR-06 CAC and cost-per-opportunity spike detection with driver decomposition.",
)
def cac_alerts(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    n = compute_alerts(get_settings())
    context.log.info(f"{n} alert episodes")
    return dg.MaterializeResult(metadata={"alert_episodes": n})


@dg.asset(
    deps=[cac_alerts, dg.AssetKey(["marts", "fct_customer_revenue_monthly"]),
          dg.AssetKey(["marts", "customer_journeys"])],
    group_name="serving",
    kinds={"duckdb"},
    description="Read-only snapshot the API serves; only published after dbt tests pass.",
)
def serving_snapshot(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    snapshot = publish(get_settings())
    context.log.info(f"published {snapshot.name}")
    return dg.MaterializeResult(metadata={"snapshot": snapshot.name})


daily_refresh = dg.define_asset_job("daily_refresh", selection=dg.AssetSelection.all())

defs = dg.Definitions(
    assets=[raw_tables, caclens_dbt_models, cac_alerts, serving_snapshot],
    jobs=[daily_refresh],
    schedules=[
        dg.ScheduleDefinition(job=daily_refresh, cron_schedule="0 6 * * *",
                              execution_timezone="UTC",
                              default_status=dg.DefaultScheduleStatus.RUNNING)
    ],
    resources={"dbt": DbtCliResource(project_dir=dbt_project)},
)
