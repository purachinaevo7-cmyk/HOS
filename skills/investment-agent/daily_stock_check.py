"""HOS Investment Agent entrypoint."""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import Any

from stock_analyzer import analyze_stocks
from notifier import ConsoleNotifier, GitHubSummaryNotifier
from stock_fetcher import fetch_market_data, save_daily_prices
from stock_reporter import generate_report

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]


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


def run() -> str:
    load_env()
    watchlist_data = load_yaml(BASE_DIR / "config" / "watchlist.yaml")
    thresholds = load_yaml(BASE_DIR / "config" / "thresholds.yaml")
    buy_ranges_data = load_yaml(BASE_DIR / "config" / "buy_ranges.yaml")
    watchlist = watchlist_data["watchlist"]
    buy_ranges = buy_ranges_data["buy_ranges_percent"]
    result = fetch_market_data(watchlist)
    analysis = analyze_stocks(result.prices, result.topix_change_percent, thresholds, buy_ranges)
    report = generate_report(
        result.trade_date,
        result.topix_change_percent,
        result.topix_source_status,
        analysis,
        result.prices,
        result.missing,
    )
    save_daily_prices(result, BASE_DIR / "data" / "daily_prices")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="毎営業日の日本株監視レポートを生成する")
    args = parser.parse_args()
    report = run()
    ConsoleNotifier().notify(report)
    GitHubSummaryNotifier().notify(report)


if __name__ == "__main__":
    main()
