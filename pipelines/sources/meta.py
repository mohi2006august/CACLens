"""Meta (Facebook/Instagram) daily campaign insights via the Graph Marketing API."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pipelines.sources.http import make_session, request_json, utc_now

SOURCE = "meta_ads"
FIELDS = "campaign_id,campaign_name,spend,impressions,clicks,inline_link_clicks,account_currency"


@dataclass(frozen=True)
class MetaConfig:
    token: str
    ad_account_id: str
    api_version: str

    @classmethod
    def from_env(cls) -> MetaConfig | None:
        token = os.environ.get("META_TOKEN")
        account = os.environ.get("META_AD_ACCOUNT_ID")
        if not token or not account:
            return None
        return cls(
            token=token,
            ad_account_id=account.removeprefix("act_"),
            api_version=os.environ.get("META_API_VERSION", "v21.0"),
        )


def normalize_row(row: dict[str, Any], account_id: str, loaded_at: datetime) -> dict[str, Any]:
    # Link clicks are the clicks that reach the site; fall back to all clicks.
    clicks = row.get("inline_link_clicks", row.get("clicks", 0))
    return {
        "source_system": SOURCE,
        "account_id": account_id,
        "campaign_id": str(row["campaign_id"]),
        "campaign_name": row.get("campaign_name"),
        "date_day": date.fromisoformat(row["date_start"]),
        "spend": float(row.get("spend", 0) or 0),
        "impressions": int(row.get("impressions", 0) or 0),
        "clicks": int(clicks or 0),
        "currency": row.get("account_currency"),
        "loaded_at": loaded_at,
    }


def fetch_spend(config: MetaConfig, start: date, end: date) -> Iterator[dict[str, Any]]:
    session = make_session({"Authorization": f"Bearer {config.token}"})
    url: str | None = (
        f"https://graph.facebook.com/{config.api_version}/act_{config.ad_account_id}/insights"
    )
    params: dict[str, Any] | None = {
        "level": "campaign",
        "fields": FIELDS,
        "time_increment": 1,
        "time_range": json.dumps({"since": start.isoformat(), "until": end.isoformat()}),
        "limit": 500,
    }
    loaded_at = utc_now()
    while url:
        page = request_json(session, "GET", url, source=SOURCE, params=params)
        for row in page.get("data", []):
            yield normalize_row(row, config.ad_account_id, loaded_at)
        url = page.get("paging", {}).get("next")
        params = None  # the `next` link already carries every parameter
