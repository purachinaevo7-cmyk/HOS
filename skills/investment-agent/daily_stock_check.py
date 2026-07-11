"""HOS Investment Agent entrypoint."""
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from stock_analyzer import MissingRecord, PriceRecord, analyze_stocks
from notifier import ConsoleNotifier, DiscordNotifier, GitHubSummaryNotifier
from stock_fetcher import FetchResult, fetch_market_data, save_daily_prices
from stock_reporter import generate_report

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]
DATA_DIR = BASE_DIR / "data" / "daily_prices"

EVENING = "evening"
MORNING_RETRY = "morning-retry"
MODE_LABELS = {
    EVENING: "夜間通常取得",
    MORNING_RETRY: "朝補完取得",
}


def load_env() -> None:
    if importlib.util.find_spec("dotenv") is not None:
        from dotenv import load_dotenv
        load_dotenv(ROOT_DIR / ".env")


def load_yaml(path: Path) -> Any:
    """Load the small YAML config files used by this skill without external deps."""
    lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if path.name == "watchlist.yaml":
        items: list[dict[str, str]] = []
        current: dict[str, str] | None = None
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- "):
                if current:
                    items.append(current)
                current = {}
                key, value = stripped[2:].split(":", 1)
                current[key.strip()] = value.strip().strip('"')
            elif current is not None and ":" in stripped:
                key, value = stripped.split(":", 1)
                current[key.strip()] = value.strip().strip('"')
        if current:
            items.append(current)
        return {"watchlist": items}

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for line in lines:
        indent = len(line) - len(line.lstrip(" "))
        key, value = line.strip().split(":", 1)
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value.strip() == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            scalar = value.strip().strip('"')
            try:
                parent[key] = float(scalar)
            except ValueError:
                parent[key] = scalar
    return root


def _jst_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Tokyo"))


def _jst_today() -> date:
    return _jst_now().date()


JAPANESE_WEEKDAYS = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
JPX_CLOSE_TIME = time(15, 30)


def _is_jpx_session(day: date) -> bool:
    try:
        import exchange_calendars as xcals
        calendar = xcals.get_calendar("XJPX")
        return calendar.is_session(day.isoformat())
    except Exception:
        # Fallback for tests/minimal environments: weekends, common JPX holidays,
        # and the Dec 31-Jan 3 market closure are non-sessions.
        fixed_holidays = {(1, 1), (1, 2), (1, 3), (12, 31)}
        known_holidays = {date(2026, 2, 23), date(2026, 7, 20), date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)}
        return day.weekday() < 5 and (day.month, day.day) not in fixed_holidays and day not in known_holidays


def _previous_jpx_session(current: date) -> date:
    day = current - timedelta(days=1)
    while not _is_jpx_session(day):
        day -= timedelta(days=1)
    return day


def _latest_jpx_session_on_or_before(current: date) -> date:
    day = current
    while not _is_jpx_session(day):
        day -= timedelta(days=1)
    return day


def _latest_finished_business_day(now: datetime) -> date:
    now_jst = now.astimezone(ZoneInfo("Asia/Tokyo")) if now.tzinfo else now.replace(tzinfo=ZoneInfo("Asia/Tokyo"))
    if _is_jpx_session(now_jst.date()) and now_jst.time() >= JPX_CLOSE_TIME:
        return now_jst.date()
    return _previous_jpx_session(now_jst.date())


def _resolve_evening_trade_date(now: datetime, override: date | None) -> tuple[date, str]:
    if override is not None:
        return override, "明示指定されたtrade_dateを使用"
    return _latest_finished_business_day(now), "実行時点で終了済みの直近東証営業日"


def _resolve_morning_trade_date(now: datetime, override: date | None, data_dir: Path) -> tuple[date, str]:
    if override is not None:
        return override, "明示指定されたtrade_dateを使用"
    fallback = _latest_finished_business_day(now)
    path = data_dir / f"{fallback.isoformat()}.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        trade_date_value = payload.get("trade_date")
        if trade_date_value:
            return date.fromisoformat(str(trade_date_value)), f"前夜JSON（{path.name}）が存在するため、そのtrade_dateを優先"
    return fallback, "前夜JSONがないため、実行時点で終了済みの直近東証営業日"


def _github_actions_delay(now: datetime, expected_date: date) -> timedelta:
    scheduled = datetime.combine(expected_date, time(21, 0), tzinfo=ZoneInfo("Asia/Tokyo"))
    now_jst = now.astimezone(ZoneInfo("Asia/Tokyo")) if now.tzinfo else now.replace(tzinfo=ZoneInfo("Asia/Tokyo"))
    return max(now_jst - scheduled, timedelta(0))


def _format_timedelta(delta: timedelta) -> str:
    total_minutes = int(delta.total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}時間{minutes:02d}分"


def _latest_available_data_date(result: FetchResult) -> date | None:
    dates = [p.price_date for p in result.prices]
    dates.extend(t.price_date for t in result.topix_records)
    for topix in result.topix_records:
        dates.extend(component.price_date for component in topix.components)
    return max(dates, default=None)


def _log_run_context(now: datetime, mode: str, expected_date: date, reason: str) -> None:
    now_jst = now.astimezone(ZoneInfo("Asia/Tokyo")) if now.tzinfo else now.replace(tzinfo=ZoneInfo("Asia/Tokyo"))
    now_utc = now_jst.astimezone(timezone.utc)
    print(f"GitHub実行日時 UTC: {now_utc.strftime('%Y-%m-%d %H:%M')}")
    print(f"実行日時JST: {now_jst.strftime('%Y-%m-%d %H:%M')}")
    print(f"曜日: {JAPANESE_WEEKDAYS[now_jst.weekday()]}")
    print(f"実行モード: {mode} ({MODE_LABELS[mode]})")
    print(f"対象取引日: {expected_date.isoformat()}")
    print(f"対象取引日の曜日: {JAPANESE_WEEKDAYS[expected_date.weekday()]}")
    print(f"対象取引日の決定理由: {reason}")
    print(f"GitHub Actions遅延時間: {_format_timedelta(_github_actions_delay(now_jst, expected_date))}")


def _log_latest_available_data_date(result: FetchResult) -> None:
    latest = _latest_available_data_date(result)
    print(f"最新取得可能データ日: {latest.isoformat() if latest else '未取得'}")


def _retry_required(result: FetchResult) -> bool:
    return bool(result.missing) or result.topix_source_status not in {"通常判定", "一致", "TOPIX ETF中央値（参考判定）"}


def _price_from_json(row: dict[str, Any]) -> PriceRecord:
    return PriceRecord(
        str(row["code"]),
        str(row["name"]),
        float(row["close"]),
        float(row["previous_close"]),
        date.fromisoformat(str(row["price_date"])),
        str(row["source"]),
        str(row["volatility"]),
    )


def _missing_from_json(row: dict[str, Any]) -> MissingRecord:
    return MissingRecord(str(row["code"]), str(row["name"]), str(row["reason"]))


def _load_previous_log(trade_date: date, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    path = data_dir / f"{trade_date.isoformat()}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _write_mode_log(result: FetchResult, mode: str, retry_required: bool, data_dir: Path = DATA_DIR, run_context: dict[str, str] | None = None) -> Path:
    path = save_daily_prices(result, data_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["run_mode"] = mode
    payload["mode"] = mode
    payload["mode_label"] = MODE_LABELS[mode]
    payload["retry_required"] = retry_required
    if run_context:
        payload["run_context"] = run_context
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path



def _reuse_previous_successes(result: FetchResult, previous: dict[str, Any] | None) -> FetchResult:
    if not previous:
        return result
    current_by_code = {p.code: p for p in result.prices}
    missing_by_code = {m.code: m for m in result.missing}
    reused: list[PriceRecord] = []
    for row in previous.get("prices", []):
        code = str(row.get("code"))
        if code in current_by_code or code not in missing_by_code:
            continue
        record = _price_from_json(row)
        reused.append(PriceRecord(record.code, record.name, record.close, record.previous_close, record.price_date, f"{record.source}（前回取得済みデータ）", record.volatility))
    if not reused:
        return result
    prices = result.prices + reused
    reused_codes = {p.code for p in reused}
    missing = [m for m in result.missing if m.code not in reused_codes]
    return FetchResult(prices, missing, result.topix_change_percent, result.topix_source_status, result.topix_source, result.trade_date, result.topix_records, result.topix_missing)

def _build_report(result: FetchResult, thresholds: Any, buy_ranges: Any, mode: str, morning_incomplete: bool = False) -> str:
    analysis = analyze_stocks(result.prices, result.topix_change_percent, thresholds, buy_ranges)
    return generate_report(
        result.trade_date,
        result.topix_change_percent,
        result.topix_source_status,
        analysis,
        result.prices,
        result.missing,
        result.topix_missing,
        mode_label=MODE_LABELS[mode],
        morning_retry_incomplete=morning_incomplete if mode == MORNING_RETRY else None,
    )


def run(mode: str = EVENING, trade_date: date | None = None, data_dir: Path = DATA_DIR) -> str | None:
    load_env()
    watchlist_data = load_yaml(BASE_DIR / "config" / "watchlist.yaml")
    thresholds = load_yaml(BASE_DIR / "config" / "thresholds.yaml")
    buy_ranges_data = load_yaml(BASE_DIR / "config" / "buy_ranges.yaml")
    watchlist = watchlist_data["watchlist"]
    buy_ranges = buy_ranges_data["buy_ranges_percent"]

    now = _jst_now()

    if mode == EVENING:
        expected_date, reason = _resolve_evening_trade_date(now, trade_date)
        _log_run_context(now, mode, expected_date, reason)
        context = {"run_at": now.isoformat(), "mode": mode, "expected_date": expected_date.isoformat(), "current_date": now.date().isoformat(), "reason": reason}
        previous = None
        try:
            previous = _load_previous_log(expected_date, data_dir)
        except FileNotFoundError:
            previous = None
        result = _reuse_previous_successes(fetch_market_data(watchlist, expected_date), previous)
        _log_latest_available_data_date(result)
        retry_required = _retry_required(result)
        _write_mode_log(result, mode, retry_required, data_dir, context)
        return _build_report(result, thresholds, buy_ranges, mode)

    if mode == MORNING_RETRY:
        target_date, reason = _resolve_morning_trade_date(now, trade_date, data_dir)
        _log_run_context(now, mode, target_date, reason)
        context = {"run_at": now.isoformat(), "mode": mode, "expected_date": target_date.isoformat(), "current_date": now.date().isoformat(), "reason": reason}
        try:
            previous = _load_previous_log(target_date, data_dir)
        except FileNotFoundError:
            previous = None
        if previous and not previous.get("retry_required", False):
            return None
        previous_prices = [_price_from_json(row) for row in previous.get("prices", [])] if previous else []
        previous_missing = [_missing_from_json(row) for row in previous.get("missing", [])] if previous else []
        missing_codes = {record.code for record in previous_missing}
        retry_watchlist = [item for item in watchlist if str(item["code"]) in missing_codes] if previous else watchlist
        retry_result = fetch_market_data(retry_watchlist, target_date)
        _log_latest_available_data_date(retry_result)
        merged_by_code = {record.code: record for record in previous_prices}
        merged_by_code.update({record.code: record for record in retry_result.prices})
        prices = [merged_by_code[str(item["code"])] for item in watchlist if str(item["code"]) in merged_by_code]
        unresolved_codes = {record.code for record in retry_result.missing}
        missing = [record for record in retry_result.missing if record.code in unresolved_codes]
        result = FetchResult(
            prices,
            missing,
            retry_result.topix_change_percent,
            retry_result.topix_source_status,
            retry_result.topix_source,
            target_date,
            retry_result.topix_records,
            retry_result.topix_missing,
        )
        still_required = _retry_required(result)
        _write_mode_log(result, mode, still_required, data_dir, context)
        return _build_report(result, thresholds, buy_ranges, mode, morning_incomplete=still_required)

    raise ValueError(f"unknown mode: {mode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="毎営業日の日本株監視レポートを生成する")
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
