from __future__ import annotations

from datetime import date

from stock_analyzer import PriceRecord
from stock_fetcher import TopixRecord


class MockProvider:
    name = "mock"

    def __init__(self, stocks=None, topix=None, failures_before_success=0):
        self.stocks = stocks or {}
        self.topix = topix
        self.calls = []
        self.failures_before_success = failures_before_success

    def fetch_stock(self, symbol: str, name: str, volatility: str, expected_date: date):
        self.calls.append(symbol)
        if self.failures_before_success > 0:
            self.failures_before_success -= 1
            return None
        key = symbol.split('.')[0].split()[0]
        value = self.stocks.get(key)
        if value is None:
            return None
        close, prev, price_date = value
        return PriceRecord(key, name, close, prev, price_date, self.name, volatility)

    def fetch_topix(self, expected_date: date):
        if self.topix is None:
            return None
        close, prev, price_date = self.topix
        return TopixRecord(self.name, close, prev, price_date)
