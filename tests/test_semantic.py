from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from api.semantic import MetricQuery, QueryFilter, SemanticError, SemanticLayer
from tests.conftest import acq_row, make_marts, rev_row


def test_every_metric_compiles(layer: SemanticLayer) -> None:
    for name in layer.metrics:
        dims = layer.metric_dimensions(name)
        compiled = layer.compile(MetricQuery(metrics=[name], dimensions=dims[:1],
                                             grain=layer.metric_min_grain(name)))
        assert compiled.sql.startswith("with cte0")


def test_catalog_lists_formulas_and_variants(layer: SemanticLayer) -> None:
    catalog = {m["name"]: m for m in layer.catalog()["metrics"]}
    assert catalog["cac"]["formula"] == "paid spend / new customers"
    assert catalog["cac"]["fully_loaded_variant"] == "cac_fully_loaded"
    assert "months_since_acquisition" not in catalog["cac"]["dimensions"]
    assert catalog["ltv"]["min_grain"] == "month"


def test_values_are_bound_parameters_not_sql(layer: SemanticLayer) -> None:
    evil = "meta_ads'; drop table marts.fct_acquisition_daily; --"
    compiled = layer.compile(MetricQuery(
        metrics=["cac"], filters=[QueryFilter(dimension="campaign", value=evil)]))
    assert evil not in compiled.sql
    assert evil in compiled.params
    assert "''" in compiled.display_sql()  # quotes are escaped in the display copy


@pytest.mark.parametrize(
    ("query", "message"),
    [
        (MetricQuery(metrics=["nope"]), "unknown metric"),
        (MetricQuery(metrics=["cac"], dimensions=["months_since_acquisition"]), "not available"),
        (MetricQuery(metrics=["ltv"], grain="day"), "finer than"),
        (MetricQuery(metrics=["cac"], filters=[QueryFilter(dimension="segment", value="huge")]),
         "invalid value"),
        (MetricQuery(metrics=["cac"], attribution_model="made_up"), "invalid value"),
        (MetricQuery(metrics=["cac"], start=date(2026, 2, 1), end=date(2026, 1, 1)), "start"),
        (MetricQuery(metrics=["cac"], filters=[QueryFilter(dimension="drop", value="x")]),
         "unknown dimension"),
    ],
)
def test_invalid_queries_are_rejected(layer: SemanticLayer, query: MetricQuery,
                                      message: str) -> None:
    with pytest.raises(SemanticError, match=message):
        layer.compile(query)


def test_ratio_and_filters_compute_correctly(layer: SemanticLayer) -> None:
    day = date(2026, 3, 1)
    conn = make_marts([
        acq_row(day, "meta_ads", paid_spend=900.0, new_customers=3.0, clicks=300.0),
        acq_row(day, "google_search", paid_spend=400.0, new_customers=4.0),
        acq_row(day, "unattributed", new_customers=1.0),
        acq_row(day, "meta_ads", paid_spend=999.0, new_customers=1.0,
                attribution_model="last_touch"),
    ])
    rows = {r["channel"]: r for r in layer.query(
        conn, MetricQuery(metrics=["cac", "cpc"], dimensions=["channel"])).rows}
    assert rows["meta_ads"]["cac"] == pytest.approx(300.0)
    assert rows["meta_ads"]["cpc"] == pytest.approx(3.0)
    assert rows["unattributed"]["cac"] == 0.0

    total = layer.query(conn, MetricQuery(metrics=["cac", "paid_cac", "unattributed_share"])).rows[0]
    assert total["cac"] == pytest.approx(1300 / 8)
    assert total["paid_cac"] == pytest.approx(1300 / 7)  # paid channels only in denominator
    assert total["unattributed_share"] == pytest.approx(1 / 8)


def test_lagged_cac_uses_previous_month_spend(layer: SemanticLayer) -> None:
    conn = make_marts([
        acq_row(date(2026, 1, 15), paid_spend=1000.0, new_customers=2.0),
        acq_row(date(2026, 2, 15), paid_spend=3000.0, new_customers=4.0),
    ])
    rows = layer.query(conn, MetricQuery(metrics=["cac", "cac_lagged"], grain="month",
                                         start=date(2026, 2, 1), end=date(2026, 2, 28))).rows
    assert len(rows) == 1
    assert rows[0]["cac"] == pytest.approx(750.0)
    assert rows[0]["cac_lagged"] == pytest.approx(250.0)  # January spend / February customers


def test_metrics_from_two_models_join_on_dimensions(layer: SemanticLayer) -> None:
    month = date(2026, 3, 1)
    conn = make_marts(
        [acq_row(month, paid_spend=1000.0, new_customers=2.0)],
        [rev_row(month, active_customers=10.0, starting_customers=10.0, churned_customers=1.0,
                 net_revenue=2000.0, gross_margin_revenue=1600.0)],
    )
    row = layer.query(conn, MetricQuery(metrics=["cac", "arpa_gm", "monthly_churn", "ltv",
                                                 "ltv_cac", "payback_months"],
                                        dimensions=["channel"], grain="month")).rows[0]
    assert row["arpa_gm"] == pytest.approx(160.0)
    assert row["ltv"] == pytest.approx(160.0 / 0.1)
    assert row["ltv_cac"] == pytest.approx(1600.0 / 500.0)
    assert row["payback_months"] == pytest.approx(500.0 / 160.0)


def test_ltv_is_capped_at_five_years_without_churn(layer: SemanticLayer) -> None:
    month = date(2026, 3, 1)
    conn = make_marts([], [rev_row(month, active_customers=5.0, starting_customers=5.0,
                                   gross_margin_revenue=500.0, net_revenue=625.0)])
    row = layer.query(conn, MetricQuery(metrics=["ltv"])).rows[0]
    assert row["ltv"] == pytest.approx(100.0 * 60)


def test_bad_derived_expression_is_rejected(tmp_path: Path) -> None:
    spec = (Path(__file__).parent.parent / "semantic" / "metrics.yml").read_text()
    spec = spec.replace('expr: "{ltv} / nullif({cac}, 0)"',
                        'expr: "{ltv} / (select 1)"')
    path = tmp_path / "metrics.yml"
    path.write_text(spec)
    with pytest.raises(SemanticError, match="unsupported expression"):
        SemanticLayer.from_yaml(path)


def test_metric_cycles_are_rejected(tmp_path: Path) -> None:
    spec = (Path(__file__).parent.parent / "semantic" / "metrics.yml").read_text()
    spec = spec.replace('expr: "{ltv} / nullif({cac}, 0)"', 'expr: "{ltv_cac} * 2"')
    path = tmp_path / "metrics.yml"
    path.write_text(spec)
    with pytest.raises(SemanticError, match="cycle"):
        SemanticLayer.from_yaml(path)
