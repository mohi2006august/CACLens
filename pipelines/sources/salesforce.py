"""Salesforce leads/contacts, campaign members (touchpoints) and opportunities via SOQL."""

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

SOURCE = "salesforce"

# Campaign.Type -> (utm_source, utm_medium)
CAMPAIGN_TYPE_MAP: dict[str, tuple[str, str]] = {
    "email": ("email", "email"),
    "webinar": ("webinar", "event"),
    "conference": ("event", "event"),
    "trade show": ("event", "event"),
    "partners": ("partner", "referral"),
    "referral program": ("referral_program", "referral"),
    "advertisement": ("advertisement", "paid"),
    "banner ads": ("display", "display"),
    "direct mail": ("direct_mail", "offline"),
    "public relations": ("pr", "pr"),
    "telemarketing": ("outbound", "outbound"),
}

LEAD_SOURCE_MAP: dict[str, tuple[str, str]] = {
    "web": ("(direct)", "(none)"),
    "phone inquiry": ("(direct)", "(none)"),
    "partner referral": ("partner", "referral"),
    "purchased list": ("purchased_list", "outbound"),
    "other": ("other", "other"),
}

LEADS_SOQL = (
    "SELECT Id, Email, Website, NumberOfEmployees, Status, LeadSource, CreatedDate "
    "FROM Lead WHERE IsConverted = false AND SystemModstamp >= {since}"
)
CONTACTS_SOQL = (
    "SELECT Id, Email, CreatedDate, LeadSource, Account.Website, Account.NumberOfEmployees "
    "FROM Contact WHERE SystemModstamp >= {since}"
)
MEMBERS_SOQL = (
    "SELECT Id, LeadId, ContactId, CreatedDate, FirstRespondedDate, "
    "Campaign.Name, Campaign.Type FROM CampaignMember WHERE SystemModstamp >= {since}"
)
OPPS_SOQL = (
    "SELECT Id, ContactId, Amount, StageName, IsWon, IsClosed, CreatedDate, CloseDate "
    "FROM Opportunity WHERE SystemModstamp >= {since}"
)


@dataclass(frozen=True)
class SalesforceConfig:
    instance_url: str
    client_id: str
    client_secret: str
    api_version: str

    @classmethod
    def from_env(cls) -> SalesforceConfig | None:
        url = os.environ.get("SALESFORCE_INSTANCE_URL")
        cid = os.environ.get("SALESFORCE_CLIENT_ID")
        secret = os.environ.get("SALESFORCE_CLIENT_SECRET")
        if not url or not cid or not secret:
            return None
        return cls(url.rstrip("/"), cid, secret, os.environ.get("SALESFORCE_API_VERSION", "v61.0"))


def parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if len(text) == 10:  # a plain date such as CloseDate
        return datetime.fromisoformat(text)
    parsed = datetime.strptime(text.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S.%f%z")
    return parsed.astimezone(UTC).replace(tzinfo=None)


def soql_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_person(record: dict[str, Any], kind: str, loaded_at: datetime) -> dict[str, Any]:
    account = record.get("Account") or {}
    email = record.get("Email")
    domain = email_domain(email)
    website = record.get("Website") or account.get("Website")
    employees = record.get("NumberOfEmployees") or account.get("NumberOfEmployees")
    created_at = parse_ts(record.get("CreatedDate"))
    return {
        "source_system": SOURCE,
        "contact_id": record["Id"],
        "email_hash": hash_email(email),
        "email_domain": domain,
        "company_domain": normalize_domain(website)
        or (domain if domain and domain not in FREE_EMAIL_DOMAINS else None),
        "segment": normalize_segment(employees),
        "lifecycle_stage": kind,
        "created_at": created_at,
        "became_lead_at": created_at,
        "loaded_at": loaded_at,
    }


def lead_source_touch(record: dict[str, Any], loaded_at: datetime) -> dict[str, Any] | None:
    lead_source = (record.get("LeadSource") or "").strip()
    if not lead_source:
        return None
    source, medium = LEAD_SOURCE_MAP.get(
        lead_source.lower(), (lead_source.lower().replace(" ", "_"), "other")
    )
    return {
        "source_system": SOURCE,
        "touchpoint_id": f"{record['Id']}:lead_source",
        "contact_id": record["Id"],
        "touched_at": parse_ts(record.get("CreatedDate")),
        "utm_source": source,
        "utm_medium": medium,
        "utm_campaign": None,
        "touch_type": "lead_source",
        "loaded_at": loaded_at,
    }


def normalize_member(record: dict[str, Any], loaded_at: datetime) -> dict[str, Any]:
    campaign = record.get("Campaign") or {}
    source, medium = CAMPAIGN_TYPE_MAP.get(
        (campaign.get("Type") or "").lower(), ("salesforce_campaign", "other")
    )
    return {
        "source_system": SOURCE,
        "touchpoint_id": record["Id"],
        "contact_id": record.get("ContactId") or record.get("LeadId"),
        "touched_at": parse_ts(record.get("FirstRespondedDate"))
        or parse_ts(record.get("CreatedDate")),
        "utm_source": source,
        "utm_medium": medium,
        "utm_campaign": campaign.get("Name"),
        "touch_type": "campaign_member",
        "loaded_at": loaded_at,
    }


def normalize_opportunity(record: dict[str, Any], loaded_at: datetime) -> dict[str, Any]:
    amount = record.get("Amount")
    return {
        "source_system": SOURCE,
        "deal_id": record["Id"],
        "contact_id": record.get("ContactId"),
        "amount": float(amount) if amount is not None else None,
        "stage": record.get("StageName"),
        "is_won": bool(record.get("IsWon")),
        "created_at": parse_ts(record.get("CreatedDate")),
        "closed_at": parse_ts(record.get("CloseDate")) if record.get("IsClosed") else None,
        "loaded_at": loaded_at,
    }


class SalesforceClient:
    def __init__(self, config: SalesforceConfig) -> None:
        self.config = config
        self.session = make_session()
        token = request_json(
            self.session,
            "POST",
            f"{config.instance_url}/services/oauth2/token",
            source=SOURCE,
            data={
                "grant_type": "client_credentials",
                "client_id": config.client_id,
                "client_secret": config.client_secret,
            },
        )
        self.instance_url = token.get("instance_url", config.instance_url).rstrip("/")
        self.session.headers["Authorization"] = f"Bearer {token['access_token']}"

    def query(self, soql: str) -> Iterator[dict[str, Any]]:
        url = f"{self.instance_url}/services/data/{self.config.api_version}/query"
        page = request_json(self.session, "GET", url, source=SOURCE, params={"q": soql})
        while True:
            yield from page.get("records", [])
            next_url = page.get("nextRecordsUrl")
            if not next_url:
                return
            page = request_json(self.session, "GET", f"{self.instance_url}{next_url}", source=SOURCE)


def fetch_contacts(config: SalesforceConfig, since: datetime) -> Iterator[dict[str, Any]]:
    client = SalesforceClient(config)
    loaded_at = utc_now()
    for record in client.query(LEADS_SOQL.format(since=soql_datetime(since))):
        yield normalize_person(record, "lead", loaded_at)
    for record in client.query(CONTACTS_SOQL.format(since=soql_datetime(since))):
        yield normalize_person(record, "contact", loaded_at)


def fetch_touchpoints(config: SalesforceConfig, since: datetime) -> Iterator[dict[str, Any]]:
    client = SalesforceClient(config)
    loaded_at = utc_now()
    for soql in (LEADS_SOQL, CONTACTS_SOQL):
        for record in client.query(soql.format(since=soql_datetime(since))):
            touch = lead_source_touch(record, loaded_at)
            if touch:
                yield touch
    for record in client.query(MEMBERS_SOQL.format(since=soql_datetime(since))):
        yield normalize_member(record, loaded_at)


def fetch_deals(config: SalesforceConfig, since: datetime) -> Iterator[dict[str, Any]]:
    client = SalesforceClient(config)
    loaded_at = utc_now()
    for record in client.query(OPPS_SOQL.format(since=soql_datetime(since))):
        yield normalize_opportunity(record, loaded_at)
