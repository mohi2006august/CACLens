"""Identity helpers used by loaders: hash emails at extraction, normalise segments."""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

_SEEDS = Path(__file__).resolve().parent.parent / "dbt" / "seeds"


def _load_free_domains() -> frozenset[str]:
    # Defined once, in the dbt seed that SQL identity stitching also uses.
    with (_SEEDS / "free_email_domains.csv").open(encoding="utf-8") as fh:
        return frozenset(row["domain"].strip().lower() for row in csv.DictReader(fh))


FREE_EMAIL_DOMAINS = _load_free_domains()

SEGMENTS = ("smb", "mid_market", "enterprise")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SEGMENT_ALIASES = {
    "smb": "smb",
    "small_business": "smb",
    "small": "smb",
    "startup": "smb",
    "mid_market": "mid_market",
    "midmarket": "mid_market",
    "mid": "mid_market",
    "mm": "mid_market",
    "enterprise": "enterprise",
    "ent": "enterprise",
    "large": "enterprise",
}


def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    value = email.strip().lower()
    return value if _EMAIL_RE.match(value) else None


def hash_email(email: str | None) -> str | None:
    value = normalize_email(email)
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


def email_domain(email: str | None) -> str | None:
    value = normalize_email(email)
    return value.split("@", 1)[1] if value else None


def normalize_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    value = domain.strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = value.split("/", 1)[0].removeprefix("www.")
    return value or None


def segment_from_employees(employees: int) -> str:
    if employees < 50:
        return "smb"
    if employees < 1000:
        return "mid_market"
    return "enterprise"


def normalize_segment(value: object) -> str:
    """Map CRM labels ("Mid-Market"), employee counts (250) or ranges ("51-200")."""
    if value is None or isinstance(value, bool):
        return "unknown"
    if isinstance(value, int | float):
        return segment_from_employees(int(value))
    text = str(value).strip().lower()
    if not text:
        return "unknown"
    label = re.sub(r"[^a-z]+", "_", text).strip("_")
    if label in _SEGMENT_ALIASES:
        return _SEGMENT_ALIASES[label]
    numbers = [int(n) for n in re.findall(r"\d+", text.replace(",", ""))]
    if numbers:
        return segment_from_employees(numbers[0])
    return "unknown"
