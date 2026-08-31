from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from household_runtime import (
    apply_household_funding_gates,
    hydrate_environment,
    load_private_manual_logic_strategy,
    load_private_profile,
    load_private_strategy,
    private_account_labels,
)
from stock_analyzer import PriceRecord
from strategy_plan import evaluate_strategy


def audited_strategy():
    return {
        "strategy_id": "TEST_PRIVATE_STRATEGY",
        "status": "ACTIVE",
        "funding": {"gift_tax_basic_deduction_jpy": 1_100_000},
        "accounts": {
            "member_a": {
                "target_budget_jpy_env": "HOS_ACCOUNT_MEMBER_A_STRATEGY_BUDGET_JPY",
                "buying_power_jpy_env": "HOS_ACCOUNT_MEMBER_A_BUYING_POWER_JPY",
                "annual_stock_cap_jpy_env": "HOS_ACCOUNT_MEMBER_A_ANNUAL_STOCK_CAP_JPY",
                "orders": [{
                    "ticker": "1111",
                    "name": "Example Income Co",
                    "market": "JP",
                    "currency": "JPY",
                    "purpose": "CORE_DIVIDEND",
                    "fy2026_decision": "BUY_2026_CORE",
                    "purchase_class": "CORE_DIVIDEND",
                    "execution_priority": 1,
                    "funding_source": "TRANSFER_EXISTING_POSITION_COMPLETION",
                    "existing_position_completion": True,
                    "current_shares": 50,
                    "target_total_shares": 100,
                    "completed_step_ids": [],
                    "order_steps": [
                        {"step_id": "1111-1", "shares": 25, "limit_price": 100},
                        {"step_id": "1111-2", "shares": 25, "limit_price": 90},
                    ],
                }],
            }
        },
    }


def base_env():
    return {
        "HOS_ACCOUNT_MEMBER_A_STRATEGY_BUDGET_JPY": "5000",
        "HOS_ACCOUNT_MEMBER_A_ANNUAL_STOCK_CAP_JPY": "5000",
        "HOS_ACCOUNT_MEMBER_A_BUYING_POWER_JPY": "5000",
        "HOS_CURRENT_HOUSEHOLD_CASH_JPY": "20000",
        "HOS_PROTECTED_CASH_FLOOR_JPY": "10000",
        "HOS_ACCOUNT_MEMBER_A_TAXABLE_GIFTS_YTD_JPY": "300000",
        "HOS_ACCOUNT_MEMBER_A_GIFT_TAX_REVIEWED": "false",
        "HOS_STRATEGY_MAX_DAILY_ORDERS": "1",
    }


def test_private_profile_hydrates_only_verified_cash_and_generic_account_keys():
    profile = {
        "balances": [
            {"id": "member_a_cash", "category": "cash", "value_jpy": 1000, "verified": True},
            {"id": "member_b_cash", "category": "cash", "value_jpy": 2000, "verified": True},
            {"id": "fund", "category": "investment_fund", "value_jpy": 9000, "verified": True},
        ],
        "accounts": {
            "member_a": {"buying_power_jpy": 3000, "strategy_budget_jpy": 4000, "taxable_gifts_ytd_jpy": 0},
            "member_b": {"buying_power_jpy": 5000},
        },
        "cash_policy": {"protected_cash_floor_jpy": 2500},
        "budgets": {"target_investment_jpy": 8000},
    }
    env = {"HOS_ACCOUNT_MEMBER_A_BUYING_POWER_JPY": "123"}
    hydrate_environment(profile, env)
    assert env["HOS_ACCOUNT_MEMBER_A_BUYING_POWER_JPY"] == "123"
    assert env["HOS_ACCOUNT_MEMBER_B_BUYING_POWER_JPY"] == "5000"
    assert env["HOS_CURRENT_HOUSEHOLD_CASH_JPY"] == "3000.0"
    assert env["HOS_PROTECTED_CASH_FLOOR_JPY"] == "2500"
    assert env["HOS_TARGET_INVESTMENT_JPY"] == "8000"


def test_explicit_household_cash_is_not_overwritten():
    profile = {"balances": [{"id": "cash", "category": "cash", "value_jpy": 1000, "verified": True}]}
    env = {"HOS_CURRENT_HOUSEHOLD_CASH_JPY": "1200"}
    hydrate_environment(profile, env)
    assert env["HOS_CURRENT_HOUSEHOLD_CASH_JPY"] == "1200"


def test_private_strategy_without_registered_authority_is_locked_fail_closed():
    profile = {
        "strategy": {
            "strategy_id": "PRIVATE",
            "status": "ACTIVE",
            "purchase_authority": {"mode": "OPEN", "auto_order": False, "auto_sell": False},
            "accounts": {"member_a": {"orders": []}},
        }
    }
    result = load_private_strategy(profile)
    assert result["status"] == "DRAFT"
    assert result["purchase_authority"]["mode"] == "REGISTERED_STRATEGY_ONLY"


def test_legacy_private_account_ids_are_normalized_only_in_memory():
    profile = load_private_profile({
        "HOS_PRIVATE_PROFILE_JSON": json.dumps({
            "accounts": {
                "legacy_alpha": {"display_name": "Private A", "buying_power_jpy": 3_000},
                "legacy_beta": {"display_name": "Private B", "buying_power_jpy": 5_000},
            },
            "holdings": [{"owner": "legacy_alpha", "ticker": "1111", "shares": 10, "verified": True}],
            "strategy": {
                "strategy_id": "LEGACY_PRIVATE",
                "status": "ACTIVE",
                "purchase_authority": {"mode": "REGISTERED_STRATEGY_ONLY", "auto_order": False, "auto_sell": False},
                "accounts": {"legacy_alpha": {"orders": []}, "legacy_beta": {"orders": []}},
            },
        })
    })

    assert set(profile["accounts"]) == {"member_a", "member_b"}
    assert set(profile["strategy"]["accounts"]) == {"member_a", "member_b"}
    assert profile["holdings"][0]["owner"] == "member_a"
    assert profile["_runtime_profile_migration_state"] == "LEGACY_ACCOUNT_IDS_NORMALIZED"
    assert load_private_strategy(profile)["status"] == "ACTIVE"
    assert private_account_labels(profile) == {"member_a": "Private A", "member_b": "Private B"}


def test_missing_private_strategy_remains_locked_with_non_identifying_reason():
    result = load_private_strategy({"accounts": {"member_a": {}}})
    assert result["status"] == "DRAFT"
    assert result["runtime_profile_lock_reason"] == "PRIVATE_PROFILE_REQUIRED"


def test_strategy_only_secret_recovers_plan_without_overwriting_generic_profile():
    legacy_strategy = audited_strategy()
    legacy_strategy["purchase_authority"] = {
        "mode": "REGISTERED_STRATEGY_ONLY",
        "auto_order": False,
        "auto_sell": False,
    }
    legacy_strategy["accounts"] = {
        "legacy_alpha": legacy_strategy["accounts"]["member_a"],
        "legacy_beta": {"orders": []},
    }
    profile = load_private_profile({
        "HOS_PRIVATE_PROFILE_JSON": json.dumps({
            "accounts": {"member_a": {}, "member_b": {}},
            "holdings": [],
        }),
        "HOS_PRIVATE_STRATEGY_JSON": json.dumps({
            "version": 1,
            "source_account_ids": ["legacy_alpha", "legacy_beta"],
            "strategy": legacy_strategy,
        }),
    })

    assert set(profile["strategy"]["accounts"]) == {"member_a", "member_b"}
    assert load_private_strategy(profile)["status"] == "ACTIVE"
    assert "legacy_alpha" not in json.dumps(profile)
    assert profile["_runtime_private_strategy_import_state"] == "IMPORTED"


def test_strategy_only_secret_fails_closed_on_ambiguous_account_binding():
    profile = load_private_profile({
        "HOS_PRIVATE_PROFILE_JSON": json.dumps({"accounts": {"legacy_gamma": {}}, "holdings": []}),
        "HOS_PRIVATE_STRATEGY_JSON": json.dumps({
            "version": 1,
            "source_account_ids": ["legacy_alpha"],
            "strategy": {
                "strategy_id": "PRIVATE",
                "status": "ACTIVE",
                "purchase_authority": {"mode": "REGISTERED_STRATEGY_ONLY", "auto_order": False, "auto_sell": False},
                "accounts": {"legacy_alpha": {"orders": []}},
            },
        }),
    })

    assert "strategy" not in profile
    assert profile["_runtime_private_strategy_import_state"] == "ACCOUNT_BINDING_REQUIRED"
    assert load_private_strategy(profile)["status"] == "DRAFT"


def test_unbound_strategy_secret_can_supply_anonymous_manual_logic_only():
    source_id = "legacy_alpha"
    profile = load_private_profile({
        "HOS_PRIVATE_PROFILE_JSON": json.dumps({"accounts": {"legacy_gamma": {}}, "holdings": []}),
        "HOS_PRIVATE_STRATEGY_JSON": json.dumps({
            "version": 1,
            "source_account_ids": [source_id],
            "strategy": {
                "strategy_id": "PRIVATE_SOURCE_PLAN",
                "status": "ACTIVE",
                "purchase_authority": {"mode": "REGISTERED_STRATEGY_ONLY", "auto_order": False, "auto_sell": False},
                "accounts": {source_id: {"orders": []}},
            },
        }),
    })

    manual = load_private_manual_logic_strategy(profile, {
        "HOS_PRIVATE_STRATEGY_JSON": json.dumps({
            "version": 1,
            "source_account_ids": [source_id],
            "strategy": {
                "strategy_id": "PRIVATE_SOURCE_PLAN",
                "status": "ACTIVE",
                "purchase_authority": {"mode": "REGISTERED_STRATEGY_ONLY", "auto_order": False, "auto_sell": False},
                "accounts": {source_id: {"orders": []}},
            },
        }),
    })

    assert set(manual["accounts"]) == {"member_logic_a"}
    assert manual["strategy_id"] == "PRIVATE_MANUAL_LOGIC"
    assert source_id not in json.dumps(manual)
    assert load_private_strategy(profile)["status"] == "DRAFT"


def test_unbound_manual_logic_rejects_automatic_order_authority():
    profile = {"_runtime_private_strategy_import_state": "ACCOUNT_BINDING_REQUIRED"}
    manual = load_private_manual_logic_strategy(profile, {
        "HOS_PRIVATE_STRATEGY_JSON": json.dumps({
            "version": 1,
            "source_account_ids": ["legacy_alpha"],
            "strategy": {
                "status": "ACTIVE",
                "purchase_authority": {"mode": "REGISTERED_STRATEGY_ONLY", "auto_order": True, "auto_sell": False},
                "accounts": {"legacy_alpha": {"orders": []}},
            },
        }),
    })
    assert manual == {}


def test_strategy_only_secret_never_replaces_an_existing_profile_strategy():
    existing = audited_strategy()
    existing["purchase_authority"] = {
        "mode": "REGISTERED_STRATEGY_ONLY",
        "auto_order": False,
        "auto_sell": False,
    }
    profile = load_private_profile({
        "HOS_PRIVATE_PROFILE_JSON": json.dumps({
            "accounts": {"member_a": {}},
            "strategy": existing,
        }),
        "HOS_PRIVATE_STRATEGY_JSON": json.dumps({
            "version": 1,
            "source_account_ids": ["legacy_alpha"],
            "strategy": {
                "strategy_id": "IMPORT_MUST_NOT_WIN",
                "status": "ACTIVE",
                "purchase_authority": {"mode": "REGISTERED_STRATEGY_ONLY", "auto_order": False, "auto_sell": False},
                "accounts": {"legacy_alpha": {"orders": []}},
            },
        }),
    })

    assert profile["strategy"]["strategy_id"] == "TEST_PRIVATE_STRATEGY"
    assert "_runtime_private_strategy_import_state" not in profile


def _first_signal(env):
    strategy = audited_strategy()
    price = PriceRecord("1111", "Example Income Co", 95, 100, date.today(), "mock", "medium")
    signal = evaluate_strategy(strategy, [price], env=env)[0]
    return apply_household_funding_gates([signal], strategy, env=env)[0]


def test_existing_position_completion_can_be_ready_only_after_all_funding_gates():
    signal = _first_signal(base_env())
    assert signal.actionability == "READY"
    assert signal.purchase_flag == "PURCHASE_READY"


def test_completion_is_blocked_until_transfer_lands():
    env = base_env()
    env["HOS_ACCOUNT_MEMBER_A_BUYING_POWER_JPY"] = "0"
    signal = _first_signal(env)
    assert signal.actionability == "DRAFT"
    assert "ACCOUNT_TRANSFER_REQUIRED" in signal.blocks


def test_completion_stops_above_gift_tax_guard_until_reviewed():
    env = base_env()
    env["HOS_ACCOUNT_MEMBER_A_TAXABLE_GIFTS_YTD_JPY"] = "1200000"
    assert "GIFT_TAX_REVIEW_REQUIRED" in _first_signal(env).blocks
    env["HOS_ACCOUNT_MEMBER_A_GIFT_TAX_REVIEWED"] = "true"
    assert "GIFT_TAX_REVIEW_REQUIRED" not in _first_signal(env).blocks


def test_cash_floor_blocks_when_verified_bank_cash_is_below_floor():
    env = base_env()
    env["HOS_CURRENT_HOUSEHOLD_CASH_JPY"] = "9999"
    signal = _first_signal(env)
    assert signal.actionability == "DRAFT"
    assert "PROTECTED_CASH_FLOOR_BREACH" in signal.blocks


def test_cash_at_floor_does_not_double_count_order_against_bank_cash():
    env = base_env()
    env["HOS_CURRENT_HOUSEHOLD_CASH_JPY"] = "10000"
    assert "PROTECTED_CASH_FLOOR_BREACH" not in _first_signal(env).blocks
