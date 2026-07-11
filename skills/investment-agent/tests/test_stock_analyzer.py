from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_analyzer import PriceRecord, analyze_stocks, calculate_buy_range, classify_topix, percent_change


def thresholds():
    return {
        "topix": {
            "market_drop_percent": -1.0,
            "individual_lower_percent": -0.5,
            "individual_upper_percent": 0.5,
        },
        "stock_drop_thresholds_percent": {"large": -2.0, "medium": -3.0, "high": -4.0},
    }


def buy_ranges():
    return {
        "large": {"lower": -1.2, "upper": -0.5},
        "medium": {"lower": -2.0, "upper": -1.0},
        "high": {"lower": -3.0, "upper": -1.5},
    }


def test_percent_change():
    assert percent_change(95, 100) == -5


def test_topix_classification():
    assert classify_topix(-1.0, thresholds()) == "A"
    assert classify_topix(0.2, thresholds()) == "B"
    assert classify_topix(-0.8, thresholds()) is None
    assert classify_topix(None, thresholds()) is None


def test_buy_range_by_volatility():
    assert calculate_buy_range(1000, "large", buy_ranges()) == (988.0, 995.0)
    assert calculate_buy_range(1000, "medium", buy_ranges()) == (980.0, 990.0)
    assert calculate_buy_range(1000, "high", buy_ranges()) == (970.0, 985.0)


def test_analyze_only_triggered_stocks_are_classified():
    prices = [
        PriceRecord("8001", "伊藤忠商事", 970, 1000, date(2026, 7, 9), "mock", "large"),
        PriceRecord("5713", "住友金属鉱山", 970, 1000, date(2026, 7, 9), "mock", "high"),
    ]
    result = analyze_stocks(prices, -1.2, thresholds(), buy_ranges())
    assert [stock.code for stock in result["market_drop"]] == ["8001"]
    assert [stock.code for stock in result["pending"]] == ["5713"]


def test_topix_inconsistent_holds_ab_classification():
    prices = [PriceRecord("8001", "伊藤忠商事", 970, 1000, date(2026, 7, 9), "mock", "large")]
    result = analyze_stocks(prices, None, thresholds(), buy_ranges())
    assert result["market_drop"] == []
    assert result["individual_drop"] == []
    assert result["pending"][0].reason == "TOPIX判定保留"


def test_etf_reference_median_a_judgement_runs_classification():
    prices = [PriceRecord("8001", "伊藤忠商事", 970, 1000, date(2026, 7, 9), "mock", "large")]
    result = analyze_stocks(prices, -1.0, thresholds(), buy_ranges())

    assert result["topix_category"] == "A"
    assert [stock.code for stock in result["market_drop"]] == ["8001"]
    assert result["individual_drop"] == []
    assert result["pending"] == []


def test_etf_reference_median_b_judgement_runs_classification():
    prices = [PriceRecord("8001", "伊藤忠商事", 970, 1000, date(2026, 7, 9), "mock", "large")]
    result = analyze_stocks(prices, 0.0, thresholds(), buy_ranges())

    assert result["topix_category"] == "B"
    assert result["market_drop"] == []
    assert [stock.code for stock in result["individual_drop"]] == ["8001"]
    assert result["pending"] == []


def test_etf_reference_median_positive_outside_rules_has_no_ab_match():
    prices = [PriceRecord("8001", "伊藤忠商事", 970, 1000, date(2026, 7, 9), "mock", "large")]
    result = analyze_stocks(prices, 0.72, thresholds(), buy_ranges())

    assert result["topix_category"] is None
    assert result["market_drop"] == []
    assert result["individual_drop"] == []
    assert result["pending"][0].reason == "TOPIX判定対象外"
