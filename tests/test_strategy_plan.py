from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from stock_analyzer import PriceRecord
from strategy_plan import evaluate_strategy, load_strategy, merge_watchlists, strategy_watchlist


def registered_strategy():
    return load_strategy(BASE / "config" / "strategies" / "HOS_2026_FINAL_AGGRESSIVE_V2.json")


def test_registered_strategy_and_unique_japanese_watchlist():
    strategy = registered_strategy()
    assert strategy["strategy_id"] == "HOS_2026_FINAL_AGGRESSIVE_V2"
    watchlist = strategy_watchlist(strategy)
    codes = [row["code"] for row in watchlist]
    assert "4262" in codes
    assert "2340" in codes
    assert codes.count("8316") == 1
    merged = merge_watchlists([{"code": "8316", "name": "SMFG", "volatility": "large"}], watchlist)
    assert [row["code"] for row in merged].count("8316") == 1


def test_limit_reached_is_ready_only_with_budget_and_no_review_block():
    strategy = {
        "strategy_id": "TEST",
        "accounts": {
            "maho": {
                "target_budget_jpy_env": "TEST_BUDGET",
                "orders": [{
                    "ticker": "2340",
                    "name": "極楽湯HD",
                    "market": "JP",
                    "currency": "JPY",
                    "purpose": "優待",
                    "order_steps": [{"shares": 100, "limit_price": 510}],
                }],
            }
        },
    }
    price = PriceRecord("2340", "極楽湯HD", 500, 520, date(2026, 7, 24), "mock", "medium")
    signal = evaluate_strategy(strategy, [price], {"TEST_BUDGET": "1000000"})[0]
    assert signal.status == "READY"
    assert signal.actionability == "READY"
    assert signal.estimated_amount == 51000


def test_earnings_wait_blocks_even_when_limit_is_reached():
    strategy = {
        "strategy_id": "TEST",
        "accounts": {
            "hiro": {
                "target_budget_jpy_env": "TEST_BUDGET",
                "orders": [{
                    "ticker": "9882",
                    "name": "イエローハット",
                    "market": "JP",
                    "currency": "JPY",
                    "earnings_wait": True,
                    "order_steps": [{"shares": 100, "limit_price": 1750}],
                }],
            }
        },
    }
    price = PriceRecord("9882", "イエローハット", 1700, 1800, date(2026, 7, 24), "mock", "medium")
    signal = evaluate_strategy(strategy, [price], {"TEST_BUDGET": "3200000"})[0]
    assert signal.status == "BLOCKED_AT_LIMIT"
    assert signal.actionability == "DRAFT"
    assert "EARNINGS_REVIEW_REQUIRED" in signal.blocks


def test_missing_hos_holding_blocks_dynamic_jt_share_rule():
    strategy = {
        "strategy_id": "TEST",
        "accounts": {
            "hiro": {
                "target_budget_jpy_env": "TEST_BUDGET",
                "orders": [{
                    "ticker": "2914",
                    "name": "JT",
                    "market": "JP",
                    "currency": "JPY",
                    "target_total_shares": 100,
                    "current_shares_source": "HOS",
                    "order_steps": [{"shares_rule": "不足株数の半分", "limit_price": 6000}],
                }],
            }
        },
    }
    price = PriceRecord("2914", "JT", 5900, 6100, date(2026, 7, 24), "mock", "medium")
    signal = evaluate_strategy(strategy, [price], {"TEST_BUDGET": "3200000"})[0]
    assert signal.status == "BLOCKED_AT_LIMIT"
    assert signal.shares is None
    assert "HOLDING_DATA_REQUIRED" in signal.blocks
