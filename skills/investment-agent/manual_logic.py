"""Manual-only investment logic review for an unbound registered strategy.

This module intentionally has no concept of an account, buying power, cash
balance, execution history, or purchase authority.  It answers a narrower
question for a private Discord report: does one registered plan step currently
pass the *security-level* checks needed for a human to consider it?

It never creates ``PURCHASE_READY`` or an order instruction.  The normal
account-bound strategy evaluator remains the only source of HOS purchase
authority.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
import math
from typing import Any, Iterable, Mapping

from earnings_assessment import POSITIVE
from stock_analyzer import PriceRecord
from strategy_plan import ACTIVE_FY_DECISIONS, _fetch_us_prices


MAX_PRICE_AGE_DAYS = 5


@dataclass(frozen=True)
class ManualLogicCandidate:
    """A display-only candidate.  It deliberately lacks order authority fields."""

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


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


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
    """Aggregate only verified shares; no account owner is inspected or emitted."""
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
        and str(authority.get("mode") or "").upper() == "REGISTERED_STRATEGY_ONLY"
        and not _bool(authority.get("auto_order"))
        and not _bool(authority.get("auto_sell"))
    )


def _assessment_block(order: Mapping[str, Any]) -> str | None:
    """Require a fresh official-IR POSITIVE result for every manual candidate."""
    if _bool(order.get("earnings_reviewed_ok")) and str(order.get("earnings_review_status") or "").upper() == POSITIVE:
        return None
    state = str(order.get("earnings_review_status") or "").upper()
    if state == "NEGATIVE":
        return "EARNINGS_NEGATIVE"
    if state == "NEUTRAL":
        return "EARNINGS_NEUTRAL"
    return "EARNINGS_AUDIT_REQUIRED"


def _pending_orders(strategy: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], int, Mapping[str, Any]]]:
    """Return exactly the next recorded step per order, without reconciliation."""
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


def evaluate_manual_logic_candidates(
    strategy: Mapping[str, Any],
    japanese_prices: Iterable[PriceRecord],
    *,
    financial_assets_jpy: float | None,
    holdings: Iterable[Any] = (),
    as_of: date | None = None,
) -> list[ManualLogicCandidate]:
    """Evaluate a non-account-bound security-level candidate list.

    The result is intentionally more restrictive than an unverified manual
    purchase: a full financial-assets denominator is required for concentration
    review, and every item needs a fresh POSITIVE official-IR assessment.  The
    function neither reads nor changes completion/execution state outside the
    HOS-recorded ``completed_step_ids``.
    """
    price_map = {str(record.code): record for record in japanese_prices}
    price_map.update(_fetch_us_prices(dict(strategy)))
    today = as_of or datetime.now(timezone.utc).date()
    strategy_active = str(strategy.get("status") or "").upper() == "ACTIVE"
    authority_valid = _registered_authority_valid(strategy)
    assets = _number(financial_assets_jpy, positive=True)
    shares_by_ticker = _verified_household_shares(holdings)
    pending_orders = _pending_orders(strategy)
    ticker_count: dict[str, int] = {}
    for order, _, _ in pending_orders:
        ticker = str(order.get("ticker") or "").strip()
        if ticker:
            ticker_count[ticker] = ticker_count.get(ticker, 0) + 1

    candidates: list[ManualLogicCandidate] = []
    for order, step_index, step in pending_orders:
        ticker = str(order.get("ticker") or "").strip()
        if not ticker:
            continue
        market = str(order.get("market") or "JP").upper()
        currency = str(order.get("currency") or "JPY").upper()
        limit_price = _number(step.get("limit_price"), positive=True)
        ceiling = _number(order.get("final_ceiling"), positive=True)
        shares = _integer(step.get("shares"))
        shares_rule = str(step.get("shares_rule") or "").strip() or None
        record = price_map.get(ticker)
        current_price = _number(getattr(record, "close", None), positive=True) if record else None
        price_date_value = getattr(record, "price_date", None) if record else None
        price_date = price_date_value.isoformat() if hasattr(price_date_value, "isoformat") else None
        blocks: list[str] = []
        warnings: list[str] = []

        if not strategy_active:
            blocks.append("STRATEGY_NOT_ACTIVE")
        if not authority_valid:
            blocks.append("PURCHASE_AUTHORITY_INVALID")
        if str(order.get("fy2026_decision") or "").upper() not in ACTIVE_FY_DECISIONS:
            blocks.append("FY_DECISION_NOT_ACTIVE")
        if limit_price is None:
            blocks.append("FIXED_LIMIT_REQUIRED")
        if shares is None:
            blocks.append("MANUAL_STEP_SHARES_REQUIRED")
        assessment_block = _assessment_block(order)
        if assessment_block:
            blocks.append(assessment_block)
        if order.get("conditional") and not _bool(order.get("condition_verified")):
            blocks.append("ORDER_CONDITION_REVIEW_REQUIRED")
        if step.get("condition") and not _bool(step.get("condition_verified")):
            blocks.append("STEP_CONDITION_REVIEW_REQUIRED")
        if str(order.get("benefit_verification_status") or "").upper() == "PARTIAL":
            blocks.append("BENEFIT_RECHECK_REQUIRED")
        if record is None or current_price is None:
            blocks.append("PRICE_UNAVAILABLE")
        elif not isinstance(price_date_value, date) or (today - price_date_value).days > MAX_PRICE_AGE_DAYS:
            blocks.append("STALE_PRICE")

        # A partial household valuation is never enough to clear concentration.
        if assets is None:
            blocks.append("CONCENTRATION_AUDIT_REQUIRED")
        elif current_price is not None and shares is not None:
            projected_weight = (shares_by_ticker.get(ticker, 0) + shares) * current_price / assets
            goal = strategy.get("household_goal", {})
            warning_limit = _number(goal.get("max_single_ticker_weight_warning")) if isinstance(goal, Mapping) else None
            hard_limit = _number(goal.get("max_single_ticker_weight_hard")) if isinstance(goal, Mapping) else None
            hard_limit = hard_limit if hard_limit is not None else warning_limit
            if hard_limit is None:
                blocks.append("CONCENTRATION_AUDIT_REQUIRED")
            elif projected_weight > hard_limit:
                blocks.append("CONCENTRATION_HARD_LIMIT")
            elif warning_limit is not None and projected_weight > warning_limit:
                warnings.append("CONCENTRATION_WARNING")

        if ticker_count.get(ticker, 0) > 1:
            blocks.append("MULTIPLE_REGISTERED_PLANS")

        if current_price is None:
            distance = None
            status = "DATA_ERROR"
        elif limit_price is None:
            distance = None
            status = "BLOCKED"
        else:
            distance = round((current_price - limit_price) / limit_price * 100, 2)
            if ceiling is not None and current_price > ceiling:
                status = "ABOVE_CEILING"
            elif current_price <= limit_price:
                status = "LOGIC_PASS" if not blocks else "BLOCKED"
            elif current_price <= limit_price * 1.05:
                status = "NEAR"
            else:
                status = "WAIT"

        candidates.append(ManualLogicCandidate(
            ticker=ticker,
            name=str(order.get("name") or ticker),
            market=market,
            currency=currency,
            purpose=str(order.get("purpose") or ""),
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
            blocks=sorted(set(blocks)),
            warnings=sorted(set(warnings)),
            final_ceiling=ceiling,
        ))

    # HOS keeps one daily order maximum.  This panel therefore surfaces at
    # most one security-level pass; it still does not know whether an order was
    # actually placed, so it cannot be an execution authorization.
    passes = [index for index, item in enumerate(candidates) if item.status == "LOGIC_PASS"]
    passes.sort(key=lambda index: (
        candidates[index].execution_priority,
        candidates[index].distance_to_limit_percent if candidates[index].distance_to_limit_percent is not None else 999,
        candidates[index].ticker,
    ))
    for index in passes[1:]:
        item = candidates[index]
        candidates[index] = replace(
            item,
            status="DAILY_LIMIT",
            blocks=sorted(set(item.blocks + ["DAILY_ORDER_LIMIT"])),
        )
    return candidates
