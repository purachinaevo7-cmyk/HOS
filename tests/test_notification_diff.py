from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "investment-agent"))

from notification_diff import build_private_notification_state, diff_private_notification_state


class Signal:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class Line:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class Dividends:
    def __init__(self, lines):
        self.lines = lines


def test_diff_orders_ready_then_earnings_then_dividend_and_reconciliation():
    strategy = {"accounts": {"member_a": {"orders": [{"ticker": "1111", "earnings_review_status": "POSITIVE"}]}}, "execution_reconciliation_audit": [{"account": "member_a", "ticker": "1111", "expected_shares": 50, "actual_shares": 75, "reason": "HOLDING_AND_EXECUTION_MISMATCH"}]}
    signal = Signal(account="member_a", ticker="1111", name="Example", status="READY", actionability="READY", blocks=[])
    dividends = Dividends([Line(owner="member_a", ticker="1111", scope="CURRENT", status="CONFIRMED", ordinary_cash_jpy=272)])
    current = build_private_notification_state(strategy, [signal], dividends)
    previous = {"signals": {"member_a:1111": {"status": "WAIT", "actionability": "DRAFT", "earnings": "NEEDS_DATA", "blocks": [], "name": "Example"}}, "dividends": {"member_a:1111": 242}, "reconciliation": {}}
    changes = diff_private_notification_state(previous, current)
    assert changes[0].category == "PURCHASE_READY"
    assert any(change.category == "EARNINGS" and "POSITIVE" in change.text for change in changes)
    assert any(change.category == "DIVIDEND" and "+30円" in change.text for change in changes)
    assert any(change.category == "RECONCILIATION" and "75株" in change.text for change in changes)


def test_first_run_is_not_noisy_about_unchanged_baseline():
    current = {"version": 1, "signals": {}, "dividends": {}, "reconciliation": {}, "replacements": {}}
    assert diff_private_notification_state(None, current) == []
