from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from progress_notification import build_progress_snapshot, render_goal_progress


def test_progress_block_shows_assets_dividend_and_year_budget():
    policy = {
        "current_financial_assets": 25_270_000,
        "target_asset_value_at_age_60": 200_000_000,
        "target_annual_dividend": 6_000_000,
    }
    strategy = {
        "funding": {
            "target_investment_to_2027_03_jpy_env": "TEST_TARGET_INVESTMENT",
        }
    }
    signals = [
        SimpleNamespace(status="COMPLETED", estimated_amount_jpy=350_000),
        SimpleNamespace(status="WAIT", estimated_amount_jpy=200_000),
    ]
    env = {
        "TEST_TARGET_INVESTMENT": "8500000",
        "HOS_CURRENT_ANNUAL_DIVIDEND_JPY": "1200000",
    }

    snapshot = build_progress_snapshot(policy, strategy, signals, env)
    assert snapshot["completed_investment"] == 350_000
    assert snapshot["remaining_investment"] == 8_150_000

    report = render_goal_progress(policy, strategy, signals, env)
    assert "資産" in report
    assert "12.6%" in report
    assert "配当" in report
    assert "20.0%" in report
    assert "年度投資" in report
    assert "815万円" in report


def test_progress_block_shows_both_active_purchase_accounts_once_per_ticker():
    policy = {
        "current_financial_assets": 25_270_000,
        "target_asset_value_at_age_60": 200_000_000,
        "target_annual_dividend": 6_000_000,
    }
    strategy = {"funding": {}}
    signals = [
        SimpleNamespace(account="maho", ticker="8316", fy2026_decision="BUY_2026_CORE", status="WAIT", estimated_amount_jpy=0),
        SimpleNamespace(account="maho", ticker="8316", fy2026_decision="BUY_2026_CORE", status="WAIT_PREVIOUS_STEP", estimated_amount_jpy=0),
        SimpleNamespace(account="hiro", ticker="8593", fy2026_decision="BUY_2026_CORE", status="WAIT", estimated_amount_jpy=0),
        SimpleNamespace(account="hiro", ticker="8316", fy2026_decision="DEFER_UNTIL_FUNDED", status="WAIT", estimated_amount_jpy=0),
    ]

    report = render_goal_progress(policy, strategy, signals, {})
    assert "👥 購入監視｜まほ 1銘柄｜ひろ 1銘柄" in report


def test_progress_block_marks_current_dividend_as_unset_without_secret():
    policy = {
        "current_financial_assets": 25_270_000,
        "target_asset_value_at_age_60": 200_000_000,
        "target_annual_dividend": 6_000_000,
    }
    strategy = {"funding": {}}
    report = render_goal_progress(policy, strategy, [], {})
    assert "現在額未設定" in report
    assert "目標 600万円/年" in report
    assert "年度投資 ?????????? 目標額未設定" in report
