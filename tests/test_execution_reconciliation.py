from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "investment-agent"))

from execution_reconciliation import reconcile_private_holdings
from stock_watch_runner import _postprocess_execution_reconciliation
from stock_analyzer import PriceRecord
from strategy_plan import evaluate_strategy


def strategy():
    return {"strategy_id": "PRIVATE", "status": "ACTIVE", "purchase_authority": {"max_household_orders_per_day": 1}, "funding": {}, "accounts": {"member_a": {"target_budget_jpy_env": "BUDGET", "buying_power_jpy_env": "POWER", "orders": [{"ticker": "1111", "name": "Example", "market": "JP", "currency": "JPY", "fy2026_decision": "BUY_2026_CORE", "purchase_class": "CORE_DIVIDEND", "execution_priority": 1, "strategy_start_shares": 50, "completed_step_ids": [], "order_steps": [{"step_id": "1111-1", "shares": 25, "limit_price": 100}, {"step_id": "1111-2", "shares": 25, "limit_price": 90}]}]}}}


def test_increased_holding_requires_confirmation_without_mutating_completed_steps():
    original = strategy()
    reconciled, findings = reconcile_private_holdings({"holdings": [{"owner": "member_a", "ticker": "1111", "shares": 75, "verified": True}]}, original)
    order = reconciled["accounts"]["member_a"]["orders"][0]
    assert findings[0].reason == "HOLDING_AND_EXECUTION_MISMATCH"
    assert findings[0].expected_shares == 50 and findings[0].actual_shares == 75
    assert order["execution_reconciliation_required"] is True
    assert order["completed_step_ids"] == []
    assert original["accounts"]["member_a"]["orders"][0]["completed_step_ids"] == []


def test_mismatch_blocks_pending_step_even_when_its_limit_is_reached():
    reconciled, _ = reconcile_private_holdings({"holdings": [{"owner": "member_a", "ticker": "1111", "shares": 75, "verified": True}]}, strategy())
    signal = evaluate_strategy(reconciled, [PriceRecord("1111", "Example", 100, 101, date.today(), "test", "medium")], env={"BUDGET": "100000", "POWER": "100000"})[0]
    blocked = _postprocess_execution_reconciliation([signal], reconciled)[0]
    assert reconciled["accounts"]["member_a"]["orders"][0]["execution_reconciliation_required"] is True
    assert signal.purchase_flag == "PURCHASE_READY"
    assert blocked.purchase_flag == "REVIEW_REQUIRED"
    assert blocked.actionability == "DRAFT"
    assert "EXECUTION_RECONCILIATION_REQUIRED" in blocked.blocks
