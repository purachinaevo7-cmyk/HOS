"""Fail-closed ingestion of normalized facts from an official IR endpoint.

An arbitrary PDF or web page must never be guessed into a purchase approval.
The private profile therefore registers an exact HTTPS endpoint, its expected
official host, and a JSON document containing the normalized earnings facts.
Unsupported documents and any transport or validation error become
``NEEDS_DATA`` through an unverified snapshot.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, asdict
from datetime import date
import json
from typing import Any, Callable, Mapping
from urllib.parse import urlparse
from urllib.request import Request, urlopen


OFFICIAL_SOURCE_TYPES = {"OFFICIAL_IR", "OFFICIAL_DISCLOSURE"}
MAX_RESPONSE_BYTES = 1_000_000


@dataclass(frozen=True)
class IRIngestionAudit:
    ticker: str
    status: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _safe_host(url: Any) -> str:
    try:
        parsed = urlparse(str(url))
        if parsed.scheme != "https":
            return ""
        return (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _source_is_registered_official(source: Mapping[str, Any]) -> bool:
    url = str(source.get("url") or source.get("source_url") or "")
    host = _safe_host(url)
    declared_host = str(source.get("official_host") or "").lower().rstrip(".")
    return (
        bool(source.get("official_source_verified"))
        and str(source.get("source_type") or "").upper() in OFFICIAL_SOURCE_TYPES
        and bool(host)
        and bool(declared_host)
        and host == declared_host
    )


def _failed_snapshot(source: Mapping[str, Any]) -> dict[str, Any]:
    """A deliberately incomplete record that cannot pass earnings assessment."""
    return {
        "source_verified": False,
        "source_url": str(source.get("url") or source.get("source_url") or ""),
        "report_date": None,
        "expires_on": None,
    }


def _read_json(url: str, opener: Callable[..., Any]) -> Mapping[str, Any] | None:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "HOS-Stock-Watch/1.0"})
    response = opener(request, timeout=15)
    try:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    if len(raw) > MAX_RESPONSE_BYTES:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    nested = payload.get("snapshot")
    return nested if isinstance(nested, Mapping) else payload


def _normalise_snapshot(source: Mapping[str, Any], payload: Mapping[str, Any], today: date) -> dict[str, Any] | None:
    # Do not manufacture metrics from prose. A structured document must state
    # the fields that the assessor itself requires.
    required = ("period", "report_date", "expires_on", "guidance_status", "dividend_status")
    if any(payload.get(key) in (None, "") for key in required):
        return None
    report_date = str(payload.get("report_date"))
    expires_on = str(payload.get("expires_on"))
    try:
        if date.fromisoformat(expires_on) <= today:
            return None
        date.fromisoformat(report_date)
    except ValueError:
        return None
    snapshot = dict(payload)
    snapshot["source_verified"] = True
    snapshot["source_url"] = str(source.get("url") or source.get("source_url"))
    snapshot["source_type"] = str(source.get("source_type")).upper()
    return snapshot


def ingest_official_ir_sources(
    profile: Mapping[str, Any],
    earnings_book: Mapping[str, Any],
    *,
    as_of: date | None = None,
    opener: Callable[..., Any] = urlopen,
) -> tuple[dict[str, Any], list[IRIngestionAudit]]:
    """Return an in-memory earnings book and value-free ingestion status.

    Registered sources are private profile data. Failed retrieval replaces the
    related review with an unverified record, so it cannot leave a stale
    ``POSITIVE`` assessment active. No URL, issuer name, or response is logged.
    """
    today = as_of or date.today()
    result = deepcopy(dict(earnings_book))
    reviews = result.setdefault("reviews", {})
    if not isinstance(reviews, dict):
        reviews = result["reviews"] = {}
    configured = profile.get("earnings_ir_sources", {}) if isinstance(profile, Mapping) else {}
    if isinstance(configured, list):
        sources = {str(item.get("ticker") or ""): item for item in configured if isinstance(item, Mapping)}
    elif isinstance(configured, Mapping):
        sources = {str(ticker): item for ticker, item in configured.items() if isinstance(item, Mapping)}
    else:
        sources = {}
    audit: list[IRIngestionAudit] = []
    for ticker, source in sources.items():
        if not ticker:
            continue
        if not _source_is_registered_official(source):
            reviews[ticker] = _failed_snapshot(source)
            audit.append(IRIngestionAudit(ticker, "OFFICIAL_SOURCE_REQUIRED"))
            continue
        url = str(source.get("url") or source.get("source_url"))
        try:
            payload = _read_json(url, opener)
            snapshot = _normalise_snapshot(source, payload or {}, today) if payload else None
        except Exception:
            snapshot = None
        if snapshot is None:
            reviews[ticker] = _failed_snapshot(source)
            audit.append(IRIngestionAudit(ticker, "IR_FETCH_OR_VALIDATION_FAILED"))
            continue
        reviews[ticker] = snapshot
        audit.append(IRIngestionAudit(ticker, "OFFICIAL_IR_REFRESHED"))
    return result, audit
