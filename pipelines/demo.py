"""Deterministic synthetic dataset for demos, tests and the Q&A eval.

It writes the same raw tables the real connectors load (see `pipelines/schema.py`),
so dbt, the semantic layer and the app run end to end without any credentials.

Built-in story for the demo: from 2026-02-20 to 2026-04-10 a new Meta lookalike
audience brings in low-quality leads (lead -> customer CVR drops ~65%) and CPCs
rise ~20%, so paid social CAC jumps in March 2026.
"""

from __future__ import annotations

import csv
import math
import random
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import duckdb

from api.log import get_logger
from pipelines.identity import SEGMENTS, email_domain, hash_email
from pipelines.schema import RAW_SCHEMA, RAW_TABLES, ensure_raw_tables

log = get_logger(__name__)

START = date(2025, 1, 1)
END = date(2026, 9, 30)
LOADED_AT = datetime(2026, 10, 1, 6, 0, 0)
META_SPIKE = (date(2026, 2, 20), date(2026, 4, 10))


@dataclass(frozen=True)
class Campaign:
    source_system: str
    campaign_id: str
    name: str
    utm_source: str
    utm_medium: str
    channel: str
    daily_budget: float
    cpc: float
    ctr: float
    lead_cvr: float
    customer_cvr: float
    segment_mix: tuple[float, float, float]


@dataclass(frozen=True)
class OrganicSource:
    channel: str
    utm_source: str
    utm_medium: str
    utm_campaign: str | None
    leads_per_day: float
    customer_cvr: float
    segment_mix: tuple[float, float, float]


@dataclass(frozen=True)
class SegmentProfile:
    price: float
    price_sd: float
    cvr_mult: float
    monthly_churn: float
    annual_share: float
    cycle_days: tuple[int, int]


CAMPAIGNS: tuple[Campaign, ...] = (
    Campaign("google_ads", "g-101", "Brand Search", "google", "cpc", "google_search",
             260, 1.9, 0.11, 0.10, 0.12, (0.55, 0.35, 0.10)),
    Campaign("google_ads", "g-102", "Nonbrand Search", "google", "cpc", "google_search",
             480, 3.6, 0.045, 0.05, 0.10, (0.60, 0.30, 0.10)),
    Campaign("google_ads", "g-103", "Competitor Search", "google", "cpc", "google_search",
             180, 4.4, 0.035, 0.045, 0.10, (0.50, 0.35, 0.15)),
    Campaign("meta_ads", "m-201", "Prospecting Lookalike", "facebook", "paid_social", "meta_ads",
             520, 1.3, 0.012, 0.035, 0.034, (0.75, 0.20, 0.05)),
    Campaign("meta_ads", "m-202", "Retargeting", "facebook", "paid_social", "meta_ads",
             220, 0.9, 0.02, 0.05, 0.036, (0.65, 0.28, 0.07)),
    Campaign("meta_ads", "m-203", "Webinar Promo", "instagram", "paid_social", "meta_ads",
             160, 1.6, 0.015, 0.06, 0.030, (0.55, 0.35, 0.10)),
    Campaign("linkedin_ads", "l-301", "ABM Enterprise", "linkedin", "paid_social", "linkedin_ads",
             300, 8.5, 0.006, 0.05, 0.14, (0.10, 0.40, 0.50)),
    Campaign("linkedin_ads", "l-302", "Lead Gen Forms", "linkedin", "paid_social", "linkedin_ads",
             160, 6.0, 0.008, 0.09, 0.08, (0.30, 0.45, 0.25)),
)

ORGANIC: tuple[OrganicSource, ...] = (
    OrganicSource("organic_search", "google", "organic", None, 7.0, 0.075, (0.60, 0.30, 0.10)),
    OrganicSource("organic_search", "bing", "organic", None, 1.0, 0.07, (0.60, 0.30, 0.10)),
    OrganicSource("referral", "g2", "referral", "g2_profile", 1.6, 0.18, (0.45, 0.40, 0.15)),
    OrganicSource("referral", "partner_hub", "referral", "partner_program", 1.2, 0.22,
                  (0.30, 0.45, 0.25)),
    OrganicSource("email", "newsletter", "email", "monthly_newsletter", 1.5, 0.06,
                  (0.60, 0.30, 0.10)),
    OrganicSource("direct", "(direct)", "(none)", None, 1.8, 0.07, (0.55, 0.35, 0.10)),
)

SEGMENT_PROFILES = {
    "smb": SegmentProfile(99, 25, 1.15, 0.070, 0.10, (3, 21)),
    "mid_market": SegmentProfile(420, 100, 1.0, 0.035, 0.30, (10, 45)),
    "enterprise": SegmentProfile(1700, 380, 0.7, 0.016, 0.60, (30, 90)),
}

CHANNEL_CHURN_MULT = {
    "google_search": 1.0,
    "meta_ads": 1.45,
    "linkedin_ads": 0.8,
    "organic_search": 0.9,
    "referral": 0.7,
    "email": 1.0,
    "direct": 1.0,
}

# Touches that happen between becoming a lead and converting (nurture, retargeting...).
NURTURE_TOUCHES: tuple[tuple[str, str, str | None, float], ...] = (
    ("newsletter", "email", "nurture_sequence", 0.40),
    ("(direct)", "(none)", None, 0.25),
    ("facebook", "paid_social", "Retargeting", 0.15),
    ("google", "cpc", "Brand Search", 0.15),
    ("linkedin", "paid_social", "ABM Enterprise", 0.05),
)

TEAMS: dict[str, tuple[str, int, float]] = {
    # team: (role, headcount, monthly fully loaded cost per head)
    "paid_media": ("Paid media manager", 2, 10_500),
    "sdr": ("Sales development rep", 4, 6_800),
    "sales_ae": ("Account executive", 3, 11_000),
    "content": ("Content marketer", 2, 8_900),
    "marketing_ops": ("Marketing ops", 1, 9_800),
}

TOOLS: tuple[tuple[str, str, float], ...] = (
    ("HubSpot", "marketing_ops", 3_200),
    ("Gong", "sales_ae", 1_400),
    ("Semrush", "content", 450),
    ("Supermetrics", "paid_media", 300),
    ("LinkedIn Sales Navigator", "sdr", 1_100),
)

_WORDS = (
    "acme", "globex", "initech", "umbrella", "stark", "wayne", "wonka", "tyrell", "cyber",
    "hooli", "vandelay", "soylent", "aperture", "massive", "pied", "dunder", "nimbus",
    "orbit", "quantum", "vertex", "lumen", "atlas", "nova", "zenith", "harbor", "summit",
)


@dataclass
class DemoData:
    rows: dict[str, list[tuple[object, ...]]] = field(
        default_factory=lambda: {name: [] for name in RAW_TABLES}
    )

    def add(self, table: str, **values: object) -> None:
        columns = RAW_TABLES[table].columns
        values.setdefault("loaded_at", LOADED_AT)
        self.rows[table].append(tuple(values.get(c) for c in columns))


def _daterange(start: date, end: date) -> Iterable[date]:
    for n in range((end - start).days + 1):
        yield start + timedelta(days=n)


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    days_in_month = [31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(day.day, days_in_month[month - 1]))


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    threshold, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= threshold:
            return k
        k += 1


def _season(day: date) -> float:
    weekday = (1.0, 1.0, 1.0, 1.0, 0.95, 0.65, 0.6)[day.weekday()]
    month = {12: 0.85, 1: 1.08, 8: 0.92}.get(day.month, 1.0)
    months_since_start = (day.year - START.year) * 12 + day.month - START.month
    return weekday * month * (1 + 0.015 * months_since_start)


def _in_meta_spike(day: date) -> bool:
    return META_SPIKE[0] <= day <= META_SPIKE[1]


def _at(day: date, rng: random.Random, start_hour: int = 7, end_hour: int = 22) -> datetime:
    seconds = rng.randint(start_hour * 3600, end_hour * 3600 - 1)
    return datetime.combine(day, time()) + timedelta(seconds=seconds)


class _Generator:
    def __init__(self, scale: float, seed: int) -> None:
        self.scale = scale
        self.rng = random.Random(seed)
        self.data = DemoData()
        self.contact_seq = 0
        self.customer_seq = 0
        self.touch_seq = 0
        self.deal_seq = 0
        self.invoice_seq = 0
        self.domains: list[str] = []

    # -- helpers -------------------------------------------------------------------
    def _company_domain(self) -> str:
        if self.domains and self.rng.random() < 0.15:
            return self.rng.choice(self.domains)
        domain = f"{self.rng.choice(_WORDS)}{self.rng.choice(_WORDS)}{len(self.domains)}.com"
        self.domains.append(domain)
        return domain

    def _touch(self, contact_id: str, at: datetime, source: str, medium: str,
               campaign: str | None, touch_type: str) -> None:
        self.touch_seq += 1
        self.data.add(
            "crm_touchpoints",
            source_system="hubspot",
            touchpoint_id=f"tp_{self.touch_seq}",
            contact_id=contact_id,
            touched_at=at,
            utm_source=source,
            utm_medium=medium,
            utm_campaign=campaign,
            touch_type=touch_type,
        )

    # -- spend ---------------------------------------------------------------------
    def ad_day(self, day: date, campaign: Campaign) -> int:
        rng = self.rng
        spike = campaign.channel == "meta_ads" and _in_meta_spike(day)
        spend = campaign.daily_budget * self.scale * _season(day) * rng.lognormvariate(0, 0.12)
        cpc = campaign.cpc * rng.lognormvariate(0, 0.08) * (1.2 if spike else 1.0)
        clicks = max(0, round(spend / cpc))
        impressions = round(clicks / (campaign.ctr * rng.lognormvariate(0, 0.1))) if clicks else 0
        self.data.add(
            "ad_spend_daily",
            source_system=campaign.source_system,
            account_id=f"{campaign.source_system}_acct_1",
            campaign_id=campaign.campaign_id,
            campaign_name=campaign.name,
            date_day=day,
            spend=round(spend, 2),
            impressions=impressions,
            clicks=clicks,
            currency="USD",
        )
        lead_rate = campaign.lead_cvr * (0.95 if spike else 1.0)
        return _poisson(rng, clicks * lead_rate)

    # -- leads -> customers ----------------------------------------------------------
    def lead(self, day: date, channel: str, source: str, medium: str, campaign: str | None,
             customer_cvr: float, mix: Sequence[float]) -> None:
        rng = self.rng
        self.contact_seq += 1
        contact_id = str(100_000 + self.contact_seq)
        segment = rng.choices(SEGMENTS, weights=mix)[0]
        profile = SEGMENT_PROFILES[segment]
        domain = self._company_domain()
        email = f"person{self.contact_seq}@{domain}"
        created_at = _at(day, rng)

        if rng.random() < 0.35:  # an earlier anonymous visit from the same source
            visit_at = created_at - timedelta(days=rng.uniform(0.5, 10))
            if visit_at.date() >= START:
                self._touch(contact_id, visit_at, source, medium, campaign, "visit")
        self._touch(contact_id, created_at, source, medium, campaign, "form_fill")

        spike = channel == "meta_ads" and _in_meta_spike(day)
        p_convert = customer_cvr * profile.cvr_mult * (0.35 if spike else 1.0)
        converts = rng.random() < p_convert
        convert_at: datetime | None = None
        if converts:
            convert_at = created_at + timedelta(days=rng.uniform(*profile.cycle_days))
            if convert_at.date() > END:
                converts, convert_at = False, None

        horizon = convert_at or min(created_at + timedelta(days=60),
                                    datetime.combine(END, time(23)))
        for _ in range(rng.randint(0, 4) if converts else rng.randint(0, 2)):
            if horizon <= created_at:
                break
            at = created_at + (horizon - created_at) * rng.random()
            src, med, camp, _w = rng.choices(NURTURE_TOUCHES,
                                             weights=[t[3] for t in NURTURE_TOUCHES])[0]
            self._touch(contact_id, at, src, med, camp, "visit")

        self.data.add(
            "crm_contacts",
            source_system="hubspot",
            contact_id=contact_id,
            email_hash=hash_email(email),
            email_domain=domain,
            company_domain=domain,
            segment={"smb": "SMB", "mid_market": "Mid-Market", "enterprise": "Enterprise"}[segment],
            lifecycle_stage="customer" if converts else "lead",
            created_at=created_at,
            became_lead_at=created_at,
        )

        if converts or rng.random() < 0.12:
            self.deal_seq += 1
            deal_created = created_at + timedelta(days=rng.uniform(1, 7))
            closed_at = convert_at or deal_created + timedelta(days=rng.uniform(10, 60))
            self.data.add(
                "crm_deals",
                source_system="hubspot",
                deal_id=f"deal_{self.deal_seq}",
                contact_id=contact_id,
                amount=round(profile.price * 12, 2),
                stage="closedwon" if converts else "closedlost",
                is_won=converts,
                created_at=deal_created,
                closed_at=closed_at if closed_at.date() <= END else None,
            )

        if converts and convert_at is not None:
            roll = rng.random()
            if roll < 0.80:
                billing_email, crm_id = email, contact_id if rng.random() < 0.3 else None
            elif roll < 0.92:
                billing_email, crm_id = f"billing@{domain}", None
            else:
                billing_email, crm_id = f"founder{self.contact_seq}@gmail.com", None
            self.customer(convert_at, segment, channel, billing_email, crm_id)

    def customer(self, convert_at: datetime, segment: str, channel: str, email: str,
                 crm_contact_id: str | None) -> None:
        rng = self.rng
        profile = SEGMENT_PROFILES[segment]
        self.customer_seq += 1
        customer_id = f"cus_{self.customer_seq:06d}"
        self.data.add(
            "stripe_customers",
            customer_id=customer_id,
            email_hash=hash_email(email),
            email_domain=email_domain(email),
            crm_contact_id=crm_contact_id,
            created_at=convert_at,
        )
        annual = rng.random() < profile.annual_share
        price = max(29.0, round(rng.gauss(profile.price, profile.price_sd)))
        monthly_churn = min(0.5, profile.monthly_churn * CHANNEL_CHURN_MULT.get(channel, 1.0))
        step = 12 if annual else 1
        churn_per_step = 1 - (1 - monthly_churn) ** step
        amount = round(price * 12 * 0.85 if annual else price, 2)

        k = 0
        start_day = convert_at.date()
        while True:
            period_start = _add_months(start_day, k * step)
            if period_start > END:
                break
            self.invoice_seq += 1
            invoice_id = f"in_{self.invoice_seq:07d}"
            paid_at = datetime.combine(period_start, convert_at.time())
            self.data.add(
                "stripe_invoices",
                invoice_id=invoice_id,
                customer_id=customer_id,
                status="paid",
                amount_paid_cents=round(amount * 100),
                currency="usd",
                paid_at=paid_at,
                period_start=datetime.combine(period_start, time()),
                period_end=datetime.combine(_add_months(period_start, step), time()),
            )
            if k == 0 and rng.random() < 0.02:
                refund_day = paid_at + timedelta(days=rng.uniform(1, 14))
                if refund_day.date() <= END:
                    self.data.add(
                        "stripe_refunds",
                        refund_id=f"re_{self.invoice_seq}",
                        customer_id=customer_id,
                        charge_id=f"ch_{self.invoice_seq}",
                        amount_cents=round(amount * 100),
                        status="succeeded",
                        created_at=refund_day,
                    )
                break
            if rng.random() < 0.003:
                dispute_day = paid_at + timedelta(days=rng.uniform(10, 40))
                if dispute_day.date() <= END:
                    self.data.add(
                        "stripe_disputes",
                        dispute_id=f"dp_{self.invoice_seq}",
                        customer_id=customer_id,
                        charge_id=f"ch_{self.invoice_seq}",
                        amount_cents=round(amount * 100),
                        status="lost" if rng.random() < 0.6 else "won",
                        created_at=dispute_day,
                    )
            if rng.random() < churn_per_step:
                break
            k += 1

    def self_serve_signups(self, day: date) -> None:
        """Customers with no CRM footprint at all: they show up as unattributed."""
        for _ in range(_poisson(self.rng, 0.12 * self.scale * _season(day))):
            segment = self.rng.choices(SEGMENTS, weights=(0.8, 0.18, 0.02))[0]
            email = f"signup{self.customer_seq + 1}@{self.rng.choice(_WORDS)}mail{day:%y%m}.io"
            self.customer(_at(day, self.rng), segment, "direct", email, None)

    # -- costs ---------------------------------------------------------------------
    def costs(self) -> None:
        month = date(START.year, START.month, 1)
        while month <= END:
            months_in = (month.year - START.year) * 12 + month.month - START.month
            raise_factor = 1.01 ** (months_in // 3)
            for team, (role, headcount, cost) in TEAMS.items():
                heads = headcount + (1 if team == "sdr" and month >= date(2026, 1, 1) else 0)
                for i in range(heads):
                    self.data.add(
                        "payroll_costs",
                        month=month,
                        employee_id=f"emp_{team}_{i + 1:02d}",
                        team=team,
                        role=role,
                        cost=round(cost * self.scale * raise_factor, 2),
                    )
            for tool, team, cost in TOOLS:
                self.data.add("tool_costs", month=month, tool=tool, team=team,
                              cost=round(cost * self.scale, 2))
            month = _add_months(month, 1)

    def run(self) -> DemoData:
        for day in _daterange(START, END):
            for campaign in CAMPAIGNS:
                for _ in range(self.ad_day(day, campaign)):
                    self.lead(day, campaign.channel, campaign.utm_source, campaign.utm_medium,
                              campaign.name, campaign.customer_cvr, campaign.segment_mix)
            for organic in ORGANIC:
                lam = organic.leads_per_day * self.scale * _season(day)
                for _ in range(_poisson(self.rng, lam)):
                    self.lead(day, organic.channel, organic.utm_source, organic.utm_medium,
                              organic.utm_campaign, organic.customer_cvr, organic.segment_mix)
            self.self_serve_signups(day)
        self.costs()
        return self.data


def generate(scale: float = 1.0, seed: int = 42) -> DemoData:
    """Generate the synthetic raw dataset. `scale` multiplies volumes (and costs)."""
    return _Generator(scale=scale, seed=seed).run()


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return value


def write_raw(conn: duckdb.DuckDBPyConnection, data: DemoData) -> dict[str, int]:
    """Replace the raw tables with the demo data. Returns row counts per table."""
    ensure_raw_tables(conn)
    counts: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="caclens_demo_") as tmp:
        for name, table in RAW_TABLES.items():
            rows = data.rows[name]
            path = Path(tmp) / f"{name}.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(table.columns)
                writer.writerows([_csv_value(v) for v in row] for row in rows)
            col_list = ", ".join(table.columns)
            col_types = ", ".join(f"'{c}': '{t}'" for c, t in table.columns.items())
            conn.execute(f"DELETE FROM {RAW_SCHEMA}.{name}")
            conn.execute(
                f"INSERT INTO {RAW_SCHEMA}.{name} ({col_list}) "
                f"SELECT {col_list} FROM read_csv('{path.as_posix()}', header = true, "
                f"nullstr = '', columns = {{{col_types}}})"
            )
            counts[name] = len(rows)
    log.info("demo_raw_loaded", **counts)
    return counts


def load_demo(warehouse_path: Path, scale: float = 1.0, seed: int = 42) -> dict[str, int]:
    warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    data = generate(scale=scale, seed=seed)
    with duckdb.connect(str(warehouse_path)) as conn:
        return write_raw(conn, data)
