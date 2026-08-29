"""Public-data Japanese dividend screener.

This module deliberately has no dependency on the household Stock Watch.
It ranks a curated universe using ordinary company-forecast dividends, current
market prices, and an approximately ten-year distribution of historic ordinary
dividend yields.  It never produces a trade instruction or accesses a private
profile.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol
from urllib.parse import urlparse


@dataclass(frozen=True)
class ScreeningIssue:
    code: str
    reason: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class DividendScreenEntry:
    code: str
    name: str
    rank: int
    grade: str
    price: float
    price_date: date
    ordinary_annual_dividend: float
    forecast_yield_percent: float
    historic_p50_percent: float
    historic_p75_percent: float
    historic_max_percent: float
    historic_high_yield_degree: int
    history_observations: int
    classification: str
    business: str
    safety_comment: str
    policy: str
    official_ir_url: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["price_date"] = self.price_date.isoformat()
        return payload


@dataclass(frozen=True)
class DividendScreenResult:
    trade_date: date
    market_closed: bool
    entries: tuple[DividendScreenEntry, ...]
    excluded: tuple[ScreeningIssue, ...]
    issues: tuple[ScreeningIssue, ...]

    @property
    def is_complete(self) -> bool:
        return not self.issues

    def counts_by_grade(self) -> dict[str, int]:
        return {grade: sum(entry.grade == grade for entry in self.entries) for grade in ("A", "B", "C")}


@dataclass(frozen=True)
class SnapshotChange:
    category: str
    text: str


class DividendMarketDataProvider(Protocol):
    def history(self, code: str, start: date, end: date): ...

    def dividends(self, code: str): ...


class YahooFinanceDividendProvider:
    """Yahoo daily price/dividend history used only for market-price math.

    Official forecast dividends and policy statements come from the checked-in
    official-IR registry; Yahoo is not an authority for those fields.
    """

    def history(self, code: str, start: date, end: date):
        import yfinance as yf

        # yfinance treats ``end`` as exclusive.  The screener requires the
        # completed JPX session passed by the runner, so include that full day.
        return yf.Ticker(f"{code}.T").history(start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(), auto_adjust=False, actions=False)

    def dividends(self, code: str):
        import yfinance as yf

        return yf.Ticker(f"{code}.T").dividends


def load_screening_config(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Dividend screener configuration cannot be loaded: {type(exc).__name__}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("universe"), list):
        raise ValueError("Dividend screener configuration must contain a universe list")
    history_years = payload.get("history_years")
    if not isinstance(history_years, int) or history_years < 5 or history_years > 10:
        raise ValueError("history_years must be an integer from 5 to 10")
    return payload


def _parse_date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO date") from exc


def _as_positive_float(value: Any, field: str, *, allow_zero: bool = False) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed) or parsed < 0 or (not allow_zero and parsed == 0):
        raise ValueError(f"{field} must be {'non-negative' if allow_zero else 'positive'}")
    return parsed


def _validated_candidate(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = ("code", "name", "fiscal_year_end_month", "classification", "business", "safety_comment", "policy", "official_ir")
    missing = [field for field in required if not raw.get(field)]
    if missing:
        raise ValueError(f"missing fields: {', '.join(missing)}")
    code = str(raw["code"])
    if not code.isdigit() or len(code) != 4:
        raise ValueError("code must be a four-digit JPX code")
    fiscal_month = int(raw["fiscal_year_end_month"])
    if fiscal_month < 1 or fiscal_month > 12:
        raise ValueError("fiscal_year_end_month must be 1 through 12")
    official = raw["official_ir"]
    if not isinstance(official, Mapping):
        raise ValueError("official_ir must be an object")
    source_url = str(official.get("url") or "")
    parsed_url = urlparse(source_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise ValueError("official_ir.url must be an HTTPS URL")
    source_as_of = _parse_date(official.get("source_as_of"), "official_ir.source_as_of")
    valid_through = _parse_date(official.get("valid_through"), "official_ir.valid_through")
    if valid_through < source_as_of:
        raise ValueError("official_ir.valid_through cannot precede source_as_of")
    ordinary = _as_positive_float(official.get("ordinary_annual_per_share"), "official_ir.ordinary_annual_per_share")
    special = _as_positive_float(official.get("special_annual_per_share", 0), "official_ir.special_annual_per_share", allow_zero=True)
    known_specials = raw.get("known_special_dividends") or {}
    if not isinstance(known_specials, Mapping):
        raise ValueError("known_special_dividends must be an object")
    normalized_specials: dict[int, float] = {}
    for fiscal_year, amount in known_specials.items():
        try:
            normalized_specials[int(fiscal_year)] = _as_positive_float(amount, "known_special_dividends", allow_zero=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("known_special_dividends contains an invalid value") from exc
    return {
        **dict(raw),
        "code": code,
        "fiscal_year_end_month": fiscal_month,
        "official_ir": {
            **dict(official),
            "source_as_of": source_as_of,
            "valid_through": valid_through,
            "ordinary_annual_per_share": ordinary,
            "special_annual_per_share": special,
            "url": source_url,
        },
        "known_special_dividends": normalized_specials,
    }


def _fiscal_year(day: date, fiscal_year_end_month: int) -> int:
    return day.year if day.month <= fiscal_year_end_month else day.year + 1


def _last_completed_fiscal_year(as_of: date, fiscal_year_end_month: int) -> int:
    import calendar

    fiscal_end = date(as_of.year, fiscal_year_end_month, calendar.monthrange(as_of.year, fiscal_year_end_month)[1])
    return as_of.year if as_of >= fiscal_end else as_of.year - 1


def _normalized_series(raw: Any, *, column: str | None = None):
    import pandas as pd

    series = raw[column] if column else raw
    if not isinstance(series, pd.Series):
        raise ValueError("market response did not contain a price/dividend series")
    result = pd.to_numeric(series.copy(), errors="coerce").dropna()
    index = pd.to_datetime(result.index)
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    result.index = index
    return result[~result.index.duplicated(keep="last")].sort_index()


def _price_and_history_distribution(
    provider: DividendMarketDataProvider,
    candidate: Mapping[str, Any],
    as_of: date,
    history_years: int,
) -> tuple[float, date, tuple[float, float, float, int], list[float]]:
    import pandas as pd

    fiscal_month = int(candidate["fiscal_year_end_month"])
    last_fiscal_year = _last_completed_fiscal_year(as_of, fiscal_month)
    first_fiscal_year = last_fiscal_year - history_years + 1
    # Start a little earlier to include interim dividends for the first year.
    history_start = date(first_fiscal_year - 1, 1, 1)
    history = _normalized_series(provider.history(str(candidate["code"]), history_start, as_of), column="Close")
    eligible_prices = history.loc[history.index <= pd.Timestamp(as_of)]
    if eligible_prices.empty:
        raise ValueError("PRICE_DATA_REQUIRED")
    latest_at = eligible_prices.index[-1]
    price_date = latest_at.date()
    if price_date != as_of:
        raise ValueError("PRICE_DATE_MISMATCH")
    price = float(eligible_prices.iloc[-1])
    if not math.isfinite(price) or price <= 0:
        raise ValueError("PRICE_DATA_REQUIRED")

    dividends = _normalized_series(provider.dividends(str(candidate["code"])))
    annual_dividends: dict[int, float] = {}
    for timestamp, amount in dividends.items():
        fiscal_year = _fiscal_year(timestamp.date(), fiscal_month)
        if first_fiscal_year <= fiscal_year <= last_fiscal_year:
            annual_dividends[fiscal_year] = annual_dividends.get(fiscal_year, 0.0) + float(amount)
    for fiscal_year, special in candidate["known_special_dividends"].items():
        if fiscal_year in annual_dividends:
            annual_dividends[fiscal_year] = max(0.0, annual_dividends[fiscal_year] - special)

    monthly_prices = history.loc[history.index <= pd.Timestamp(as_of)].resample("ME").last().dropna()
    samples: list[float] = []
    for timestamp, close in monthly_prices.items():
        fiscal_year = _fiscal_year(timestamp.date(), fiscal_month)
        annual_dividend = annual_dividends.get(fiscal_year, 0.0)
        if first_fiscal_year <= fiscal_year <= last_fiscal_year and annual_dividend > 0 and float(close) > 0:
            samples.append(annual_dividend / float(close) * 100)
    required_observations = history_years * 8
    if len(samples) < required_observations:
        raise ValueError(f"HISTORICAL_YIELD_DATA_REQUIRED:{len(samples)}")
    values = pd.Series(samples, dtype="float64")
    return price, price_date, (float(values.quantile(0.5)), float(values.quantile(0.75)), float(values.max()), len(samples)), samples


def _grade(current_yield: float, p75: float, high_yield_degree: int) -> str:
    # A means the current normal-dividend yield is in, or virtually in, the
    # historical upper quartile.  B is a near-high or otherwise useful income
    # candidate; C is a policy/record monitor rather than a valuation signal.
    if high_yield_degree >= 70 and current_yield >= p75 * 0.99:
        return "A"
    if high_yield_degree >= 50 or (current_yield >= 3.5 and high_yield_degree >= 40):
        return "B"
    return "C"


def screen_dividend_universe(
    config: Mapping[str, Any],
    *,
    trade_date: date,
    market_closed: bool = False,
    provider: DividendMarketDataProvider | None = None,
) -> DividendScreenResult:
    """Screen only ordinary forecasts with a current official-IR record.

    Any unavailable/stale official forecast or price produces an issue and is
    excluded from rank computation.  The prior state must therefore remain in
    place rather than silently publishing a partial ranking as complete.
    """
    history_years = config.get("history_years")
    if not isinstance(history_years, int):
        raise ValueError("history_years must be configured")
    data_provider = provider or YahooFinanceDividendProvider()
    pending: list[DividendScreenEntry] = []
    excluded: list[ScreeningIssue] = []
    issues: list[ScreeningIssue] = []
    for raw_candidate in config.get("universe") or []:
        code = str(raw_candidate.get("code") or "UNKNOWN") if isinstance(raw_candidate, Mapping) else "UNKNOWN"
        try:
            candidate = _validated_candidate(raw_candidate)
        except (TypeError, ValueError) as exc:
            issues.append(ScreeningIssue(code, "CONFIGURATION_REQUIRED", type(exc).__name__))
            continue
        official = candidate["official_ir"]
        if official["valid_through"] < trade_date:
            issues.append(ScreeningIssue(candidate["code"], "OFFICIAL_IR_STALE", official["valid_through"].isoformat()))
            continue
        if official["special_annual_per_share"] > 0:
            excluded.append(ScreeningIssue(candidate["code"], "SPECIAL_DIVIDEND_EXCLUDED", f"{official['special_annual_per_share']:.2f}"))
            continue
        try:
            price, price_date, (p50, p75, maximum, observations), samples = _price_and_history_distribution(data_provider, candidate, trade_date, history_years)
        except Exception as exc:
            reason = str(exc).split(":", 1)[0]
            issues.append(ScreeningIssue(candidate["code"], reason if reason else "MARKET_DATA_REQUIRED", type(exc).__name__))
            continue
        ordinary = float(official["ordinary_annual_per_share"])
        current_yield = ordinary / price * 100
        high_degree = int(round(sum(sample <= current_yield for sample in samples) * 100 / observations))
        pending.append(DividendScreenEntry(
            code=candidate["code"],
            name=str(candidate["name"]),
            rank=0,
            grade=_grade(current_yield, p75, high_degree),
            price=price,
            price_date=price_date,
            ordinary_annual_dividend=ordinary,
            forecast_yield_percent=current_yield,
            historic_p50_percent=p50,
            historic_p75_percent=p75,
            historic_max_percent=maximum,
            historic_high_yield_degree=high_degree,
            history_observations=observations,
            classification=str(candidate["classification"]),
            business=str(candidate["business"]),
            safety_comment=str(candidate["safety_comment"]),
            policy=str(candidate["policy"]),
            official_ir_url=str(official["url"]),
        ))
    ranked = sorted(
        pending,
        key=lambda entry: (
            -entry.historic_high_yield_degree,
            -(entry.forecast_yield_percent / entry.historic_p75_percent if entry.historic_p75_percent else 0),
            -entry.forecast_yield_percent,
            entry.code,
        ),
    )
    entries = tuple(replace(entry, rank=index) for index, entry in enumerate(ranked, start=1))
    return DividendScreenResult(trade_date, market_closed, entries, tuple(excluded), tuple(issues))


def build_snapshot(result: DividendScreenResult) -> dict[str, Any]:
    return {
        "version": 1,
        "trade_date": result.trade_date.isoformat(),
        "entries": {
            entry.code: {
                "rank": entry.rank,
                "grade": entry.grade,
                "forecast_yield_percent": round(entry.forecast_yield_percent, 4),
                "historic_high_yield_degree": entry.historic_high_yield_degree,
            }
            for entry in result.entries
        },
        "excluded": {issue.code: issue.reason for issue in result.excluded},
    }


def load_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and isinstance(payload.get("entries"), Mapping) else None


def write_snapshot(path: Path, snapshot: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def diff_snapshots(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> list[SnapshotChange]:
    current_entries = current.get("entries", {}) if isinstance(current.get("entries"), Mapping) else {}
    if not previous:
        return [SnapshotChange("BASELINE", f"初回スナップショット：{len(current_entries)}銘柄を新規登録")]
    previous_entries = previous.get("entries", {}) if isinstance(previous.get("entries"), Mapping) else {}
    current_excluded = current.get("excluded", {}) if isinstance(current.get("excluded"), Mapping) else {}
    changes: list[SnapshotChange] = []
    for code in sorted(set(current_entries) - set(previous_entries)):
        changes.append(SnapshotChange("ADDED", f"🆕 {code} 新規追加"))
    for code in sorted(set(previous_entries) - set(current_entries)):
        reason = current_excluded.get(code, "データ要確認")
        changes.append(SnapshotChange("REMOVED", f"➖ {code} 削除（{reason}）"))
    for code in sorted(set(current_entries) & set(previous_entries)):
        before = previous_entries.get(code, {}) if isinstance(previous_entries.get(code), Mapping) else {}
        after = current_entries.get(code, {}) if isinstance(current_entries.get(code), Mapping) else {}
        before_rank, after_rank = before.get("rank"), after.get("rank")
        if isinstance(before_rank, int) and isinstance(after_rank, int) and before_rank != after_rank:
            arrow = "↑" if after_rank < before_rank else "↓"
            changes.append(SnapshotChange("RANK", f"{arrow} {code} {before_rank}位→{after_rank}位"))
        if before.get("grade") and after.get("grade") and before.get("grade") != after.get("grade"):
            changes.append(SnapshotChange("GRADE", f"🔁 {code} {before['grade']}→{after['grade']}"))
    return changes or [SnapshotChange("UNCHANGED", "順位・候補区分の変更なし")]


def _yen(value: float) -> str:
    rounded = round(value)
    return f"¥{rounded:,}" if abs(value - rounded) < 0.005 else f"¥{value:,.1f}".rstrip("0").rstrip(".")


def _percent(value: float) -> str:
    return f"{value:.2f}%"


def render_discord_messages(result: DividendScreenResult, changes: Iterable[SnapshotChange]) -> list[str]:
    """Build compact, public-data-only Discord posts grouped by grade."""
    counts = result.counts_by_grade()
    trade_label = f"{result.trade_date.isoformat()}終値"
    if result.market_closed:
        trade_label += "（JPX休場・直近取引日）"
    header = [
        "📈 日本株・連続増配／累進配当スクリーナー",
        trade_label,
        f"対象 {len(result.entries)}銘柄｜A {counts['A']}｜B {counts['B']}｜C {counts['C']}",
        "【前回から】",
    ]
    header.extend(change.text for change in list(changes)[:8])
    if result.excluded:
        excluded = "、".join(f"{issue.code}（{issue.reason}）" for issue in result.excluded[:4])
        header.append(f"【除外】{excluded}")
    if result.issues:
        issue_codes = "、".join(f"{issue.code}:{issue.reason}" for issue in result.issues[:6])
        header.append(f"⚠️ データ要確認：{issue_codes}")
    header.append("※会社予想の普通配当のみ。自動売買・売買指示は行いません。")
    messages = ["\n".join(header)]
    grade_titles = {"A": "強い候補", "B": "準候補", "C": "監視枠"}
    for grade in ("A", "B", "C"):
        rows = [entry for entry in result.entries if entry.grade == grade]
        if not rows:
            continue
        lines = [f"【{grade}｜{grade_titles[grade]}】"]
        for entry in rows:
            lines.extend([
                f"{entry.rank}. {entry.code} {entry.name}｜{_yen(entry.price)}｜配{_yen(entry.ordinary_annual_dividend)}｜利{_percent(entry.forecast_yield_percent)}",
                f"　過去 P50 {_percent(entry.historic_p50_percent)} / P75 {_percent(entry.historic_p75_percent)} / 最大 {_percent(entry.historic_max_percent)}｜高利回り度 {entry.historic_high_yield_degree}%",
                f"　{entry.classification}｜{entry.business}",
                f"　{entry.policy}｜安全性: {entry.safety_comment}",
            ])
        message = "\n".join(lines)
        messages.append(message if len(message) <= 1_900 else f"{message[:1_860].rstrip()}\n…続きは次回更新で再掲")
    return messages
