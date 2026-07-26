"""Stock Watch V3 entrypoint.

This wrapper reuses the proven V2 market-data plumbing while adding explicit
next-session order plans, account-specific strategy orders and a morning reminder
even when no retry is needed.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import daily_stock_check as legacy
from notifier import ConsoleNotifier, DiscordNotifier, GitHubSummaryNotifier
from stock_fetcher import FetchResult, fetch_market_data
from stock_watch_v3 import (
    apply_private_budget,
    decide,
    dedupe,
    fetcher_watchlist,
    load_json,
    load_universe,
    render_notification,
    write_outputs,
)
from strategy_plan import (
    evaluate_strategy,
    load_strategy,
    merge_watchlists,
    render_strategy_notification,
    strategy_watchlist,
    suppress_generic_buy_for_strategy,
    write_strategy_output,
)

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]
DATA_DIR = BASE_DIR / "data" / "daily_prices"
STRATEGY_PATH = BASE_DIR / "config" / "strategies" / "HOS_2026_FINAL_AGGRESSIVE_V2.json"
EVENING = legacy.EVENING
MORNING_RETRY = legacy.MORNING_RETRY


def _next_jpx_session(day: date) -> date:
    candidate = day + timedelta(days=1)
    while not legacy._is_jpx_session(candidate):
        candidate += timedelta(days=1)
    return candidate


def _topix_change_from_log(previous: dict[str, Any] | None) -> float | None:
    if not previous:
        return None
    for row in previous.get("topix", []):
        value = row.get("change_percent")
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _result_from_previous(previous: dict[str, Any], target_date: date) -> FetchResult:
    prices = [legacy._price_from_json(row) for row in previous.get("prices", [])]
    missing = [legacy._missing_from_json(row) for row in previous.get("missing", [])]
    return FetchResult(
        prices=prices,
        missing=missing,
        topix_change_percent=_topix_change_from_log(previous),
        topix_source_status=str(previous.get("topix_source_status") or "判定保留"),
        topix_source=str(previous.get("topix_source") or "前夜ログ"),
        trade_date=target_date,
        topix_records=[],
        topix_missing=list(previous.get("topix_missing", [])),
    )


def _bind_private_account_secrets(strategy: dict[str, Any]) -> dict[str, Any]:
    accounts = strategy.get("accounts", {})
    if "maho" in accounts:
        accounts["maho"]["buying_power_jpy_env"] = "HOS_MAHO_BUYING_POWER_JPY"
    if "hiro" in accounts:
        accounts["hiro"]["buying_power_jpy_env"] = "HOS_HIRO_BUYING_POWER_JPY"
    return strategy


def _render_v3(
    universe: list[dict[str, Any]],
    policy: dict[str, Any],
    strategy: dict[str, Any],
    result: FetchResult,
    mode: str,
    data_dir: Path,
) -> str | None:
    order_session = _next_jpx_session(result.trade_date)
    decisions = decide(
        universe,
        result.prices,
        policy,
        result.topix_change_percent,
        result.trade_date,
        order_session=order_session,
    )
    decisions = suppress_generic_buy_for_strategy(decisions, strategy)
    write_outputs(decisions, universe, policy, ROOT_DIR / "outputs")

    # The registered strategy report is authoritative. Suppressed generic BUY
    # rows remain in JSON for diagnostics but are omitted from Discord to avoid
    # two contradictory order instructions for the same ticker.
    generic_decisions = [row for row in decisions if row.actionability != "STRATEGY_CONTROLLED"]
    state_name = "notification_state_v3_morning.json" if mode == MORNING_RETRY else "notification_state_v3_evening.json"
    alerts = dedupe(
        generic_decisions,
        data_dir / state_name,
        float(policy.get("notification", {}).get("price_change_renotify_threshold_percent", 1.0)),
    )
    base_report = render_notification(
        alerts,
        generic_decisions,
        result.trade_date,
        "朝の注文確認" if mode == MORNING_RETRY else "夜の注文案",
        bool(policy.get("notification", {}).get("discord_notify_no_alert", False)),
    )

    strategy_report = None
    if strategy:
        strategy_signals = evaluate_strategy(strategy, result.prices, policy=policy)
        write_strategy_output(strategy_signals, ROOT_DIR / "outputs" / "strategy_order_plan.json")
        strategy_report = render_strategy_notification(strategy_signals)

    parts = [part for part in (strategy_report, base_report) if part]
    return "\n\n".join(parts)[:1_980] if parts else None


def run(mode: str = EVENING, trade_date: date | None = None, data_dir: Path = DATA_DIR) -> str | None:
    legacy.load_env()
    universe_path = BASE_DIR / "config" / "stock_watch_universe.json"
    policy_path = BASE_DIR / "config" / "portfolio_policy.json"
    universe = load_universe(universe_path)
    strategy = _bind_private_account_secrets(load_strategy(STRATEGY_PATH)) if STRATEGY_PATH.exists() else {}
    watchlist = merge_watchlists(fetcher_watchlist(universe), strategy_watchlist(strategy))
    policy = apply_private_budget(load_json(policy_path))
    now = legacy._jst_now()

    if mode == EVENING:
        expected_date, reason = legacy._resolve_evening_trade_date(now, trade_date)
        legacy._log_run_context(now, mode, expected_date, reason)
        context = {
            "run_at": now.isoformat(),
            "mode": mode,
            "expected_date": expected_date.isoformat(),
            "current_date": now.date().isoformat(),
            "reason": reason,
            "strategy_id": strategy.get("strategy_id"),
        }
        try:
            previous = legacy._load_previous_log(expected_date, data_dir)
        except FileNotFoundError:
            previous = None
        result = legacy._reuse_previous_successes(fetch_market_data(watchlist, expected_date), previous)
        legacy._log_latest_available_data_date(result)
        retry_required = legacy._retry_required(result)
        legacy._write_mode_log(result, mode, retry_required, data_dir, context)
        return _render_v3(universe, policy, strategy, result, mode, data_dir)

    if mode == MORNING_RETRY:
        target_date, reason = legacy._resolve_morning_trade_date(now, trade_date, data_dir)
        legacy._log_run_context(now, mode, target_date, reason)
        context = {
            "run_at": now.isoformat(),
            "mode": mode,
            "expected_date": target_date.isoformat(),
            "current_date": now.date().isoformat(),
            "reason": reason,
            "strategy_id": strategy.get("strategy_id"),
        }
        try:
            previous = legacy._load_previous_log(target_date, data_dir)
        except FileNotFoundError:
            previous = None

        if previous and not previous.get("retry_required", False):
            result = _result_from_previous(previous, target_date)
            return _render_v3(universe, policy, strategy, result, mode, data_dir)

        previous_prices = [legacy._price_from_json(row) for row in previous.get("prices", [])] if previous else []
        previous_missing = [legacy._missing_from_json(row) for row in previous.get("missing", [])] if previous else []
        missing_codes = {record.code for record in previous_missing}
        retry_watchlist = [item for item in watchlist if str(item["code"]) in missing_codes] if previous else watchlist
        retry_result = fetch_market_data(retry_watchlist, target_date)
        legacy._log_latest_available_data_date(retry_result)
        merged_by_code = {record.code: record for record in previous_prices}
        merged_by_code.update({record.code: record for record in retry_result.prices})
        prices = [merged_by_code[str(item["code"])] for item in watchlist if str(item["code"]) in merged_by_code]
        result = FetchResult(
            prices=prices,
            missing=retry_result.missing,
            topix_change_percent=retry_result.topix_change_percent,
            topix_source_status=retry_result.topix_source_status,
            topix_source=retry_result.topix_source,
            trade_date=target_date,
            topix_records=retry_result.topix_records,
            topix_missing=retry_result.topix_missing,
        )
        still_required = legacy._retry_required(result)
        legacy._write_mode_log(result, mode, still_required, data_dir, context)
        return _render_v3(universe, policy, strategy, result, mode, data_dir)

    raise ValueError(f"unknown mode: {mode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="翌営業日の注文案付き日本株監視レポートを生成する")
    parser.add_argument("--mode", choices=[EVENING, MORNING_RETRY], default=EVENING)
    args = parser.parse_args()
    report = run(args.mode)
    if report is None:
        return
    ConsoleNotifier().notify(report)
    GitHubSummaryNotifier().notify(report)
    DiscordNotifier().notify(report)


if __name__ == "__main__":
    main()
