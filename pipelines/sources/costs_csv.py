"""Payroll and tool-cost CSV loaders (see `data/sample/*.csv` for the expected format)."""

from __future__ import annotations

import csv
import os
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

from api.config import resolve_path
from pipelines.sources.http import utc_now

PAYROLL_COLUMNS = ("month", "employee_id", "team", "cost")
TOOL_COLUMNS = ("month", "tool", "team", "cost")


class CostFileError(ValueError):
    """Raised when a cost CSV is missing required columns or has bad values."""


def parse_month(value: str) -> date:
    text = value.strip()
    if len(text) == 7:  # YYYY-MM
        text = f"{text}-01"
    parsed = date.fromisoformat(text[:10])
    return parsed.replace(day=1)


def parse_cost(value: str) -> float:
    return float(value.replace(",", "").replace("$", "").strip() or 0)


def _read(path: Path, required: tuple[str, ...]) -> Iterator[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in required if c not in (reader.fieldnames or [])]
        if missing:
            raise CostFileError(f"{path.name} is missing columns: {', '.join(missing)}")
        for line_no, row in enumerate(reader, start=2):
            if not any(row.values()):
                continue
            if not all((row.get(c) or "").strip() for c in required):
                raise CostFileError(f"{path.name}:{line_no} has an empty required value")
            yield row


def read_payroll(path: Path) -> Iterator[dict[str, Any]]:
    loaded_at = utc_now()
    for row in _read(path, PAYROLL_COLUMNS):
        yield {
            "month": parse_month(row["month"]),
            "employee_id": row["employee_id"].strip(),
            "team": row["team"].strip().lower(),
            "role": (row.get("role") or "").strip() or None,
            "cost": parse_cost(row["cost"]),
            "loaded_at": loaded_at,
        }


def read_tools(path: Path) -> Iterator[dict[str, Any]]:
    loaded_at = utc_now()
    for row in _read(path, TOOL_COLUMNS):
        yield {
            "month": parse_month(row["month"]),
            "tool": row["tool"].strip(),
            "team": row["team"].strip().lower(),
            "cost": parse_cost(row["cost"]),
            "loaded_at": loaded_at,
        }


def payroll_path_from_env() -> Path | None:
    raw = os.environ.get("PAYROLL_CSV_PATH")
    return resolve_path(raw) if raw else None


def tools_path_from_env() -> Path | None:
    raw = os.environ.get("TOOL_COSTS_CSV_PATH")
    return resolve_path(raw) if raw else None
