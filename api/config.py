"""Runtime settings. Secrets and paths come only from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WAREHOUSE = "data/caclens.duckdb"
DEFAULT_QA_MODEL = "claude-opus-5-5"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def resolve_path(raw: str) -> Path:
    """Resolve a path relative to the repo root (env values are usually relative)."""
    path = Path(raw).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


@dataclass(frozen=True)
class Settings:
    warehouse_path: Path
    semantic_path: Path
    demo: bool
    anthropic_api_key: str | None
    qa_model: str
    alert_window_days: int
    alert_baseline_days: int
    alert_threshold_pct: float
    alert_min_customers: int
    cors_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> Settings:
        origins = os.environ.get("CACLENS_CORS_ORIGINS", "http://localhost:3000")
        return cls(
            warehouse_path=resolve_path(os.environ.get("WAREHOUSE_URL", DEFAULT_WAREHOUSE)),
            semantic_path=resolve_path(
                os.environ.get("CACLENS_SEMANTIC_PATH", "semantic/metrics.yml")
            ),
            demo=_env_bool("CACLENS_DEMO", True),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            qa_model=os.environ.get("CACLENS_QA_MODEL", DEFAULT_QA_MODEL),
            alert_window_days=_env_int("CACLENS_ALERT_WINDOW_DAYS", 14),
            alert_baseline_days=_env_int("CACLENS_ALERT_BASELINE_DAYS", 56),
            alert_threshold_pct=_env_float("CACLENS_ALERT_THRESHOLD_PCT", 0.30),
            alert_min_customers=_env_int("CACLENS_ALERT_MIN_CUSTOMERS", 5),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
