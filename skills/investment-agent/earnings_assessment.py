"""Audited earnings assessment for HOS.

This module is advisory only. It never submits orders and it never bypasses the
existing purchase-authority gates. It turns verified IR facts into a transparent
assessment that the existing HOS strategy can use as one input.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, asdict
from datetime import date
import json
import math
from pathlib import Path
from typing import Any, Mapping

POSITIVE = "POSITIVE"
NEUTRAL = "NEUTRAL"
NEGATIVE = "NEGATIVE"
NEEDS_DATA = "NEEDS_DATA"

RECOMMENDATION = {
    POSITIVE: "MAINTAIN_BUY_CANDIDATE",
    NEUTRAL: "PAUSE_AND_WATCH",
    NEGATIVE: "SUSPEND_AND_REVIEW_REPLACEMENT",
    NEEDS_DATA: "IR_REVIEW_REQUIRED",
}

HARD_NEGATIVE_FLAGS = {
    "GOING_CONCERN",
    "MATERIAL_RESTATEMENT",
    "MATERIAL_ACCOUNTING_ISSUE",
    "FRAUD_OR_REGULATORY_CRISIS",
    "DIVIDEND_SUSPENDED",
    "COVENANT_OR_CAPITAL_BREACH",
}

@dataclass(frozen=True)
class EarningsAssessment:
    ticker: str
    state: str
    recommendation: str
    score: int | None
    period: str | None
    report_date: str | None
    expires_on: str | None
    source_verified: bool
    reasons: list[str]
    hard_flags: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_assessment_book(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "reviews": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("earnings assessment book must be a JSON object")
    payload.setdefault("reviews", {})
    return payload


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _d(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _u(value: Any) -> str:
    return str(value or "").strip().upper()


def assess_snapshot(ticker: str, snapshot: Mapping[str, Any] | None, *, as_of: date | None = None) -> EarningsAssessment:
    today = as_of or date.today()
    if not snapshot:
        return EarningsAssessment(ticker, NEEDS_DATA, RECOMMENDATION[NEEDS_DATA], None, None, None, None, False, ["IR_SNAPSHOT_MISSING"], [])

    period = str(snapshot.get("period") or "") or None
    report_date = str(snapshot.get("report_date") or "") or None
    expires_on = str(snapshot.get("expires_on") or "") or None
    verified = bool(snapshot.get("source_verified"))
    hard_flags = sorted({_u(x) for x in snapshot.get("hard_flags", []) if str(x).strip()})
    missing: list[str] = []
    if not verified:
        missing.append("SOURCE_NOT_VERIFIED")
    if not snapshot.get("source_url"):
        missing.append("OFFICIAL_SOURCE_URL_MISSING")
    if _d(report_date) is None:
        missing.append("REPORT_DATE_MISSING")
    expiry = _d(expires_on)
    if expiry is None:
        missing.append("REVIEW_EXPIRY_MISSING")
    elif today >= expiry:
        missing.append("REVIEW_EXPIRED_FOR_NEXT_EARNINGS")
    if missing:
        return EarningsAssessment(ticker, NEEDS_DATA, RECOMMENDATION[NEEDS_DATA], None, period, report_date, expires_on, verified, missing, hard_flags)

    hard_hit = sorted(set(hard_flags) & HARD_NEGATIVE_FLAGS)
    if hard_hit:
        return EarningsAssessment(ticker, NEGATIVE, RECOMMENDATION[NEGATIVE], 0, period, report_date, expires_on, True, [f"HARD_NEGATIVE:{x}" for x in hard_hit], hard_flags)

    guidance = _u(snapshot.get("guidance_status"))
    dividend = _u(snapshot.get("dividend_status"))
    guidance_revision = _num(snapshot.get("guidance_revision_pct"))
    revenue_yoy = _num(snapshot.get("revenue_yoy_pct"))
    primary_profit_yoy = _num(snapshot.get("primary_profit_yoy_pct"))
    net_income_yoy = _num(snapshot.get("net_income_yoy_pct"))
    progress = _num(snapshot.get("full_year_profit_progress_pct"))
    margin_change = _num(snapshot.get("margin_change_pt"))

    evidence_errors: list[str] = []
    if guidance not in {"RAISED", "UNCHANGED", "LOWERED"}:
        evidence_errors.append("GUIDANCE_STATUS_MISSING")
    if dividend not in {"RAISED", "UNCHANGED", "LOWERED", "NO_DIVIDEND_POLICY"}:
        evidence_errors.append("DIVIDEND_STATUS_MISSING")
    if sum(v is not None for v in (revenue_yoy, primary_profit_yoy, net_income_yoy, progress)) < 2:
        evidence_errors.append("OPERATING_METRICS_INSUFFICIENT")
    if evidence_errors:
        return EarningsAssessment(ticker, NEEDS_DATA, RECOMMENDATION[NEEDS_DATA], None, period, report_date, expires_on, True, evidence_errors, hard_flags)

    negative: list[str] = []
    if dividend == "LOWERED":
        negative.append("DIVIDEND_CUT")
    if guidance == "LOWERED" and (guidance_revision is None or guidance_revision <= -5):
        negative.append("MATERIAL_GUIDANCE_CUT")
    if net_income_yoy is not None and net_income_yoy <= -30:
        negative.append("NET_INCOME_COLLAPSE")
    if primary_profit_yoy is not None and primary_profit_yoy <= -30:
        negative.append("PRIMARY_PROFIT_COLLAPSE")
    if negative:
        return EarningsAssessment(ticker, NEGATIVE, RECOMMENDATION[NEGATIVE], 20, period, report_date, expires_on, True, negative, hard_flags)

    score = 50
    score += 12 if guidance == "RAISED" else 7 if guidance == "UNCHANGED" else -12
    score += 10 if dividend == "RAISED" else 5 if dividend in {"UNCHANGED", "NO_DIVIDEND_POLICY"} else -15
    for value, strong, weak in ((revenue_yoy, 5, -10), (primary_profit_yoy, 10, -15), (net_income_yoy, 10, -15)):
        if value is None:
            continue
        if value >= strong:
            score += 7
        elif value >= 0:
            score += 3
        elif value <= weak:
            score -= 10
        else:
            score -= 4
    if progress is not None:
        score += 5 if progress >= 22 else -8 if progress < 15 else 0
    if margin_change is not None:
        score += 4 if margin_change >= 1 else -8 if margin_change <= -3 else 0

    watch: list[str] = []
    if guidance == "LOWERED":
        watch.append("MILD_GUIDANCE_CUT")
    if primary_profit_yoy is not None and -30 < primary_profit_yoy < -15:
        watch.append("PROFIT_DETERIORATION")
    if net_income_yoy is not None and -30 < net_income_yoy < -15:
        watch.append("NET_INCOME_DETERIORATION")
    if progress is not None and progress < 15:
        watch.append("LOW_FULL_YEAR_PROGRESS")
    if margin_change is not None and margin_change <= -3:
        watch.append("MARGIN_DETERIORATION")

    state = NEUTRAL if score < 55 or watch else POSITIVE
    reasons = watch or ["VERIFIED_RESULTS_AND_OUTLOOK_OK"]
    return EarningsAssessment(ticker, state, RECOMMENDATION[state], max(0, min(100, int(round(score)))), period, report_date, expires_on, True, reasons, hard_flags)


def apply_earnings_assessments(strategy: Mapping[str, Any], book: Mapping[str, Any], *, as_of: date | None = None) -> dict[str, Any]:
    result = deepcopy(dict(strategy))
    reviews = book.get("reviews", {}) if isinstance(book, Mapping) else {}
    audit: list[dict[str, Any]] = []
    for account_name, account in result.get("accounts", {}).items():
        for order in account.get("orders", []):
            if not order.get("earnings_wait"):
                continue
            ticker = str(order.get("ticker") or "")
            assessment = assess_snapshot(ticker, reviews.get(ticker), as_of=as_of)
            order["earnings_review_status"] = assessment.state
            order["earnings_reviewed_ok"] = assessment.state == POSITIVE
            order["post_earnings_recommendation"] = assessment.recommendation
            order["earnings_review_score"] = assessment.score
            order["earnings_review_period"] = assessment.period
            order["earnings_review_report_date"] = assessment.report_date
            order["earnings_review_expires_on"] = assessment.expires_on
            order["earnings_review_reasons"] = list(assessment.reasons)
            order["replacement_review_required"] = assessment.state == NEGATIVE
            audit.append({"account": account_name, **assessment.to_dict()})
    result["earnings_review_audit"] = audit
    return result
