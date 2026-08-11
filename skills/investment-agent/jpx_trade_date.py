"""JPX cash-market session helpers for Stock Watch.

The exchange_calendars package is useful, but its future holiday tables can lag
or disagree with the JPX cash-market calendar.  HOS therefore keeps explicit
JPX closures for the planning horizon and only falls back to exchange_calendars
outside that horizon.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

JPX_CLOSE_TIME = time(15, 30)

# Official JPX cash-market holidays.  Derivatives holiday trading is a separate
# market and must not be treated as a cash-equity session.
JPX_CASH_HOLIDAYS: frozenset[date] = frozenset({
    # 2026
    date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3),
    date(2026, 1, 12), date(2026, 2, 11), date(2026, 2, 23),
    date(2026, 3, 20), date(2026, 4, 29),
    date(2026, 5, 3), date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6),
    date(2026, 7, 20), date(2026, 8, 11),
    date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23),
    date(2026, 10, 12), date(2026, 11, 3), date(2026, 11, 23),
    date(2026, 12, 31),
    # 2027
    date(2027, 1, 1), date(2027, 1, 2), date(2027, 1, 3),
    date(2027, 1, 11), date(2027, 2, 11), date(2027, 2, 23),
    date(2027, 3, 21), date(2027, 3, 22), date(2027, 4, 29),
    date(2027, 5, 3), date(2027, 5, 4), date(2027, 5, 5),
    date(2027, 7, 19), date(2027, 8, 11),
    date(2027, 9, 20), date(2027, 9, 23),
    date(2027, 10, 11), date(2027, 11, 3), date(2027, 11, 23),
    date(2027, 12, 31),
})


def is_jpx_cash_session(day: date) -> bool:
    if day.weekday() >= 5 or day in JPX_CASH_HOLIDAYS:
        return False
    if day.year in {2026, 2027}:
        return True
    try:
        import exchange_calendars as xcals
        return bool(xcals.get_calendar("XJPX").is_session(day.isoformat()))
    except Exception:
        return day.weekday() < 5


def previous_jpx_cash_session(day: date) -> date:
    candidate = day - timedelta(days=1)
    while not is_jpx_cash_session(candidate):
        candidate -= timedelta(days=1)
    return candidate


def next_jpx_cash_session(day: date) -> date:
    candidate = day + timedelta(days=1)
    while not is_jpx_cash_session(candidate):
        candidate += timedelta(days=1)
    return candidate


def latest_finished_jpx_cash_session(now: datetime | None = None) -> date:
    current = now or datetime.now(ZoneInfo("Asia/Tokyo"))
    now_jst = current.astimezone(ZoneInfo("Asia/Tokyo")) if current.tzinfo else current.replace(tzinfo=ZoneInfo("Asia/Tokyo"))
    today = now_jst.date()
    if is_jpx_cash_session(today) and now_jst.time() >= JPX_CLOSE_TIME:
        return today
    return previous_jpx_cash_session(today)
