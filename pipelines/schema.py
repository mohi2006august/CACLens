"""Raw-layer contract shared by every loader (dlt sources and the demo generator).

dbt sources (`dbt/models/staging/sources.yml`) read exactly these tables and columns.
Emails never reach the warehouse: loaders store a SHA-256 hash plus the domain.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

RAW_SCHEMA = "raw"

# DuckDB type -> dlt data type, used for dlt column hints.
DLT_TYPES = {
    "VARCHAR": "text",
    "DOUBLE": "double",
    "BIGINT": "bigint",
    "BOOLEAN": "bool",
    "DATE": "date",
    "TIMESTAMP": "timestamp",
}


@dataclass(frozen=True)
class RawTable:
    name: str
    columns: dict[str, str]
    primary_key: tuple[str, ...]
    description: str

    def dlt_columns(self) -> dict[str, dict[str, object]]:
        hints: dict[str, dict[str, object]] = {}
        for col, typ in self.columns.items():
            hint: dict[str, object] = {
                "data_type": DLT_TYPES[typ],
                "nullable": col not in self.primary_key,
            }
            if typ == "TIMESTAMP":
                hint["timezone"] = False
            hints[col] = hint
        return hints

    def create_sql(self) -> str:
        cols = ",\n  ".join(f"{c} {t}" for c, t in self.columns.items())
        return f"CREATE TABLE IF NOT EXISTS {RAW_SCHEMA}.{self.name} (\n  {cols}\n)"


RAW_TABLES: dict[str, RawTable] = {
    t.name: t
    for t in [
        RawTable(
            "ad_spend_daily",
            {
                "source_system": "VARCHAR",
                "account_id": "VARCHAR",
                "campaign_id": "VARCHAR",
                "campaign_name": "VARCHAR",
                "date_day": "DATE",
                "spend": "DOUBLE",
                "impressions": "BIGINT",
                "clicks": "BIGINT",
                "currency": "VARCHAR",
                "loaded_at": "TIMESTAMP",
            },
            ("source_system", "campaign_id", "date_day"),
            "Daily campaign spend, impressions and clicks from ad platforms.",
        ),
        RawTable(
            "crm_contacts",
            {
                "source_system": "VARCHAR",
                "contact_id": "VARCHAR",
                "email_hash": "VARCHAR",
                "email_domain": "VARCHAR",
                "company_domain": "VARCHAR",
                "segment": "VARCHAR",
                "lifecycle_stage": "VARCHAR",
                "created_at": "TIMESTAMP",
                "became_lead_at": "TIMESTAMP",
                "loaded_at": "TIMESTAMP",
            },
            ("source_system", "contact_id"),
            "CRM contacts/leads with hashed email and company domain.",
        ),
        RawTable(
            "crm_touchpoints",
            {
                "source_system": "VARCHAR",
                "touchpoint_id": "VARCHAR",
                "contact_id": "VARCHAR",
                "touched_at": "TIMESTAMP",
                "utm_source": "VARCHAR",
                "utm_medium": "VARCHAR",
                "utm_campaign": "VARCHAR",
                "touch_type": "VARCHAR",
                "loaded_at": "TIMESTAMP",
            },
            ("source_system", "touchpoint_id"),
            "Marketing touches (UTM-tagged visits, form fills, campaign membership).",
        ),
        RawTable(
            "crm_deals",
            {
                "source_system": "VARCHAR",
                "deal_id": "VARCHAR",
                "contact_id": "VARCHAR",
                "amount": "DOUBLE",
                "stage": "VARCHAR",
                "is_won": "BOOLEAN",
                "created_at": "TIMESTAMP",
                "closed_at": "TIMESTAMP",
                "loaded_at": "TIMESTAMP",
            },
            ("source_system", "deal_id"),
            "CRM deals/opportunities linked to their primary contact.",
        ),
        RawTable(
            "stripe_customers",
            {
                "customer_id": "VARCHAR",
                "email_hash": "VARCHAR",
                "email_domain": "VARCHAR",
                "crm_contact_id": "VARCHAR",
                "created_at": "TIMESTAMP",
                "loaded_at": "TIMESTAMP",
            },
            ("customer_id",),
            "Stripe customers; crm_contact_id comes from customer metadata when present.",
        ),
        RawTable(
            "stripe_invoices",
            {
                "invoice_id": "VARCHAR",
                "customer_id": "VARCHAR",
                "status": "VARCHAR",
                "amount_paid_cents": "BIGINT",
                "currency": "VARCHAR",
                "paid_at": "TIMESTAMP",
                "period_start": "TIMESTAMP",
                "period_end": "TIMESTAMP",
                "loaded_at": "TIMESTAMP",
            },
            ("invoice_id",),
            "Stripe invoices; period is the service period of the subscription lines.",
        ),
        RawTable(
            "stripe_refunds",
            {
                "refund_id": "VARCHAR",
                "customer_id": "VARCHAR",
                "charge_id": "VARCHAR",
                "amount_cents": "BIGINT",
                "status": "VARCHAR",
                "created_at": "TIMESTAMP",
                "loaded_at": "TIMESTAMP",
            },
            ("refund_id",),
            "Stripe refunds (reduce LTV).",
        ),
        RawTable(
            "stripe_disputes",
            {
                "dispute_id": "VARCHAR",
                "customer_id": "VARCHAR",
                "charge_id": "VARCHAR",
                "amount_cents": "BIGINT",
                "status": "VARCHAR",
                "created_at": "TIMESTAMP",
                "loaded_at": "TIMESTAMP",
            },
            ("dispute_id",),
            "Stripe disputes / chargebacks (reduce LTV unless won).",
        ),
        RawTable(
            "payroll_costs",
            {
                "month": "DATE",
                "employee_id": "VARCHAR",
                "team": "VARCHAR",
                "role": "VARCHAR",
                "cost": "DOUBLE",
                "loaded_at": "TIMESTAMP",
            },
            ("month", "employee_id"),
            "Monthly fully loaded people cost per (pseudonymous) employee.",
        ),
        RawTable(
            "tool_costs",
            {
                "month": "DATE",
                "tool": "VARCHAR",
                "team": "VARCHAR",
                "cost": "DOUBLE",
                "loaded_at": "TIMESTAMP",
            },
            ("month", "tool"),
            "Monthly SaaS/tool cost per owning team.",
        ),
    ]
}


def ensure_raw_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Create the raw schema and every contract table so dbt sources always resolve."""
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {RAW_SCHEMA}")
    for table in RAW_TABLES.values():
        conn.execute(table.create_sql())
