"""Integration: synthetic data -> dlt/demo load -> dbt build -> API, end to end."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from pipelines.load import run_source
from pipelines.sources import SourceSpec, Window

pytestmark = pytest.mark.integration


def test_dlt_loads_into_contract_tables_and_merges(tmp_path: Path) -> None:
    def extract(_window: Window) -> Iterator[tuple[str, dict[str, object]]]:
        for i in range(3):
            yield "crm_contacts", {
                "source_system": "hubspot", "contact_id": str(i), "email_hash": "h",
                "email_domain": "a.com", "company_domain": "a.com", "segment": "smb",
                "lifecycle_stage": "lead", "created_at": datetime(2026, 1, 1),
                "became_lead_at": datetime(2026, 1, 1), "loaded_at": datetime(2026, 1, 2),
            }

    spec = SourceSpec("hubspot", "crm", ("crm_contacts",), lambda: True, extract)
    path = tmp_path / "w.duckdb"
    run_source(spec, path, today=date(2026, 1, 2))
    run_source(spec, path, today=date(2026, 1, 2))  # re-load merges, no duplicates
    with duckdb.connect(str(path)) as conn:
        assert conn.execute("select count(*) from raw.crm_contacts").fetchone() == (3,)
        cols = {r[0] for r in conn.execute("describe raw.crm_contacts").fetchall()}
    assert {"email_hash", "created_at", "_dlt_id"} <= cols


@pytest.fixture(scope="module")
def client(built_warehouse: Path) -> TestClient:
    from api.main import app

    return TestClient(app)


def _warehouse(built_warehouse: Path) -> duckdb.DuckDBPyConnection:
    # Same configuration as dbt's in-process connection (DuckDB refuses to mix them).
    return duckdb.connect(str(built_warehouse / "caclens.duckdb"))


def test_marts_reconcile_to_sources(built_warehouse: Path) -> None:
    with _warehouse(built_warehouse) as conn:
        raw_spend = conn.execute("select sum(spend) from raw.ad_spend_daily").fetchone()[0]
        mart_spend = conn.execute(
            "select sum(paid_spend) from marts.fct_acquisition_daily "
            "where attribution_model = 'first_touch'").fetchone()[0]
        customers = conn.execute("select count(*) from journeys.int_customers").fetchone()[0]
        credited = conn.execute(
            "select sum(new_customers) from marts.fct_acquisition_daily "
            "where attribution_model = 'linear'").fetchone()[0]
        emails = conn.execute(
            "select count(*) from information_schema.columns where column_name = 'email'"
        ).fetchone()[0]
    assert mart_spend == pytest.approx(raw_spend, rel=0.02)
    assert credited == pytest.approx(customers, rel=1e-6)  # every customer credited once
    assert emails == 0  # PII minimised: only hashes reach the warehouse


def test_health_and_catalog(client: TestClient) -> None:
    health = client.get("/v1/health").json()
    assert health["status"] == "ok" and health["data_through"] == "2026-09-30"
    catalog = client.get("/v1/metrics").json()
    assert {"cac", "ltv_cac", "payback_months"} <= {m["name"] for m in catalog["metrics"]}


def test_overview_and_fully_loaded_toggle(client: TestClient) -> None:
    paid = client.get("/v1/overview").json()
    loaded = client.get("/v1/overview?fully_loaded=true").json()
    assert paid["kpis"]["blended_cac"]["metric"] == "cac"
    assert loaded["kpis"]["blended_cac"]["metric"] == "cac_fully_loaded"
    assert loaded["kpis"]["blended_cac"]["value"] > paid["kpis"]["blended_cac"]["value"]
    channels = {c["channel"] for c in paid["channels"]}
    assert {"google_search", "meta_ads", "linkedin_ads"} <= channels


def test_metric_endpoint_matches_technical_spec(client: TestClient) -> None:
    body = client.get("/v1/metrics/cac?by=channel&period=month").json()
    assert body["columns"] == ["period", "channel", "cac"]
    assert "select" in body["sql"]
    assert client.get("/v1/metrics/cac?by=months_since_acquisition").status_code == 400


def test_channel_detail_explains_the_march_meta_spike(client: TestClient) -> None:
    body = client.get("/v1/channels/meta_ads?start=2026-03-01&end=2026-03-31").json()
    dec = body["decomposition"]
    assert dec["cac_change_pct"] > 0.2
    assert dec["drivers"][0]["factor"] == "customer_cvr"


def test_alerts_catch_the_spike_early(client: TestClient) -> None:
    alerts = client.get("/v1/alerts?channel=meta_ads").json()["alerts"]
    march = [a for a in alerts if "2026-02-20" <= a["first_detected_on"] <= "2026-04-15"]
    assert march, alerts
    leading = min(a["first_detected_on"] for a in march)
    assert leading <= "2026-03-10"  # leading indicator fires within ~2 weeks of the change


def test_payback_cohorts_and_optimiser(client: TestClient) -> None:
    payback = client.get("/v1/metrics/payback?cohort=2025-Q3").json()
    google = next(c for c in payback["curves"] if c["series"] == "google_search")
    assert google["payback_month"] is not None
    points = [p["cumulative_gross_margin_per_customer"] for p in google["points"]]
    assert points[-1] > points[0] > 0
    assert google["points"][google["payback_month"]]["cac_recovered_pct"] >= 1

    opt = client.get("/v1/optimiser").json()
    assert opt["budget"] == pytest.approx(sum(c["recommended_spend"] for c in opt["channels"]))
    assert opt["recommended_customers"] >= opt["current_customers"]


def test_attribution_compare_and_data_quality(client: TestClient) -> None:
    compare = client.get("/v1/attribution/compare?metric=new_customers").json()
    assert compare["models"][0] == "first_touch"
    email = next(r for r in compare["rows"] if r["channel"] == "email")
    assert email["values"]["last_touch"] > email["values"]["first_touch"]
    quality = client.get("/v1/data-quality").json()
    assert {m["match_method"] for m in quality["identity_matches"]} >= {"email", "domain"}


def test_ask_answers_with_queries(client: TestClient) -> None:
    body = client.post("/v1/ask", json={"question": "Why did paid social CAC jump in March?"}).json()
    assert body["planner"] == "rules"
    assert "Lead to customer CVR" in body["answer"]
    assert body["chart"]["type"] == "drivers"
    assert body["queries"][0]["tool"] == "explain_cac_change"


def test_rule_planner_passes_the_qa_eval(built_warehouse: Path) -> None:
    from api.qa.eval import run

    scores = run("rules")
    assert sum(s.passed for s in scores) >= 90
