"""FR-06 CAC driver decomposition.

    CAC = spend / customers = CPC / (lead CVR x customer CVR)          (paid)
    CAC = overhead x CPC / (lead CVR x customer CVR)                    (fully loaded)

where CPC = spend/clicks, lead CVR = leads/clicks, customer CVR = customers/leads and
overhead = fully loaded spend / paid spend. Taking logs makes the change additive:

    ln(CAC1/CAC0) = ln(CPC1/CPC0) - ln(LCVR1/LCVR0) - ln(CCVR1/CCVR0) [+ ln(OH1/OH0)]

so each factor's share of the CAC change is its log term over the total. The same
identity decomposes the early-warning costs, swapping the last factor: cost per
qualified lead uses the lead qualification rate (known at form fill) and cost per
opportunity the lead-to-opportunity rate (known within days).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

Outcome = Literal["new_customers", "opportunities", "qualified_leads"]


@dataclass(frozen=True)
class Funnel:
    paid_spend: float
    fully_loaded_spend: float
    clicks: float
    leads: float
    new_customers: float
    opportunities: float = 0.0
    qualified_leads: float = 0.0

    @classmethod
    def zero(cls) -> Funnel:
        return cls(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    @classmethod
    def from_row(cls, row: dict[str, Any] | None) -> Funnel:
        row = row or {}
        return cls(
            paid_spend=float(row.get("paid_spend") or 0),
            fully_loaded_spend=float(row.get("fully_loaded_spend") or 0),
            clicks=float(row.get("clicks") or 0),
            leads=float(row.get("leads") or 0),
            new_customers=float(row.get("new_customers") or 0),
            opportunities=float(row.get("opportunities") or 0),
            qualified_leads=float(row.get("qualified_leads") or 0),
        )

    def __add__(self, other: Funnel) -> Funnel:
        return Funnel(
            self.paid_spend + other.paid_spend,
            self.fully_loaded_spend + other.fully_loaded_spend,
            self.clicks + other.clicks,
            self.leads + other.leads,
            self.new_customers + other.new_customers,
            self.opportunities + other.opportunities,
            self.qualified_leads + other.qualified_leads,
        )

    def __sub__(self, other: Funnel) -> Funnel:
        return Funnel(
            self.paid_spend - other.paid_spend,
            self.fully_loaded_spend - other.fully_loaded_spend,
            self.clicks - other.clicks,
            self.leads - other.leads,
            self.new_customers - other.new_customers,
            self.opportunities - other.opportunities,
            self.qualified_leads - other.qualified_leads,
        )

    def outcome(self, outcome: Outcome) -> float:
        value: float = getattr(self, outcome)
        return value

    def spend(self, fully_loaded: bool) -> float:
        return self.fully_loaded_spend if fully_loaded else self.paid_spend

    def cost_per(self, outcome: Outcome = "new_customers", fully_loaded: bool = False
                 ) -> float | None:
        count = self.outcome(outcome)
        return self.spend(fully_loaded) / count if count > 0 else None

    def cac(self, fully_loaded: bool = False) -> float | None:
        return self.cost_per("new_customers", fully_loaded)

    def factors(self, fully_loaded: bool, outcome: Outcome = "new_customers"
                ) -> dict[str, float] | None:
        count = self.outcome(outcome)
        if min(self.paid_spend, self.clicks, self.leads, count) <= 0:
            return None
        factors = {
            "cpc": self.paid_spend / self.clicks,
            "lead_cvr": self.leads / self.clicks,
            OUTCOME_FACTOR[outcome]: count / self.leads,
        }
        if fully_loaded:
            factors["overhead"] = self.fully_loaded_spend / self.paid_spend
        return factors


OUTCOME_FACTOR = {"new_customers": "customer_cvr", "opportunities": "opportunity_rate",
                  "qualified_leads": "qualified_rate"}
FACTOR_LABELS = {
    "cpc": "CPC",
    "lead_cvr": "Click to lead CVR",
    "customer_cvr": "Lead to customer CVR",
    "opportunity_rate": "Lead to opportunity rate",
    "qualified_rate": "Lead qualification rate",
    "overhead": "People and tool cost per $ of media",
}
# +1: cost moves with the factor; -1: cost moves against it.
FACTOR_DIRECTION = {"cpc": 1, "lead_cvr": -1, "customer_cvr": -1, "opportunity_rate": -1,
                    "qualified_rate": -1, "overhead": 1}


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
    baseline: Funnel,
    current: Funnel,
    fully_loaded: bool = False,
    subject: str = "CAC",
    outcome: Outcome = "new_customers",
) -> Decomposition:
    cost0 = baseline.cost_per(outcome, fully_loaded)
    cost1 = current.cost_per(outcome, fully_loaded)
    change = (cost1 / cost0 - 1) if cost0 and cost1 else None
    f0, f1 = baseline.factors(fully_loaded, outcome), current.factors(fully_loaded, outcome)
    if not f0 or not f1 or cost0 is None or cost1 is None:
        return Decomposition(cost0, cost1, change, [],
                             f"Not enough funnel data to decompose {subject}.")

    total_log = math.log(cost1 / cost0)
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
        f"{subject} {_pct(change or 0)} (${cost1:,.0f} vs ${cost0:,.0f}). "
        f"Main driver: {lead.label} {_pct(lead.change_pct)}, "
        f"which moved {subject} {_pct(lead.cac_effect_pct)} on its own."
    )
    return Decomposition(cost0, cost1, change, drivers, summary)
