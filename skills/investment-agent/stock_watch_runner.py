"""Reliable scheduled runner for HOS Stock Watch V3.

This is the only production entrypoint. It fixes the trade date before invoking
V3, applies the private household profile, audited funding rules and verified
post-earnings assessments, emits one Discord report, and records a heartbeat.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import daily_stock_check as legacy
import daily_stock_check_v3 as v3
import discord_report
import stock_fetcher
from earnings_assessment import apply_earnings_assessments, load_assessment_book
from household_runtime import (
    apply_household_funding_gates,
    apply_strategy_overrides,
    hydrate_environment,
    load_private_profile,
    private_jp_watchlist,
    publish_runtime_asset_snapshot,
)
from jpx_trade_date import is_jpx_cash_session, latest_finished_jpx_cash_session
from notifier import ConsoleNotifier, DiscordNotifier, GitHubSummaryNotifier

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]
DATA_DIR = BASE_DIR / "data" / "daily_prices"
DIAGNOSTIC_PATH = ROOT_DIR / "outputs" / "stock-watch-diagnostic.json"
OVERRIDE_PATH = BASE_DIR / "config" / "strategy_household_overrides_2026-08-12.json"
EARNINGS_PATH = BASE_DIR / "config" / "earnings_assessments_2026.json"

PURCHASE_CONFIGURATION = [
    "HOS_MAHO_BUYING_POWER_JPY",
    "HOS_HIRO_BUYING_POWER_JPY",
    "HOS_MONTHLY_STOCK_BUDGET_REMAINING_JPY",
    "HOS_ANNUAL_STOCK_BUDGET_REMAINING_JPY",
    "HOS_MAX_SINGLE_ORDER_JPY",
    "HOS_TARGET_INVESTMENT_TO_2027_03_JPY",
    "HOS_MAHO_2026_STOCK_CAP_JPY",
    "HOS_MAHO_STRATEGY_BUDGET_JPY",
    "HOS_HIRO_STRATEGY_BUDGET_JPY",
    "HOS_CURRENT_HOUSEHOLD_CASH_JPY",
    "HOS_PROTECTED_CASH_FLOOR_JPY",
    "HOS_HIRO_TAXABLE_GIFTS_YTD_JPY",
]

HOUSEHOLD_BLOCK_LABELS = {
    "HOUSEHOLD_CASH_REQUIRED": "世帯現預金未設定",
    "PROTECTED_CASH_FLOOR_REQUIRED": "現金防衛ライン未設定",
    "PROTECTED_CASH_FLOOR_BREACH": "現金防衛ライン割れ",
    "EXISTING_POSITION_REQUIRED": "既存保有確認",
    "HIRO_COMPLETION_TRANSFER_REQUIRED": "補完資金の入金待ち",
    "HIRO_TAXABLE_GIFTS_YTD_REQUIRED": "課税対象贈与累計未設定",
    "GIFT_TAX_REVIEW_REQUIRED": "贈与税確認",
    "EARNINGS_AUDIT_REQUIRED": "HOS決算監査待ち",
    "EARNINGS_NEUTRAL": "決算様子見",
    "EARNINGS_NEGATIVE": "決算悪化・購入停止",
}


def _install_calendar_guard() -> None:
    legacy._is_jpx_session = is_jpx_cash_session
    stock_fetcher._is_jpx_session = is_jpx_cash_session


def _postprocess_earnings_blocks(signals, strategy):
    """Translate the generic earnings gate into the audited assessment state.

    The base planner still owns the purchase authority. This layer can only keep
    or add blocks; it never creates an executable signal by itself.
    """
    lookup = {}
    for account_name, account in strategy.get("accounts", {}).items():
        for order in account.get("orders", []):
            lookup[(str(account_name), str(order.get("ticker")))] = order

    result = []
    for signal in signals:
        order = lookup.get((str(getattr(signal, "account", "")), str(getattr(signal, "ticker", ""))), {})
        review_state = str(order.get("earnings_review_status") or "")
        blocks = list(getattr(signal, "blocks", []) or [])
        if "EARNINGS_REVIEW_REQUIRED" in blocks:
            blocks = [b for b in blocks if b != "EARNINGS_REVIEW_REQUIRED"]
            if review_state == "NEGATIVE":
                blocks.append("EARNINGS_NEGATIVE")
            elif review_state == "NEUTRAL":
                blocks.append("EARNINGS_NEUTRAL")
            else:
                blocks.append("EARNINGS_AUDIT_REQUIRED")
        result.append(replace(signal, blocks=sorted(set(blocks))))
    return result


def _install_household_runtime(profile: dict) -> None:
    base_load_strategy = v3.load_strategy
    base_strategy_watchlist = v3.strategy_watchlist
    base_evaluate_strategy = v3.evaluate_strategy
    base_render_v3 = v3._render_v3
    base_progress_lines = discord_report._progress_lines
    earnings_book = load_assessment_book(EARNINGS_PATH)

    def load_strategy_with_overrides(path):
        strategy = apply_strategy_overrides(base_load_strategy(path), OVERRIDE_PATH)
        return apply_earnings_assessments(strategy, earnings_book)

    def strategy_watchlist_with_private(strategy):
        return v3.merge_watchlists(base_strategy_watchlist(strategy), private_jp_watchlist(profile))

    def evaluate_strategy_with_household_gates(strategy, japanese_prices, policy=None, env=None):
        signals = base_evaluate_strategy(strategy, japanese_prices, policy=policy, env=env)
        signals = _postprocess_earnings_blocks(signals, strategy)
        return apply_household_funding_gates(signals, strategy, env=env)

    def render_with_asset_snapshot(universe, policy, strategy, result, mode, data_dir):
        publish_runtime_asset_snapshot(profile, result.prices)
        return base_render_v3(universe, policy, strategy, result, mode, data_dir)

    def progress_lines_with_confirmed_partial(policy, strategy, signals):
        lines = base_progress_lines(policy, strategy, signals)
        if os.getenv("HOS_CURRENT_FINANCIAL_ASSETS_JPY", "").strip():
            return lines
        partial_raw = os.getenv("HOS_CONFIRMED_INVESTED_ASSETS_JPY", "").strip()
        if not partial_raw:
            return lines
        try:
            partial = float(partial_raw)
        except ValueError:
            return lines
        missing_raw = [item for item in os.getenv("HOS_FINANCIAL_ASSETS_MISSING_ITEMS", "").split(",") if item]
        labels = []
        for item in missing_raw:
            if item == "maho_cash":
                label = "まほ現預金"
            elif item.startswith("price:"):
                label = f"{item.split(':', 1)[1]}株価"
            else:
                label = item
            if label not in labels:
                labels.append(label)
        suffix = f"｜未確定：{'・'.join(labels[:3])}" if labels else ""
        lines.insert(2, f"確認済み投資資産 {discord_report._compact_yen(partial)}{suffix}")
        return lines

    discord_report.BLOCK_LABELS.update(HOUSEHOLD_BLOCK_LABELS)
    discord_report._progress_lines = progress_lines_with_confirmed_partial
    v3.load_strategy = load_strategy_with_overrides
    v3.strategy_watchlist = strategy_watchlist_with_private
    v3.evaluate_strategy = evaluate_strategy_with_household_gates
    v3._render_v3 = render_with_asset_snapshot


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _already_complete(slot: str) -> bool:
    current = _load_json(DIAGNOSTIC_PATH)
    return (
        current.get("slot") == slot
        and current.get("status") == "success"
        and current.get("market_data_status") == "complete"
        and int(current.get("market_missing_count", 1)) == 0
        and int(current.get("market_price_count", 0)) > 0
    )


def _missing_purchase_configuration() -> list[str]:
    return [name for name in PURCHASE_CONFIGURATION if not os.getenv(name, "").strip()]


def _write_diagnostic(*, slot: str, mode: str, trade_date, delivery_confirmed: bool, notify_error: str | None = None) -> dict:
    daily_path = DATA_DIR / f"{trade_date.isoformat()}.json"
    daily = _load_json(daily_path)
    prices = daily.get("prices") or []
    missing = daily.get("missing") or []
    missing_configuration = _missing_purchase_configuration()
    missing_progress: list[str] = []
    if not os.getenv("HOS_CURRENT_FINANCIAL_ASSETS_JPY", "").strip():
        missing_progress.append("HOS_CURRENT_FINANCIAL_ASSETS_JPY")
    if not os.getenv("HOS_CURRENT_ANNUAL_DIVIDEND_JPY", "").strip():
        missing_progress.append("HOS_CURRENT_ANNUAL_DIVIDEND_JPY")
    market_complete = bool(prices) and not missing
    if not delivery_confirmed:
        status = "failure"
    elif market_complete:
        status = "success"
    else:
        status = "degraded"
    payload = {
        "slot": slot,
        "mode": mode,
        "checked_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        "status": status,
        "discord_delivery_confirmed": delivery_confirmed,
        "trade_date": trade_date.isoformat(),
        "daily_data_file": str(daily_path.relative_to(ROOT_DIR)) if daily_path.exists() else None,
        "market_price_count": len(prices),
        "market_missing_count": len(missing),
        "market_data_status": "complete" if market_complete else "incomplete",
        "retry_required": bool(missing) or not bool(prices),
        "configuration_status": "complete" if not missing_configuration else "incomplete",
        "missing_configuration": missing_configuration,
        "progress_status": "complete" if not missing_progress else "incomplete",
        "missing_progress_inputs": missing_progress,
        "private_profile_loaded": bool(os.getenv("HOS_PRIVATE_PROFILE_JSON", "").strip()),
        "earnings_assessment_book": str(EARNINGS_PATH.relative_to(ROOT_DIR)),
        "confirmed_invested_assets_jpy": os.getenv("HOS_CONFIRMED_INVESTED_ASSETS_JPY") or None,
        "financial_assets_missing_items": [item for item in os.getenv("HOS_FINANCIAL_ASSETS_MISSING_ITEMS", "").split(",") if item],
        "current_household_cash_jpy": os.getenv("HOS_CURRENT_HOUSEHOLD_CASH_JPY") or None,
        "protected_cash_floor_jpy": os.getenv("HOS_PROTECTED_CASH_FLOOR_JPY") or None,
        "hiro_taxable_gifts_ytd_jpy": os.getenv("HOS_HIRO_TAXABLE_GIFTS_YTD_JPY") or None,
        "notification_layout": "account-separated-v3-household-audit",
        "notify_error": notify_error,
    }
    DIAGNOSTIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIAGNOSTIC_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def run(mode: str, force: bool = False) -> int:
    _install_calendar_guard()
    profile = load_private_profile()
    hydrate_environment(profile)
    _install_household_runtime(profile)

    now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))
    trade_date = latest_finished_jpx_cash_session(now_jst)
    slot = f"{trade_date.isoformat()}-{mode}"
    print(f"Stock Watch production runner: JST={now_jst.isoformat()} trade_date={trade_date} mode={mode} slot={slot}")
    print(f"Private household profile loaded: {bool(profile)}")

    if not force and _already_complete(slot):
        print("Already completed successfully with complete market data; duplicate Discord notification skipped.")
        return 0

    report = v3.run(mode=mode, trade_date=trade_date)
    ConsoleNotifier().notify(report)
    GitHubSummaryNotifier().notify(report)

    delivered = False
    notify_error = None
    try:
        DiscordNotifier().notify(report)
        delivered = True
    except Exception as exc:
        notify_error = f"{type(exc).__name__}: {exc}"

    diagnostic = _write_diagnostic(slot=slot, mode=mode, trade_date=trade_date, delivery_confirmed=delivered, notify_error=notify_error)
    print(json.dumps(diagnostic, ensure_ascii=False))
    if not delivered:
        raise RuntimeError(notify_error or "Discord delivery failed")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=[v3.EVENING, v3.MORNING_RETRY], required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(args.mode, args.force))


if __name__ == "__main__":
    main()
