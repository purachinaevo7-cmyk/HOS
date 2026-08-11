from datetime import date, datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from jpx_trade_date import (
    is_jpx_cash_session,
    latest_finished_jpx_cash_session,
    next_jpx_cash_session,
)


def test_mountain_day_2026_is_not_cash_session():
    assert is_jpx_cash_session(date(2026, 8, 11)) is False


def test_morning_after_mountain_day_uses_august_10_close():
    now = datetime(2026, 8, 12, 7, 32, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert latest_finished_jpx_cash_session(now) == date(2026, 8, 10)


def test_next_cash_session_after_august_10_skips_mountain_day():
    assert next_jpx_cash_session(date(2026, 8, 10)) == date(2026, 8, 12)
