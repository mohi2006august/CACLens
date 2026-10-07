"""FR-01 connector registry: which sources exist and how each one maps to raw tables.

Every connector yields rows shaped exactly like `pipelines.schema.RAW_TABLES`. The dlt
loader (`pipelines/load.py`) routes each row to its raw table with merge semantics.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pipelines.sources import costs_csv, google_ads, hubspot, linkedin, meta, salesforce, stripe

# A row tagged with its destination table.
Routed = tuple[str, dict[str, Any]]


@dataclass(frozen=True)
class Window:
    """Extraction window: ads use dates; CRM/billing use a modified-since timestamp."""

    start: date
    end: date
    since: datetime


@dataclass(frozen=True)
class SourceSpec:
    name: str
    group: str
    tables: tuple[str, ...]
    is_configured: Callable[[], bool]
    extract: Callable[[Window], Iterator[Routed]]


def _ads(fetch: Callable[[Any, date, date], Iterator[dict[str, Any]]],
         load_config: Callable[[], Any]) -> Callable[[Window], Iterator[Routed]]:
    def run(window: Window) -> Iterator[Routed]:
        config = load_config()
        for row in fetch(config, window.start, window.end):
            yield "ad_spend_daily", row

    return run


def _hubspot(window: Window) -> Iterator[Routed]:
    config = hubspot.HubSpotConfig.from_env()
    assert config is not None
    contact_ids: list[str] = []
    for contact, touches in hubspot.fetch_contacts(config, window.since):
        yield "crm_contacts", contact
        contact_ids.append(contact["contact_id"])
        snapshot = hubspot.score_snapshot(contact)
        if snapshot:
            yield "crm_score_history", snapshot
        for touch in touches:
            yield "crm_touchpoints", touch
    for row in hubspot.fetch_score_history(config, contact_ids):
        yield "crm_score_history", row
    for deal in hubspot.fetch_deals(config):
        yield "crm_deals", deal


def _salesforce(window: Window) -> Iterator[Routed]:
    config = salesforce.SalesforceConfig.from_env()
    assert config is not None
    for row in salesforce.fetch_contacts(config, window.since):
        yield "crm_contacts", row
        snapshot = salesforce.score_snapshot(row)
        if snapshot:
            yield "crm_score_history", snapshot
    for row in salesforce.fetch_rating_history(config, window.since):
        yield "crm_score_history", row
    for row in salesforce.fetch_touchpoints(config, window.since):
        yield "crm_touchpoints", row
    for row in salesforce.fetch_deals(config, window.since):
        yield "crm_deals", row


def _stripe(window: Window) -> Iterator[Routed]:
    config = stripe.StripeConfig.from_env()
    assert config is not None
    for row in stripe.fetch_customers(config, window.since):
        yield "stripe_customers", row
    for row in stripe.fetch_invoices(config, window.since):
        yield "stripe_invoices", row
    for row in stripe.fetch_refunds(config, window.since):
        yield "stripe_refunds", row
    for row in stripe.fetch_disputes(config, window.since):
        yield "stripe_disputes", row


def _costs(_window: Window) -> Iterator[Routed]:
    payroll = costs_csv.payroll_path_from_env()
    tools = costs_csv.tools_path_from_env()
    if payroll:
        for row in costs_csv.read_payroll(payroll):
            yield "payroll_costs", row
    if tools:
        for row in costs_csv.read_tools(tools):
            yield "tool_costs", row


SOURCES: dict[str, SourceSpec] = {
    spec.name: spec
    for spec in [
        SourceSpec(
            "google_ads", "ads", ("ad_spend_daily",),
            lambda: google_ads.GoogleAdsConfig.from_env() is not None,
            _ads(google_ads.fetch_spend, google_ads.GoogleAdsConfig.from_env),
        ),
        SourceSpec(
            "meta_ads", "ads", ("ad_spend_daily",),
            lambda: meta.MetaConfig.from_env() is not None,
            _ads(meta.fetch_spend, meta.MetaConfig.from_env),
        ),
        SourceSpec(
            "linkedin_ads", "ads", ("ad_spend_daily",),
            lambda: linkedin.LinkedInConfig.from_env() is not None,
            _ads(linkedin.fetch_spend, linkedin.LinkedInConfig.from_env),
        ),
        SourceSpec(
            "hubspot", "crm",
            ("crm_contacts", "crm_touchpoints", "crm_deals", "crm_score_history"),
            lambda: hubspot.HubSpotConfig.from_env() is not None,
            _hubspot,
        ),
        SourceSpec(
            "salesforce", "crm",
            ("crm_contacts", "crm_touchpoints", "crm_deals", "crm_score_history"),
            lambda: salesforce.SalesforceConfig.from_env() is not None,
            _salesforce,
        ),
        SourceSpec(
            "stripe", "billing",
            ("stripe_customers", "stripe_invoices", "stripe_refunds", "stripe_disputes"),
            lambda: stripe.StripeConfig.from_env() is not None,
            _stripe,
        ),
        SourceSpec(
            "costs_csv", "costs", ("payroll_costs", "tool_costs"),
            lambda: bool(costs_csv.payroll_path_from_env() or costs_csv.tools_path_from_env()),
            _costs,
        ),
    ]
}

SOURCE_GROUPS = ("ads", "crm", "billing", "costs")
