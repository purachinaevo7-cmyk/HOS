"""Data retrieval layer for HOS Investment Agent."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
from statistics import median
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
    user_agent = "Mozilla/5.0 (compatible; HOS Investment Agent/1.0; +https://finance.yahoo.com)"

    def _history(self, ticker: str):
        try:
            import requests
            import yfinance as yf

            session = requests.Session()
            session.headers.update({"User-Agent": self.user_agent})
            try:
                return yf.Ticker(ticker, session=session).history(period="10d", auto_adjust=False)
            except TypeError:
                return yf.Ticker(ticker).history(period="10d", auto_adjust=False)
        except Exception:
            return self._chart_history(ticker)

    def _chart_history(self, ticker: str):
        """Fetch Yahoo history via the chart endpoint as a fallback for HTML/API changes."""
        import pandas as pd
        import requests

        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={"range": "10d", "interval": "1d", "events": "history"},
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            timeout=20,
        )
        r.raise_for_status()
        result = (r.json().get("chart", {}).get("result") or [None])[0]
        if not result:
            return pd.DataFrame()
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []
        rows = [
            {"Date": datetime.fromtimestamp(ts).date(), "Close": close}
            for ts, close in zip(timestamps, closes, strict=False)
            if close is not None
        ]
        return pd.DataFrame(rows)

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
    csv_url = "https://www.jpx.co.jp/markets/indices/topix/tvdivq00000030ne-att/topix.csv"

    def fetch_stock(self, symbol: str, name: str, volatility: str, expected_date: date) -> PriceRecord | None:
        return None

    def fetch_topix(self, expected_date: date) -> TopixRecord | None:
        url = os.getenv("JPX_TOPIX_CSV_URL", self.csv_url)
        import pandas as pd

        df = pd.read_csv(url)
        df.columns = [str(c).strip() for c in df.columns]
        date_col = next((c for c in df.columns if c.lower() in {"date", "trade_date", "日付", "年月日"}), None)
        close_col = next((c for c in df.columns if c.lower() in {"close", "topix", "終値", "指数値"}), None)
        prev_col = next((c for c in df.columns if c.lower() in {"previous_close", "prev_close", "前日終値"}), None)
        if not (date_col and close_col):
            return None
        df[date_col] = pd.to_datetime(df[date_col]).dt.date
        rows = df[df[date_col] == expected_date]
        if rows.empty:
            return None
        current_idx = rows.index[-1]
        if prev_col:
            previous_close = float(rows.iloc[-1][prev_col])
        else:
            prior = df[df[date_col] < expected_date].tail(1)
            if prior.empty:
                return None
            previous_close = float(prior.iloc[-1][close_col])
        return TopixRecord(self.name, float(df.loc[current_idx, close_col]), previous_close, expected_date)


class TradingViewProvider:
    name = "TradingView"

    def fetch_stock(self, symbol: str, name: str, volatility: str, expected_date: date) -> PriceRecord | None:
        return None

    def fetch_topix(self, expected_date: date) -> TopixRecord | None:
        import requests

        payload = {
            "symbols": {"tickers": ["TSE:TOPIX"], "query": {"types": []}},
            "columns": ["close", "prev_close", "update_mode"],
        }
        r = requests.post("https://scanner.tradingview.com/japan/scan", json=payload, timeout=20)
        r.raise_for_status()
        data = (r.json().get("data") or [])
        if not data:
            return None
        values = data[0].get("d") or []
        if len(values) < 2 or values[0] is None or values[1] is None:
            return None
        close = float(values[0])
        previous_close = float(values[1])
        return TopixRecord(self.name, close, previous_close, expected_date)


class StooqProvider:
    name = "Stooq"

    def fetch_stock(self, symbol: str, name: str, volatility: str, expected_date: date) -> PriceRecord | None:
        return None

    def fetch_topix(self, expected_date: date) -> TopixRecord | None:
        import pandas as pd

        symbols = ["^tpix", "^topx", "topix"]
        for symbol in symbols:
            url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
            df = pd.read_csv(url)
            if df.empty or "Date" not in df or "Close" not in df:
                continue
            df["Date"] = pd.to_datetime(df["Date"]).dt.date
            current_idx = df.index[df["Date"] == expected_date].tolist()
            if not current_idx:
                continue
            idx = current_idx[-1]
            if idx == 0:
                continue
            return TopixRecord(self.name, float(df.loc[idx, "Close"]), float(df.loc[idx - 1, "Close"]), expected_date)
        return None


class InvestingComProvider:
    name = "Investing.com"

    def fetch_stock(self, symbol: str, name: str, volatility: str, expected_date: date) -> PriceRecord | None:
        return None

    def fetch_topix(self, expected_date: date) -> TopixRecord | None:
        import requests

        url = "https://api.investing.com/api/financialdata/indices/175/historical/chart/"
        r = requests.get(
            url,
            params={"interval": "P1D", "period": "P1M"},
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=20,
        )
        r.raise_for_status()
        points = r.json().get("data") or []
        rows: list[tuple[date, float]] = []
        for point in points:
            ts = point.get("rowDateTimestamp") or point.get("timestamp") or point.get("date")
            close = point.get("last_close") or point.get("close") or point.get("last")
            if ts is None or close is None:
                continue
            if str(ts).isdigit():
                divisor = 1000 if int(ts) > 10_000_000_000 else 1
                price_date = datetime.fromtimestamp(int(ts) / divisor).date()
            else:
                price_date = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date()
            rows.append((price_date, float(str(close).replace(",", ""))))
        rows = sorted(rows)
        current_idx = next((i for i, row in enumerate(rows) if row[0] == expected_date), None)
        if current_idx is None or current_idx == 0:
            return None
        return TopixRecord(self.name, rows[current_idx][1], rows[current_idx - 1][1], expected_date)


class TopixEtfMedianProvider(YahooFinanceProvider):
    name = "TOPIX ETF median"
    codes = ("1306", "1308", "1475")

    def fetch_stock(self, symbol: str, name: str, volatility: str, expected_date: date) -> PriceRecord | None:
        return None

    def fetch_topix(self, expected_date: date) -> TopixRecord | None:
        records: list[TopixRecord] = []
        for code in self.codes:
            history = self._history(f"{code}.T")
            row, prev = _valid_current_and_previous_rows(history, expected_date)
            if row is None or prev is None:
                continue
            records.append(
                TopixRecord(
                    f"TOPIX ETF {code}",
                    float(row["Close"]),
                    float(prev["Close"]),
                    _row_date(row),
                    "TOPIX連動ETFを指数プロキシとして使用",
                )
            )
        if len(records) != len(self.codes):
            return None
        median_change = median(r.change_percent for r in records)
        base_previous_close = 100.0
        synthetic_close = base_previous_close * (1 + median_change / 100)
        details = ", ".join(
            f"{r.provider}: date={r.price_date}, close={r.close:.2f}, previous_close={r.previous_close:.2f}, change={r.change_percent:.2f}%"
            for r in records
        )
        return TopixRecord(
            self.name,
            synthetic_close,
            base_previous_close,
            expected_date,
            f"1306・1308・1475の前日比中央値を採用（{details}）",
        )


class TopixEtfProvider(YahooFinanceProvider):
    def __init__(self, code: str) -> None:
        self.code = code
        self.name = f"TOPIX ETF {code}"

    def fetch_stock(self, symbol: str, name: str, volatility: str, expected_date: date) -> PriceRecord | None:
        return None

    def fetch_topix(self, expected_date: date) -> TopixRecord | None:
        history = self._history(f"{self.code}.T")
        row, prev = _valid_current_and_previous_rows(history, expected_date)
        if row is None or prev is None:
            return None
        return TopixRecord(self.name, float(row["Close"]), float(prev["Close"]), _row_date(row), "TOPIX連動ETFを指数プロキシとして使用")


def default_topix_providers() -> list[PriceProvider]:
    return [
        YahooFinanceProvider(),
        StooqProvider(),
        JPXProvider(),
        TradingViewProvider(),
        InvestingComProvider(),
        TopixEtfMedianProvider(),
    ]


def _format_topix_success(topix: TopixRecord) -> str:
    details = (
        f"取得日 {topix.price_date.isoformat()}, "
        f"終値 {topix.close:.2f}, "
        f"前日終値 {topix.previous_close:.2f}, "
        f"計算した前日比 {topix.change_percent:.2f}%"
    )
    if topix.reason:
        details = f"{details}, {topix.reason}"
    return f"{topix.provider}: 成功（{details}）"


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
    import pandas as pd

    rows["DateOnly"] = pd.to_datetime(rows[date_col]).dt.date
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
    active_topix_providers = default_topix_providers() if topix_providers is None else topix_providers
    for provider in active_topix_providers:
        try:
            topix = provider.fetch_topix(trade_date)
        except Exception as exc:
            topix_missing.append(f"{provider.name}: 失敗（{exc}）"); continue
        if topix is None:
            topix_missing.append(f"{provider.name}: 失敗（データなし）")
            continue
        if topix.price_date != trade_date:
            topix_missing.append(f"{provider.name}: 失敗（日付不一致 {topix.price_date}）"); continue
        topix_records.append(topix)
        topix_missing.append(_format_topix_success(topix))
    if len(topix_records) >= 2:
        changes = [t.change_percent for t in topix_records]
        diff = max(changes) - min(changes)
        if diff < 0.30:
            status = "一致"
            change = round(median(changes), 2)
        else:
            status = "要確認（指数値不一致）"
            change = None
        source = "/".join(t.provider for t in topix_records)
    elif len(topix_records) == 1:
        status = "要確認（TOPIX 1ソースのみ）" if not missing else "要確認"
        change = None
        source = topix_records[0].provider
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
