"""Human investment-review cards for registered HOS strategies.

This module is deliberately separate from purchase authority. It answers the
question a household member needs before a manual order: is this registered
idea attractive enough to consider at today's price, and what still needs a
human check? It never creates ``PURCHASE_READY``, an order instruction, or an
execution record.

The account-bound evaluator remains stricter. In particular, an order which
explicitly declares ``earnings_wait`` stays locked until a current official-IR
assessment passes. A plan which did not declare that wait must not be made to
look like it can only be considered after the next earnings release.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import math
from typing import Any, Iterable, Mapping

from earnings_assessment import NEGATIVE, NEUTRAL, POSITIVE, assess_snapshot
from stock_analyzer import PriceRecord
from strategy_plan import ACTIVE_FY_DECISIONS, _fetch_us_prices


MAX_PRICE_AGE_DAYS = 5
OFFICIAL_DIVIDEND_SOURCES = {
    "OFFICIAL_IR",
    "OFFICIAL_DISCLOSURE",
    "OFFICIAL_FUND_DOCUMENT",
    "OFFICIAL_ETF_ISSUER",
}
CORE_DIVIDEND_ROLES = {"CORE_DIVIDEND", "DEFENSIVE", "FINANCIAL_INCOME"}
EVENT_REVIEW_REASONS = {
    "NEXT_EARNINGS_IMMINENT",
    "NEXT_EARNINGS_ALREADY_DUE",
}
REVIEW_SCORE_FIELDS = (
    "cash_dividend_contribution",
    "earnings_quality_and_growth",
    "valuation_and_entry_margin",
    "portfolio_diversification",
    "shareholder_return_durability",
)
ROLE_SCORE_WEIGHTS = {
    "CORE_DIVIDEND": (35, 20, 20, 15, 10),
    "DEFENSIVE": (30, 20, 20, 20, 10),
    "FINANCIAL_INCOME": (35, 20, 20, 15, 10),
    "QUALITY_GROWTH": (10, 35, 25, 20, 10),
    "GROWTH_SATELLITE": (5, 40, 25, 20, 10),
    "BENEFIT_SATELLITE": (15, 20, 25, 15, 25),
}
DEFAULT_SCORE_WEIGHTS = (30, 25, 20, 15, 10)


@dataclass(frozen=True)
class ManualLogicCandidate:
    """A display-only, no-authority investment-review card."""

    ticker: str
    name: str
    market: str
    currency: str
    purpose: str
    execution_priority: int
    step_id: str
    step_index: int
    shares: int | None
    shares_rule: str | None
    limit_price: float | None
    current_price: float | None
    price_date: str | None
    distance_to_limit_percent: float | None
    status: str
    blocks: list[str]
    warnings: list[str]
    final_ceiling: float | None
    entry_status: str = "DATA_REQUIRED"
    earnings_state: str = "UNREVIEWED"
    thesis_state: str = "REGISTERED_PLAN"
    dividend_state: str = "UNCONFIRMED"
    projected_weight: float | None = None
    investment_score: float | None = None
    dividend_yield: float | None = None
    planned_step_count: int = 1
    combined_pending_shares: int | None = None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _number(value: Any, *, positive: bool = False) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or (positive and result <= 0):
        return None
    return result


def _integer(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _as_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _first_pending_step(order: Mapping[str, Any]) -> tuple[int, Mapping[str, Any]] | None:
    completed = {str(value) for value in order.get("completed_step_ids", [])}
    steps = order.get("order_steps", [])
    if not isinstance(steps, list):
        return None
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, Mapping):
            continue
        step_id = str(step.get("step_id") or f"step-{index}")
        if step_id not in completed:
            return index, step
    return None


def _verified_household_shares(holdings: Iterable[Any]) -> dict[str, int]:
    """Aggregate only verified shares; account ownership is never emitted."""
    totals: dict[str, int] = {}
    for holding in holdings:
        if not isinstance(holding, Mapping) or not holding.get("verified", True):
            continue
        ticker = str(holding.get("ticker") or "").strip()
        shares = _integer(holding.get("shares"))
        if ticker and shares is not None:
            totals[ticker] = totals.get(ticker, 0) + shares
    return totals


def _registered_authority_valid(strategy: Mapping[str, Any]) -> bool:
    authority = strategy.get("purchase_authority", {})
    return (
        isinstance(authority, Mapping)
        and _upper(authority.get("mode")) == "REGISTERED_STRATEGY_ONLY"
        and not _bool(authority.get("auto_order"))
        and not _bool(authority.get("auto_sell"))
    )


def _pending_orders(strategy: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], int, Mapping[str, Any]]]:
    """Return the HOS-recorded next step for every plan without reconciliation."""
    result: list[tuple[Mapping[str, Any], int, Mapping[str, Any]]] = []
    accounts = strategy.get("accounts", {})
    if not isinstance(accounts, Mapping):
        return result
    for account in accounts.values():
        if not isinstance(account, Mapping):
            continue
        orders = account.get("orders", [])
        if not isinstance(orders, list):
            continue
        for order in orders:
            if not isinstance(order, Mapping):
                continue
            pending = _first_pending_step(order)
            if pending is not None:
                result.append((order, pending[0], pending[1]))
    return result


def _review_row(order: Mapping[str, Any], ticker: str, reviews: Mapping[str, Any]) -> Mapping[str, Any] | None:
    inline = order.get("investment_review")
    if isinstance(inline, Mapping):
        return inline
    row = reviews.get(ticker) if isinstance(reviews, Mapping) else None
    return row if isinstance(row, Mapping) else None


def _weighted_review_score(review: Mapping[str, Any], role: str) -> tuple[float | None, str | None]:
    raw_scores = review.get("scores") if isinstance(review.get("scores"), Mapping) else review
    values: list[float] = []
    any_present = False
    for field in REVIEW_SCORE_FIELDS:
        value = _number(raw_scores.get(field)) if isinstance(raw_scores, Mapping) else None
        any_present = any_present or value is not None
        if value is None:
            return (None, "INCOMPLETE") if any_present else (None, None)
        if not 0 <= value <= 100:
            return None, "INVALID"
        values.append(value)
    weights = ROLE_SCORE_WEIGHTS.get(role, DEFAULT_SCORE_WEIGHTS)
    return round(sum(value * weight for value, weight in zip(values, weights)) / sum(weights), 1), None


def _investment_case_assessment(
    order: Mapping[str, Any],
    ticker: str,
    reviews: Mapping[str, Any],
    today: date,
) -> tuple[str, float | None, list[str], list[str], list[str]]:
    """Return thesis state, score, hard blocks, review blocks, and warnings."""
    review = _review_row(order, ticker, reviews)
    if review is None:
        return "REGISTERED_PLAN", None, [], [], ["INVESTMENT_REVIEW_NOT_REGISTERED"]

    hard: list[str] = []
    needs_review: list[str] = []
    warnings: list[str] = []
    verified = _bool(review.get("source_verified"))
    reviewed_on = _as_date(review.get("reviewed_on"))
    valid_until = _as_date(review.get("valid_until") or review.get("expires_on"))
    evidence_id = next((str(review.get(key) or "").strip() for key in ("source_url", "source_document_id", "source_id") if str(review.get(key) or "").strip()), "")
    if not verified:
        warnings.append("INVESTMENT_REVIEW_UNVERIFIED")
    if reviewed_on is None:
        warnings.append("INVESTMENT_REVIEW_DATE_MISSING")
    elif reviewed_on > today:
        needs_review.append("INVESTMENT_REVIEW_INVALID")
    if not evidence_id:
        warnings.append("INVESTMENT_REVIEW_EVIDENCE_MISSING")
    if valid_until is None:
        warnings.append("INVESTMENT_REVIEW_VALIDITY_MISSING")
    elif today > valid_until:
        needs_review.append("INVESTMENT_REVIEW_EXPIRED")

    thesis = _upper(review.get("investment_thesis_status") or review.get("thesis_status") or review.get("status"))
    valuation = _upper(review.get("valuation_status") or review.get("valuation"))
    dividend = _upper(review.get("dividend_outlook") or review.get("dividend_status"))
    quality = _upper(review.get("quality_status") or review.get("earnings_quality_status"))
    if thesis in {"BROKEN", "INVALID", "NEGATIVE", "PAUSE"}:
        hard.append("INVESTMENT_THESIS_BROKEN")
    elif thesis in {"WATCH", "REVIEW", "WEAKENING"}:
        needs_review.append("INVESTMENT_THESIS_REVIEW_REQUIRED")
    elif thesis not in {"VALID", "CONFIRMED", "MAINTAIN", "POSITIVE"}:
        warnings.append("INVESTMENT_THESIS_STATUS_MISSING" if not thesis else "INVESTMENT_REVIEW_INVALID")
    if valuation in {"EXPENSIVE", "OVERVALUED", "AVOID"}:
        needs_review.append("VALUATION_REVIEW_REQUIRED")
    elif valuation not in {"ATTRACTIVE", "FAIR", "UNDERVALUED", "REASONABLE"}:
        warnings.append("VALUATION_STATUS_MISSING" if not valuation else "INVESTMENT_REVIEW_INVALID")
    if quality in {"WEAK", "DETERIORATING", "NEGATIVE"}:
        needs_review.append("BUSINESS_QUALITY_REVIEW_REQUIRED")
    elif quality not in {"STRONG", "STABLE", "POSITIVE"}:
        warnings.append("BUSINESS_QUALITY_STATUS_MISSING" if not quality else "INVESTMENT_REVIEW_INVALID")
    if dividend in {"CUT", "LOWERED", "SUSPENDED", "NO_DIVIDEND"}:
        hard.append("DIVIDEND_THESIS_BROKEN")
    elif dividend in {"RISK", "WEAKENING", "REVIEW"}:
        needs_review.append("DIVIDEND_DURABILITY_REVIEW_REQUIRED")
    elif dividend not in {"GROWING", "RAISED", "STABLE", "UNCHANGED", "NOT_APPLICABLE"}:
        warnings.append("DIVIDEND_OUTLOOK_MISSING" if not dividend else "INVESTMENT_REVIEW_INVALID")

    score, score_state = _weighted_review_score(review, _upper(order.get("purpose")))
    if score_state == "INVALID":
        needs_review.append("INVESTMENT_REVIEW_INVALID")
    elif score_state == "INCOMPLETE":
        warnings.append("INVESTMENT_REVIEW_SCORE_INCOMPLETE")
    elif score is None:
        warnings.append("INVESTMENT_REVIEW_SCORE_MISSING")
    minimum = _number(review.get("minimum_score"))
    if score is not None and score < (minimum if minimum is not None else 55):
        needs_review.append("INVESTMENT_REVIEW_SCORE_TOO_LOW")

    metadata_complete = (
        verified
        and reviewed_on is not None
        and reviewed_on <= today
        and bool(evidence_id)
        and valid_until is not None
        and today <= valid_until
        and thesis in {"VALID", "CONFIRMED", "MAINTAIN", "POSITIVE"}
        and valuation in {"ATTRACTIVE", "FAIR", "UNDERVALUED", "REASONABLE"}
        and quality in {"STRONG", "STABLE", "POSITIVE"}
        and dividend in {"GROWING", "RAISED", "STABLE", "UNCHANGED", "NOT_APPLICABLE"}
        and score is not None
    )
    state = "VALIDATED" if metadata_complete and not hard and not needs_review else "PARTIAL"
    return state, score, hard, needs_review, warnings


def _earnings_assessment(
    order: Mapping[str, Any],
    ticker: str,
    ir_audit_status: Mapping[str, Any],
    official_assessment: Any | None,
) -> tuple[str, list[str], list[str], list[str]]:
    """Use a current official assessment when present; never trust a raw green flag.

    ``apply_earnings_assessments`` intentionally annotates only orders that
    explicitly wait for earnings.  The manual review layer must nevertheless
    show a current *official* result for every ticker when it exists.  A
    strategy JSON field saying ``POSITIVE`` is not provenance, so it can never
    create a green card by itself.  Negative or neutral legacy fields are
    retained as conservative stop/review facts until an official refresh says
    otherwise.
    """
    raw_state = _upper(order.get("earnings_review_status"))
    raw_reasons = {
        _upper(reason)
        for reason in order.get("earnings_review_reasons", [])
        if str(reason).strip()
    }
    official_state = _upper(getattr(official_assessment, "state", ""))
    official_reasons = {
        _upper(reason)
        for reason in (getattr(official_assessment, "reasons", []) or [])
        if str(reason).strip()
    }

    # A successfully evaluated official snapshot takes precedence over a
    # stale field copied into the strategy.  It is the only source that can
    # mark earnings POSITIVE in this display.
    if official_state == NEGATIVE:
        return "NEGATIVE", ["EARNINGS_NEGATIVE"], [], []
    if official_state == NEUTRAL:
        return "NEUTRAL", [], ["EARNINGS_NEUTRAL"], []
    if official_state == POSITIVE:
        return "POSITIVE", [], [], []

    # A known adverse result must remain visible even when price data is stale
    # or the official refresh is temporarily unavailable.
    if raw_state == NEGATIVE:
        return "NEGATIVE", ["EARNINGS_NEGATIVE"], [], []
    if raw_state == NEUTRAL:
        return "NEUTRAL", [], ["EARNINGS_NEUTRAL"], []

    reasons = official_reasons or raw_reasons
    if reasons & EVENT_REVIEW_REASONS:
        return "EVENT_REVIEW", [], ["EARNINGS_EVENT_REVIEW_REQUIRED"], []
    if "REVIEW_EXPIRED_FOR_NEXT_EARNINGS" in reasons:
        return "REVIEW_EXPIRED", [], ["EARNINGS_REVIEW_EXPIRED"], []
    if _bool(order.get("earnings_wait")):
        # ``earnings_wait`` remains a hard gate in the account-bound
        # PURCHASE_READY path.  This display-only review should not turn that
        # into "buy only twice a year": outside an actual report event it is a
        # visible condition for the human, not a fabricated negative result.
        return "AUDIT_REQUIRED", [], [], ["EARNINGS_AUDIT_REQUIRED"]

    audit = _upper(ir_audit_status.get(ticker)) if isinstance(ir_audit_status, Mapping) else ""
    if audit == "IR_FETCH_OR_VALIDATION_FAILED":
        warning = "OFFICIAL_IR_FETCH_WARNING"
    elif audit == "OFFICIAL_SOURCE_REQUIRED":
        warning = "OFFICIAL_IR_SOURCE_REQUIRED"
    else:
        warning = "EARNINGS_NOT_CURRENTLY_AUDITED"
    return "UNREVIEWED", [], [], [warning]


def _duplicate_plan_signature(order: Mapping[str, Any], step: Mapping[str, Any]) -> str:
    """Return the non-account execution facts that must agree to aggregate a ticker.

    Shares and Step ids are deliberately excluded: matching plans may be
    combined for display, while a different price, condition, role, cap, or
    inline review is treated as an ambiguous plan rather than silently merged.
    """
    payload = {
        "name": str(order.get("name") or ""),
        "market": _upper(order.get("market")) or "JP",
        "currency": _upper(order.get("currency")) or "JPY",
        "purpose": _upper(order.get("purpose")),
        "fy_decision": _upper(order.get("fy2026_decision")),
        "limit_price": _number(step.get("limit_price"), positive=True),
        "final_ceiling": _number(order.get("final_ceiling"), positive=True),
        "earnings_wait": _bool(order.get("earnings_wait")),
        "conditional": _bool(order.get("conditional")),
        "condition": str(order.get("condition") or ""),
        "condition_verified": _bool(order.get("condition_verified")),
        "step_condition": str(step.get("condition") or ""),
        "step_condition_verified": _bool(step.get("condition_verified")),
        "benefit_verification_status": _upper(order.get("benefit_verification_status")),
        "strategy_conflict": _bool(order.get("strategy_conflict")),
        "investment_review": order.get("investment_review"),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)


def _dividend_assessment(
    ticker: str,
    role: str,
    current_price: float | None,
    forecasts: Mapping[str, Any],
    today: date,
) -> tuple[str, float | None, list[str], list[str]]:
    """Evaluate ordinary-dividend evidence; special dividends are excluded."""
    forecast = forecasts.get(ticker) if isinstance(forecasts, Mapping) else None
    if not isinstance(forecast, Mapping):
        return "UNCONFIRMED", None, [], ["DIVIDEND_FORECAST_UNCONFIRMED"]
    valid_source = _bool(forecast.get("source_verified")) and _upper(forecast.get("source_type")) in OFFICIAL_DIVIDEND_SOURCES
    expires = _as_date(forecast.get("expires_on"))
    ordinary = _number(forecast.get("ordinary_annual_per_share"))
    if not valid_source or expires is None or today > expires or ordinary is None:
        return "UNCONFIRMED", None, [], ["DIVIDEND_FORECAST_UNCONFIRMED"]
    ratio = 1.0
    if _upper(forecast.get("dividend_basis")) == "UNDERLYING_SHARE":
        ratio = _number(forecast.get("adr_ratio")) or 0.0
        if ratio <= 0:
            return "UNCONFIRMED", None, [], ["DIVIDEND_FORECAST_UNCONFIRMED"]
    yield_value = ordinary * ratio / current_price if current_price and current_price > 0 else None
    if role in CORE_DIVIDEND_ROLES and ordinary * ratio <= 0:
        return "NO_ORDINARY_DIVIDEND", yield_value, ["ORDINARY_DIVIDEND_REVIEW_REQUIRED"], []
    return "CONFIRMED", round(yield_value, 6) if yield_value is not None else None, [], []


def evaluate_manual_logic_candidates(
    strategy: Mapping[str, Any],
    japanese_prices: Iterable[PriceRecord],
    *,
    financial_assets_jpy: float | None,
    holdings: Iterable[Any] = (),
    investment_reviews: Mapping[str, Any] | None = None,
    dividend_forecasts: Mapping[str, Any] | None = None,
    earnings_book: Mapping[str, Any] | None = None,
    ir_audit_status: Mapping[str, Any] | None = None,
    as_of: date | None = None,
) -> list[ManualLogicCandidate]:
    """Return all registered security-level investment-review cards.

    Comparing several attractive ideas is not the same action as placing several
    orders, so the one-order-per-day execution cap is not applied here. Actual
    ``PURCHASE_READY`` enforcement is unchanged elsewhere.
    """
    price_map = {str(record.code): record for record in japanese_prices}
    price_map.update(_fetch_us_prices(dict(strategy)))
    today = as_of or datetime.now(timezone.utc).date()
    strategy_active = _upper(strategy.get("status")) == "ACTIVE"
    authority_valid = _registered_authority_valid(strategy)
    assets = _number(financial_assets_jpy, positive=True)
    shares_by_ticker = _verified_household_shares(holdings)
    pending_orders = _pending_orders(strategy)
    reviews = investment_reviews if isinstance(investment_reviews, Mapping) else {}
    forecasts = dividend_forecasts if isinstance(dividend_forecasts, Mapping) else {}
    earnings_reviews = earnings_book.get("reviews", {}) if isinstance(earnings_book, Mapping) else {}
    earnings_reviews = earnings_reviews if isinstance(earnings_reviews, Mapping) else {}
    ir_status = ir_audit_status if isinstance(ir_audit_status, Mapping) else {}

    grouped_pending: dict[str, list[tuple[int, Mapping[str, Any], int, Mapping[str, Any]]]] = {}
    for record_index, (order, step_index, step) in enumerate(pending_orders):
        ticker = str(order.get("ticker") or "").strip()
        if not ticker:
            continue
        grouped_pending.setdefault(ticker, []).append((record_index, order, step_index, step))

    pending_count: dict[str, int] = {ticker: len(group) for ticker, group in grouped_pending.items()}
    combined_shares: dict[str, int | None] = {}
    representative_index: dict[str, int] = {}
    equivalent_plans: dict[str, bool] = {}
    for ticker, group in grouped_pending.items():
        representative_index[ticker] = group[0][0]
        shares = [_integer(step.get("shares")) for _, _, _, step in group]
        combined_shares[ticker] = sum(value for value in shares if value is not None) if all(value is not None for value in shares) else None
        signatures = {_duplicate_plan_signature(order, step) for _, order, _, step in group}
        equivalent_plans[ticker] = len(signatures) == 1

    candidates: list[ManualLogicCandidate] = []
    for record_index, (order, step_index, step) in enumerate(pending_orders):
        ticker = str(order.get("ticker") or "").strip()
        if not ticker or record_index != representative_index.get(ticker):
            continue
        market = _upper(order.get("market")) or "JP"
        currency = _upper(order.get("currency")) or "JPY"
        purpose = _upper(order.get("purpose"))
        limit_price = _number(step.get("limit_price"), positive=True)
        ceiling = _number(order.get("final_ceiling"), positive=True)
        step_shares = _integer(step.get("shares"))
        has_duplicate_plan = pending_count.get(ticker, 0) > 1
        plan_is_equivalent = equivalent_plans.get(ticker, True)
        combined_pending = combined_shares.get(ticker)
        # An equivalent duplicate is one aggregated review card.  If plans
        # conflict, showing an apparent total would invite a double order, so
        # require strategy repair and withhold a manual quantity instead.
        shares = combined_pending if (has_duplicate_plan and plan_is_equivalent) else step_shares
        if has_duplicate_plan and not plan_is_equivalent:
            shares = None
        shares_rule = str(step.get("shares_rule") or "").strip() or None
        record = price_map.get(ticker)
        current_price = _number(getattr(record, "close", None), positive=True) if record else None
        price_date_value = getattr(record, "price_date", None) if record else None
        price_date = price_date_value.isoformat() if hasattr(price_date_value, "isoformat") else None
        data_blocks: list[str] = []
        hard_blocks: list[str] = []
        review_blocks: list[str] = []
        warnings: list[str] = []
        projected_weight: float | None = None

        if not strategy_active:
            data_blocks.append("STRATEGY_NOT_ACTIVE")
        if not authority_valid:
            data_blocks.append("PURCHASE_AUTHORITY_INVALID")
        if _upper(order.get("fy2026_decision")) not in ACTIVE_FY_DECISIONS:
            data_blocks.append("FY_DECISION_NOT_ACTIVE")
        if limit_price is None:
            data_blocks.append("FIXED_LIMIT_REQUIRED")
        if step_shares is None or (has_duplicate_plan and combined_pending is None):
            data_blocks.append("MANUAL_STEP_SHARES_REQUIRED")
        if has_duplicate_plan and not plan_is_equivalent:
            review_blocks.append("PLAN_CONFLICT")
        if _bool(order.get("conditional")) and not _bool(order.get("condition_verified")):
            review_blocks.append("ORDER_CONDITION_REVIEW_REQUIRED")
        if step.get("condition") and not _bool(step.get("condition_verified")):
            review_blocks.append("STEP_CONDITION_REVIEW_REQUIRED")
        if _upper(order.get("benefit_verification_status")) == "PARTIAL":
            review_blocks.append("BENEFIT_RECHECK_REQUIRED")
        if _bool(order.get("strategy_conflict")):
            review_blocks.append("PLAN_CONFLICT")
        if record is None or current_price is None:
            data_blocks.append("PRICE_UNAVAILABLE")
        elif not isinstance(price_date_value, date) or (today - price_date_value).days > MAX_PRICE_AGE_DAYS:
            data_blocks.append("STALE_PRICE")

        official_snapshot = earnings_reviews.get(ticker)
        official_assessment = assess_snapshot(ticker, official_snapshot, as_of=today) if isinstance(official_snapshot, Mapping) else None
        earnings_state, earnings_hard, earnings_review, earnings_warning = _earnings_assessment(
            order,
            ticker,
            ir_status,
            official_assessment,
        )
        hard_blocks.extend(earnings_hard)
        review_blocks.extend(earnings_review)
        warnings.extend(earnings_warning)
        thesis_state, investment_score, thesis_hard, thesis_review, thesis_warning = _investment_case_assessment(order, ticker, reviews, today)
        hard_blocks.extend(thesis_hard)
        review_blocks.extend(thesis_review)
        warnings.extend(thesis_warning)
        dividend_state, dividend_yield, dividend_review, dividend_warning = _dividend_assessment(ticker, purpose, current_price, forecasts, today)
        review_blocks.extend(dividend_review)
        warnings.extend(dividend_warning)

        if assets is None:
            data_blocks.append("CONCENTRATION_AUDIT_REQUIRED")
        elif current_price is not None and combined_pending is not None:
            projected_shares = shares_by_ticker.get(ticker, 0) + combined_pending
            projected_weight = projected_shares * current_price / assets
            goal = strategy.get("household_goal", {})
            warning_limit = _number(goal.get("max_single_ticker_weight_warning")) if isinstance(goal, Mapping) else None
            hard_limit = _number(goal.get("max_single_ticker_weight_hard")) if isinstance(goal, Mapping) else None
            hard_limit = hard_limit if hard_limit is not None else warning_limit
            if hard_limit is None:
                data_blocks.append("CONCENTRATION_AUDIT_REQUIRED")
            elif projected_weight > hard_limit:
                hard_blocks.append("CONCENTRATION_HARD_LIMIT")
            elif warning_limit is not None and projected_weight > warning_limit:
                warnings.append("CONCENTRATION_WARNING")

        if current_price is None or limit_price is None:
            distance = None
            entry_status = "DATA_REQUIRED"
        else:
            distance = round((current_price - limit_price) / limit_price * 100, 2)
            if ceiling is not None and current_price > ceiling:
                entry_status = "ABOVE_CEILING"
            elif current_price <= limit_price:
                entry_status = "BUY_ZONE"
            elif current_price <= limit_price * 1.05:
                entry_status = "NEAR"
            else:
                entry_status = "WAIT_PRICE"

        if hard_blocks:
            status = "PAUSE"
        elif data_blocks:
            status = "DATA_REQUIRED"
        elif review_blocks:
            status = "REVIEW_REQUIRED"
        elif entry_status == "BUY_ZONE":
            status = "BUY_CONSIDER" if not warnings else "CONDITIONAL_CONSIDER"
        elif entry_status == "NEAR":
            status = "NEAR"
        elif entry_status == "ABOVE_CEILING":
            status = "ABOVE_CEILING"
        else:
            status = "WAIT_PRICE"

        candidates.append(ManualLogicCandidate(
            ticker=ticker,
            name=str(order.get("name") or ticker),
            market=market,
            currency=currency,
            purpose=purpose,
            execution_priority=int(order.get("execution_priority") or 99),
            step_id=str(step.get("step_id") or f"{ticker}-{step_index}"),
            step_index=step_index,
            shares=shares,
            shares_rule=shares_rule,
            limit_price=limit_price,
            current_price=current_price,
            price_date=price_date,
            distance_to_limit_percent=distance,
            status=status,
            blocks=sorted(set(data_blocks + hard_blocks + review_blocks)),
            warnings=sorted(set(warnings)),
            final_ceiling=ceiling,
            entry_status=entry_status,
            earnings_state=earnings_state,
            thesis_state=thesis_state,
            dividend_state=dividend_state,
            projected_weight=round(projected_weight, 6) if projected_weight is not None else None,
            investment_score=investment_score,
            dividend_yield=dividend_yield,
            planned_step_count=pending_count.get(ticker, 1),
            combined_pending_shares=combined_pending if plan_is_equivalent else None,
        ))
    return candidates
