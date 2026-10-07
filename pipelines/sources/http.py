"""Shared HTTP plumbing for connectors: retries, timeouts and structured errors."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from api.log import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT = 60


class SourceError(RuntimeError):
    """Raised when a source API returns an error we cannot recover from."""


def utc_now() -> datetime:
    """Naive UTC timestamp; the warehouse stores every timestamp as naive UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


def make_session(headers: dict[str, str] | None = None) -> requests.Session:
    retry = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "caclens/0.1", **(headers or {})})
    return session


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    source: str,
    params: dict[str, Any] | list[tuple[str, Any]] | None = None,
    json: Any = None,
    data: dict[str, Any] | None = None,
) -> Any:
    response = session.request(
        method, url, params=params, json=json, data=data, timeout=DEFAULT_TIMEOUT
    )
    if response.status_code >= 400:
        # Never log the URL query: some APIs echo tokens in pagination links.
        log.error(
            "source_http_error",
            source=source,
            status=response.status_code,
            path=urlparse(url).path,
            body=response.text[:500],
        )
        raise SourceError(f"{source} returned HTTP {response.status_code}")
    return response.json()
