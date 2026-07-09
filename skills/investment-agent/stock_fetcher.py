"""データ取得層 for HOS Investment Agent.

外部API未設定でも動く MockPriceProvider を標準にし、将来 Yahoo Finance / pandas-datareader /
yfinance などへ差し替えられるよう PriceProvider インターフェースに分離している。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol
import importlib
import importlib.util

from stock_analyzer import MissingRecord, PriceRecord


@dataclass(frozen=True)
class FetchResult:
    prices: list[PriceRecord]
    missing: list[MissingRecord]
    topix_change_percent: float | None
    topix_source_status: str
    topix_source: str
    trade_date: date


class PriceProvider(Protocol):
    name: str

    def fetch_stock(self, code: str, name: str, volatility: str, expected_date: date) -> PriceRecord | None: ...

    def fetch_topix(self, expected_date: date) -> tuple[float, date] | None: ...


def recent_business_day(today: date | None = None) -> date:
    current = today or date.today()
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


class MockPriceProvider:
    name = "mock"

    MOCK_PRICES = {
        "5713": (4280.0, 4485.0),
        "5711": (3030.0, 3120.0),
        "2768": (3880.0, 4020.0),
        "7456": (2940.0, 3000.0),
        "4063": (6120.0, 6250.0),
        "6981": (2835.0, 2890.0),
        "8001": (7760.0, 7925.0),
        "8002": (2890.0, 2970.0),
        "7832": (3210.0, 3325.0),
        "9697": (2980.0, 3060.0),
        "9684": (5480.0, 5650.0),
        # 5698 は未取得の例として残す
    }

    def fetch_stock(self, code: str, name: str, volatility: str, expected_date: date) -> PriceRecord | None:
        values = self.MOCK_PRICES.get(code)
        if values is None:
            return None
        close, previous_close = values
        return PriceRecord(code, name, close, previous_close, expected_date, self.name, volatility)

    def fetch_topix(self, expected_date: date) -> tuple[float, date] | None:
        return -1.15, expected_date


class YFinancePriceProvider:
    """任意依存の yfinance を使う将来用プロバイダ。未導入なら None を返す。"""

    name = "yfinance"

    def fetch_stock(self, code: str, name: str, volatility: str, expected_date: date) -> PriceRecord | None:
        if importlib.util.find_spec("yfinance") is None:
            return None
        yf = importlib.import_module("yfinance")
        ticker = f"{code}.T"
        history = yf.Ticker(ticker).history(period="7d", auto_adjust=False)
        if history is None or len(history) < 2:
            return None
        rows = history.reset_index()
        rows["DateOnly"] = rows["Date"].dt.date
        current = rows[rows["DateOnly"] == expected_date]
        if current.empty:
            return None
        current_index = current.index[-1]
        if current_index == 0:
            return None
        close = float(rows.loc[current_index, "Close"])
        previous_close = float(rows.loc[current_index - 1, "Close"])
        return PriceRecord(code, name, close, previous_close, expected_date, self.name, volatility)

    def fetch_topix(self, expected_date: date) -> tuple[float, date] | None:
        if importlib.util.find_spec("yfinance") is None:
            return None
        yf = importlib.import_module("yfinance")
        history = yf.Ticker("^TOPX").history(period="7d", auto_adjust=False)
        if history is None or len(history) < 2:
            return None
        rows = history.reset_index()
        rows["DateOnly"] = rows["Date"].dt.date
        current = rows[rows["DateOnly"] == expected_date]
        if current.empty:
            return None
        current_index = current.index[-1]
        if current_index == 0:
            return None
        close = float(rows.loc[current_index, "Close"])
        previous_close = float(rows.loc[current_index - 1, "Close"])
        return ((close - previous_close) / previous_close) * 100, expected_date


def fetch_market_data(watchlist: list[dict], expected_date: date | None = None, providers: list[PriceProvider] | None = None) -> FetchResult:
    trade_date = expected_date or recent_business_day()
    active_providers = providers or [YFinancePriceProvider(), MockPriceProvider()]
    prices: list[PriceRecord] = []
    missing: list[MissingRecord] = []

    for item in watchlist:
        code = str(item["code"])
        name = str(item.get("name", code))
        volatility = str(item["volatility"])
        record = None
        failures: list[str] = []
        for provider in active_providers:
            try:
                candidate = provider.fetch_stock(code, name, volatility, trade_date)
            except Exception as exc:  # provider failure should not stop other symbols
                failures.append(f"{provider.name}: {exc}")
                continue
            if candidate is None:
                failures.append(f"{provider.name}: データなし")
                continue
            if candidate.price_date != trade_date:
                failures.append(f"{provider.name}: 日付不一致({candidate.price_date})")
                continue
            record = candidate
            break
        if record is None:
            missing.append(MissingRecord(code, name, "; ".join(failures) or "要確認（データ未取得）"))
        else:
            prices.append(record)

    topix_change = None
    topix_status = "要確認"
    topix_source = "未取得"
    for provider in active_providers:
        try:
            topix = provider.fetch_topix(trade_date)
        except Exception:
            topix = None
        if topix is None:
            continue
        value, topix_date = topix
        if topix_date == trade_date:
            topix_change = round(value, 2)
            topix_status = "一致"
            topix_source = provider.name
            break

    return FetchResult(prices, missing, topix_change, topix_status, topix_source, trade_date)
