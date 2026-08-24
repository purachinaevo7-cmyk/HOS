from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
import sys
sys.path.insert(0, str(BASE))

from stock_analyzer import PriceRecord
from stock_watch_v3 import (
    apply_private_budget,
    decide,
    dedupe,
    entry_levels,
    fetcher_watchlist,
    load_json,
    load_universe,
    render_notification,
    round_limit_down,
    watchlist_review,
    write_outputs,
)


def fixture_policy():
    return load_json(BASE / "config" / "portfolio_policy.json")


def fixture_universe():
    return load_universe(BASE / "config" / "stock_watch_universe.json")


def test_existing_universe_stays_available_as_research_universe():
    universe = fixture_universe()
    assert len(universe) == 40
    assert not any("owned" in row or "current_shares" in row for row in universe)
    assert len(fetcher_watchlist(universe)) == 40


def test_entry_levels_are_next_session_limits_and_use_valid_ticks():
    assert entry_levels(1000, "medium", fixture_policy()) == (990, 980, 965)
    assert round_limit_down(3880.5) == 3880
    assert round_limit_down(12003) == 12000


def test_missing_budget_and_facts_keeps_exact_plan_as_draft():
    universe = [row for row in fixture_universe() if row["ticker"] == "4063"]
    price = PriceRecord("4063", "信越化学工業", 3900, 4200, date(2026, 7, 14), "mock", "large")
    row = decide(universe, [price], fixture_policy(), -0.5, date(2026, 7, 14), date(2026, 7, 15))[0]
    assert row.status == "BUY_CANDIDATE"
    assert row.actionability == "BUDGET_AND_FACTS_REQUIRED"
    assert row.order_plan_status == "DRAFT"
    assert row.limit_price == 3880
    assert row.recommended_shares is None
    assert row.valid_until == "2026-07-15T15:30:00+09:00"


def test_verified_facts_and_private_budget_produce_ready_member_b_order():
    universe = [{
        **row,
        "fundamentals_as_of": "2026-07-10",
        "fundamentals_verified": True,
        "valuation_as_of": "2026-07-14",
        "valuation_verified": True,
        "news_as_of": "2026-07-14",
        "news_verified": True,
    } for row in fixture_universe() if row["ticker"] == "4063"]
    policy = apply_private_budget(fixture_policy(), {
        "HOS_EXECUTION_ACCOUNT": "member_b",
        "HOS_ACCOUNT_MEMBER_B_BUYING_POWER_JPY": "300000",
        "HOS_MONTHLY_STOCK_BUDGET_REMAINING_JPY": "100000",
        "HOS_ANNUAL_STOCK_BUDGET_REMAINING_JPY": "1000000",
        "HOS_MAX_SINGLE_ORDER_JPY": "100000",
        "HOS_ALLOW_ODD_LOT": "true",
    })
    price = PriceRecord("4063", "信越化学工業", 3900, 4200, date(2026, 7, 14), "mock", "large")
    row = decide(universe, [price], policy, -0.5, date(2026, 7, 14), date(2026, 7, 15))[0]
    assert row.status == "BUY"
    assert row.actionability == "READY"
    assert row.execution_account == "member_b"
    assert row.limit_price == 3880
    assert row.recommended_shares and row.recommended_shares > 0
    assert row.estimated_amount == row.recommended_shares * row.limit_price


def test_large_drop_is_never_ready_without_news_review():
    universe = [row for row in fixture_universe() if row["ticker"] == "5713"]
    price = PriceRecord("5713", "住友金属鉱山", 900, 1000, date(2026, 7, 14), "mock", "high")
    row = decide(universe, [price], fixture_policy(), 0.1, date(2026, 7, 14), date(2026, 7, 15))[0]
    assert row.status == "REVIEW_REQUIRED"
    assert row.actionability != "READY"


def test_notification_has_price_quantity_deadline_account_and_no_fake_score():
    universe = [row for row in fixture_universe() if row["ticker"] == "4063"]
    price = PriceRecord("4063", "信越化学工業", 3900, 4200, date(2026, 7, 14), "mock", "large")
    rows = decide(universe, [price], fixture_policy(), -0.5, date(2026, 7, 14), date(2026, 7, 15))
    message = render_notification(rows, rows, date(2026, 7, 14), "夜の注文案")
    assert "口座: member_a" in message
    assert "仮指値 ¥3,880以下" in message
    assert "数量未計算" in message
    assert "2026/07/15 15:30まで" in message
    assert "score" not in message


def test_watchlist_review_splits_daily_core_secondary_and_monitor(tmp_path):
    universe = fixture_universe()
    review = watchlist_review(universe)
    assert review["watch_enabled_count"] == 40
    assert review["daily_core_count"] > 0
    assert review["secondary_count"] > 0
    assert review["monitor_only_count"] > 0
    one = [row for row in universe if row["ticker"] == "4063"]
    price = PriceRecord("4063", "信越化学工業", 3900, 4200, date(2026, 7, 14), "mock", "large")
    rows = decide(one, [price], fixture_policy(), -1, date(2026, 7, 14), date(2026, 7, 15))
    write_outputs(rows, one, fixture_policy(), tmp_path)
    assert (tmp_path / "stock_watch_decisions.json").exists()
    assert (tmp_path / "watchlist_review.json").exists()
    first = dedupe(rows, tmp_path / "state.json")
    second = dedupe(rows, tmp_path / "state.json")
    assert len(first) == 1 and first[0].new_signal is True and second == []


def test_daily_order_limit_allows_only_top_ranked_ready_order():
    source = next(row for row in fixture_universe() if row["ticker"] == "4063")
    universe = [{
        **row,
        "fundamentals_as_of": "2026-07-10",
        "fundamentals_verified": True,
        "valuation_as_of": "2026-07-14",
        "valuation_verified": True,
        "news_as_of": "2026-07-14",
        "news_verified": True,
    } for row in [source, {**source, "ticker": "9999", "company_name": "Example Two"}]]
    policy = apply_private_budget(fixture_policy(), {
        "HOS_ACCOUNT_MEMBER_A_BUYING_POWER_JPY": "600000",
        "HOS_MONTHLY_STOCK_BUDGET_REMAINING_JPY": "600000",
            "HOS_ANNUAL_STOCK_BUDGET_REMAINING_JPY": "2000000",
            "HOS_MAX_SINGLE_ORDER_JPY": "600000",
            "HOS_ALLOW_ODD_LOT": "true",
    })
    prices = [
        PriceRecord("4063", "信越化学工業", 3900, 4200, date(2026, 7, 14), "mock", "large"),
        PriceRecord("9999", "Example Two", 3900, 4200, date(2026, 7, 14), "mock", "large"),
    ]
    rows = decide(universe, prices, policy, -0.5, date(2026, 7, 14), date(2026, 7, 15))
    assert sum(row.actionability == "READY" for row in rows) == 1
    assert sum(row.actionability == "DAILY_ORDER_LIMIT" for row in rows) == 1
