from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from stock_watch_runner import _annotate_live_household_targets, _full_financial_assets_for_authority, _private_profile_runtime_notices


def test_additional_share_targets_include_existing_household_holdings():
    strategy = {
        "accounts": {
            "member_b": {
                "orders": [
                    {"ticker": "NVDA", "target_additional_shares": 15},
                    {"ticker": "TSM", "target_additional_shares": 7},
                ]
            }
        }
    }
    profile = {
        "holdings": [
            {"owner": "member_a", "ticker": "NVDA", "shares": 25, "verified": True},
            {"owner": "member_a", "ticker": "TSM", "shares": 5, "verified": True},
        ]
    }
    result = _annotate_live_household_targets(strategy, profile)
    orders = {row["ticker"]: row for row in result["accounts"]["member_b"]["orders"]}
    assert orders["NVDA"]["household_existing_shares_live"] == 25
    assert orders["NVDA"]["household_target_after_completion"] == 40
    assert orders["TSM"]["household_target_after_completion"] == 12


def test_explicit_audited_household_target_is_not_overwritten():
    strategy = {
        "accounts": {
            "member_b": {
                "orders": [
                    {
                        "ticker": "7832",
                        "target_shares": 200,
                        "household_target_after_completion": 300,
                    }
                ]
            }
        }
    }
    profile = {"holdings": [{"owner": "member_a", "ticker": "7832", "shares": 100, "verified": True}]}
    result = _annotate_live_household_targets(strategy, profile)
    order = result["accounts"]["member_b"]["orders"][0]
    assert order["household_existing_shares_live"] == 100
    assert order["household_target_after_completion"] == 300


def test_account_total_target_replaces_only_that_accounts_existing_shares():
    strategy = {
        "accounts": {
            "member_a": {
                "orders": [{"ticker": "8593", "target_total_shares": 300}]
            }
        }
    }
    profile = {
        "holdings": [
            {"owner": "member_a", "ticker": "8593", "shares": 50, "verified": True},
            {"owner": "member_b", "ticker": "8593", "shares": 20, "verified": True},
        ]
    }
    result = _annotate_live_household_targets(strategy, profile)
    order = result["accounts"]["member_a"]["orders"][0]
    assert order["household_existing_shares_live"] == 70
    assert order["household_target_after_completion"] == 320


def test_private_profile_migration_notices_do_not_contain_account_or_financial_values():
    assert _private_profile_runtime_notices({}, {"runtime_profile_lock_reason": "PRIVATE_PROFILE_REQUIRED"}) == [
        "⚠️ HOS側：Private Profileの登録戦略が未移行のため、購入判定を安全停止中"
    ]
    assert _private_profile_runtime_notices({"_runtime_profile_migration_state": "LEGACY_ACCOUNT_IDS_NORMALIZED"}, {}) == [
        "ℹ️ HOS側：旧口座IDを内部で安全に移行済み。次回Secret更新時にProfile v2へ更新してください"
    ]


def test_strategy_import_migration_notices_are_non_identifying_and_fail_closed():
    invalid = _private_profile_runtime_notices({"_runtime_private_strategy_import_state": "INVALID"}, {})
    ambiguous = _private_profile_runtime_notices({"_runtime_private_strategy_import_state": "ACCOUNT_BINDING_REQUIRED"}, {})
    assert invalid == ["⚠️ HOS側：登録戦略Secretの形式不備のため、購入判定を安全停止中"]
    assert ambiguous == ["⚠️ HOS側：登録戦略SecretとPrivate Profileの口座照合が必要なため、購入判定を安全停止中"]
    assert "member_" not in "".join(invalid + ambiguous)


def test_unbound_strategy_notice_keeps_order_safety_but_announces_manual_logic_panel():
    notice = _private_profile_runtime_notices(
        {"_runtime_private_strategy_import_state": "ACCOUNT_BINDING_REQUIRED"},
        {},
        manual_logic_available=True,
    )
    assert notice == ["ℹ️ HOS側：口座別の発注安全判定は保留。銘柄ロジックを手動判断用に表示中"]
    assert "member_" not in "".join(notice)


def test_partial_asset_snapshot_never_clears_concentration_authority_gate():
    assert _full_financial_assets_for_authority({
        "complete": False,
        "confirmed_partial_jpy": 1_000_000,
        "current_financial_assets_jpy": None,
    }) is None
    assert _full_financial_assets_for_authority({
        "complete": True,
        "confirmed_partial_jpy": 1_000_000,
        "current_financial_assets_jpy": 1_000_000,
    }) == 1_000_000

