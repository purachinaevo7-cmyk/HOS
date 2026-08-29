from datetime import date
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from dividend_screener import (
    DividendScreenResult,
    ScreeningIssue,
    build_snapshot,
    diff_snapshots,
    render_discord_messages,
    screen_dividend_universe,
)
import dividend_screener_runner as runner
from notifier import DiscordNotifier


AS_OF = date(2026, 8, 21)


class StaticProvider:
    def __init__(self):
        monthly = pd.date_range("2016-04-30", "2026-07-31", freq="ME")
        index = monthly.append(pd.DatetimeIndex([pd.Timestamp("2026-08-21")]))
        self.prices = pd.DataFrame({"Close": [100.0] * len(index)}, index=index)
        dividend_dates = pd.DatetimeIndex([pd.Timestamp(year, 3, 31) for year in range(2017, 2027)])
        self.payouts = pd.Series([3.0] * len(dividend_dates), index=dividend_dates)

    def history(self, code, start, end):
        return self.prices.copy()

    def dividends(self, code):
        return self.payouts.copy()


def candidate(code="1111", *, special=0.0, valid_through="2027-05-31"):
    return {
        "code": code,
        "name": "テスト連続増配",
        "fiscal_year_end_month": 3,
        "classification": "ディフェンシブ",
        "business": "テスト事業",
        "policy": "連続増配方針",
        "safety_comment": "利益とCFを確認",
        "official_ir": {
            "url": "https://example.com/ir/dividend",
            "source_as_of": "2026-05-01",
            "valid_through": valid_through,
            "ordinary_annual_per_share": 4.0,
            "special_annual_per_share": special,
        },
    }


def test_screener_uses_ordinary_forecast_and_monthly_historical_distribution():
    result = screen_dividend_universe({"history_years": 10, "universe": [candidate()]}, trade_date=AS_OF, provider=StaticProvider())

    assert result.is_complete
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.rank == 1
    assert entry.forecast_yield_percent == 4.0
    assert entry.historic_p50_percent == 3.0
    assert entry.historic_p75_percent == 3.0
    assert entry.historic_high_yield_degree == 100
    assert entry.grade == "A"
    assert entry.history_observations >= 80


def test_special_dividend_is_excluded_from_ranking_before_price_fetch():
    result = screen_dividend_universe({"history_years": 10, "universe": [candidate(special=1.0)]}, trade_date=AS_OF, provider=StaticProvider())

    assert not result.entries
    assert result.excluded == (ScreeningIssue("1111", "SPECIAL_DIVIDEND_EXCLUDED", "1.00"),)
    assert result.is_complete


def test_stale_official_ir_fails_closed_without_replacing_prior_state():
    result = screen_dividend_universe(
        {"history_years": 10, "universe": [candidate(valid_through="2026-08-20")]},
        trade_date=AS_OF,
        provider=StaticProvider(),
    )

    assert not result.is_complete
    assert result.issues[0].reason == "OFFICIAL_IR_STALE"
    assert not result.entries


def test_snapshot_diff_reports_additions_removals_and_rank_changes():
    previous = {
        "entries": {
            "1111": {"rank": 2, "grade": "B"},
            "2222": {"rank": 1, "grade": "A"},
        }
    }
    current = {
        "entries": {
            "1111": {"rank": 1, "grade": "A"},
            "3333": {"rank": 2, "grade": "B"},
        },
        "excluded": {"2222": "SPECIAL_DIVIDEND_EXCLUDED"},
    }

    messages = [change.text for change in diff_snapshots(previous, current)]

    assert "🆕 3333 新規追加" in messages
    assert "➖ 2222 削除（SPECIAL_DIVIDEND_EXCLUDED）" in messages
    assert "↑ 1111 2位→1位" in messages
    assert "🔁 1111 B→A" in messages


def test_discord_messages_include_required_metrics_and_no_trade_instruction():
    result = screen_dividend_universe({"history_years": 10, "universe": [candidate()]}, trade_date=AS_OF, provider=StaticProvider())
    messages = render_discord_messages(result, diff_snapshots(None, build_snapshot(result)))
    joined = "\n".join(messages)

    assert "1111 テスト連続増配" in joined
    assert "P50" in joined and "P75" in joined and "最大" in joined
    assert "高利回り度 100%" in joined
    assert "ディフェンシブ" in joined
    assert "連続増配方針" in joined
    assert "自動売買・売買指示は行いません" in joined
    assert all(len(message) <= 1900 for message in messages)


def test_runner_dry_run_persists_only_public_snapshot(tmp_path, monkeypatch):
    result = screen_dividend_universe({"history_years": 10, "universe": [candidate()]}, trade_date=AS_OF, provider=StaticProvider())
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(runner, "load_screening_config", lambda _path: {"history_years": 10, "universe": [candidate()]})
    monkeypatch.setattr(runner, "screen_dividend_universe", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(runner, "latest_finished_jpx_cash_session", lambda _now: AS_OF)
    monkeypatch.setattr(runner, "is_jpx_cash_session", lambda _day: True)

    assert runner.run(state_path=state_path, dry_run=True) == 0
    snapshot = runner.load_snapshot(state_path)
    assert snapshot["entries"]["1111"]["rank"] == 1
    assert "price" not in snapshot["entries"]["1111"]


def test_discord_notifier_can_use_a_separate_webhook_secret(monkeypatch):
    monkeypatch.setenv("DIVIDEND_SCREENER_DISCORD_WEBHOOK_URL", "https://discord.example/webhook")

    notifier = DiscordNotifier(env_var="DIVIDEND_SCREENER_DISCORD_WEBHOOK_URL")

    assert notifier.webhook_url == "https://discord.example/webhook"
    assert notifier.env_var == "DIVIDEND_SCREENER_DISCORD_WEBHOOK_URL"
