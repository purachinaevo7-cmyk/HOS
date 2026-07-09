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
    p = MockProvider(stocks={"5713": (90, 100, D)})
    r = fetch_market_data(WATCH, D, providers=[p], topix_providers=[])
    assert r.prices[0].code == "5713"
    assert p.calls == ["5713.T"]


def test_retry_failure_missing_record():
    p = MockProvider()
    r = fetch_market_data(WATCH, D, providers=[p], topix_providers=[])
    assert r.prices == []
    assert r.missing[0].code == "5713"


def test_old_date_is_missing_record():
    p = MockProvider(stocks={"5713": (90, 100, date(2026,7,8))})
    r = fetch_market_data(WATCH, D, providers=[p], topix_providers=[])
    assert r.missing[0].reason.count("日付不一致") == 1


def test_provider_switch():
    p1 = MockProvider()
    p2 = MockProvider(stocks={"5713": (90, 100, D)})
    r = fetch_market_data(WATCH, D, providers=[p1, p2], topix_providers=[])
    assert r.prices[0].source == "mock"
    assert len(p1.calls) == 1


def test_topix_match_and_mismatch():
    ok1 = MockProvider(topix=(99,100,D)); ok2 = MockProvider(topix=(98.9,100,D))
    r = fetch_market_data([], D, providers=[], topix_providers=[ok1, ok2])
    assert r.topix_source_status == "一致"
    bad = MockProvider(topix=(98,100,D))
    r = fetch_market_data([], D, providers=[], topix_providers=[ok1, bad])
    assert r.topix_source_status == "要確認（指数値不一致）"
    assert r.topix_change_percent is None


def test_topix_mismatch_only_when_diff_is_at_least_threshold():
    ok1 = MockProvider(topix=(99.00,100,D))
    ok2 = MockProvider(topix=(98.71,100,D))
    r = fetch_market_data([], D, providers=[], topix_providers=[ok1, ok2])
    assert r.topix_source_status == "一致"

    bad = MockProvider(topix=(98.70,100,D))
    r = fetch_market_data([], D, providers=[], topix_providers=[ok1, bad])
    assert r.topix_source_status == "要確認（指数値不一致）"


def test_symbol_patterns():
    assert symbol_patterns("5713") == ["5713.T"]

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
    assert r.topix_change_percent == -1.05
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
        "JPX",
        "Yahoo Finance",
        "TradingView",
        "TOPIX ETF median",
    ]

    monkeypatch.setenv("JPX_TOPIX_CSV_URL", "https://example.test/topix.csv")
    assert [p.name for p in default_topix_providers()] == [
        "JPX",
        "Yahoo Finance",
        "TradingView",
        "TOPIX ETF median",
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


def test_jpx_empty_url_is_skipped(monkeypatch):
    from stock_fetcher import JPXProvider

    monkeypatch.setenv("JPX_TOPIX_CSV_URL", "")

    r = fetch_market_data([], D, providers=[], topix_providers=[JPXProvider()])

    assert r.topix_missing == ["JPX: スキップ（JPX_TOPIX_CSV_URL未設定）"]


def test_topix_logs_success_and_failure_until_two_sources():
    yahoo = NamedTopixProvider("Yahoo Finance", None)
    stooq = NamedTopixProvider("Stooq", (99, 100, D))
    jpx = NamedTopixProvider("JPX", (98.9, 100, D))
    tv = NamedTopixProvider("TradingView", (98.8, 100, D))

    r = fetch_market_data([], D, providers=[], topix_providers=[yahoo, stooq, jpx, tv])

    assert r.topix_source == "Stooq/JPX"
    assert r.topix_missing == [
        "Yahoo Finance: 失敗（取得日 2026-07-09, 終値 -, 前日終値 -, 前日比 -, 取得方法 -, 失敗理由 データなし）",
        "Stooq: 成功（取得日 2026-07-09, 終値 99.00, 前日終値 100.00, 前日比 -1.00%, 取得方法 直接取得, 失敗理由 -）",
        "JPX: 成功（取得日 2026-07-09, 終値 98.90, 前日終値 100.00, 前日比 -1.10%, 取得方法 直接取得, 失敗理由 -）",
    ]
    assert tv.called is False


def test_tradingview_uses_previous_close_column(monkeypatch):
    from stock_fetcher import TradingViewProvider

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"d": [101.0, 100.0, "delayed_streaming_900"]}]}

    def post(url, json, timeout):
        assert "prev_close" in json["columns"]
        assert "change_abs" not in json["columns"]
        return Response()

    monkeypatch.setattr("requests.post", post)

    record = TradingViewProvider().fetch_topix(D)

    assert record.close == 101.0
    assert record.previous_close == 100.0
    assert record.change_percent == 1.0


def test_topix_etf_median_provider_uses_at_least_two_etfs(monkeypatch):
    import pandas as pd
    from stock_fetcher import TopixEtfMedianProvider

    histories = {
        "1306.T": pd.DataFrame({"Date": [date(2026, 7, 8), D], "Close": [100.0, 99.0]}),
        "1308.T": pd.DataFrame({"Date": [date(2026, 7, 8), D], "Close": [100.0, 98.5]}),
        "1475.T": pd.DataFrame({"Date": [date(2026, 7, 8), D], "Close": [100.0, 99.2]}),
    }

    provider = TopixEtfMedianProvider()
    monkeypatch.setattr(provider, "_history", lambda ticker: histories[ticker])

    record = provider.fetch_topix(D)

    assert record.provider == "TOPIX ETF median"
    assert record.previous_close == 100.0
    assert record.change_percent == -1.0
    assert "1306・1308・1475" in record.reason
    assert [component.provider for component in record.components] == ["TOPIX ETF 1306", "TOPIX ETF 1308", "TOPIX ETF 1475"]


def test_jpx_provider_fetches_csv_over_http(monkeypatch):
    from stock_fetcher import JPXProvider

    class Response:
        text = "date,close,previous_close\n2026-07-09,2800.5,2790.0\n"

        def raise_for_status(self):
            return None

    def get(url, headers, timeout):
        assert url.startswith("https://")
        assert "User-Agent" in headers
        assert headers["Accept"].startswith("text/csv")
        return Response()

    monkeypatch.setenv("JPX_TOPIX_CSV_URL", "https://example.test/topix.csv")
    monkeypatch.setattr("requests.get", get)

    record = JPXProvider().fetch_topix(D)

    assert record.close == 2800.5
    assert record.previous_close == 2790.0
    assert record.reason == "JPX公式CSVをHTTP取得"


def test_etf_only_success_is_reference_value():
    etf = NamedTopixProvider("TOPIX ETF median", (99, 100, D))

    r = fetch_market_data([], D, providers=[], topix_providers=[etf])

    assert r.topix_source_status == "代替（TOPIX ETF中央値）"
    assert r.topix_change_percent == -1.0


def test_topix_etf_median_provider_uses_two_or_more_etfs(monkeypatch):
    import pandas as pd
    from stock_fetcher import TopixEtfMedianProvider

    histories = {
        "1306.T": pd.DataFrame({"Date": [date(2026, 7, 8), D], "Close": [100.0, 99.0]}),
        "1308.T": pd.DataFrame({"Date": [date(2026, 7, 8), D], "Close": [100.0, 98.5]}),
        "1475.T": pd.DataFrame({"Date": [date(2026, 7, 8)], "Close": [100.0]}),
    }

    provider = TopixEtfMedianProvider()
    monkeypatch.setattr(provider, "_history", lambda ticker: histories[ticker])

    record = provider.fetch_topix(D)

    assert record is not None
    assert record.change_percent == -1.25
    assert [component.provider for component in record.components] == ["TOPIX ETF 1306", "TOPIX ETF 1308"]


def test_topix_etf_median_provider_rejects_one_etf(monkeypatch):
    import pandas as pd
    from stock_fetcher import TopixEtfMedianProvider

    histories = {
        "1306.T": pd.DataFrame({"Date": [date(2026, 7, 8), D], "Close": [100.0, 99.0]}),
        "1308.T": pd.DataFrame({"Date": [date(2026, 7, 8)], "Close": [100.0]}),
        "1475.T": pd.DataFrame({"Date": [date(2026, 7, 8)], "Close": [100.0]}),
    }

    provider = TopixEtfMedianProvider()
    monkeypatch.setattr(provider, "_history", lambda ticker: histories[ticker])

    assert provider.fetch_topix(D) is None
