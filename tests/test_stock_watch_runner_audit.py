from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from stock_watch_runner import _annotate_live_household_targets


def test_additional_share_targets_include_existing_household_holdings():
    strategy = {
        "accounts": {
            "maho": {
                "orders": [
                    {"ticker": "NVDA", "target_additional_shares": 15},
                    {"ticker": "TSM", "target_additional_shares": 7},
                ]
            }
        }
    }
    profile = {
        "holdings": [
            {"owner": "hiro", "ticker": "NVDA", "shares": 25, "verified": True},
            {"owner": "hiro", "ticker": "TSM", "shares": 5, "verified": True},
        ]
    }
    result = _annotate_live_household_targets(strategy, profile)
    orders = {row["ticker"]: row for row in result["accounts"]["maho"]["orders"]}
    assert orders["NVDA"]["household_existing_shares_live"] == 25
    assert orders["NVDA"]["household_target_after_completion"] == 40
    assert orders["TSM"]["household_target_after_completion"] == 12


def test_explicit_audited_household_target_is_not_overwritten():
    strategy = {
        "accounts": {
            "maho": {
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
    profile = {"holdings": [{"owner": "hiro", "ticker": "7832", "shares": 100, "verified": True}]}
    result = _annotate_live_household_targets(strategy, profile)
    order = result["accounts"]["maho"]["orders"][0]
    assert order["household_existing_shares_live"] == 100
    assert order["household_target_after_completion"] == 300


def test_account_total_target_replaces_only_that_accounts_existing_shares():
    strategy = {
        "accounts": {
            "hiro": {
                "orders": [{"ticker": "8593", "target_total_shares": 300}]
            }
        }
    }
    profile = {
        "holdings": [
            {"owner": "hiro", "ticker": "8593", "shares": 50, "verified": True},
            {"owner": "maho", "ticker": "8593", "shares": 20, "verified": True},
        ]
    }
    result = _annotate_live_household_targets(strategy, profile)
    order = result["accounts"]["hiro"]["orders"][0]
    assert order["household_existing_shares_live"] == 70
    assert order["household_target_after_completion"] == 320
