"""Stripe customers, paid invoices, refunds and disputes via the REST API."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pipelines.identity import email_domain, hash_email
from pipelines.sources.http import make_session, request_json, utc_now

SOURCE = "stripe"
BASE = "https://api.stripe.com/v1"


@dataclass(frozen=True)
class StripeConfig:
    key: str
    crm_id_metadata_key: str

    @classmethod
    def from_env(cls) -> StripeConfig | None:
        key = os.environ.get("STRIPE_KEY")
        if not key:
            return None
        return cls(key, os.environ.get("STRIPE_CRM_ID_METADATA_KEY", "hubspot_contact_id"))


def ts(value: int | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(value, tz=UTC).replace(tzinfo=None)


def _customer_id(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("id")
    return value


def normalize_customer(obj: dict[str, Any], metadata_key: str, loaded_at: datetime) -> dict[str, Any]:
    email = obj.get("email")
    return {
        "customer_id": obj["id"],
        "email_hash": hash_email(email),
        "email_domain": email_domain(email),
        "crm_contact_id": (obj.get("metadata") or {}).get(metadata_key),
        "created_at": ts(obj.get("created")),
        "loaded_at": loaded_at,
    }


def normalize_invoice(obj: dict[str, Any], loaded_at: datetime) -> dict[str, Any]:
    lines = (obj.get("lines") or {}).get("data", [])
    periods = [line["period"] for line in lines if line.get("period")]
    period_start = min((p["start"] for p in periods), default=obj.get("period_start"))
    period_end = max((p["end"] for p in periods), default=obj.get("period_end"))
    transitions = obj.get("status_transitions") or {}
    return {
        "invoice_id": obj["id"],
        "customer_id": _customer_id(obj.get("customer")),
        "status": obj.get("status"),
        "amount_paid_cents": int(obj.get("amount_paid") or 0),
        "currency": obj.get("currency"),
        "paid_at": ts(transitions.get("paid_at")) or ts(obj.get("created")),
        "period_start": ts(period_start),
        "period_end": ts(period_end),
        "loaded_at": loaded_at,
    }


def normalize_refund(obj: dict[str, Any], loaded_at: datetime) -> dict[str, Any]:
    charge = obj.get("charge") or {}
    return {
        "refund_id": obj["id"],
        "customer_id": _customer_id(charge.get("customer")) if isinstance(charge, dict) else None,
        "charge_id": charge.get("id") if isinstance(charge, dict) else charge,
        "amount_cents": int(obj.get("amount") or 0),
        "status": obj.get("status"),
        "created_at": ts(obj.get("created")),
        "loaded_at": loaded_at,
    }


def normalize_dispute(obj: dict[str, Any], loaded_at: datetime) -> dict[str, Any]:
    charge = obj.get("charge") or {}
    return {
        "dispute_id": obj["id"],
        "customer_id": _customer_id(charge.get("customer")) if isinstance(charge, dict) else None,
        "charge_id": charge.get("id") if isinstance(charge, dict) else charge,
        "amount_cents": int(obj.get("amount") or 0),
        "status": obj.get("status"),
        "created_at": ts(obj.get("created")),
        "loaded_at": loaded_at,
    }


def list_all(
    config: StripeConfig, path: str, since: datetime, extra: dict[str, Any] | None = None
) -> Iterator[dict[str, Any]]:
    session = make_session({"Authorization": f"Bearer {config.key}"})
    params: dict[str, Any] = {
        "limit": 100,
        "created[gte]": int(since.replace(tzinfo=UTC).timestamp()),
        **(extra or {}),
    }
    while True:
        page = request_json(session, "GET", f"{BASE}/{path}", source=SOURCE, params=params)
        data = page.get("data", [])
        yield from data
        if not page.get("has_more") or not data:
            return
        params = {**params, "starting_after": data[-1]["id"]}


def fetch_customers(config: StripeConfig, since: datetime) -> Iterator[dict[str, Any]]:
    loaded_at = utc_now()
    for obj in list_all(config, "customers", since):
        yield normalize_customer(obj, config.crm_id_metadata_key, loaded_at)


def fetch_invoices(config: StripeConfig, since: datetime) -> Iterator[dict[str, Any]]:
    loaded_at = utc_now()
    for obj in list_all(config, "invoices", since, {"status": "paid"}):
        yield normalize_invoice(obj, loaded_at)


def fetch_refunds(config: StripeConfig, since: datetime) -> Iterator[dict[str, Any]]:
    loaded_at = utc_now()
    for obj in list_all(config, "refunds", since, {"expand[]": "data.charge"}):
        yield normalize_refund(obj, loaded_at)


def fetch_disputes(config: StripeConfig, since: datetime) -> Iterator[dict[str, Any]]:
    loaded_at = utc_now()
    for obj in list_all(config, "disputes", since, {"expand[]": "data.charge"}):
        yield normalize_dispute(obj, loaded_at)
