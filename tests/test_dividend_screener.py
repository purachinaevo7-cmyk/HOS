from datetime import date
from io import BytesIO
import json
from pathlib import Path
import sys
from urllib.error import HTTPError

import pandas as pd
import pytest


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


def test_runner_retries_transient_market_failure_before_delivery(tmp_path, monkeypatch):
    incomplete = DividendScreenResult(
        AS_OF,
        False,
        (),
        (),
        (ScreeningIssue("1111", "PRICE_DATA_REQUIRED"),),
    )
    complete = screen_dividend_universe(
        {"history_years": 10, "universe": [candidate()]},
        trade_date=AS_OF,
        provider=StaticProvider(),
    )
    results = iter((incomplete, complete))
    calls = []
    monkeypatch.setattr(runner, "load_screening_config", lambda _path: {"history_years": 10, "universe": [candidate()]})
    monkeypatch.setattr(runner, "screen_dividend_universe", lambda *_args, **_kwargs: calls.append(1) or next(results))
    monkeypatch.setattr(runner, "latest_finished_jpx_cash_session", lambda _now: AS_OF)
    monkeypatch.setattr(runner, "is_jpx_cash_session", lambda _day: True)
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

    assert runner.run(state_path=tmp_path / "state.json", dry_run=True) == 0
    assert len(calls) == 2


def test_runner_does_not_retry_permanent_official_ir_failure(tmp_path, monkeypatch):
    incomplete = DividendScreenResult(
        AS_OF,
        False,
        (),
        (),
        (ScreeningIssue("1111", "OFFICIAL_IR_STALE"),),
    )
    calls = []
    monkeypatch.setattr(runner, "load_screening_config", lambda _path: {"history_years": 10, "universe": [candidate()]})
    monkeypatch.setattr(runner, "screen_dividend_universe", lambda *_args, **_kwargs: calls.append(1) or incomplete)
    monkeypatch.setattr(runner, "latest_finished_jpx_cash_session", lambda _now: AS_OF)
    monkeypatch.setattr(runner, "is_jpx_cash_session", lambda _day: True)

    assert runner.run(state_path=tmp_path / "state.json", dry_run=True) == 2
    assert len(calls) == 1


def test_discord_notifier_can_use_a_separate_webhook_secret(monkeypatch):
    monkeypatch.setenv("DIVIDEND_SCREENER_DISCORD_WEBHOOK_URL", "https://discord.example/webhook")

    notifier = DiscordNotifier(env_var="DIVIDEND_SCREENER_DISCORD_WEBHOOK_URL")

    assert notifier.webhook_url == "https://discord.example/webhook"
    assert notifier.env_var == "DIVIDEND_SCREENER_DISCORD_WEBHOOK_URL"


def test_discord_rate_limit_retries_only_the_rejected_message(monkeypatch):
    delivered, calls, waits = [], [], []

    class RateLimitedNotifier:
        def notify(self, message):
            calls.append(message)
            if message == "second" and calls.count(message) == 1:
                raise HTTPError("https://discord.example/private", 429, "limited", {}, BytesIO(b'{"retry_after": 2.5}'))
            delivered.append(message)

    monkeypatch.setattr(runner.time, "sleep", waits.append)
    notifier = RateLimitedNotifier()
    for message in ("first", "second", "third"):
        runner._notify_with_rate_limit_retries(notifier, message)

    assert delivered == ["first", "second", "third"]
    assert calls == ["first", "second", "second", "third"]
    assert waits == [2.5]


def test_discord_rate_limit_retries_are_bounded(monkeypatch):
    calls, waits = [], []

    class AlwaysLimited:
        def notify(self, message):
            calls.append(message)
            raise HTTPError("https://discord.example/private", 429, "limited", {"Retry-After": "nan"}, BytesIO())

    monkeypatch.setattr(runner.time, "sleep", waits.append)
    with pytest.raises(HTTPError):
        runner._notify_with_rate_limit_retries(AlwaysLimited(), "report")
    assert len(calls) == 3
    assert waits == [5.0, 5.0]


@pytest.mark.parametrize("error", [TimeoutError("private URL"), HTTPError("private URL", 503, "private body", {}, BytesIO())])
def test_discord_does_not_retry_possibly_delivered_requests(monkeypatch, error):
    calls = []

    class FailedNotifier:
        def notify(self, message):
            calls.append(message)
            raise error

    monkeypatch.setattr(runner.time, "sleep", lambda _: pytest.fail("unexpected retry"))
    with pytest.raises(type(error)):
        runner._notify_with_rate_limit_retries(FailedNotifier(), "report")
    assert calls == ["report"]


def test_failed_delivery_keeps_state_and_publishes_only_safe_diagnostics(tmp_path, monkeypatch):
    result = DividendScreenResult(AS_OF, False, (), (), (
        ScreeningIssue("1111", "PRICE_DATE_MISMATCH"),
        ScreeningIssue("2222", "https://provider.example/private-token", "private body"),
    ))
    state_path, status_path, summary_path = (tmp_path / name for name in ("state.json", "status.json", "summary.md"))
    state_path.write_text('{"entries": {"1111": {"rank": 1}}}', encoding="utf-8")
    original_state = state_path.read_bytes()

    class FailedNotifier:
        def notify(self, message):
            raise HTTPError("https://discord.example/private-token", 403, "private body", {}, BytesIO())

    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    monkeypatch.setattr(runner, "load_screening_config", lambda _: {})
    monkeypatch.setattr(runner, "_screen_with_retries", lambda *args, **kwargs: (result, 3))
    monkeypatch.setattr(runner, "latest_finished_jpx_cash_session", lambda _: AS_OF)
    monkeypatch.setattr(runner, "is_jpx_cash_session", lambda _: True)
    monkeypatch.setattr(runner, "DiscordNotifier", lambda **kwargs: FailedNotifier())

    assert runner.run(state_path=state_path, status_path=status_path) == 1
    assert state_path.read_bytes() == original_state
    status = json.loads(status_path.read_text())
    assert status["discord_failure_reason"] == "HTTP_403"
    assert status["data_issue_reasons"] == {"PRICE_DATE_MISMATCH": 1, "MARKET_DATA_REQUIRED": 1}
    diagnostics = status_path.read_text() + summary_path.read_text()
    assert "private" not in diagnostics
    assert "https://" not in diagnostics

