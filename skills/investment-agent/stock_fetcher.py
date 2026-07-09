"""Data retrieval layer for HOS Investment Agent."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
from typing import Protocol

from stock_analyzer import MissingRecord, PriceRecord, percent_change


@dataclass(frozen=True)
class TopixRecord:
    provider: str
    close: float
    previous_close: float
    price_date: date
    reason: str = ""

    @property
    def change_percent(self) -> float:
        return round(percent_change(self.close, self.previous_close), 2)


@dataclass(frozen=True)
class FetchResult:
    prices: list[PriceRecord]
    missing: list[MissingRecord]
    topix_change_percent: float | None
    topix_source_status: str
    topix_source: str
    trade_date: date
    topix_records: list[TopixRecord]
    topix_missing: list[str]


class PriceProvider(Protocol):
    name: str

    def fetch_stock(self, symbol: str, name: str, volatility: str, expected_date: date) -> PriceRecord | None: ...

    def fetch_topix(self, expected_date: date) -> TopixRecord | None: ...


class YahooFinanceProvider:
    name = "Yahoo Finance"

    def _history(self, ticker: str):
        import yfinance as yf
        return yf.Ticker(ticker).history(period="10d", auto_adjust=False)

    def fetch_stock(self, symbol: str, name: str, volatility: str, expected_date: date) -> PriceRecord | None:
        history = self._history(symbol)
        row, prev = _valid_current_and_previous_rows(history, expected_date)
        if row is None or prev is None:
            return None
        return PriceRecord(_normalize_code(symbol), name, float(row["Close"]), float(prev["Close"]), _row_date(row), self.name, volatility)

    def fetch_topix(self, expected_date: date) -> TopixRecord | None:
        history = self._history("^TOPX")
        row, prev = _valid_current_and_previous_rows(history, expected_date)
        if row is None or prev is None:
            return None
        return TopixRecord(self.name, float(row["Close"]), float(prev["Close"]), _row_date(row))


class JPXProvider:
    """TOPIX provider using JPX CSV endpoint when configured.

    Set JPX_TOPIX_CSV_URL to a CSV with date, close, previous_close columns. This
    keeps the provider swappable until an official production feed is contracted.
    """

    name = "JPX"

    def fetch_stock(self, symbol: str, name: str, volatility: str, expected_date: date) -> PriceRecord | None:
        return None

    def fetch_topix(self, expected_date: date) -> TopixRecord | None:
        url = os.getenv("JPX_TOPIX_CSV_URL")
        if not url:
            return None
        import pandas as pd
        df = pd.read_csv(url)
        date_col = next((c for c in df.columns if c.lower() in {"date", "trade_date"}), None)
        close_col = next((c for c in df.columns if c.lower() in {"close", "topix"}), None)
        prev_col = next((c for c in df.columns if c.lower() in {"previous_close", "prev_close"}), None)
        if not (date_col and close_col and prev_col):
            return None
        df[date_col] = pd.to_datetime(df[date_col]).dt.date
        rows = df[df[date_col] == expected_date]
        if rows.empty:
            return None
        row = rows.iloc[-1]
        return TopixRecord(self.name, float(row[close_col]), float(row[prev_col]), expected_date)


class AlphaVantageProvider:
    name = "Alpha Vantage"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("ALPHAVANTAGE_API_KEY", "")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def fetch_stock(self, symbol: str, name: str, volatility: str, expected_date: date) -> PriceRecord | None:
        if not self.enabled:
            return None
        import requests
        r = requests.get("https://www.alphavantage.co/query", params={"function": "TIME_SERIES_DAILY", "symbol": symbol, "apikey": self.api_key}, timeout=20)
        r.raise_for_status()
        series = r.json().get("Time Series (Daily)", {})
        current = series.get(expected_date.isoformat())
        previous_date = max((date.fromisoformat(d) for d in series if date.fromisoformat(d) < expected_date), default=None)
        if not current or previous_date is None:
            return None
        return PriceRecord(_normalize_code(symbol), name, float(current["4. close"]), float(series[previous_date.isoformat()]["4. close"]), expected_date, self.name, volatility)

    def fetch_topix(self, expected_date: date) -> TopixRecord | None:
        return None


def recent_business_day(today: date | None = None) -> date:
    current = today or date.today()
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def symbol_patterns(code: str) -> list[str]:
    base = code.split(".")[0].split()[0]
    return [f"{base}.T", f"{base} JP", base]


def _normalize_code(symbol: str) -> str:
    return symbol.split(".")[0].split()[0]


def _row_date(row) -> date:
    value = row.get("DateOnly") if hasattr(row, "get") else None
    if value:
        return value
    value = row.name
    return value.date() if hasattr(value, "date") else value


def _valid_current_and_previous_rows(history, expected_date: date):
    if history is None or len(history) < 2:
        return None, None
    rows = history.reset_index()
    date_col = "Date" if "Date" in rows else rows.columns[0]
    rows["DateOnly"] = rows[date_col].dt.date
    current = rows[rows["DateOnly"] == expected_date]
    if current.empty:
        return None, None
    idx = current.index[-1]
    if idx == 0:
        return None, None
    return rows.loc[idx], rows.loc[idx - 1]


def default_providers() -> list[PriceProvider]:
    providers: list[PriceProvider] = [YahooFinanceProvider()]
    if os.getenv("ALPHAVANTAGE_API_KEY"):
        providers.append(AlphaVantageProvider())
    return providers


def default_topix_providers() -> list[PriceProvider]:
    return [YahooFinanceProvider(), JPXProvider()]


def fetch_market_data(watchlist: list[dict], expected_date: date | None = None, providers: list[PriceProvider] | None = None, topix_providers: list[PriceProvider] | None = None) -> FetchResult:
    trade_date = expected_date or recent_business_day()
    active_providers = providers or default_providers()
    prices: list[PriceRecord] = []
    missing: list[MissingRecord] = []
    for item in watchlist:
        code, name, volatility = str(item["code"]), str(item.get("name", item["code"])), str(item["volatility"])
        record = None; failures: list[str] = []
        for provider in active_providers:
            for symbol in symbol_patterns(code):
                try:
                    candidate = provider.fetch_stock(symbol, name, volatility, trade_date)
                except Exception as exc:
                    failures.append(f"{provider.name}/{symbol}: {exc}"); continue
                if candidate is None:
                    failures.append(f"{provider.name}/{symbol}: データなし"); continue
                if candidate.price_date != trade_date:
                    failures.append(f"{provider.name}/{symbol}: 日付不一致({candidate.price_date})"); continue
                record = PriceRecord(code, name, candidate.close, candidate.previous_close, candidate.price_date, provider.name, volatility)
                break
            if record:
                break
        (prices.append(record) if record else missing.append(MissingRecord(code, name, "; ".join(failures) or "要確認（データ未取得）")))

    topix_records: list[TopixRecord] = []; topix_missing: list[str] = []
    for provider in (topix_providers or default_topix_providers()):
        try:
            topix = provider.fetch_topix(trade_date)
        except Exception as exc:
            topix_missing.append(f"{provider.name}: {exc}"); continue
        if topix is None:
            topix_missing.append(f"{provider.name}: データなし"); continue
        if topix.price_date != trade_date:
            topix_missing.append(f"{provider.name}: 日付不一致({topix.price_date})"); continue
        topix_records.append(topix)
    if len(topix_records) >= 2:
        diff = abs(topix_records[0].change_percent - topix_records[1].change_percent)
        status = "一致" if diff < 0.30 else "要確認"
        change = topix_records[0].change_percent if status == "一致" else None
        source = "/".join(t.provider for t in topix_records)
    else:
        status, change, source = "要確認", None, "未取得"
    return FetchResult(prices, missing, change, status, source, trade_date, topix_records, topix_missing)


def save_daily_prices(result: FetchResult, data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "trade_date": result.trade_date.isoformat(),
        "topix": [asdict(t) | {"price_date": t.price_date.isoformat(), "change_percent": t.change_percent} for t in result.topix_records],
        "topix_source_status": result.topix_source_status,
        "prices": [asdict(p) | {"price_date": p.price_date.isoformat(), "change_percent": round(percent_change(p.close, p.previous_close), 2), "reason": ""} for p in result.prices],
        "missing": [asdict(m) for m in result.missing],
        "topix_missing": result.topix_missing,
    }
    path = data_dir / f"{result.trade_date.isoformat()}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
