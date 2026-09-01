from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from manual_logic import evaluate_manual_logic_candidates
from stock_analyzer import PriceRecord


AS_OF = date(2026, 8, 31)


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


def order(ticker="1111", *, priority=1, limit=100, shares=10, purpose="QUALITY_GROWTH", earnings_wait=False):
    return {
        "ticker": ticker,
        "name": f"Example {ticker}",
        "market": "JP",
        "currency": "JPY",
        "purpose": purpose,
        "fy2026_decision": "BUY_2026_CORE",
        "execution_priority": priority,
        "earnings_wait": earnings_wait,
        "order_steps": [{"step_id": f"{ticker}-1", "shares": shares, "limit_price": limit}],
        "completed_step_ids": [],
    }


def price(ticker="1111", close=95, price_date=AS_OF):
    return PriceRecord(ticker, f"Example {ticker}", close, close + 1, price_date, "mock", "medium")


def investment_review(*, valid_until="2026-12-31", score=70):
    return {
        "source_verified": True,
        "reviewed_on": "2026-08-20",
        "source_url": "https://example.invalid/investment-review",
        "valid_until": valid_until,
        "investment_thesis_status": "VALID",
        "valuation_status": "FAIR",
        "quality_status": "STABLE",
        "dividend_outlook": "STABLE",
        "scores": {
            "cash_dividend_contribution": score,
            "earnings_quality_and_growth": score,
            "valuation_and_entry_margin": score,
            "portfolio_diversification": score,
            "shareholder_return_durability": score,
        },
    }


def dividend_forecast(*, expires_on="2026-12-31", ordinary=4):
    return {
        "source_verified": True,
        "source_type": "OFFICIAL_IR",
        "expires_on": expires_on,
        "ordinary_annual_per_share": ordinary,
        "special_annual_per_share": 99,
    }


def earnings_snapshot(*, expires_on="2026-12-31"):
    return {
        "source_verified": True,
        "source_url": "https://example.invalid/earnings",
        "period": "FY2026 Q1",
        "report_date": "2026-08-15",
        "expires_on": expires_on,
        "next_report_date": "2026-11-15",
        "guidance_status": "UNCHANGED",
        "dividend_status": "UNCHANGED",
        "revenue_yoy_pct": 5,
        "primary_profit_yoy_pct": 6,
        "net_income_yoy_pct": 4,
        "full_year_profit_progress_pct": 25,
    }


def full_evidence(candidate_order, *, ticker="1111"):
    return {
        "investment_reviews": {ticker: investment_review()},
        "dividend_forecasts": {ticker: dividend_forecast()},
        "earnings_book": {"reviews": {ticker: earnings_snapshot()}},
    }


def test_non_earnings_wait_plan_is_conditional_not_stopped_by_missing_ir():
    candidate = evaluate_manual_logic_candidates(
        strategy(order()),
        [price()],
        financial_assets_jpy=100_000,
        as_of=AS_OF,
    )[0]

    assert candidate.status == "CONDITIONAL_CONSIDER"
    assert candidate.entry_status == "BUY_ZONE"
    assert "EARNINGS_AUDIT_REQUIRED" not in candidate.blocks
    assert "EARNINGS_NOT_CURRENTLY_AUDITED" in candidate.warnings
    assert not hasattr(candidate, "account")
    assert not hasattr(candidate, "purchase_flag")
    assert not hasattr(candidate, "actionability")


def test_explicit_earnings_wait_is_a_visible_manual_condition_not_a_half_year_lock():
    candidate = evaluate_manual_logic_candidates(
        strategy(order(earnings_wait=True)),
        [price()],
        financial_assets_jpy=100_000,
        as_of=AS_OF,
    )[0]

    assert candidate.status == "CONDITIONAL_CONSIDER"
    assert "EARNINGS_AUDIT_REQUIRED" in candidate.warnings
    assert "EARNINGS_AUDIT_REQUIRED" not in candidate.blocks


def test_missing_dividend_forecast_is_visible_as_a_manual_condition_not_a_false_stop():
    candidate_order = order(purpose="CORE_DIVIDEND")
    candidate = evaluate_manual_logic_candidates(
        strategy(candidate_order),
        [price()],
        financial_assets_jpy=100_000,
        as_of=AS_OF,
    )[0]

    assert candidate.status == "CONDITIONAL_CONSIDER"
    assert "DIVIDEND_FORECAST_UNCONFIRMED" in candidate.warnings
    assert "DIVIDEND_FORECAST_REVIEW_REQUIRED" not in candidate.blocks


def test_full_price_thesis_dividend_and_earnings_evidence_becomes_buy_consider():
    candidate_order = order(purpose="CORE_DIVIDEND")
    facts = full_evidence(candidate_order)
    candidate = evaluate_manual_logic_candidates(
        strategy(candidate_order),
        [price()],
        financial_assets_jpy=100_000,
        as_of=AS_OF,
        **facts,
    )[0]

    assert candidate.status == "BUY_CONSIDER"
    assert candidate.earnings_state == "POSITIVE"
    assert candidate.thesis_state == "VALIDATED"
    assert candidate.dividend_state == "CONFIRMED"
    assert candidate.dividend_yield == round(4 / 95, 6)
    assert candidate.investment_score == 70


def test_raw_positive_strategy_flag_cannot_make_a_green_card_without_official_evidence():
    candidate_order = order(purpose="CORE_DIVIDEND")
    candidate_order.update({"earnings_review_status": "POSITIVE", "earnings_reviewed_ok": True})
    facts = {
        "investment_reviews": {"1111": investment_review()},
        "dividend_forecasts": {"1111": dividend_forecast()},
    }
    candidate = evaluate_manual_logic_candidates(
        strategy(candidate_order),
        [price()],
        financial_assets_jpy=100_000,
        as_of=AS_OF,
        **facts,
    )[0]

    assert candidate.status == "CONDITIONAL_CONSIDER"
    assert candidate.earnings_state == "UNREVIEWED"
    assert "EARNINGS_NOT_CURRENTLY_AUDITED" in candidate.warnings


def test_negative_and_neutral_earnings_are_not_hidden_by_an_attractive_price():
    negative = order()
    negative.update({"earnings_review_status": "NEGATIVE", "earnings_reviewed_ok": False})
    neutral = order("2222")
    neutral.update({"earnings_review_status": "NEUTRAL", "earnings_reviewed_ok": False})
    candidates = evaluate_manual_logic_candidates(
        strategy(negative, neutral),
        [price(), price("2222")],
        financial_assets_jpy=100_000,
        as_of=AS_OF,
    )
    by_ticker = {candidate.ticker: candidate for candidate in candidates}

    assert by_ticker["1111"].status == "PAUSE"
    assert "EARNINGS_NEGATIVE" in by_ticker["1111"].blocks
    assert by_ticker["2222"].status == "REVIEW_REQUIRED"
    assert "EARNINGS_NEUTRAL" in by_ticker["2222"].blocks


def test_pre_or_post_earnings_event_requires_review_even_without_explicit_wait():
    candidate_order = order()
    candidate_order.update({
        "earnings_review_status": "NEEDS_DATA",
        "earnings_review_reasons": ["NEXT_EARNINGS_IMMINENT"],
    })
    candidate = evaluate_manual_logic_candidates(
        strategy(candidate_order),
        [price()],
        financial_assets_jpy=100_000,
        as_of=AS_OF,
    )[0]

    assert candidate.status == "REVIEW_REQUIRED"
    assert "EARNINGS_EVENT_REVIEW_REQUIRED" in candidate.blocks


def test_multiple_attractive_ideas_are_all_visible_not_limited_to_one_daily_order():
    first = order("1111", priority=1, purpose="CORE_DIVIDEND")
    second = order("2222", priority=2, purpose="CORE_DIVIDEND")
    facts = {
        "investment_reviews": {"1111": investment_review(), "2222": investment_review()},
        "dividend_forecasts": {"1111": dividend_forecast(), "2222": dividend_forecast()},
    }
    facts["earnings_book"] = {"reviews": {"1111": earnings_snapshot(), "2222": earnings_snapshot()}}
    candidates = evaluate_manual_logic_candidates(
        strategy(first, second),
        [price("1111"), price("2222")],
        financial_assets_jpy=100_000,
        as_of=AS_OF,
        **facts,
    )

    assert {candidate.ticker: candidate.status for candidate in candidates} == {
        "1111": "BUY_CONSIDER",
        "2222": "BUY_CONSIDER",
    }


def test_same_ticker_across_registered_plans_is_aggregated_not_automatically_stopped():
    first = order("1111", shares=10, purpose="CORE_DIVIDEND")
    second = order("1111", shares=5, purpose="CORE_DIVIDEND")
    facts = {
        "investment_reviews": {"1111": investment_review()},
        "dividend_forecasts": {"1111": dividend_forecast()},
        "earnings_book": {"reviews": {"1111": earnings_snapshot()}},
    }
    candidates = evaluate_manual_logic_candidates(
        strategy(first, second),
        [price()],
        financial_assets_jpy=100_000,
        as_of=AS_OF,
        **facts,
    )

    assert len(candidates) == 1
    assert candidates[0].status == "BUY_CONSIDER"
    assert candidates[0].shares == 15
    assert candidates[0].combined_pending_shares == 15
    assert candidates[0].planned_step_count == 2


def test_conflicting_duplicate_ticker_plans_require_repair_instead_of_showing_a_quantity():
    first = order("1111", shares=10, purpose="CORE_DIVIDEND", limit=100)
    second = order("1111", shares=5, purpose="CORE_DIVIDEND", limit=90)
    facts = {
        "investment_reviews": {"1111": investment_review()},
        "dividend_forecasts": {"1111": dividend_forecast()},
        "earnings_book": {"reviews": {"1111": earnings_snapshot()}},
    }
    candidate = evaluate_manual_logic_candidates(
        strategy(first, second),
        [price()],
        financial_assets_jpy=100_000,
        as_of=AS_OF,
        **facts,
    )[0]

    assert candidate.status == "REVIEW_REQUIRED"
    assert candidate.shares is None
    assert candidate.combined_pending_shares is None
    assert "PLAN_CONFLICT" in candidate.blocks


def test_complete_asset_denominator_and_hard_concentration_stay_fail_closed():
    candidate_order = order()
    incomplete = evaluate_manual_logic_candidates(
        strategy(candidate_order), [price()], financial_assets_jpy=None, as_of=AS_OF
    )[0]
    concentrated = evaluate_manual_logic_candidates(
        strategy(candidate_order), [price()], financial_assets_jpy=1_000, as_of=AS_OF
    )[0]

    assert incomplete.status == "DATA_REQUIRED"
    assert "CONCENTRATION_AUDIT_REQUIRED" in incomplete.blocks
    assert concentrated.status == "PAUSE"
    assert "CONCENTRATION_HARD_LIMIT" in concentrated.blocks


def test_stale_price_and_unverified_conditions_are_not_buy_consider():
    candidate_order = order()
    candidate_order.update({"conditional": True, "condition_verified": False})
    candidate = evaluate_manual_logic_candidates(
        strategy(candidate_order),
        [price(price_date=AS_OF - timedelta(days=6))],
        financial_assets_jpy=100_000,
        as_of=AS_OF,
    )[0]

    assert candidate.status == "DATA_REQUIRED"
    assert {"STALE_PRICE", "ORDER_CONDITION_REVIEW_REQUIRED"}.issubset(candidate.blocks)


def test_known_negative_earnings_is_not_hidden_by_stale_price():
    candidate_order = order()
    candidate_order.update({"earnings_review_status": "NEGATIVE"})
    candidate = evaluate_manual_logic_candidates(
        strategy(candidate_order),
        [price(price_date=AS_OF - timedelta(days=6))],
        financial_assets_jpy=100_000,
        as_of=AS_OF,
    )[0]

    assert candidate.status == "PAUSE"
    assert {"EARNINGS_NEGATIVE", "STALE_PRICE"}.issubset(candidate.blocks)


def test_expired_earnings_review_is_not_mislabeled_as_a_pre_earnings_event():
    candidate = evaluate_manual_logic_candidates(
        strategy(order()),
        [price()],
        financial_assets_jpy=100_000,
        earnings_book={"reviews": {"1111": earnings_snapshot(expires_on="2026-08-30")}},
        as_of=AS_OF,
    )[0]

    assert candidate.status == "REVIEW_REQUIRED"
    assert "EARNINGS_REVIEW_EXPIRED" in candidate.blocks
    assert "EARNINGS_EVENT_REVIEW_REQUIRED" not in candidate.blocks


def test_incomplete_investment_review_is_not_enough_for_a_green_card():
    incomplete = {"source_verified": True, "valid_until": "2026-12-31"}
    candidate = evaluate_manual_logic_candidates(
        strategy(order(purpose="CORE_DIVIDEND")),
        [price()],
        financial_assets_jpy=100_000,
        investment_reviews={"1111": incomplete},
        dividend_forecasts={"1111": dividend_forecast()},
        earnings_book={"reviews": {"1111": earnings_snapshot()}},
        as_of=AS_OF,
    )[0]

    assert candidate.status == "CONDITIONAL_CONSIDER"
    assert candidate.thesis_state == "PARTIAL"
    assert {"INVESTMENT_REVIEW_DATE_MISSING", "INVESTMENT_REVIEW_EVIDENCE_MISSING"}.issubset(candidate.warnings)


def test_only_the_first_recorded_pending_step_is_used_without_mutating_execution_state():
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
        as_of=AS_OF,
    )[0]

    assert candidate.step_id == "1111-2"
    assert candidate.step_index == 2
    assert candidate.shares == 5
    assert candidate_order == original
