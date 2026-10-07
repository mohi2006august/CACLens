"""HubSpot contacts, touchpoints and deals via the CRM v3 API.

Touchpoints come from HubSpot's first-touch (`hs_analytics_source*`) and latest-touch
(`hs_latest_source*`) properties, plus optional custom `utm_*` contact properties.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pipelines.identity import (
    FREE_EMAIL_DOMAINS,
    email_domain,
    hash_email,
    normalize_domain,
    normalize_segment,
)
from pipelines.sources.http import make_session, request_json, utc_now

SOURCE = "hubspot"
BASE = "https://api.hubapi.com"
SEARCH_LIMIT = 10_000  # HubSpot search returns at most 10k results per query

# HubSpot analytics source -> (utm_source fallback, utm_medium)
SOURCE_MAP: dict[str, tuple[str | None, str]] = {
    "PAID_SEARCH": (None, "cpc"),
    "PAID_SOCIAL": (None, "paid_social"),
    "ORGANIC_SEARCH": (None, "organic"),
    "SOCIAL_MEDIA": (None, "social"),
    "REFERRALS": (None, "referral"),
    "EMAIL_MARKETING": ("email", "email"),
    "DIRECT_TRAFFIC": ("(direct)", "(none)"),
    "OTHER_CAMPAIGNS": ("other", "other"),
    "OFFLINE": ("offline", "offline"),
    "AI_REFERRALS": (None, "referral"),
}


@dataclass(frozen=True)
class HubSpotConfig:
    token: str
    segment_property: str
    lead_score_property: str = "hubspotscore"

    @classmethod
    def from_env(cls) -> HubSpotConfig | None:
        token = os.environ.get("HUBSPOT_TOKEN")
        if not token:
            return None
        return cls(
            token,
            os.environ.get("HUBSPOT_SEGMENT_PROPERTY", "company_size"),
            os.environ.get("HUBSPOT_LEAD_SCORE_PROPERTY", "hubspotscore"),
        )

    def contact_properties(self) -> list[str]:
        return [
            "email", "createdate", "lastmodifieddate", "lifecyclestage",
            "hs_lifecyclestage_lead_date", "website", "hs_email_domain",
            self.segment_property,
            self.lead_score_property,
            "hs_analytics_source", "hs_analytics_source_data_1", "hs_analytics_source_data_2",
            "hs_analytics_first_timestamp",
            "hs_latest_source", "hs_latest_source_data_1", "hs_latest_source_data_2",
            "hs_latest_source_timestamp",
            "utm_source", "utm_medium", "utm_campaign",
        ]


def parse_ts(value: Any) -> datetime | None:
    """HubSpot returns ISO-8601 strings (or epoch millis on older properties)."""
    if value in (None, ""):
        return None
    if isinstance(value, int | float) or str(value).isdigit():
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC).replace(tzinfo=None)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed


def map_source(kind: str | None, data_1: str | None) -> tuple[str, str]:
    if not kind:
        return "(direct)", "(none)"
    fallback_source, medium = SOURCE_MAP.get(kind.upper(), ("other", "other"))
    source = (data_1 or fallback_source or "unknown").strip().lower()
    return source, medium


def parse_score(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def normalize_contact(
    record: dict[str, Any],
    segment_property: str,
    loaded_at: datetime,
    lead_score_property: str = "hubspotscore",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    props = record.get("properties", {})
    contact_id = str(record["id"])
    email = props.get("email")
    domain = email_domain(email)
    company_domain = normalize_domain(props.get("website")) or (
        domain if domain and domain not in FREE_EMAIL_DOMAINS else None
    )
    created_at = parse_ts(props.get("createdate"))
    contact = {
        "source_system": SOURCE,
        "contact_id": contact_id,
        "email_hash": hash_email(email),
        "email_domain": domain,
        "company_domain": company_domain,
        "segment": normalize_segment(props.get(segment_property)),
        "lead_score": parse_score(props.get(lead_score_property)),
        "lifecycle_stage": props.get("lifecyclestage"),
        "created_at": created_at,
        "became_lead_at": parse_ts(props.get("hs_lifecyclestage_lead_date")) or created_at,
        "loaded_at": loaded_at,
    }

    touches: list[dict[str, Any]] = []
    first_at = parse_ts(props.get("hs_analytics_first_timestamp")) or created_at
    if first_at:
        source, medium = map_source(
            props.get("hs_analytics_source"), props.get("hs_analytics_source_data_1")
        )
        # Explicit UTM properties (if the portal captures them) beat HubSpot's inference.
        touches.append(
            {
                "touchpoint_id": f"{contact_id}:first",
                "touched_at": first_at,
                "utm_source": (props.get("utm_source") or source).lower(),
                "utm_medium": (props.get("utm_medium") or medium).lower(),
                "utm_campaign": props.get("utm_campaign")
                or props.get("hs_analytics_source_data_2"),
                "touch_type": "first_touch",
            }
        )
    latest_at = parse_ts(props.get("hs_latest_source_timestamp"))
    if latest_at and latest_at != first_at:
        source, medium = map_source(
            props.get("hs_latest_source"), props.get("hs_latest_source_data_1")
        )
        touches.append(
            {
                "touchpoint_id": f"{contact_id}:latest",
                "touched_at": latest_at,
                "utm_source": source,
                "utm_medium": medium,
                "utm_campaign": props.get("hs_latest_source_data_2"),
                "touch_type": "latest_touch",
            }
        )
    for touch in touches:
        touch.update(source_system=SOURCE, contact_id=contact_id, loaded_at=loaded_at)
    return contact, touches


def normalize_deal(record: dict[str, Any], loaded_at: datetime) -> dict[str, Any]:
    props = record.get("properties", {})
    contacts = record.get("associations", {}).get("contacts", {}).get("results", [])
    stage = props.get("dealstage")
    is_won = str(props.get("hs_is_closed_won", "")).lower() == "true" or stage == "closedwon"
    amount = props.get("amount")
    return {
        "source_system": SOURCE,
        "deal_id": str(record["id"]),
        "contact_id": str(contacts[0]["id"]) if contacts else None,
        "amount": float(amount) if amount not in (None, "") else None,
        "stage": stage,
        "is_won": is_won,
        "created_at": parse_ts(props.get("createdate")),
        "closed_at": parse_ts(props.get("closedate")),
        "loaded_at": loaded_at,
    }


def fetch_contacts(
    config: HubSpotConfig, since: datetime
) -> Iterator[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Search contacts modified since `since`, restarting the query past the 10k cap."""
    session = make_session({"Authorization": f"Bearer {config.token}"})
    loaded_at = utc_now()
    cursor_ts = since
    while True:
        after: str | None = None
        seen = 0
        last_modified = cursor_ts
        while True:
            body: dict[str, Any] = {
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "lastmodifieddate",
                                "operator": "GTE",
                                "value": str(int(cursor_ts.replace(tzinfo=UTC).timestamp() * 1000)),
                            }
                        ]
                    }
                ],
                "sorts": [{"propertyName": "lastmodifieddate", "direction": "ASCENDING"}],
                "properties": config.contact_properties(),
                "limit": 100,
            }
            if after:
                body["after"] = after
            page = request_json(
                session, "POST", f"{BASE}/crm/v3/objects/contacts/search",
                source=SOURCE, json=body,
            )
            for record in page.get("results", []):
                seen += 1
                last_modified = (
                    parse_ts(record.get("properties", {}).get("lastmodifieddate"))
                    or last_modified
                )
                yield normalize_contact(record, config.segment_property, loaded_at,
                                        config.lead_score_property)
            after = page.get("paging", {}).get("next", {}).get("after")
            if not after:
                return
            if seen + 100 > SEARCH_LIMIT:
                break
        if last_modified <= cursor_ts:
            return  # cannot advance the window; avoid an infinite loop
        cursor_ts = last_modified


def fetch_deals(config: HubSpotConfig) -> Iterator[dict[str, Any]]:
    session = make_session({"Authorization": f"Bearer {config.token}"})
    loaded_at = utc_now()
    params: dict[str, Any] = {
        "limit": 100,
        "properties": "amount,dealstage,closedate,createdate,hs_is_closed_won",
        "associations": "contacts",
    }
    while True:
        page = request_json(
            session, "GET", f"{BASE}/crm/v3/objects/deals", source=SOURCE, params=params
        )
        for record in page.get("results", []):
            yield normalize_deal(record, loaded_at)
        after = page.get("paging", {}).get("next", {}).get("after")
        if not after:
            return
        params = {**params, "after": after}
