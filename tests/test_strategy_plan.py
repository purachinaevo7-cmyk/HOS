from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from stock_analyzer import PriceRecord
from strategy_plan import evaluate_strategy, merge_watchlists, strategy_watchlist


def base_order(ticker, name, steps, **extra):
    order = {
        "ticker": ticker,
        "name": name,
        "market": "JP",
        "currency": "JPY",
        "purpose": "test",
        "fy2026_decision": "BUY_2026_CORE",
        "purchase_class": "CORE_DIVIDEND",
        "execution_priority": 1,
        "completed_step_ids": [],
        "order_steps": steps,
    }
    order.update(extra)
    return order


def env_values():
    return {
        "TEST_BUDGET": "1000000",
        "TEST_BUYING_POWER": "1000000",
        "HOS_STRATEGY_MAX_DAILY_ORDERS": "1",
    }


def test_registered_strategy_and_unique_japanese_watchlist():
    strategy = {
        "strategy_id": "TEST_REGISTERED_STRATEGY",
        "status": "ACTIVE",
        "accounts": {
            "member_a": {"orders": [base_order("1111", "Example A", [{"step_id": "1111-1", "shares": 1, "limit_price": 100}])]},
            "member_b": {"orders": [base_order("1111", "Example A", [{"step_id": "1111-1", "shares": 1, "limit_price": 100}]), base_order("2222", "Example B", [{"step_id": "2222-1", "shares": 1, "limit_price": 100}])]},
        },
    }
    assert strategy["status"] == "ACTIVE"
    watchlist = strategy_watchlist(strategy)
    codes = [row["code"] for row in watchlist]
    assert codes == ["1111", "2222"]
    merged = merge_watchlists([{"code": "1111", "name": "Example A", "volatility": "large"}], watchlist)
    assert [row["code"] for row in merged].count("1111") == 1


def test_limit_reached_is_purchase_ready_only_with_all_gates():
    strategy = {
        "strategy_id": "TEST",
        "status": "ACTIVE",
        "accounts": {
            "member_b": {
                "target_budget_jpy_env": "TEST_BUDGET",
                "buying_power_jpy_env": "TEST_BUYING_POWER",
                "orders": [base_order("2340", "極楽湯HD", [{"step_id": "2340-1", "shares": 100, "limit_price": 510}])],
            }
        },
    }
    price = PriceRecord("2340", "極楽湯HD", 500, 520, date.today(), "mock", "medium")
    signal = evaluate_strategy(strategy, [price], env=env_values())[0]
    assert signal.status == "READY"
    assert signal.purchase_flag == "PURCHASE_READY"
    assert signal.actionability == "READY"
    assert signal.estimated_amount_jpy == 51000


def test_earnings_wait_blocks_even_when_limit_is_reached():
    strategy = {
        "strategy_id": "TEST",
        "status": "ACTIVE",
        "accounts": {
            "member_a": {
                "target_budget_jpy_env": "TEST_BUDGET",
                "buying_power_jpy_env": "TEST_BUYING_POWER",
                "orders": [base_order(
                    "9882", "イエローハット",
                    [{"step_id": "9882-1", "shares": 100, "limit_price": 1750}],
                    earnings_wait=True,
                )],
            }
        },
    }
    price = PriceRecord("9882", "イエローハット", 1700, 1800, date.today(), "mock", "medium")
    signal = evaluate_strategy(strategy, [price], env=env_values())[0]
    assert signal.status == "BLOCKED_AT_LIMIT"
    assert signal.purchase_flag == "REVIEW_REQUIRED"
    assert "EARNINGS_REVIEW_REQUIRED" in signal.blocks


def test_inactive_strategy_blocks_a_reached_order():
    strategy = {
        "strategy_id": "TEST",
        "status": "ACTIVE_PENDING_REVALIDATION",
        "accounts": {
            "member_b": {
                "target_budget_jpy_env": "TEST_BUDGET",
                "buying_power_jpy_env": "TEST_BUYING_POWER",
                "orders": [base_order("2340", "極楽湯HD", [{"step_id": "2340-1", "shares": 100, "limit_price": 510}])],
            }
        },
    }
    price = PriceRecord("2340", "極楽湯HD", 500, 520, date.today(), "mock", "medium")
    signal = evaluate_strategy(strategy, [price], env=env_values())[0]
    assert signal.status == "BLOCKED_AT_LIMIT"
    assert "STRATEGY_NOT_ACTIVE" in signal.blocks


def test_only_first_incomplete_step_can_be_ready():
    strategy = {
        "strategy_id": "TEST",
        "status": "ACTIVE",
        "accounts": {
            "member_b": {
                "target_budget_jpy_env": "TEST_BUDGET",
                "buying_power_jpy_env": "TEST_BUYING_POWER",
                "orders": [base_order("7832", "バンダイナムコHD", [
                    {"step_id": "7832-1", "shares": 100, "limit_price": 4050},
                    {"step_id": "7832-2", "shares": 100, "limit_price": 3900},
                ])],
            }
        },
    }
    price = PriceRecord("7832", "バンダイナムコHD", 3800, 4100, date.today(), "mock", "medium")
    signals = evaluate_strategy(strategy, [price], env=env_values())
    assert signals[0].purchase_flag == "PURCHASE_READY"
    assert signals[1].status == "WAIT_PREVIOUS_STEP"


def test_deferred_fy_decision_never_becomes_ready():
    deferred = base_order("2702", "日本マクドナルドHD", [{"step_id": "2702-1", "shares": 100, "limit_price": 7200}])
    deferred["fy2026_decision"] = "SKIP_2026"
    strategy = {
        "strategy_id": "TEST",
        "status": "ACTIVE",
        "accounts": {
            "member_b": {
                "target_budget_jpy_env": "TEST_BUDGET",
                "buying_power_jpy_env": "TEST_BUYING_POWER",
                "orders": [deferred],
            }
        },
    }
    price = PriceRecord("2702", "日本マクドナルドHD", 7000, 7300, date.today(), "mock", "medium")
    signal = evaluate_strategy(strategy, [price], env=env_values())[0]
    assert signal.status == "SKIP_2026"
    assert signal.actionability == "DRAFT"


def test_missing_hos_holding_blocks_dynamic_jt_share_rule():
    strategy = {
        "strategy_id": "TEST",
        "status": "ACTIVE",
        "accounts": {
            "member_a": {
                "target_budget_jpy_env": "TEST_BUDGET",
                "buying_power_jpy_env": "TEST_BUYING_POWER",
                "orders": [base_order(
                    "2914", "JT",
                    [{"step_id": "2914-1", "shares_rule": "不足株数の半分", "limit_price": 6000}],
                    target_total_shares=100,
                    current_shares_source="HOS",
                )],
            }
        },
    }
    price = PriceRecord("2914", "JT", 5900, 6100, date.today(), "mock", "medium")
    signal = evaluate_strategy(strategy, [price], env=env_values())[0]
    assert signal.status == "BLOCKED_AT_LIMIT"
    assert signal.shares is None
    assert "HOLDING_DATA_REQUIRED" in signal.blocks


def test_registered_strategy_requires_complete_concentration_audit():
    strategy = {
        "strategy_id": "TEST", "status": "ACTIVE",
        "purchase_authority": {"mode": "REGISTERED_STRATEGY_ONLY"},
        "household_goal": {"max_single_ticker_weight_hard": 0.10},
        "accounts": {"member_a": {"target_budget_jpy_env": "TEST_BUDGET", "buying_power_jpy_env": "TEST_BUYING_POWER", "orders": [base_order("1111", "Example", [{"step_id": "1111-1", "shares": 10, "limit_price": 100}], target_shares=10)]}},
    }
    price = PriceRecord("1111", "Example", 100, 101, date.today(), "mock", "medium")
    signal = evaluate_strategy(strategy, [price], env=env_values())[0]
    assert signal.actionability == "DRAFT"
    assert "CONCENTRATION_AUDIT_REQUIRED" in signal.blocks


def test_hard_concentration_limit_blocks_purchase_ready():
    strategy = {
        "strategy_id": "TEST", "status": "ACTIVE",
        "purchase_authority": {"mode": "REGISTERED_STRATEGY_ONLY"},
        "household_goal": {"max_single_ticker_weight_hard": 0.10},
        "accounts": {"member_a": {"target_budget_jpy_env": "TEST_BUDGET", "buying_power_jpy_env": "TEST_BUYING_POWER", "orders": [base_order("1111", "Example", [{"step_id": "1111-1", "shares": 20, "limit_price": 100}], target_shares=20)]}},
    }
    price = PriceRecord("1111", "Example", 100, 101, date.today(), "mock", "medium")
    signal = evaluate_strategy(strategy, [price], policy={"current_financial_assets": 10_000}, env=env_values())[0]
    assert signal.purchase_flag == "REVIEW_REQUIRED"
    assert "CONCENTRATION_HARD_LIMIT:20.00%" in signal.blocks
