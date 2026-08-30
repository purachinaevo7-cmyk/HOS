from datetime import date
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

import stock_watch_runner
from discord_report import render_public_summary
from household_runtime import load_private_profile


def test_private_profile_parse_error_never_echoes_input():
    raw = '{"display_name":"private-display-name","value_jpy":123456'
    try:
        load_private_profile({"HOS_PRIVATE_PROFILE_JSON": raw})
    except RuntimeError as exc:
        assert raw not in str(exc)
        assert "private-display-name" not in str(exc)
    else:
        raise AssertionError("invalid JSON must be rejected")


def test_diagnostic_contains_no_household_values_or_identifiers(tmp_path, monkeypatch):
    data_dir = tmp_path / "daily"
    data_dir.mkdir()
    (data_dir / "2026-01-05.json").write_text(json.dumps({"prices": [{"code": "0000"}], "missing": []}), encoding="utf-8")
    diagnostic_path = tmp_path / "diagnostic.json"
    monkeypatch.setattr(stock_watch_runner, "DATA_DIR", data_dir)
    monkeypatch.setattr(stock_watch_runner, "DIAGNOSTIC_PATH", diagnostic_path)
    monkeypatch.setenv("HOS_CURRENT_HOUSEHOLD_CASH_JPY", "123456")
    monkeypatch.setenv("HOS_PROTECTED_CASH_FLOOR_JPY", "120000")
    payload = stock_watch_runner._write_diagnostic(
        slot="2026-01-05-evening",
        mode="evening",
        trade_date=date(2026, 1, 5),
        decision_fingerprint="public-code-only",
        delivery_confirmed=True,
        private_profile_loaded=True,
    )
    serialized = json.dumps(payload)
    assert "123456" not in serialized
    assert "120000" not in serialized
    assert "cash" not in serialized.lower()
    assert "current_household_cash" not in serialized.lower()
    assert diagnostic_path.read_text(encoding="utf-8") == json.dumps(payload, ensure_ascii=False, indent=2)


def test_github_summary_renderer_is_value_free():
    text = render_public_summary(
        trade_date=date(2026, 1, 5),
        mode_label="evening",
        delivery_confirmed=True,
        private_profile_loaded=True,
    )
    assert "balances" in text
    assert "123456" not in text
    assert "member_a" not in text
    assert "PURCHASE_READY" not in text


def test_duplicate_fingerprint_changes_only_for_declared_nonfinancial_revision():
    first = stock_watch_runner._public_decision_fingerprint("revision-a")
    second = stock_watch_runner._public_decision_fingerprint("revision-b")
    assert first != second
    assert "revision-a" not in first


def test_workflow_uses_private_secrets_without_persisting_runtime_data():
    text = (ROOT / ".github" / "workflows" / "stock-watch-diagnostic.yml").read_text(encoding="utf-8")
    assert "HOS_PRIVATE_PROFILE_JSON: ${{ secrets.HOS_PRIVATE_PROFILE_JSON }}" in text
    assert "HOS_PRIVATE_STRATEGY_JSON: ${{ secrets.HOS_PRIVATE_STRATEGY_JSON }}" in text
    assert "HOS_ACCOUNT_MEMBER_" not in text
    assert "git add" not in text
    assert "tee logs/stock-watch.log" not in text
    assert "outputs/stock-watch-diagnostic.json" in text
    assert "actions/cache/restore@v4" in text
    assert "actions/cache/save@v4" in text


def test_runner_sends_private_detail_only_to_discord_and_value_free_summary(tmp_path, monkeypatch):
    profile = {
        "version": 2,
        "goals": {"target_financial_assets_jpy": 1_000_000, "target_annual_dividend_jpy": 20_000, "target_date": "2030-01-01"},
        "accounts": {"member_a": {"display_name": "Private Label", "buying_power_jpy": 5000, "strategy_budget_jpy": 5000, "annual_stock_cap_jpy": 5000}},
        "balances": [], "holdings": [], "cash_policy": {"protected_cash_floor_jpy": 0}, "budgets": {},
        "progress": {"financial_assets_jpy": 1000, "financial_assets_verified": True},
        "strategy": {"strategy_id": "PRIVATE", "status": "DRAFT", "purchase_authority": {"max_household_orders_per_day": 1, "auto_order": False, "auto_sell": False}, "accounts": {}},
    }
    data_dir = tmp_path / "daily"; data_dir.mkdir()
    trade_day = date(2026, 1, 5)
    (data_dir / f"{trade_day.isoformat()}.json").write_text(json.dumps({"prices": [{"code": "0000"}], "missing": []}), encoding="utf-8")
    monkeypatch.setattr(stock_watch_runner, "DATA_DIR", data_dir)
    monkeypatch.setattr(stock_watch_runner, "DIAGNOSTIC_PATH", tmp_path / "diagnostic.json")
    monkeypatch.setattr(stock_watch_runner, "latest_finished_jpx_cash_session", lambda _now: trade_day)
    monkeypatch.setattr(stock_watch_runner.v3, "run", lambda **_kwargs: "private report Private Label ¥1,000")
    discord, summary = [], []
    monkeypatch.setattr(stock_watch_runner, "DiscordNotifier", lambda: type("N", (), {"notify": discord.append})())
    monkeypatch.setattr(stock_watch_runner, "GitHubSummaryNotifier", lambda: type("N", (), {"notify": summary.append})())
    monkeypatch.delenv("HOS_CURRENT_ANNUAL_DIVIDEND_JPY", raising=False)
    monkeypatch.setenv("HOS_PRIVATE_PROFILE_JSON", json.dumps(profile))
    originals = (stock_watch_runner.v3.load_strategy, stock_watch_runner.v3.strategy_watchlist, stock_watch_runner.v3.evaluate_strategy, stock_watch_runner.v3._render_v3, stock_watch_runner.discord_report._progress_lines)
    try:
        assert stock_watch_runner.run("evening", force=True) == 0
        assert "Private Label" in discord[0]
        assert "Private Label" not in summary[0]
        assert "¥1,000" not in summary[0]
    finally:
        (stock_watch_runner.v3.load_strategy, stock_watch_runner.v3.strategy_watchlist, stock_watch_runner.v3.evaluate_strategy, stock_watch_runner.v3._render_v3, stock_watch_runner.discord_report._progress_lines) = originals
        os.environ.pop("HOS_CURRENT_ANNUAL_DIVIDEND_JPY", None)
