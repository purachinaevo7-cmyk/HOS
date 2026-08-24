from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from dividend_tracker import annual_dividend_summary


AS_OF = date(2026, 8, 22)


def profile(**overrides):
    value = {
        "goals": {"target_annual_dividend_jpy": 600000},
        "progress": {"financial_assets_jpy": 10000000, "financial_assets_verified": True},
        "holdings": [],
        "dividend_forecasts": {},
        "fx_rates": {"USD": {"source_verified": True, "jpy_per_unit": 150, "expires_on": "2026-12-31"}},
        "strategy": {"accounts": {}},
    }
    value.update(overrides)
    return value


def official(**extra):
    value = {
        "source_type": "OFFICIAL_IR",
        "source_verified": True,
        "expires_on": "2026-12-31",
        "currency": "JPY",
        "ordinary_annual_per_share": 10,
        "special_annual_per_share": 0,
    }
    value.update(extra)
    return value


def test_confirmed_japanese_dividend_is_ordinary_cash_only():
    result = annual_dividend_summary(profile(
        holdings=[{"owner": "member_a", "ticker": "1111", "asset_type": "JP_STOCK", "shares": 100, "verified": True}],
        dividend_forecasts={"1111": official(special_annual_per_share=2)},
    ), as_of=AS_OF)
    assert result.current_ordinary_cash_jpy == 1000
    assert result.current_special_cash_jpy == 200
    assert result.target_shortfall_jpy == 599000
    assert result.current_yield == 0.0001


def test_missing_or_unofficial_dividend_is_not_added_to_progress():
    result = annual_dividend_summary(profile(
        holdings=[{"owner": "member_a", "ticker": "1111", "asset_type": "JP_STOCK", "shares": 100, "verified": True}],
        dividend_forecasts={"1111": official(source_verified=False)},
    ), as_of=AS_OF)
    assert result.current_ordinary_cash_jpy == 0
    assert result.current_unconfirmed_count == 1
    assert result.lines[0].reason == "OFFICIAL_DIVIDEND_SOURCE_REQUIRED"


def test_stock_split_uses_post_split_per_share_without_double_counting():
    result = annual_dividend_summary(profile(
        holdings=[{"owner": "member_a", "ticker": "1111", "asset_type": "JP_STOCK", "shares": 200, "verified": True}],
        dividend_forecasts={"1111": official(ordinary_annual_per_share=5, split_adjusted=True)},
    ), as_of=AS_OF)
    assert result.current_ordinary_cash_jpy == 1000


def test_adr_ratio_and_fx_conversion_are_applied_before_yen_total():
    result = annual_dividend_summary(profile(
        holdings=[{"owner": "member_b", "ticker": "ADR1", "asset_type": "ADR", "shares": 10, "verified": True}],
        dividend_forecasts={"ADR1": official(currency="USD", ordinary_annual_per_share=1.5, dividend_basis="UNDERLYING_SHARE", adr_ratio=2, foreign_withholding_rate=0.1)},
    ), as_of=AS_OF)
    assert result.current_ordinary_cash_jpy == 4500
    assert result.current_foreign_withholding_jpy == 450


def test_reinvesting_fund_and_wealthnavi_distribution_are_excluded():
    result = annual_dividend_summary(profile(
        holdings=[
            {"owner": "member_a", "ticker": "FUND", "asset_type": "FUND", "distribution_mode": "REINVEST", "shares": 10, "verified": True},
            {"owner": "member_a", "ticker": "WN", "asset_type": "WEALTHNAVI", "distribution_mode": "REINVEST", "shares": 10, "verified": True},
            {"owner": "member_a", "ticker": "BTC", "asset_type": "CRYPTO", "shares": 1, "verified": True},
        ],
    ), as_of=AS_OF)
    assert result.current_ordinary_cash_jpy == 0
    assert result.current_unconfirmed_count == 0
    assert {line.reason for line in result.lines} == {"REINVESTING_FUND_EXCLUDED", "WEALTHNAVI_REINVESTED_DISTRIBUTION_EXCLUDED", "CRYPTO_EXCLUDED"}


def test_plan_completion_adds_only_verified_future_shares():
    result = annual_dividend_summary(profile(
        holdings=[{"owner": "member_a", "ticker": "1111", "asset_type": "JP_STOCK", "shares": 50, "verified": True}],
        dividend_forecasts={"1111": official(ordinary_annual_per_share=10)},
        strategy={"accounts": {"member_a": {"orders": [{
            "ticker": "1111", "target_total_shares": 100, "completed_step_ids": [],
            "order_steps": [{"step_id": "1111-1", "shares": 25, "limit_price": 100}, {"step_id": "1111-2", "shares": 25, "limit_price": 90}],
        }]}}},
    ), as_of=AS_OF)
    assert result.current_ordinary_cash_jpy == 500
    assert result.projected_ordinary_cash_jpy == 1000
    assert result.plan_increment_ordinary_jpy == 500
    assert result.projected_yield == round(1000 / 10015000, 6)


def test_plan_with_unverified_baseline_is_not_added():
    result = annual_dividend_summary(profile(
        holdings=[{"owner": "member_a", "ticker": "1111", "asset_type": "JP_STOCK", "shares": 50, "verified": False}],
        dividend_forecasts={"1111": official()},
        strategy={"accounts": {"member_a": {"orders": [{"ticker": "1111", "target_total_shares": 100, "order_steps": []}]}}},
    ), as_of=AS_OF)
    assert result.projected_ordinary_cash_jpy == 0
    assert result.projected_unconfirmed_count >= 2
