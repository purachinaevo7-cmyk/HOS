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
