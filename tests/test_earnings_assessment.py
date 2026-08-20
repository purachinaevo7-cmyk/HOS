from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from earnings_assessment import (
    POSITIVE,
    NEUTRAL,
    NEGATIVE,
    NEEDS_DATA,
    apply_earnings_assessments,
    assess_snapshot,
)
from stock_analyzer import PriceRecord
from stock_watch_runner import _postprocess_earnings_blocks
from strategy_plan import evaluate_strategy


def good_snapshot(**overrides):
    data = {
        "period": "FY2027/3 Q1",
        "report_date": "2026-08-07",
        "expires_on": "2026-11-01",
        "source_verified": True,
        "source_url": "https://example.com/official-ir.pdf",
        "revenue_yoy_pct": 5.0,
        "primary_profit_yoy_pct": 20.0,
        "net_income_yoy_pct": 20.0,
        "full_year_profit_progress_pct": 25.0,
        "guidance_status": "UNCHANGED",
        "guidance_revision_pct": 0.0,
        "dividend_status": "UNCHANGED",
        "hard_flags": [],
    }
    data.update(overrides)
    return data


def test_verified_healthy_results_are_positive():
    result = assess_snapshot("TEST", good_snapshot(), as_of=date(2026, 8, 21))
    assert result.state == POSITIVE
    assert result.recommendation == "MAINTAIN_BUY_CANDIDATE"
    assert result.score >= 55


def test_expired_review_returns_to_needs_data():
    result = assess_snapshot("TEST", good_snapshot(expires_on="2026-08-20"), as_of=date(2026, 8, 21))
    assert result.state == NEEDS_DATA
    assert "REVIEW_EXPIRED_FOR_NEXT_EARNINGS" in result.reasons


def test_unverified_source_never_clears_review():
    result = assess_snapshot("TEST", good_snapshot(source_verified=False), as_of=date(2026, 8, 21))
    assert result.state == NEEDS_DATA
    assert result.score is None


def test_dividend_cut_is_negative_for_household_income_goal():
    result = assess_snapshot("TEST", good_snapshot(dividend_status="LOWERED"), as_of=date(2026, 8, 21))
    assert result.state == NEGATIVE
    assert result.recommendation == "SUSPEND_AND_REVIEW_REPLACEMENT"


def test_mild_profit_deterioration_becomes_neutral_not_positive():
    result = assess_snapshot(
        "TEST",
        good_snapshot(primary_profit_yoy_pct=-20, net_income_yoy_pct=-18),
        as_of=date(2026, 8, 21),
    )
    assert result.state == NEUTRAL
    assert result.recommendation == "PAUSE_AND_WATCH"


def test_missing_operating_metrics_fail_closed():
    result = assess_snapshot(
        "TEST",
        good_snapshot(revenue_yoy_pct=None, primary_profit_yoy_pct=None, net_income_yoy_pct=None, full_year_profit_progress_pct=None),
        as_of=date(2026, 8, 21),
    )
    assert result.state == NEEDS_DATA
    assert "OPERATING_METRICS_INSUFFICIENT" in result.reasons


def test_strategy_is_enriched_but_original_fy_decision_is_preserved():
    strategy = {
        "accounts": {
            "maho": {
                "orders": [
                    {
                        "ticker": "TEST",
                        "fy2026_decision": "BUY_2026_CORE",
                        "earnings_wait": True,
                    }
                ]
            }
        }
    }
    book = {"reviews": {"TEST": good_snapshot()}}
    result = apply_earnings_assessments(strategy, book, as_of=date(2026, 8, 21))
    order = result["accounts"]["maho"]["orders"][0]
    assert order["fy2026_decision"] == "BUY_2026_CORE"
    assert order["earnings_reviewed_ok"] is True
    assert order["earnings_review_status"] == POSITIVE
    assert strategy["accounts"]["maho"]["orders"][0].get("earnings_reviewed_ok") is None


def planner_strategy(snapshot):
    base = {
        "strategy_id": "TEST",
        "status": "ACTIVE",
        "household_goal": {"max_single_ticker_weight_warning": 0.05},
        "funding": {},
        "accounts": {
            "maho": {
                "target_budget_jpy_env": "ACCOUNT_BUDGET",
                "buying_power_jpy_env": "BUYING_POWER",
                "orders": [
                    {
                        "ticker": "TEST",
                        "name": "Test Co",
                        "market": "JP",
                        "currency": "JPY",
                        "purpose": "test",
                        "fy2026_decision": "BUY_2026_CORE",
                        "purchase_class": "CORE_DIVIDEND",
                        "execution_priority": 1,
                        "completed_step_ids": [],
                        "order_steps": [{"step_id": "TEST-1", "shares": 10, "limit_price": 100}],
                        "target_shares": 10,
                        "earnings_wait": True,
                        "final_ceiling": 110,
                    }
                ],
            }
        },
    }
    return apply_earnings_assessments(base, {"reviews": {"TEST": snapshot}}, as_of=date(2026, 8, 21))


def planner_signal(strategy):
    env = {"ACCOUNT_BUDGET": "100000", "BUYING_POWER": "100000"}
    price = PriceRecord("TEST", "Test Co", 100, 101, date.today(), "mock", "medium")
    return evaluate_strategy(strategy, [price], env=env)[0]


def test_positive_earnings_can_clear_only_the_earnings_gate():
    strategy = planner_strategy(good_snapshot())
    signal = planner_signal(strategy)
    assert strategy["accounts"]["maho"]["orders"][0]["earnings_review_status"] == POSITIVE
    assert "EARNINGS_REVIEW_REQUIRED" not in signal.blocks
    assert signal.purchase_flag == "PURCHASE_READY"


def test_negative_earnings_is_translated_to_explicit_purchase_stop():
    strategy = planner_strategy(good_snapshot(dividend_status="LOWERED"))
    signal = planner_signal(strategy)
    assert "EARNINGS_REVIEW_REQUIRED" in signal.blocks
    processed = _postprocess_earnings_blocks([signal], strategy)[0]
    assert "EARNINGS_REVIEW_REQUIRED" not in processed.blocks
    assert "EARNINGS_NEGATIVE" in processed.blocks
    assert processed.purchase_flag == "REVIEW_REQUIRED"


def test_missing_ir_data_is_translated_to_hos_audit_wait():
    strategy = planner_strategy(good_snapshot(revenue_yoy_pct=None, primary_profit_yoy_pct=None, net_income_yoy_pct=None, full_year_profit_progress_pct=None))
    signal = planner_signal(strategy)
    processed = _postprocess_earnings_blocks([signal], strategy)[0]
    assert "EARNINGS_AUDIT_REQUIRED" in processed.blocks
