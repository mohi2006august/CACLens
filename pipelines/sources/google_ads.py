"""Google Ads daily campaign spend via the REST `googleAds:searchStream` endpoint."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pipelines.sources.http import make_session, request_json, utc_now

TOKEN_URL = "https://oauth2.googleapis.com/token"
SOURCE = "google_ads"

GAQL = """
SELECT segments.date, campaign.id, campaign.name, customer.currency_code,
       metrics.cost_micros, metrics.impressions, metrics.clicks
FROM campaign
WHERE segments.date BETWEEN '{start}' AND '{end}'
"""


@dataclass(frozen=True)
class GoogleAdsConfig:
    developer_token: str
    client_id: str
    client_secret: str
    refresh_token: str
    customer_id: str
    login_customer_id: str | None
    api_version: str

    @classmethod
    def from_env(cls) -> GoogleAdsConfig | None:
        required = {
            "developer_token": os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": os.environ.get("GOOGLE_ADS_CLIENT_ID"),
            "client_secret": os.environ.get("GOOGLE_ADS_CLIENT_SECRET"),
            "refresh_token": os.environ.get("GOOGLE_ADS_REFRESH_TOKEN"),
            "customer_id": os.environ.get("GOOGLE_ADS_CUSTOMER_ID"),
        }
        if not all(required.values()):
            return None
        login = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or None
        return cls(
            developer_token=str(required["developer_token"]),
            client_id=str(required["client_id"]),
            client_secret=str(required["client_secret"]),
            refresh_token=str(required["refresh_token"]),
            customer_id=str(required["customer_id"]).replace("-", ""),
            login_customer_id=login.replace("-", "") if login else None,
            api_version=os.environ.get("GOOGLE_ADS_API_VERSION", "v21"),
        )


def normalize_row(row: dict[str, Any], customer_id: str, loaded_at: datetime) -> dict[str, Any]:
    campaign = row.get("campaign", {})
    metrics = row.get("metrics", {})
    return {
        "source_system": SOURCE,
        "account_id": customer_id,
        "campaign_id": str(campaign.get("id")),
        "campaign_name": campaign.get("name"),
        "date_day": date.fromisoformat(row["segments"]["date"]),
        "spend": int(metrics.get("costMicros", 0)) / 1_000_000,
        "impressions": int(metrics.get("impressions", 0)),
        "clicks": int(metrics.get("clicks", 0)),
        "currency": row.get("customer", {}).get("currencyCode"),
        "loaded_at": loaded_at,
    }


def fetch_spend(config: GoogleAdsConfig, start: date, end: date) -> Iterator[dict[str, Any]]:
    session = make_session()
    token = request_json(
        session,
        "POST",
        TOKEN_URL,
        source=SOURCE,
        data={
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "refresh_token": config.refresh_token,
            "grant_type": "refresh_token",
        },
    )["access_token"]
    session.headers.update(
        {"Authorization": f"Bearer {token}", "developer-token": config.developer_token}
    )
    if config.login_customer_id:
        session.headers["login-customer-id"] = config.login_customer_id
    url = (
        f"https://googleads.googleapis.com/{config.api_version}"
        f"/customers/{config.customer_id}/googleAds:searchStream"
    )
    batches = request_json(
        session,
        "POST",
        url,
        source=SOURCE,
        json={"query": GAQL.format(start=start.isoformat(), end=end.isoformat())},
    )
    loaded_at = utc_now()
    for batch in batches:
        for row in batch.get("results", []):
            yield normalize_row(row, config.customer_id, loaded_at)
