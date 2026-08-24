from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "investment-agent"))

from dividend_tracker import annual_dividend_summary
from portfolio_simulation import simulate_completion


def profile():
    return {"goals": {"target_financial_assets_jpy": 20_000_000, "target_annual_dividend_jpy": 600_000, "target_date": "2036-08-22"}, "progress": {"financial_assets_jpy": 10_000_000, "financial_assets_verified": True}, "holdings": [{"owner": "member_a", "ticker": "1111", "asset_type": "JP_STOCK", "shares": 100, "market_value_jpy": 1_000_000, "sector": "Financials", "verified": True}], "dividend_forecasts": {"1111": {"source_type": "OFFICIAL_IR", "source_verified": True, "expires_on": "2026-12-31", "currency": "JPY", "ordinary_annual_per_share": 10}}, "strategy": {"accounts": {"member_a": {"orders": [{"ticker": "1111", "sector": "Financials", "currency": "JPY", "completed_step_ids": [], "target_total_shares": 200, "order_steps": [{"step_id": "one", "shares": 100, "limit_price": 1000}]}]}}}, "simulation_assumptions": {"annual_additional_investment_jpy": 300_000}}


def test_completion_simulation_keeps_asset_value_nominal_but_adds_verified_dividend():
    item = profile()
    dividends = annual_dividend_summary(item, as_of=date(2026, 8, 22))
    result = simulate_completion(item, dividends, as_of=date(2026, 8, 22))
    assert result.current_financial_assets_jpy == 10_000_000
    assert result.plan_financial_assets_jpy == 10_000_000
    assert result.plan_cost_jpy == 100_000
    assert result.current_annual_dividend_jpy == 1_000
    assert result.plan_annual_dividend_jpy == 2_000
    assert len(result.scenarios) == 3
    assert result.scenarios[0].annual_return == 0.03
    assert result.required_average_return is not None


def test_unverified_assets_and_missing_holding_values_never_become_complete_simulation():
    item = profile()
    item["progress"]["financial_assets_verified"] = False
    item["holdings"][0].pop("market_value_jpy")
    result = simulate_completion(item, annual_dividend_summary(item, as_of=date(2026, 8, 22)), as_of=date(2026, 8, 22))
    assert result.current_financial_assets_jpy is None
    assert "FINANCIAL_ASSETS_UNVERIFIED" in result.incomplete_reasons
    assert result.current_sector_weights is None
