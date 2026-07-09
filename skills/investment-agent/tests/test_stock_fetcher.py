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
    assert r.topix_source_status == "要確認"
    assert r.topix_change_percent is None


def test_symbol_patterns():
    assert symbol_patterns("5713") == ["5713.T", "5713 JP", "5713"]
