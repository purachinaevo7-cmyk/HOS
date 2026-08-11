"""Reliable scheduled runner for HOS Stock Watch V3.

This is the only production entrypoint.  It fixes the trade date before invoking
V3, patches the legacy session helper used inside V3, emits one Discord report,
and records a machine-readable heartbeat.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import daily_stock_check as legacy
import daily_stock_check_v3 as v3
import stock_fetcher
from jpx_trade_date import is_jpx_cash_session, latest_finished_jpx_cash_session
from notifier import ConsoleNotifier, DiscordNotifier, GitHubSummaryNotifier

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]
DATA_DIR = BASE_DIR / "data" / "daily_prices"
DIAGNOSTIC_PATH = ROOT_DIR / "outputs" / "stock-watch-diagnostic.json"

REQUIRED_CONFIGURATION = [
    "HOS_CURRENT_FINANCIAL_ASSETS_JPY",
    "HOS_CURRENT_ANNUAL_DIVIDEND_JPY",
    "HOS_MAHO_BUYING_POWER_JPY",
    "HOS_HIRO_BUYING_POWER_JPY",
    "HOS_MONTHLY_STOCK_BUDGET_REMAINING_JPY",
    "HOS_ANNUAL_STOCK_BUDGET_REMAINING_JPY",
    "HOS_MAX_SINGLE_ORDER_JPY",
    "HOS_HOUSEHOLD_AVAILABLE_CASH_JPY",
    "HOS_TARGET_INVESTMENT_TO_2027_03_JPY",
    "HOS_RESERVE_AFTER_EXECUTION_JPY",
    "HOS_MAHO_2026_STOCK_CAP_JPY",
    "HOS_MAHO_STRATEGY_BUDGET_JPY",
    "HOS_HIRO_STRATEGY_BUDGET_JPY",
]


def _install_calendar_guard() -> None:
    # V3 still reuses two legacy helpers.  Keep all cash-market date decisions on
    # the same JPX holiday source until the legacy modules are retired.
    legacy._is_jpx_session = is_jpx_cash_session
    stock_fetcher._is_jpx_session = is_jpx_cash_session


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


def _write_diagnostic(*, slot: str, mode: str, trade_date, delivery_confirmed: bool, notify_error: str | None = None) -> dict:
    daily_path = DATA_DIR / f"{trade_date.isoformat()}.json"
    daily = _load_json(daily_path)
    prices = daily.get("prices") or []
    missing = daily.get("missing") or []
    missing_configuration = [name for name in REQUIRED_CONFIGURATION if not os.getenv(name, "").strip()]
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
        "notification_layout": "account-separated-v2",
        "notify_error": notify_error,
    }
    DIAGNOSTIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIAGNOSTIC_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def run(mode: str, force: bool = False) -> int:
    _install_calendar_guard()
    now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))
    trade_date = latest_finished_jpx_cash_session(now_jst)
    slot = f"{trade_date.isoformat()}-{mode}"
    print(f"Stock Watch production runner: JST={now_jst.isoformat()} trade_date={trade_date} mode={mode} slot={slot}")

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

    diagnostic = _write_diagnostic(
        slot=slot,
        mode=mode,
        trade_date=trade_date,
        delivery_confirmed=delivered,
        notify_error=notify_error,
    )
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
