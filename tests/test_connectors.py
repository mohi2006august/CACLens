from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from pipelines.identity import email_domain, hash_email, normalize_domain, normalize_segment
from pipelines.sources import costs_csv, google_ads, hubspot, linkedin, meta, salesforce, stripe
from pipelines.sources.http import SourceError

LOADED = datetime(2026, 1, 1)


# --- identity ---------------------------------------------------------------------


def test_emails_are_hashed_case_insensitively() -> None:
    assert hash_email(" Ann@Acme.COM ") == hash_email("ann@acme.com")
    assert hash_email("not-an-email") is None
    assert email_domain("Ann@Acme.com") == "acme.com"
    assert normalize_domain("https://www.Acme.com/pricing") == "acme.com"


@pytest.mark.parametrize(
    ("raw", "segment"),
    [("SMB", "smb"), ("Mid-Market", "mid_market"), ("Enterprise", "enterprise"), (25, "smb"),
     ("51-200", "mid_market"), ("5,000+", "enterprise"), ("", "unknown"), (None, "unknown")],
)
def test_normalize_segment(raw: object, segment: str) -> None:
    assert normalize_segment(raw) == segment


# --- ad platforms -----------------------------------------------------------------


def test_google_ads_row_converts_micros() -> None:
    row = google_ads.normalize_row(
        {"campaign": {"id": "11", "name": "Brand"}, "segments": {"date": "2026-03-01"},
         "metrics": {"costMicros": "12345678", "impressions": "100", "clicks": "7"},
         "customer": {"currencyCode": "USD"}},
        "123", LOADED,
    )
    assert row["spend"] == pytest.approx(12.345678)
    assert row["date_day"] == date(2026, 3, 1)
    assert (row["campaign_id"], row["clicks"], row["currency"]) == ("11", 7, "USD")


@responses.activate
def test_google_ads_fetch_refreshes_token_and_streams() -> None:
    responses.post(google_ads.TOKEN_URL, json={"access_token": "tok"})
    responses.post(
        "https://googleads.googleapis.com/v21/customers/1234567890/googleAds:searchStream",
        json=[{"results": [{"campaign": {"id": "1", "name": "A"},
                            "segments": {"date": "2026-03-01"},
                            "metrics": {"costMicros": "1000000", "impressions": "1",
                                        "clicks": "1"}}]}],
    )
    config = google_ads.GoogleAdsConfig("dev", "cid", "secret", "refresh", "1234567890",
                                        None, "v21")
    rows = list(google_ads.fetch_spend(config, date(2026, 3, 1), date(2026, 3, 2)))
    assert rows[0]["spend"] == 1.0
    stream_call = responses.calls[1].request
    assert stream_call.headers["developer-token"] == "dev"
    assert "2026-03-01" in json.loads(stream_call.body)["query"]


@responses.activate
def test_meta_follows_pagination_and_prefers_link_clicks() -> None:
    base = "https://graph.facebook.com/v21.0/act_42/insights"
    responses.get(base, json={
        "data": [{"campaign_id": "1", "campaign_name": "P", "spend": "10.5", "clicks": "9",
                  "inline_link_clicks": "4", "impressions": "100", "date_start": "2026-03-01"}],
        "paging": {"next": "https://graph.facebook.com/next-page"},
    })
    responses.get("https://graph.facebook.com/next-page", json={
        "data": [{"campaign_id": "1", "spend": "1", "date_start": "2026-03-02"}]})
    rows = list(meta.fetch_spend(meta.MetaConfig("tok", "42", "v21.0"), date(2026, 3, 1),
                                 date(2026, 3, 2)))
    assert [r["clicks"] for r in rows] == [4, 0]
    assert responses.calls[0].request.headers["Authorization"] == "Bearer tok"


def test_linkedin_url_keeps_restli_syntax() -> None:
    url = linkedin.analytics_url("99", date(2026, 3, 1), date(2026, 3, 31))
    assert "dateRange=(start:(year:2026,month:3,day:1),end:(year:2026,month:3,day:31))" in url
    assert "accounts=List(urn%3Ali%3AsponsoredAccount%3A99)" in url


def test_linkedin_row_uses_campaign_names() -> None:
    row = linkedin.normalize_row(
        {"dateRange": {"start": {"year": 2026, "month": 3, "day": 5}},
         "pivotValues": ["urn:li:sponsoredCampaign:7"], "costInLocalCurrency": "55.1",
         "impressions": 10, "clicks": 2},
        {"7": "ABM"}, "99", LOADED)
    assert (row["campaign_name"], row["spend"], row["date_day"]) == ("ABM", 55.1, date(2026, 3, 5))


# --- CRM --------------------------------------------------------------------------


def test_hubspot_contact_yields_first_and_latest_touches() -> None:
    contact, touches = hubspot.normalize_contact(
        {"id": "501", "properties": {
            "email": "Ann@Acme.com", "createdate": "2026-03-01T10:00:00Z",
            "company_size": "250", "hs_analytics_source": "PAID_SOCIAL",
            "hs_analytics_source_data_1": "Facebook", "hs_analytics_source_data_2": "Spring",
            "hs_analytics_first_timestamp": "2026-02-27T09:00:00Z",
            "hs_latest_source": "EMAIL_MARKETING",
            "hs_latest_source_timestamp": "2026-03-10T09:00:00Z"}},
        "company_size", LOADED)
    assert contact["email_hash"] == hash_email("ann@acme.com")
    assert contact["company_domain"] == "acme.com"
    assert contact["segment"] == "mid_market"
    first, latest = touches
    assert (first["utm_source"], first["utm_medium"], first["utm_campaign"]) == (
        "facebook", "paid_social", "Spring")
    assert (latest["utm_source"], latest["utm_medium"]) == ("email", "email")


def test_hubspot_free_mail_has_no_company_domain() -> None:
    contact, _ = hubspot.normalize_contact(
        {"id": "1", "properties": {"email": "x@gmail.com", "createdate": "2026-03-01"}},
        "company_size", LOADED)
    assert contact["company_domain"] is None


def test_hubspot_deal_picks_primary_contact() -> None:
    deal = hubspot.normalize_deal(
        {"id": "9", "properties": {"amount": "1200", "dealstage": "closedwon",
                                   "createdate": "2026-03-01T00:00:00Z"},
         "associations": {"contacts": {"results": [{"id": "501"}]}}}, LOADED)
    assert (deal["contact_id"], deal["is_won"], deal["amount"]) == ("501", True, 1200.0)


@responses.activate
def test_hubspot_search_pages_with_after_cursor() -> None:
    url = f"{hubspot.BASE}/crm/v3/objects/contacts/search"
    responses.post(url, json={"results": [{"id": "1", "properties": {"createdate": "2026-01-01"}}],
                              "paging": {"next": {"after": "1"}}})
    responses.post(url, json={"results": [{"id": "2", "properties": {"createdate": "2026-01-02"}}]})
    out = list(hubspot.fetch_contacts(hubspot.HubSpotConfig("t", "company_size"),
                                      datetime(2026, 1, 1)))
    assert [c["contact_id"] for c, _ in out] == ["1", "2"]
    assert json.loads(responses.calls[1].request.body)["after"] == "1"


def test_salesforce_timestamps_and_campaign_members() -> None:
    assert salesforce.parse_ts("2026-03-01T10:30:00.000+0200") == datetime(2026, 3, 1, 8, 30)
    member = salesforce.normalize_member(
        {"Id": "00v1", "ContactId": "003A", "CreatedDate": "2026-03-01T10:30:00.000+0000",
         "Campaign": {"Name": "Spring Webinar", "Type": "Webinar"}}, LOADED)
    assert (member["contact_id"], member["utm_medium"], member["utm_campaign"]) == (
        "003A", "event", "Spring Webinar")


@responses.activate
def test_salesforce_query_follows_next_records_url() -> None:
    inst = "https://acme.my.salesforce.com"
    responses.post(f"{inst}/services/oauth2/token",
                   json={"access_token": "tok", "instance_url": inst})
    responses.get(f"{inst}/services/data/v61.0/query",
                  json={"records": [{"Id": "1"}], "nextRecordsUrl": "/services/data/v61.0/query/x-2"})
    responses.get(f"{inst}/services/data/v61.0/query/x-2", json={"records": [{"Id": "2"}]})
    client = salesforce.SalesforceClient(salesforce.SalesforceConfig(inst, "id", "s", "v61.0"))
    assert [r["Id"] for r in client.query("SELECT Id FROM Lead")] == ["1", "2"]


# --- billing ----------------------------------------------------------------------


def test_stripe_invoice_uses_line_periods() -> None:
    row = stripe.normalize_invoice(
        {"id": "in_1", "customer": "cus_1", "status": "paid", "amount_paid": 129900,
         "currency": "usd", "created": 1772323200,
         "status_transitions": {"paid_at": 1772326800},
         "lines": {"data": [{"period": {"start": 1772323200, "end": 1803859200}}]}}, LOADED)
    assert row["amount_paid_cents"] == 129900
    assert (row["period_end"] - row["period_start"]).days == 365


def test_stripe_refund_reads_expanded_charge() -> None:
    row = stripe.normalize_refund(
        {"id": "re_1", "amount": 500, "status": "succeeded", "created": 1772323200,
         "charge": {"id": "ch_1", "customer": "cus_9"}}, LOADED)
    assert (row["customer_id"], row["charge_id"]) == ("cus_9", "ch_1")


@responses.activate
def test_stripe_paginates_with_starting_after() -> None:
    url = f"{stripe.BASE}/customers"
    responses.get(url, json={"data": [{"id": "cus_1"}], "has_more": True})
    responses.get(url, json={"data": [{"id": "cus_2", "email": "a@b.co",
                                       "metadata": {"hubspot_contact_id": "77"}}],
                             "has_more": False})
    rows = list(stripe.fetch_customers(stripe.StripeConfig("sk", "hubspot_contact_id"),
                                       datetime(2026, 1, 1)))
    assert [r["customer_id"] for r in rows] == ["cus_1", "cus_2"]
    assert rows[1]["crm_contact_id"] == "77"
    query = parse_qs(urlparse(responses.calls[1].request.url).query)
    assert query["starting_after"] == ["cus_1"]


@responses.activate
def test_http_errors_raise_without_leaking_query_strings() -> None:
    responses.get(f"{stripe.BASE}/customers", status=401, json={"error": "bad key"})
    with pytest.raises(SourceError, match="HTTP 401"):
        list(stripe.fetch_customers(stripe.StripeConfig("sk", "x"), datetime(2026, 1, 1)))


# --- cost CSVs --------------------------------------------------------------------


def test_payroll_csv_parses_months_and_currency(tmp_path: Path) -> None:
    path = tmp_path / "payroll.csv"
    path.write_text("month,employee_id,team,role,cost\n2026-01,e1,SDR,Rep,\"$6,800\"\n")
    rows = list(costs_csv.read_payroll(path))
    assert rows[0]["month"] == date(2026, 1, 1)
    assert (rows[0]["team"], rows[0]["cost"]) == ("sdr", 6800.0)


def test_cost_csv_reports_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "tools.csv"
    path.write_text("month,tool,cost\n2026-01,HubSpot,100\n")
    with pytest.raises(costs_csv.CostFileError, match="team"):
        list(costs_csv.read_tools(path))
