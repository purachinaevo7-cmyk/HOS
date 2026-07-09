"""判定ロジック for HOS Investment Agent."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping


@dataclass(frozen=True)
class PriceRecord:
    code: str
    name: str
    close: float
    previous_close: float
    price_date: date
    source: str
    volatility: str


@dataclass(frozen=True)
class MissingRecord:
    code: str
    name: str
    reason: str


@dataclass(frozen=True)
class AnalyzedStock:
    code: str
    name: str
    close: float
    previous_close: float
    change_percent: float
    buy_range_low: float
    buy_range_high: float
    category: str | None
    reason: str


def percent_change(close: float, previous_close: float) -> float:
    if previous_close == 0:
        raise ValueError("previous_close must not be zero")
    return ((close - previous_close) / previous_close) * 100


def calculate_buy_range(close: float, volatility: str, buy_ranges: Mapping[str, Any]) -> tuple[float, float]:
    settings = buy_ranges[volatility]
    low = close * (1 + float(settings["lower"]) / 100)
    high = close * (1 + float(settings["upper"]) / 100)
    return round(low, 2), round(high, 2)


def classify_topix(topix_change_percent: float | None, thresholds: Mapping[str, Any]) -> str | None:
    if topix_change_percent is None:
        return None
    topix = thresholds["topix"]
    if topix_change_percent <= float(topix["market_drop_percent"]):
        return "A"
    if float(topix["individual_lower_percent"]) <= topix_change_percent <= float(topix["individual_upper_percent"]):
        return "B"
    return None


def analyze_stocks(
    prices: list[PriceRecord],
    topix_change_percent: float | None,
    thresholds: Mapping[str, Any],
    buy_ranges: Mapping[str, Any],
) -> dict[str, Any]:
    """取得済み銘柄だけを判定し、A/B/保留に分類する。"""
    topix_category = classify_topix(topix_change_percent, thresholds)
    stock_thresholds = thresholds["stock_drop_thresholds_percent"]
    analyzed: list[AnalyzedStock] = []

    for price in prices:
        change = round(percent_change(price.close, price.previous_close), 2)
        trigger = change <= float(stock_thresholds[price.volatility])
        buy_low, buy_high = calculate_buy_range(price.close, price.volatility, buy_ranges)
        category = topix_category if trigger and topix_category in {"A", "B"} else None
        reason = "しきい値到達" if trigger else "しきい値未達"
        if trigger and topix_category is None:
            reason = "TOPIX判定保留"
        analyzed.append(
            AnalyzedStock(
                code=price.code,
                name=price.name,
                close=price.close,
                previous_close=price.previous_close,
                change_percent=change,
                buy_range_low=buy_low,
                buy_range_high=buy_high,
                category=category,
                reason=reason,
            )
        )

    return {
        "topix_category": topix_category,
        "market_drop": [s for s in analyzed if s.category == "A"],
        "individual_drop": [s for s in analyzed if s.category == "B"],
        "pending": [s for s in analyzed if s.category is None],
        "all": analyzed,
    }
