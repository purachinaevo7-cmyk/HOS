"""HOS Investment Agent entrypoint."""
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import date, datetime, timedelta
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


def _previous_business_day(current: date) -> date:
    day = current - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _latest_finished_business_day(current: date) -> date:
    return _previous_business_day(current)


def _resolve_evening_trade_date(now: datetime, override: date | None) -> tuple[date, str]:
    if override is not None:
        return override, "明示指定されたtrade_dateを使用"
    current = now.date()
    return current, "eveningモードは21:00 JST時点の当日営業日を対象にするため"


def _resolve_morning_trade_date(now: datetime, override: date | None, data_dir: Path) -> tuple[date, str]:
    if override is not None:
        return override, "明示指定されたtrade_dateを使用"
    fallback = _latest_finished_business_day(now.date())
    path = data_dir / f"{fallback.isoformat()}.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        trade_date_value = payload.get("trade_date")
        if trade_date_value:
            return date.fromisoformat(str(trade_date_value)), f"前夜JSON（{path.name}）が存在するため、そのtrade_dateを優先"
    return fallback, "前夜JSONがないため、直近の終了済み営業日を対象にするため"


def _log_run_context(now: datetime, mode: str, expected_date: date, reason: str) -> None:
    print(f"実行日時: {now.isoformat()}")
    print(f"実行モード: {mode} ({MODE_LABELS[mode]})")
    print(f"対象取引日 expected_date: {expected_date.isoformat()}")
    print(f"現在日: {now.date().isoformat()}")
    print(f"対象取引日の決定理由: {reason}")


def _retry_required(result: FetchResult) -> bool:
    return bool(result.missing) or result.topix_source_status != "一致"


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
    payload["mode"] = mode
    payload["mode_label"] = MODE_LABELS[mode]
    payload["retry_required"] = retry_required
    if run_context:
        payload["run_context"] = run_context
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


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
        result = fetch_market_data(watchlist, expected_date)
        retry_required = _retry_required(result)
        _write_mode_log(result, mode, retry_required, data_dir, context)
        return _build_report(result, thresholds, buy_ranges, mode)

    if mode == MORNING_RETRY:
        target_date, reason = _resolve_morning_trade_date(now, trade_date, data_dir)
        _log_run_context(now, mode, target_date, reason)
        context = {"run_at": now.isoformat(), "mode": mode, "expected_date": target_date.isoformat(), "current_date": now.date().isoformat(), "reason": reason}
        previous = _load_previous_log(target_date, data_dir)
        if not previous.get("retry_required", False):
            return None
        previous_prices = [_price_from_json(row) for row in previous.get("prices", [])]
        previous_missing = [_missing_from_json(row) for row in previous.get("missing", [])]
        missing_codes = {record.code for record in previous_missing}
        retry_watchlist = [item for item in watchlist if str(item["code"]) in missing_codes]
        retry_result = fetch_market_data(retry_watchlist, target_date)
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
