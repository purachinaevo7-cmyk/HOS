"""Standalone scheduled runner for the public Japanese dividend screener."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
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


def _write_safe_summary(*, trade_date, result, delivered: bool, dry_run: bool) -> None:
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
            f"- Discord delivery: {delivery}",
            "- This job uses public market and official-IR registry data only; it cannot place orders.",
        ]) + "\n",
        encoding="utf-8",
    )


def run(*, config_path: Path = DEFAULT_CONFIG_PATH, state_path: Path = DEFAULT_STATE_PATH, dry_run: bool = False, now: datetime | None = None) -> int:
    now_jst = now or datetime.now(ZoneInfo("Asia/Tokyo"))
    if now_jst.tzinfo is None:
        now_jst = now_jst.replace(tzinfo=ZoneInfo("Asia/Tokyo"))
    else:
        now_jst = now_jst.astimezone(ZoneInfo("Asia/Tokyo"))
    trade_date = latest_finished_jpx_cash_session(now_jst)
    market_closed = not is_jpx_cash_session(now_jst.date())
    config = load_screening_config(config_path)
    result = screen_dividend_universe(config, trade_date=trade_date, market_closed=market_closed)
    previous = load_snapshot(state_path)
    snapshot = build_snapshot(result)
    changes = diff_snapshots(previous, snapshot)
    delivered = False
    if dry_run:
        delivered = True
    else:
        try:
            notifier = DiscordNotifier(env_var=WEBHOOK_ENV)
            for message in render_discord_messages(result, changes):
                notifier.notify(message)
            delivered = True
        except Exception:
            # Never include a webhook URL or provider exception body in CI logs.
            delivered = False
    if result.is_complete and delivered:
        write_snapshot(state_path, snapshot)
    _write_safe_summary(trade_date=trade_date, result=result, delivered=delivered, dry_run=dry_run)
    heartbeat = {
        "job": "japan-dividend-screener",
        "trade_date": trade_date.isoformat(),
        "market_closed": market_closed,
        "screen_status": "complete" if result.is_complete else "needs-data",
        "candidate_count": len(result.entries),
        "special_dividend_exclusions": len(result.excluded),
        "data_issue_count": len(result.issues),
        "discord_delivery_confirmed": delivered and not dry_run,
        "dry_run": dry_run,
    }
    print(json.dumps(heartbeat, ensure_ascii=False))
    if not delivered:
        return 1
    return 0 if result.is_complete else 2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(config_path=args.config, state_path=args.state_path, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
