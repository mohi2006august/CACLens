"""LinkedIn Ads daily campaign analytics via the versioned Marketing REST API."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

from pipelines.sources.http import make_session, request_json, utc_now

SOURCE = "linkedin_ads"
BASE = "https://api.linkedin.com/rest"


@dataclass(frozen=True)
class LinkedInConfig:
    token: str
    ad_account_id: str
    api_version: str

    @classmethod
    def from_env(cls) -> LinkedInConfig | None:
        token = os.environ.get("LINKEDIN_TOKEN")
        account = os.environ.get("LINKEDIN_AD_ACCOUNT_ID")
        if not token or not account:
            return None
        return cls(token, account, os.environ.get("LINKEDIN_API_VERSION", "202409"))


def _restli_date(day: date) -> str:
    return f"(year:{day.year},month:{day.month},day:{day.day})"


def analytics_url(account_id: str, start: date, end: date) -> str:
    """Rest.li query strings must keep their parentheses/colons unencoded."""
    account_urn = quote(f"urn:li:sponsoredAccount:{account_id}", safe="")
    return (
        f"{BASE}/adAnalytics?q=analytics&pivot=CAMPAIGN&timeGranularity=DAILY"
        f"&dateRange=(start:{_restli_date(start)},end:{_restli_date(end)})"
        f"&accounts=List({account_urn})"
        "&fields=dateRange,pivotValues,costInLocalCurrency,impressions,clicks"
    )


def normalize_row(
    row: dict[str, Any], names: dict[str, str], account_id: str, loaded_at: datetime
) -> dict[str, Any]:
    start = row["dateRange"]["start"]
    campaign_id = row["pivotValues"][0].rsplit(":", 1)[-1]
    return {
        "source_system": SOURCE,
        "account_id": account_id,
        "campaign_id": campaign_id,
        "campaign_name": names.get(campaign_id, campaign_id),
        "date_day": date(start["year"], start["month"], start["day"]),
        "spend": float(row.get("costInLocalCurrency", 0) or 0),
        "impressions": int(row.get("impressions", 0) or 0),
        "clicks": int(row.get("clicks", 0) or 0),
        "currency": None,
        "loaded_at": loaded_at,
    }


def fetch_campaign_names(session: Any, account_id: str) -> dict[str, str]:
    names: dict[str, str] = {}
    params: dict[str, Any] = {"q": "search", "pageSize": 100}
    while True:
        page = request_json(
            session, "GET", f"{BASE}/adAccounts/{account_id}/adCampaigns",
            source=SOURCE, params=params,
        )
        for campaign in page.get("elements", []):
            names[str(campaign["id"])] = campaign.get("name", str(campaign["id"]))
        token = page.get("metadata", {}).get("nextPageToken")
        if not token:
            return names
        params = {**params, "pageToken": token}


def fetch_spend(config: LinkedInConfig, start: date, end: date) -> Iterator[dict[str, Any]]:
    session = make_session(
        {
            "Authorization": f"Bearer {config.token}",
            "LinkedIn-Version": config.api_version,
            "X-Restli-Protocol-Version": "2.0.0",
        }
    )
    names = fetch_campaign_names(session, config.ad_account_id)
    page = request_json(
        session, "GET", analytics_url(config.ad_account_id, start, end), source=SOURCE
    )
    loaded_at = utc_now()
    for row in page.get("elements", []):
        yield normalize_row(row, names, config.ad_account_id, loaded_at)
