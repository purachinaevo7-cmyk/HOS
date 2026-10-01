"""Standalone scheduled runner for the public Japanese dividend screener."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

from dividend_screener import (
    build_snapshot,
    diff_snapshots,
    load_screening_config,
    load_snapshot,
    render_discord_messages,
    screen_dividend_universe,
    write_snapshot,
)
from jpx_trade_date import is_jpx_cash_session, latest_finished_jpx_cash_session
from notifier import DiscordNotifier


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "dividend_screener_universe.json"
DEFAULT_STATE_PATH = ROOT_DIR / "runs" / "dividend-screener" / "state.json"
WEBHOOK_ENV = "DIVIDEND_SCREENER_DISCORD_WEBHOOK_URL"
MARKET_DATA_ATTEMPTS = 3
MARKET_DATA_RETRY_SECONDS = 5
_PERMANENT_ISSUES = {"CONFIGURATION_REQUIRED", "OFFICIAL_IR_STALE"}
_PUBLIC_ISSUES = _PERMANENT_ISSUES | {
    "PRICE_DATA_REQUIRED", "PRICE_DATE_MISMATCH", "HISTORICAL_YIELD_DATA_REQUIRED",
    "MARKET_DATA_REQUIRED",
}
DISCORD_RATE_LIMIT_ATTEMPTS = 3


def _safe_issue_counts(result) -> dict[str, int]:
    # Provider exception text can contain URLs or credentials; never publish it.
    return dict(Counter(
        issue.reason if issue.reason in _PUBLIC_ISSUES else "MARKET_DATA_REQUIRED"
        for issue in result.issues
    ))


def _notify_with_rate_limit_retries(notifier, message: str) -> None:
    """Retry only rejected 429 requests, never a possibly delivered message."""
    for attempt in range(1, DISCORD_RATE_LIMIT_ATTEMPTS + 1):
        try:
            notifier.notify(message)
            return
        except HTTPError as exc:
            if exc.code != 429 or attempt == DISCORD_RATE_LIMIT_ATTEMPTS:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if retry_after is None:
                try:
                    retry_after = json.loads(exc.read()).get("retry_after")
                except (ValueError, AttributeError):
                    retry_after = None
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                delay = 5.0
            # Keep waits bounded even if the response is malformed.
            if not 0 <= delay <= 30:
                delay = 5.0
            time.sleep(max(1.0, delay))


def _safe_delivery_failure(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP_{exc.code}" if 400 <= exc.code <= 599 else "HTTP_ERROR"
    if isinstance(exc, TimeoutError) or isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError):
        return "TIMEOUT"
    if isinstance(exc, URLError):
        return "CONNECTION_ERROR"
    return "DELIVERY_ERROR"


def _screen_with_retries(config, *, trade_date, market_closed: bool):
    """Retry only public-market acquisition before any Discord delivery.

    Configuration and official-IR freshness failures remain fail-closed and are
    never retried.  Keeping retries ahead of rendering/delivery prevents a
    partially delivered Discord report from being sent twice.
    """
    result = None
    attempts_used = 0
    for attempt in range(1, MARKET_DATA_ATTEMPTS + 1):
        attempts_used = attempt
        result = screen_dividend_universe(config, trade_date=trade_date, market_closed=market_closed)
        if result.is_complete:
            break
        if not result.issues or any(issue.reason in _PERMANENT_ISSUES for issue in result.issues):
            break
        if attempt < MARKET_DATA_ATTEMPTS:
            time.sleep(MARKET_DATA_RETRY_SECONDS * attempt)
    return result, attempts_used


def _write_safe_summary(*, trade_date, result, delivered: bool, dry_run: bool, attempts_used: int, delivery_failure: str = "") -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return
    status = "complete" if result.is_complete else "needs-data"
    delivery = "dry-run" if dry_run else "confirmed" if delivered else "failed"
    Path(summary_path).write_text(
        "\n".join([
            "## Japan Dividend Screener",
            f"- Trade date: {trade_date.isoformat()}",
            f"- Screen status: {status}",
            f"- Candidate count: {len(result.entries)}",
            f"- Special-dividend exclusions: {len(result.excluded)}",
            f"- Data issues: {len(result.issues)}",
            f"- Data issue reasons: {json.dumps(_safe_issue_counts(result), sort_keys=True)}",
            f"- Market-data attempts: {attempts_used}",
            f"- Discord delivery: {delivery}",
            f"- Discord failure reason: {delivery_failure or 'none'}",
            "- This job uses public market and official-IR registry data only; it cannot place orders.",
        ]) + "\n",
        encoding="utf-8",
    )


def run(*, config_path: Path = DEFAULT_CONFIG_PATH, state_path: Path = DEFAULT_STATE_PATH, dry_run: bool = False, now: datetime | None = None, status_path: Path | None = None) -> int:
    now_jst = now or datetime.now(ZoneInfo("Asia/Tokyo"))
    if now_jst.tzinfo is None:
        now_jst = now_jst.replace(tzinfo=ZoneInfo("Asia/Tokyo"))
    else:
        now_jst = now_jst.astimezone(ZoneInfo("Asia/Tokyo"))
    trade_date = latest_finished_jpx_cash_session(now_jst)
    market_closed = not is_jpx_cash_session(now_jst.date())
    config = load_screening_config(config_path)
    result, attempts_used = _screen_with_retries(config, trade_date=trade_date, market_closed=market_closed)
    previous = load_snapshot(state_path)
    snapshot = build_snapshot(result)
    changes = diff_snapshots(previous, snapshot)
    delivered = False
    delivery_failure = ""
    if dry_run:
        delivered = True
    else:
        try:
            notifier = DiscordNotifier(env_var=WEBHOOK_ENV)
            for message in render_discord_messages(result, changes):
                _notify_with_rate_limit_retries(notifier, message)
            delivered = True
        except Exception as exc:
            # Never include a webhook URL or provider exception body in CI logs.
            delivered = False
            delivery_failure = _safe_delivery_failure(exc)
    if result.is_complete and delivered:
        write_snapshot(state_path, snapshot)
    _write_safe_summary(
        trade_date=trade_date,
        result=result,
        delivered=delivered,
        dry_run=dry_run,
        attempts_used=attempts_used,
        delivery_failure=delivery_failure,
    )
    heartbeat = {
        "job": "japan-dividend-screener",
        "trade_date": trade_date.isoformat(),
        "market_closed": market_closed,
        "screen_status": "complete" if result.is_complete else "needs-data",
        "candidate_count": len(result.entries),
        "special_dividend_exclusions": len(result.excluded),
        "data_issue_count": len(result.issues),
        "data_issue_reasons": _safe_issue_counts(result),
        "market_data_attempts": attempts_used,
        "discord_delivery_confirmed": delivered and not dry_run,
        "discord_failure_reason": delivery_failure or "none",
        "dry_run": dry_run,
    }
    public_status = json.dumps(heartbeat, ensure_ascii=False)
    if status_path is not None:
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(public_status + "\n", encoding="utf-8")
    print(public_status)
    if not delivered:
        return 1
    return 0 if result.is_complete else 2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status-path", type=Path)
    args = parser.parse_args()
    raise SystemExit(run(config_path=args.config, state_path=args.state_path, dry_run=args.dry_run, status_path=args.status_path))


if __name__ == "__main__":
    main()

