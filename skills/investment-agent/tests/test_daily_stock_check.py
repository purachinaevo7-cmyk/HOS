from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import daily_stock_check as dsc
from stock_analyzer import PriceRecord
from stock_fetcher import FetchResult, TopixRecord

D = date(2026, 7, 9)
WATCH = [
    {"code": "1111", "name": "A", "volatility": "medium"},
    {"code": "2222", "name": "B", "volatility": "medium"},
]
THRESHOLDS = {"topix": {"market_drop_percent": -2, "individual_lower_percent": -1, "individual_upper_percent": 1}, "stock_drop_thresholds_percent": {"medium": -3}}
BUY_RANGES = {"buy_ranges_percent": {"medium": {"lower": -2, "upper": 0}}}


def price(code, close=100, prev=101):
    return PriceRecord(code, code, close, prev, D, "mock", "medium")


def result(prices, missing, topix_change=-1.0, status="一致"):
    return FetchResult(prices, missing, topix_change, status, "mock/mock2", D, [TopixRecord("mock", 99, 100, D)], [])


def setup_config(monkeypatch):
    monkeypatch.setattr(dsc, "load_env", lambda: None)
    monkeypatch.setattr(dsc, "load_yaml", lambda path: {"watchlist": WATCH} if path.name == "watchlist.yaml" else (BUY_RANGES if path.name == "buy_ranges.yaml" else THRESHOLDS))


def test_evening_all_success_saves_retry_false(monkeypatch, tmp_path):
    setup_config(monkeypatch)
    monkeypatch.setattr(dsc, "fetch_market_data", lambda watchlist, trade_date: result([price("1111"), price("2222")], []))

    report = dsc.run(dsc.EVENING, D, tmp_path)

    assert "取得モード：夜間通常取得" in report
    assert '"retry_required": false' in (tmp_path / "2026-07-09.json").read_text(encoding="utf-8")


def test_evening_missing_sets_retry_required_true(monkeypatch, tmp_path):
    setup_config(monkeypatch)
    from stock_analyzer import MissingRecord
    monkeypatch.setattr(dsc, "fetch_market_data", lambda watchlist, trade_date: result([price("1111")], [MissingRecord("2222", "B", "データなし")]))

    report = dsc.run(dsc.EVENING, D, tmp_path)

    assert "2222 B: 要確認（データ未取得）" in report
    assert '"retry_required": true' in (tmp_path / "2026-07-09.json").read_text(encoding="utf-8")


def test_morning_retry_reads_previous_evening_data(monkeypatch, tmp_path):
    setup_config(monkeypatch)
    monkeypatch.setattr(dsc, "fetch_market_data", lambda watchlist, trade_date: result([price(item["code"]) for item in watchlist], []))
    dsc.run(dsc.EVENING, D, tmp_path)
    calls = []
    monkeypatch.setattr(dsc, "fetch_market_data", lambda watchlist, trade_date: calls.append(watchlist) or result([], [], status="一致"))

    report = dsc.run(dsc.MORNING_RETRY, D, tmp_path)

    assert report is None
    assert calls == []


def test_morning_retry_refetches_only_missing_stocks(monkeypatch, tmp_path):
    setup_config(monkeypatch)
    from stock_analyzer import MissingRecord
    monkeypatch.setattr(dsc, "fetch_market_data", lambda watchlist, trade_date: result([price("1111")], [MissingRecord("2222", "B", "データなし")], status="要確認"))
    dsc.run(dsc.EVENING, D, tmp_path)
    calls = []
    def retry_fetch(watchlist, trade_date):
        calls.append([item["code"] for item in watchlist])
        return result([price("2222", 98, 100)], [], status="一致")
    monkeypatch.setattr(dsc, "fetch_market_data", retry_fetch)

    report = dsc.run(dsc.MORNING_RETRY, D, tmp_path)

    assert calls == [["2222"]]
    assert "1111 1111" in report
    assert "2222 2222" in report
    assert "朝補完取得で判定更新" in report


def test_morning_retry_overwrites_topix_only(monkeypatch, tmp_path):
    setup_config(monkeypatch)
    monkeypatch.setattr(dsc, "fetch_market_data", lambda watchlist, trade_date: result([price("1111"), price("2222")], [], topix_change=None, status="要確認（TOPIX 1ソースのみ）"))
    dsc.run(dsc.EVENING, D, tmp_path)
    calls = []
    monkeypatch.setattr(dsc, "fetch_market_data", lambda watchlist, trade_date: calls.append(watchlist) or result([], [], topix_change=-2.5, status="一致"))

    report = dsc.run(dsc.MORNING_RETRY, D, tmp_path)

    assert calls == [[]]
    assert "TOPIX前日比：-2.50%" in report
    assert "朝補完取得で判定更新" in report


def test_morning_retry_keeps_confirmation_when_still_missing(monkeypatch, tmp_path):
    setup_config(monkeypatch)
    from stock_analyzer import MissingRecord
    monkeypatch.setattr(dsc, "fetch_market_data", lambda watchlist, trade_date: result([price("1111")], [MissingRecord("2222", "B", "データなし")]))
    dsc.run(dsc.EVENING, D, tmp_path)
    monkeypatch.setattr(dsc, "fetch_market_data", lambda watchlist, trade_date: result([], [MissingRecord("2222", "B", "データなし")], status="要確認"))

    report = dsc.run(dsc.MORNING_RETRY, D, tmp_path)

    assert "要確認（データ未取得）。朝補完後も不足あり。" in report
    assert '"retry_required": true' in (tmp_path / "2026-07-09.json").read_text(encoding="utf-8")
