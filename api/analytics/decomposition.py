"""FR-06 CAC driver decomposition.

    CAC = spend / customers = CPC / (lead CVR x customer CVR)          (paid)
    CAC = overhead x CPC / (lead CVR x customer CVR)                    (fully loaded)

where CPC = spend/clicks, lead CVR = leads/clicks, customer CVR = customers/leads and
overhead = fully loaded spend / paid spend. Taking logs makes the change additive:

    ln(CAC1/CAC0) = ln(CPC1/CPC0) - ln(LCVR1/LCVR0) - ln(CCVR1/CCVR0) [+ ln(OH1/OH0)]

so each factor's share of the CAC change is its log term over the total.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Funnel:
    paid_spend: float
    fully_loaded_spend: float
    clicks: float
    leads: float
    new_customers: float

    @classmethod
    def from_row(cls, row: dict[str, Any] | None) -> Funnel:
        row = row or {}
        return cls(
            paid_spend=float(row.get("paid_spend") or 0),
            fully_loaded_spend=float(row.get("fully_loaded_spend") or 0),
            clicks=float(row.get("clicks") or 0),
            leads=float(row.get("leads") or 0),
            new_customers=float(row.get("new_customers") or 0),
        )

    def __add__(self, other: Funnel) -> Funnel:
        return Funnel(
            self.paid_spend + other.paid_spend,
            self.fully_loaded_spend + other.fully_loaded_spend,
            self.clicks + other.clicks,
            self.leads + other.leads,
            self.new_customers + other.new_customers,
        )

    def cac(self, fully_loaded: bool = False) -> float | None:
        spend = self.fully_loaded_spend if fully_loaded else self.paid_spend
        return spend / self.new_customers if self.new_customers > 0 else None

    def factors(self, fully_loaded: bool) -> dict[str, float] | None:
        if min(self.paid_spend, self.clicks, self.leads, self.new_customers) <= 0:
            return None
        factors = {
            "cpc": self.paid_spend / self.clicks,
            "lead_cvr": self.leads / self.clicks,
            "customer_cvr": self.new_customers / self.leads,
        }
        if fully_loaded:
            factors["overhead"] = self.fully_loaded_spend / self.paid_spend
        return factors


FACTOR_LABELS = {
    "cpc": "CPC",
    "lead_cvr": "Click to lead CVR",
    "customer_cvr": "Lead to customer CVR",
    "overhead": "People and tool cost per $ of media",
}
# +1: CAC moves with the factor; -1: CAC moves against it.
FACTOR_DIRECTION = {"cpc": 1, "lead_cvr": -1, "customer_cvr": -1, "overhead": 1}


@dataclass(frozen=True)
class Driver:
    factor: str
    label: str
    baseline: float
    current: float
    change_pct: float
    cac_effect_pct: float
    share_of_change: float


@dataclass(frozen=True)
class Decomposition:
    cac_baseline: float | None
    cac_current: float | None
    cac_change_pct: float | None
    drivers: list[Driver]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "drivers": [asdict(d) for d in self.drivers]}


def _pct(value: float) -> str:
    return f"{value * 100:+.0f}%"


def decompose(
    baseline: Funnel, current: Funnel, fully_loaded: bool = False, subject: str = "CAC"
) -> Decomposition:
    cac0, cac1 = baseline.cac(fully_loaded), current.cac(fully_loaded)
    change = (cac1 / cac0 - 1) if cac0 and cac1 else None
    f0, f1 = baseline.factors(fully_loaded), current.factors(fully_loaded)
    if not f0 or not f1 or cac0 is None or cac1 is None:
        return Decomposition(cac0, cac1, change, [], f"Not enough funnel data to decompose {subject}.")

    total_log = math.log(cac1 / cac0)
    drivers: list[Driver] = []
    for factor in f0:
        term = FACTOR_DIRECTION[factor] * math.log(f1[factor] / f0[factor])
        drivers.append(
            Driver(
                factor=factor,
                label=FACTOR_LABELS[factor],
                baseline=f0[factor],
                current=f1[factor],
                change_pct=f1[factor] / f0[factor] - 1,
                cac_effect_pct=math.exp(term) - 1,
                share_of_change=term / total_log if abs(total_log) > 1e-9 else 0.0,
            )
        )
    # Largest contributors in the direction of the overall change first.
    drivers.sort(key=lambda d: d.cac_effect_pct * (1 if total_log >= 0 else -1), reverse=True)

    lead = drivers[0]
    summary = (
        f"{subject} {_pct(change or 0)} ({cac1:,.0f} vs {cac0:,.0f}). "
        f"Main driver: {lead.label} {_pct(lead.change_pct)}, "
        f"which moved {subject} {_pct(lead.cac_effect_pct)} on its own."
    )
    return Decomposition(cac0, cac1, change, drivers, summary)
