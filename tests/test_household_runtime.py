from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from household_runtime import apply_household_funding_gates, apply_strategy_overrides, hydrate_environment
from stock_analyzer import PriceRecord
from strategy_plan import evaluate_strategy, load_strategy

OVERRIDE = BASE / "config" / "strategy_household_overrides_2026-08-12.json"
STRATEGY = BASE / "config" / "strategies" / "HOS_2026_FINAL_AGGRESSIVE_V2.json"


def audited_strategy():
    strategy = apply_strategy_overrides(load_strategy(STRATEGY), OVERRIDE)
    strategy["accounts"]["hiro"]["buying_power_jpy_env"] = "HOS_HIRO_BUYING_POWER_JPY"
    strategy["accounts"]["maho"]["buying_power_jpy_env"] = "HOS_MAHO_BUYING_POWER_JPY"
    return strategy


def base_env():
    return {
        "HOS_HIRO_STRATEGY_BUDGET_JPY": "3200000",
        "HOS_MAHO_STRATEGY_BUDGET_JPY": "5300000",
        "HOS_HIRO_BUYING_POWER_JPY": "1000000",
        "HOS_MAHO_BUYING_POWER_JPY": "1000000",
        "HOS_TARGET_INVESTMENT_TO_2027_03_JPY": "8500000",
        "HOS_HOUSEHOLD_AVAILABLE_CASH_JPY": "8500000",
        "HOS_RESERVE_AFTER_EXECUTION_JPY": "0",
        "HOS_CURRENT_HOUSEHOLD_CASH_JPY": "20000000",
        "HOS_PROTECTED_CASH_FLOOR_JPY": "10000000",
        "HOS_HIRO_TAXABLE_GIFTS_YTD_JPY": "300000",
        "HOS_HIRO_GIFT_TAX_REVIEWED": "false",
        "HOS_USDJPY_PLANNING_RATE": "160",
        "HOS_STRATEGY_MAX_DAILY_ORDERS": "1",
    }


def test_household_overrides_fix_hiro_quantities_and_block_new_positions():
    strategy = audited_strategy()
    hiro = {order["ticker"]: order for order in strategy["accounts"]["hiro"]["orders"]}
    assert strategy["revision"] == 4
    assert hiro["2914"]["current_shares"] == 50
    assert [step["shares"] for step in hiro["2914"]["order_steps"]] == [25, 25]
    assert hiro["9697"]["current_shares"] == 12
    assert [step["shares"] for step in hiro["9697"]["order_steps"]] == [44, 44]
    assert hiro["9882"]["fy2026_decision"] == "DEFER_NEW_POSITION_NO_HIRO_CASH"
    assert hiro["8593"]["existing_position_completion"] is True


def test_private_profile_hydrates_bank_cash_from_verified_cash_balances_only():
    profile = {
        "balances": [
            {"id": "hiro_cash", "category": "cash", "value_jpy": 0, "verified": True},
            {"id": "maho_cash", "category": "cash", "value_jpy": 10000000, "verified": True},
            {"id": "funds", "category": "investment_fund", "value_jpy": 7900000, "verified": True},
        ],
        "buying_power": {"hiro_jpy": 0, "maho_jpy": 15000000},
        "cash_policy": {"current_household_cash_jpy": 25000000, "protected_cash_floor_jpy": 10000000},
        "budgets": {"target_investment_to_2027_03_jpy": 8500000, "hiro_strategy_budget_jpy": 3200000},
        "transfers": {"hiro_taxable_gifts_ytd_jpy": 0, "hiro_gift_tax_reviewed": False},
    }
    env = {"HOS_HIRO_BUYING_POWER_JPY": "123"}
    hydrate_environment(profile, env)
    assert env["HOS_HIRO_BUYING_POWER_JPY"] == "123"
    assert env["HOS_MAHO_BUYING_POWER_JPY"] == "15000000"
    # The legacy private-profile field says 25m, but bank cash is only the
    # verified 10m cash balance. Buying power is not silently added again.
    assert env["HOS_CURRENT_HOUSEHOLD_CASH_JPY"] == "10000000.0"
    assert env["HOS_PROTECTED_CASH_FLOOR_JPY"] == "10000000"
    assert env["HOS_HIRO_TAXABLE_GIFTS_YTD_JPY"] == "0"


def test_explicit_household_cash_secret_is_not_overwritten():
    profile = {
        "balances": [{"id": "maho_cash", "category": "cash", "value_jpy": 10000000, "verified": True}],
        "cash_policy": {"protected_cash_floor_jpy": 10000000},
    }
    env = {"HOS_CURRENT_HOUSEHOLD_CASH_JPY": "12000000"}
    hydrate_environment(profile, env)
    assert env["HOS_CURRENT_HOUSEHOLD_CASH_JPY"] == "12000000"


def _mhcc_first_signal(env):
    strategy = audited_strategy()
    mhcc = next(order for order in strategy["accounts"]["hiro"]["orders"] if order["ticker"] == "8593")
    mhcc["earnings_reviewed_ok"] = True
    price = PriceRecord("8593", "三菱HCキャピタル", 1390, 1410, date.today(), "mock", "medium")
    signals = evaluate_strategy(strategy, [price], env=env)
    signal = next(row for row in signals if row.account == "hiro" and row.ticker == "8593" and row.step_id == "8593-1")
    return apply_household_funding_gates([signal], strategy, env=env)[0]


def test_hiro_completion_can_be_ready_only_after_transfer_and_cash_floor_gates():
    signal = _mhcc_first_signal(base_env())
    assert signal.actionability == "READY"
    assert signal.purchase_flag == "PURCHASE_READY"


def test_hiro_completion_is_blocked_until_transfer_lands():
    env = base_env()
    env["HOS_HIRO_BUYING_POWER_JPY"] = "0"
    signal = _mhcc_first_signal(env)
    assert signal.actionability == "DRAFT"
    assert "HIRO_COMPLETION_TRANSFER_REQUIRED" in signal.blocks


def test_hiro_completion_stops_above_gift_tax_guard_until_reviewed():
    env = base_env()
    env["HOS_HIRO_TAXABLE_GIFTS_YTD_JPY"] = "1200000"
    signal = _mhcc_first_signal(env)
    assert signal.actionability == "DRAFT"
    assert "GIFT_TAX_REVIEW_REQUIRED" in signal.blocks

    env["HOS_HIRO_GIFT_TAX_REVIEWED"] = "true"
    signal = _mhcc_first_signal(env)
    assert "GIFT_TAX_REVIEW_REQUIRED" not in signal.blocks


def test_cash_floor_blocks_when_verified_bank_cash_is_below_floor():
    env = base_env()
    env["HOS_CURRENT_HOUSEHOLD_CASH_JPY"] = "9999999"
    signal = _mhcc_first_signal(env)
    assert signal.actionability == "DRAFT"
    assert "PROTECTED_CASH_FLOOR_BREACH" in signal.blocks


def test_cash_at_floor_does_not_double_count_order_against_bank_cash():
    env = base_env()
    env["HOS_CURRENT_HOUSEHOLD_CASH_JPY"] = "10000000"
    env["HOS_HIRO_BUYING_POWER_JPY"] = "1000000"
    signal = _mhcc_first_signal(env)
    assert "PROTECTED_CASH_FLOOR_BREACH" not in signal.blocks
