from __future__ import annotations

import math
import random
from datetime import date

import pytest

from api.analytics.alerts import AlertConfig, detect_alerts, nb_cdf, poisson_cdf
from api.analytics.cohorts import parse_cohort
from api.analytics.decomposition import Funnel, decompose
from api.analytics.optimiser import fit_curve
from api.semantic import SemanticLayer
from tests.conftest import acq_row, daterange, make_marts


def test_decomposition_terms_multiply_back_to_the_cac_change() -> None:
    base = Funnel(paid_spend=10_000, fully_loaded_spend=15_000, clicks=5_000, leads=250,
                  new_customers=25, opportunities=60)
    cur = Funnel(paid_spend=11_500, fully_loaded_spend=16_000, clicks=5_000, leads=240,
                 new_customers=14, opportunities=40)
    dec = decompose(base, cur)
    product = math.prod(1 + d.cac_effect_pct for d in dec.drivers)
    assert product == pytest.approx(1 + (dec.cac_change_pct or 0))
    assert sum(d.share_of_change for d in dec.drivers) == pytest.approx(1.0)
    assert dec.drivers[0].factor == "customer_cvr"  # the biggest mover comes first
    assert "Main driver: Lead to customer CVR" in dec.summary


def test_fully_loaded_decomposition_adds_overhead_factor() -> None:
    base = Funnel(1000, 2000, 500, 50, 5)
    cur = Funnel(1000, 3000, 500, 50, 5)
    dec = decompose(base, cur, fully_loaded=True)
    assert dec.cac_change_pct == pytest.approx(0.5)
    assert dec.drivers[0].factor == "overhead"


def test_decomposition_without_data_says_so() -> None:
    dec = decompose(Funnel.zero(), Funnel(100, 100, 10, 1, 1))
    assert dec.drivers == []
    assert "Not enough" in dec.summary


def test_poisson_cdf_matches_known_values() -> None:
    assert poisson_cdf(0, 2.0) == pytest.approx(math.exp(-2))
    assert poisson_cdf(3, 3.0) == pytest.approx(0.6472, abs=1e-4)
    assert poisson_cdf(5.9, 20.0) < 0.001  # fractional credits are floored


def test_negative_binomial_widens_poisson() -> None:
    assert nb_cdf(4, 12.0, 1.0) == pytest.approx(poisson_cdf(4, 12.0))
    # The same shortfall is less surprising in a noisier (over-dispersed) series.
    assert nb_cdf(4, 12.0, 3.0) > 5 * poisson_cdf(4, 12.0)
    total = sum(nb_cdf(k, 12.0, 3.0) - nb_cdf(k - 1, 12.0, 3.0) for k in range(1, 200))
    assert total + nb_cdf(0, 12.0, 3.0) == pytest.approx(1.0, abs=1e-6)


def _series(spike_from: date | None) -> list[dict[str, object]]:
    """Daily Meta funnel where a share of leads are good fits; a spike lowers that share."""
    rng = random.Random(7)
    rows = []
    for day in daterange(date(2025, 1, 1), 450):
        fit = 0.15 if spike_from is not None and day >= spike_from else 0.55
        good = [rng.random() < fit for _ in range(40)]
        qualified = sum(rng.random() < (0.93 if g else 0.16) for g in good)
        customers = sum(rng.random() < (0.12 if g else 0.018) for g in good)
        rows.append(acq_row(day, "meta_ads", paid_spend=1000.0, clicks=800.0, leads=40.0,
                            qualified_leads=float(qualified), new_customers=float(customers)))
    return rows


def test_alerts_fire_early_on_a_lead_quality_drop_and_stay_quiet_otherwise(
    layer: SemanticLayer,
) -> None:
    as_of = date(2026, 3, 26)
    assert detect_alerts(layer, make_marts(_series(None)), as_of, AlertConfig()) == []

    spike = date(2026, 3, 1)
    alerts = detect_alerts(layer, make_marts(_series(spike)), as_of, AlertConfig())
    early = [a for a in alerts if a.metric == "cost_per_qualified_lead"]
    cac = [a for a in alerts if a.metric == "cac"]
    assert len(early) == 1 and len(cac) == 1
    # Lead time: qualified leads are known at form fill, so the warning is within 3 days.
    assert (early[0].first_detected_on - spike).days < 3
    assert early[0].drivers[0]["factor"] == "qualified_rate"
    assert early[0].status == "open"
    # CAC confirms later, once (fewer) customers arrive.
    assert cac[0].first_detected_on > early[0].first_detected_on
    assert cac[0].severity == "critical"
    assert cac[0].drivers[0]["factor"] == "customer_cvr"


def test_fit_curve_recovers_elasticity_and_shrinks_thin_data() -> None:
    points = [(s, 0.05 * s ** 0.6) for s in (5_000, 8_000, 12_000, 20_000, 30_000, 45_000)]
    curve = fit_curve(points)
    assert curve.fitted
    assert curve.b == pytest.approx(0.6, abs=0.01)
    assert curve.marginal_cac(20_000) > curve.marginal_cac(10_000)  # diminishing returns

    flat = fit_curve([(10_000, 20.0)] * 8)  # no spend variation: fall back to the prior
    assert not flat.fitted
    assert flat.b == pytest.approx(0.7)
    assert flat.customers(10_000) == pytest.approx(20.0)


@pytest.mark.parametrize(
    ("value", "start", "end"),
    [("2026-Q1", date(2026, 1, 1), date(2026, 3, 1)),
     ("2025-11", date(2025, 11, 1), date(2025, 11, 1)),
     ("2025", date(2025, 1, 1), date(2025, 12, 1))],
)
def test_parse_cohort(value: str, start: date, end: date) -> None:
    rng = parse_cohort(value)
    assert (rng.start, rng.end) == (start, end)


def test_parse_cohort_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_cohort("2026-Q7")
