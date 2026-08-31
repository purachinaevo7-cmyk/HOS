from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from manual_logic import evaluate_manual_logic_candidates
from stock_analyzer import PriceRecord


def strategy(*orders):
    return {
        "strategy_id": "DUMMY_PRIVATE_PLAN",
        "status": "ACTIVE",
        "purchase_authority": {
            "mode": "REGISTERED_STRATEGY_ONLY",
            "auto_order": False,
            "auto_sell": False,
        },
        "household_goal": {
            "max_single_ticker_weight_warning": 0.15,
            "max_single_ticker_weight_hard": 0.25,
        },
        "accounts": {"member_logic_a": {"orders": list(orders)}},
    }


def order(ticker="1111", *, priority=1, limit=100, shares=10):
    return {
        "ticker": ticker,
        "name": f"Example {ticker}",
        "market": "JP",
        "currency": "JPY",
        "purpose": "CORE_DIVIDEND",
        "fy2026_decision": "BUY_2026_CORE",
        "execution_priority": priority,
        "earnings_wait": True,
        "earnings_review_status": "POSITIVE",
        "earnings_reviewed_ok": True,
        "order_steps": [{"step_id": f"{ticker}-1", "shares": shares, "limit_price": limit}],
        "completed_step_ids": [],
    }


def price(ticker="1111", close=95, price_date=None):
    return PriceRecord(ticker, f"Example {ticker}", close, close + 1, price_date or date.today(), "mock", "medium")


def test_manual_logic_passes_security_checks_without_account_or_execution_reconciliation():
    candidate_order = order()
    candidate_order["execution_reconciliation_required"] = True
    plan = strategy(candidate_order)
    # Intentionally insufficient runtime fields must not be used by this
    # display-only evaluator; actual PURCHASE_READY remains separately gated.
    plan["accounts"]["member_logic_a"].update({
        "buying_power_jpy_env": "UNSET_BUYING_POWER",
        "target_budget_jpy_env": "UNSET_BUDGET",
    })

    candidate = evaluate_manual_logic_candidates(
        plan,
        [price()],
        financial_assets_jpy=100_000,
        holdings=[],
    )[0]

    assert candidate.status == "LOGIC_PASS"
    assert "ACCOUNT_BUYING_POWER_REQUIRED" not in candidate.blocks
    assert "EXECUTION_RECONCILIATION_REQUIRED" not in candidate.blocks
    assert not hasattr(candidate, "account")
    assert not hasattr(candidate, "purchase_flag")
    assert not hasattr(candidate, "actionability")


def test_manual_logic_fails_closed_for_ir_missing_stale_price_and_unverified_conditions():
    base = order()
    base["earnings_review_status"] = "NEEDS_DATA"
    base["earnings_reviewed_ok"] = False
    base["conditional"] = True
    base["condition_verified"] = False
    candidate = evaluate_manual_logic_candidates(
        strategy(base),
        [price(price_date=date.today() - timedelta(days=6))],
        financial_assets_jpy=100_000,
        holdings=[],
    )[0]

    assert candidate.status == "BLOCKED"
    assert {"EARNINGS_AUDIT_REQUIRED", "STALE_PRICE", "ORDER_CONDITION_REVIEW_REQUIRED"}.issubset(candidate.blocks)


def test_manual_logic_requires_complete_asset_denominator_and_enforces_hard_concentration_limit():
    plan = strategy(order())
    incomplete = evaluate_manual_logic_candidates(plan, [price()], financial_assets_jpy=None, holdings=[])[0]
    assert incomplete.status == "BLOCKED"
    assert "CONCENTRATION_AUDIT_REQUIRED" in incomplete.blocks

    concentrated = evaluate_manual_logic_candidates(plan, [price()], financial_assets_jpy=1_000, holdings=[])[0]
    assert concentrated.status == "BLOCKED"
    assert "CONCENTRATION_HARD_LIMIT" in concentrated.blocks


def test_manual_logic_only_uses_first_recorded_pending_step_without_mutating_completed_state():
    candidate_order = order()
    candidate_order["completed_step_ids"] = ["1111-1"]
    candidate_order["order_steps"] = [
        {"step_id": "1111-1", "shares": 10, "limit_price": 100},
        {"step_id": "1111-2", "shares": 5, "limit_price": 90},
    ]
    original = deepcopy(candidate_order)
    candidate = evaluate_manual_logic_candidates(
        strategy(candidate_order),
        [price(close=85)],
        financial_assets_jpy=100_000,
        holdings=[{"ticker": "1111", "shares": 20, "verified": True}],
    )[0]

    assert candidate.step_id == "1111-2"
    assert candidate.step_index == 2
    assert candidate.shares == 5
    assert candidate_order == original


def test_manual_logic_limits_the_display_to_one_daily_candidate():
    first, second = order("1111", priority=1), order("2222", priority=2)
    result = evaluate_manual_logic_candidates(
        strategy(first, second),
        [price("1111"), price("2222")],
        financial_assets_jpy=100_000,
        holdings=[],
    )
    statuses = {candidate.ticker: candidate.status for candidate in result}
    assert statuses == {"1111": "LOGIC_PASS", "2222": "DAILY_LIMIT"}


def test_manual_logic_does_not_merge_duplicate_registered_plans():
    first, duplicate = order("1111", priority=1), order("1111", priority=2)
    result = evaluate_manual_logic_candidates(
        strategy(first, duplicate),
        [price("1111")],
        financial_assets_jpy=100_000,
        holdings=[],
    )
    assert all(candidate.status == "BLOCKED" for candidate in result)
    assert all("MULTIPLE_REGISTERED_PLANS" in candidate.blocks for candidate in result)
