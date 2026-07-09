from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_fetcher import fetch_market_data, symbol_patterns
from mock_provider import MockProvider

WATCH = [{"code":"5713","name":"住友金属鉱山","volatility":"high"}]
D = date(2026,7,9)


def test_retry_success():
    p = MockProvider(stocks={"5713": (90, 100, D)}, failures_before_success=2)
    r = fetch_market_data(WATCH, D, providers=[p], topix_providers=[])
    assert r.prices[0].code == "5713"
    assert p.calls == ["5713.T", "5713 JP", "5713"]


def test_retry_failure_missing_record():
    p = MockProvider()
    r = fetch_market_data(WATCH, D, providers=[p], topix_providers=[])
    assert r.prices == []
    assert r.missing[0].code == "5713"


def test_old_date_is_missing_record():
    p = MockProvider(stocks={"5713": (90, 100, date(2026,7,8))})
    r = fetch_market_data(WATCH, D, providers=[p], topix_providers=[])
    assert r.missing[0].reason.count("日付不一致") == 3


def test_provider_switch():
    p1 = MockProvider()
    p2 = MockProvider(stocks={"5713": (90, 100, D)})
    r = fetch_market_data(WATCH, D, providers=[p1, p2], topix_providers=[])
    assert r.prices[0].source == "mock"
    assert len(p1.calls) == 3


def test_topix_match_and_mismatch():
    ok1 = MockProvider(topix=(99,100,D)); ok2 = MockProvider(topix=(98.9,100,D))
    r = fetch_market_data([], D, providers=[], topix_providers=[ok1, ok2])
    assert r.topix_source_status == "一致"
    bad = MockProvider(topix=(98,100,D))
    r = fetch_market_data([], D, providers=[], topix_providers=[ok1, bad])
    assert r.topix_source_status == "要確認（指数値不一致）"
    assert r.topix_change_percent is None


def test_symbol_patterns():
    assert symbol_patterns("5713") == ["5713.T", "5713 JP", "5713"]

class NamedTopixProvider:
    def __init__(self, name, topix=None):
        self.name = name
        self.topix = topix
        self.called = False

    def fetch_stock(self, symbol: str, name: str, volatility: str, expected_date: date):
        return None

    def fetch_topix(self, expected_date: date):
        self.called = True
        if self.topix is None:
            return None
        from stock_fetcher import TopixRecord
        close, prev, price_date = self.topix
        return TopixRecord(self.name, close, prev, price_date)


def test_topix_falls_back_until_two_sources_are_collected():
    yahoo = NamedTopixProvider("Yahoo Finance", None)
    jpx = NamedTopixProvider("JPX", (99, 100, D))
    tradingview = NamedTopixProvider("TradingView", (98.9, 100, D))
    investing = NamedTopixProvider("Investing.com", (98.8, 100, D))

    r = fetch_market_data([], D, providers=[], topix_providers=[yahoo, jpx, tradingview, investing])

    assert r.topix_source_status == "一致"
    assert r.topix_change_percent == -1.0
    assert r.topix_source == "JPX/TradingView"
    assert [t.provider for t in r.topix_records] == ["JPX", "TradingView"]
    assert investing.called is False


def test_topix_requires_two_valid_sources_to_calculate_change():
    yahoo = NamedTopixProvider("Yahoo Finance", (99, 100, D))
    jpx = NamedTopixProvider("JPX", None)

    r = fetch_market_data([], D, providers=[], topix_providers=[yahoo, jpx])

    assert r.topix_source_status == "要確認（TOPIX 1ソースのみ）"
    assert r.topix_change_percent is None
    assert r.topix_source == "Yahoo Finance"


def test_default_topix_provider_order_skips_unconfigured_jpx(monkeypatch):
    from stock_fetcher import default_topix_providers

    monkeypatch.delenv("JPX_TOPIX_CSV_URL", raising=False)
    assert [p.name for p in default_topix_providers()] == [
        "Yahoo Finance",
        "Stooq",
        "JPX",
        "TradingView",
        "Investing.com",
        "TOPIX ETF 1306",
        "TOPIX ETF 1308",
        "TOPIX ETF 1475",
    ]

    monkeypatch.setenv("JPX_TOPIX_CSV_URL", "https://example.test/topix.csv")
    assert [p.name for p in default_topix_providers()] == [
        "Yahoo Finance",
        "Stooq",
        "JPX",
        "TradingView",
        "Investing.com",
        "TOPIX ETF 1306",
        "TOPIX ETF 1308",
        "TOPIX ETF 1475",
    ]


def test_topix_one_source_status_when_all_stocks_fetched():
    stock = NamedTopixProvider("stock")
    stock.fetch_stock = lambda symbol, name, volatility, expected_date: __import__("stock_analyzer").PriceRecord("5713", name, 90, 100, expected_date, "stock", volatility)
    yahoo = NamedTopixProvider("Yahoo Finance", (99, 100, D))
    tv = NamedTopixProvider("TradingView", None)

    r = fetch_market_data(WATCH, D, providers=[stock], topix_providers=[yahoo, tv])

    assert r.missing == []
    assert r.topix_source_status == "要確認（TOPIX 1ソースのみ）"
    assert r.topix_source == "Yahoo Finance"
    assert r.topix_change_percent is None


def test_topix_mismatch_status_has_reason():
    yahoo = NamedTopixProvider("Yahoo Finance", (99, 100, D))
    tv = NamedTopixProvider("TradingView", (98, 100, D))

    r = fetch_market_data([], D, providers=[], topix_providers=[yahoo, tv])

    assert r.topix_source_status == "要確認（指数値不一致）"
    assert r.topix_change_percent is None


def test_topix_attempts_are_always_logged(monkeypatch):
    monkeypatch.delenv("JPX_TOPIX_CSV_URL", raising=False)
    jpx = NamedTopixProvider("JPX", None)

    r = fetch_market_data([], D, providers=[], topix_providers=[jpx])

    assert r.topix_missing == ["JPX: 失敗（データなし）"]


def test_topix_logs_success_and_failure_until_two_sources():
    yahoo = NamedTopixProvider("Yahoo Finance", None)
    stooq = NamedTopixProvider("Stooq", (99, 100, D))
    jpx = NamedTopixProvider("JPX", (98.9, 100, D))
    tv = NamedTopixProvider("TradingView", (98.8, 100, D))

    r = fetch_market_data([], D, providers=[], topix_providers=[yahoo, stooq, jpx, tv])

    assert r.topix_source == "Stooq/JPX"
    assert r.topix_missing == [
        "Yahoo Finance: 失敗（データなし）",
        "Stooq: 成功（前日比 -1.00%）",
        "JPX: 成功（前日比 -1.10%）",
    ]
    assert tv.called is False
