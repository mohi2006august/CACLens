from __future__ import annotations

import math
import random
from datetime import date

import pytest

from api.analytics.alerts import AlertConfig, detect_alerts, poisson_cdf
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


def _series(spike_from: date | None) -> list[dict[str, object]]:
    rng = random.Random(7)
    rows = []
    for day in daterange(date(2025, 1, 1), 450):
        cvr = 0.1 if spike_from is None or day < spike_from else 0.03
        leads = 40
        rows.append(acq_row(day, "meta_ads", paid_spend=1000.0, clicks=800.0, leads=leads,
                            opportunities=float(sum(rng.random() < 3 * cvr for _ in range(leads))),
                            new_customers=float(sum(rng.random() < cvr for _ in range(leads)))))
    return rows


def test_alerts_fire_on_a_real_spike_and_stay_quiet_otherwise(layer: SemanticLayer) -> None:
    as_of = date(2026, 3, 26)
    quiet = detect_alerts(layer, make_marts(_series(None)), as_of, AlertConfig())
    assert quiet == []

    spike = date(2026, 3, 1)
    alerts = detect_alerts(layer, make_marts(_series(spike)), as_of, AlertConfig())
    cac = [a for a in alerts if a.metric == "cac"]
    assert len(cac) == 1
    assert spike <= cac[0].first_detected_on <= date(2026, 3, 10)
    assert cac[0].severity == "critical"
    assert cac[0].drivers[0]["factor"] == "customer_cvr"
    assert cac[0].status == "open"


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
