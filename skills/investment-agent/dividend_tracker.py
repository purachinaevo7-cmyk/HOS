"""Verified, cash-available annual dividend aggregation.

All inputs are private runtime data. Missing data, unofficial sources, stale
records, reinvesting funds, and crypto are excluded from the household progress
numerator instead of being estimated.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
import math
from typing import Any, Mapping


OFFICIAL_SOURCES = {
    "OFFICIAL_IR",
    "OFFICIAL_DISCLOSURE",
    "OFFICIAL_FUND_DOCUMENT",
    "OFFICIAL_ETF_ISSUER",
}
CASH_ASSET_TYPES = {"JP_STOCK", "US_STOCK", "ADR", "ETF", "FUND", "OTHER_INCOME"}
EXCLUDED_ASSET_TYPES = {"CRYPTO", "CASH", "POINTS"}


@dataclass(frozen=True)
class DividendLine:
    owner: str
    ticker: str
    asset_type: str
    status: str
    ordinary_cash_jpy: float | None
    special_cash_jpy: float | None
    foreign_withholding_jpy: float | None
    reason: str | None
    scope: str = "CURRENT"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DividendSummary:
    current_ordinary_cash_jpy: float
    current_special_cash_jpy: float
    current_foreign_withholding_jpy: float
    current_unconfirmed_count: int
    projected_ordinary_cash_jpy: float
    projected_special_cash_jpy: float
    projected_unconfirmed_count: int
    plan_increment_ordinary_jpy: float
    target_annual_dividend_jpy: float | None
    target_shortfall_jpy: float | None
    current_yield: float | None
    projected_yield: float | None
    lines: list[DividendLine]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "lines": [line.to_dict() for line in self.lines]}


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _as_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _forecast_for(profile: Mapping[str, Any], ticker: str) -> Mapping[str, Any] | None:
    forecasts = profile.get("dividend_forecasts", {}) if isinstance(profile, Mapping) else {}
    if not isinstance(forecasts, Mapping):
        return None
    row = forecasts.get(ticker)
    return row if isinstance(row, Mapping) else None


def _fx(profile: Mapping[str, Any], currency: str, today: date) -> tuple[float | None, str | None]:
    currency = currency.upper()
    if currency == "JPY":
        return 1.0, None
    rates = profile.get("fx_rates", {}) if isinstance(profile, Mapping) else {}
    row = rates.get(currency) if isinstance(rates, Mapping) else None
    if not isinstance(row, Mapping) or not row.get("source_verified"):
        return None, "FX_UNVERIFIED"
    expires = _as_date(row.get("expires_on"))
    if expires is None or today > expires:
        return None, "FX_STALE"
    rate = _number(row.get("jpy_per_unit"))
    return (rate, None) if rate else (None, "FX_MISSING")


def _forecast_line(holding: Mapping[str, Any], profile: Mapping[str, Any], *, shares: float, today: date) -> DividendLine:
    owner = str(holding.get("owner") or "")
    ticker = str(holding.get("ticker") or holding.get("id") or "")
    asset_type = str(holding.get("asset_type") or holding.get("market") or "").upper()
    if asset_type in EXCLUDED_ASSET_TYPES:
        return DividendLine(owner, ticker, asset_type, "EXCLUDED", 0.0, 0.0, 0.0, f"{asset_type}_EXCLUDED")
    if asset_type == "WEALTHNAVI" and str(holding.get("distribution_mode") or "").upper() != "CASH":
        return DividendLine(owner, ticker, asset_type, "EXCLUDED", 0.0, 0.0, 0.0, "WEALTHNAVI_REINVESTED_DISTRIBUTION_EXCLUDED")
    if asset_type == "FUND" and str(holding.get("distribution_mode") or "").upper() != "CASH":
        return DividendLine(owner, ticker, asset_type, "EXCLUDED", 0.0, 0.0, 0.0, "REINVESTING_FUND_EXCLUDED")
    if asset_type not in CASH_ASSET_TYPES and asset_type != "WEALTHNAVI":
        return DividendLine(owner, ticker, asset_type, "UNCONFIRMED", None, None, None, "ASSET_TYPE_UNSUPPORTED")
    if not holding.get("verified"):
        return DividendLine(owner, ticker, asset_type, "UNCONFIRMED", None, None, None, "HOLDING_UNVERIFIED")
    forecast = _forecast_for(profile, ticker)
    if forecast is None:
        return DividendLine(owner, ticker, asset_type, "UNCONFIRMED", None, None, None, "DIVIDEND_FORECAST_MISSING")
    if not forecast.get("source_verified") or str(forecast.get("source_type") or "").upper() not in OFFICIAL_SOURCES:
        return DividendLine(owner, ticker, asset_type, "UNCONFIRMED", None, None, None, "OFFICIAL_DIVIDEND_SOURCE_REQUIRED")
    expires = _as_date(forecast.get("expires_on"))
    if expires is None or today > expires:
        return DividendLine(owner, ticker, asset_type, "UNCONFIRMED", None, None, None, "DIVIDEND_FORECAST_STALE")
    ordinary_per_share = _number(forecast.get("ordinary_annual_per_share"))
    special_per_share = _number(forecast.get("special_annual_per_share")) or 0.0
    if ordinary_per_share is None:
        return DividendLine(owner, ticker, asset_type, "UNCONFIRMED", None, None, None, "ORDINARY_DIVIDEND_MISSING")
    ratio = 1.0
    if asset_type == "ADR" and str(forecast.get("dividend_basis") or "").upper() == "UNDERLYING_SHARE":
        ratio = _number(forecast.get("adr_ratio")) or 0.0
        if ratio <= 0:
            return DividendLine(owner, ticker, asset_type, "UNCONFIRMED", None, None, None, "ADR_RATIO_REQUIRED")
    currency = str(forecast.get("currency") or holding.get("currency") or "JPY")
    fx, fx_error = _fx(profile, currency, today)
    if fx is None:
        return DividendLine(owner, ticker, asset_type, "UNCONFIRMED", None, None, None, fx_error)
    ordinary = shares * ordinary_per_share * ratio * fx
    special = shares * special_per_share * ratio * fx
    withholding_rate = _number(forecast.get("foreign_withholding_rate")) or 0.0
    withholding = (ordinary + special) * withholding_rate if withholding_rate else 0.0
    return DividendLine(owner, ticker, asset_type, "CONFIRMED", round(ordinary, 2), round(special, 2), round(withholding, 2), None)


def _shares(holding: Mapping[str, Any]) -> float | None:
    shares = _number(holding.get("shares"))
    return shares if shares is not None else None


def _current_holdings(profile: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for holding in profile.get("holdings", []) if isinstance(profile, Mapping) else []:
        if not isinstance(holding, Mapping):
            continue
        key = (str(holding.get("owner") or ""), str(holding.get("ticker") or holding.get("id") or ""))
        if key[1]:
            result[key] = holding
    return result


def _planned_holdings(profile: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], list[DividendLine]]:
    current = _current_holdings(profile)
    planned: list[Mapping[str, Any]] = []
    unavailable: list[DividendLine] = []
    strategy = profile.get("strategy", {}) if isinstance(profile, Mapping) else {}
    for owner, account in (strategy.get("accounts", {}) if isinstance(strategy, Mapping) else {}).items():
        for order in account.get("orders", []) if isinstance(account, Mapping) else []:
            ticker = str(order.get("ticker") or "")
            holding = current.get((str(owner), ticker))
            if not ticker or holding is None or not holding.get("verified"):
                unavailable.append(DividendLine(str(owner), ticker, "UNKNOWN", "UNCONFIRMED", None, None, None, "PLAN_HOLDING_BASELINE_UNVERIFIED"))
                continue
            current_shares = _shares(holding)
            if current_shares is None:
                unavailable.append(DividendLine(str(owner), ticker, "UNKNOWN", "UNCONFIRMED", None, None, None, "PLAN_HOLDING_SHARES_MISSING"))
                continue
            target = _number(order.get("target_total_shares"))
            if target is None:
                completed = {str(value) for value in order.get("completed_step_ids", [])}
                additions = 0.0
                for step in order.get("order_steps", []):
                    if str(step.get("step_id")) not in completed:
                        amount = _number(step.get("shares"))
                        if amount is None:
                            additions = -1
                            break
                        additions += amount
                if additions < 0:
                    unavailable.append(DividendLine(str(owner), ticker, "UNKNOWN", "UNCONFIRMED", None, None, None, "PLAN_SHARES_UNCONFIRMED"))
                    continue
                target = current_shares + additions
            if target < current_shares:
                unavailable.append(DividendLine(str(owner), ticker, "UNKNOWN", "UNCONFIRMED", None, None, None, "PLAN_TARGET_BELOW_CURRENT_HOLDING"))
                continue
            planned.append({**holding, "shares": target})
    return planned, unavailable


def _asset_value(profile: Mapping[str, Any]) -> float | None:
    progress = profile.get("progress", {}) if isinstance(profile, Mapping) else {}
    if not isinstance(progress, Mapping) or not progress.get("financial_assets_verified"):
        return None
    return _number(progress.get("financial_assets_jpy"))


def annual_dividend_summary(profile: Mapping[str, Any], *, as_of: date | None = None) -> DividendSummary:
    today = as_of or date.today()
    current_lines: list[DividendLine] = []
    for holding in profile.get("holdings", []) if isinstance(profile, Mapping) else []:
        if not isinstance(holding, Mapping):
            continue
        shares = _shares(holding)
        if shares is None:
            current_lines.append(DividendLine(str(holding.get("owner") or ""), str(holding.get("ticker") or ""), str(holding.get("asset_type") or "UNKNOWN"), "UNCONFIRMED", None, None, None, "HOLDING_SHARES_MISSING"))
        else:
            current_lines.append(_forecast_line(holding, profile, shares=shares, today=today))
    projected_holdings, plan_unavailable = _planned_holdings(profile)
    projected_lines = [replace(_forecast_line(holding, profile, shares=_shares(holding) or 0, today=today), scope="PLAN") for holding in projected_holdings]
    current_ordinary = sum(line.ordinary_cash_jpy or 0 for line in current_lines if line.status == "CONFIRMED")
    current_special = sum(line.special_cash_jpy or 0 for line in current_lines if line.status == "CONFIRMED")
    current_withholding = sum(line.foreign_withholding_jpy or 0 for line in current_lines if line.status == "CONFIRMED")
    projected_ordinary = current_ordinary + sum(
        max(0.0, (line.ordinary_cash_jpy or 0) - next((base.ordinary_cash_jpy or 0 for base in current_lines if base.owner == line.owner and base.ticker == line.ticker), 0.0))
        for line in projected_lines if line.status == "CONFIRMED"
    )
    projected_special = current_special + sum(
        max(0.0, (line.special_cash_jpy or 0) - next((base.special_cash_jpy or 0 for base in current_lines if base.owner == line.owner and base.ticker == line.ticker), 0.0))
        for line in projected_lines if line.status == "CONFIRMED"
    )
    current_unconfirmed = sum(line.status == "UNCONFIRMED" for line in current_lines)
    projected_unconfirmed = current_unconfirmed + sum(line.status == "UNCONFIRMED" for line in projected_lines) + len(plan_unavailable)
    target = _number((profile.get("goals") or {}).get("target_annual_dividend_jpy"))
    assets = _asset_value(profile)
    planned_cost = sum(
        (_number(step.get("shares")) or 0) * (_number(step.get("limit_price")) or 0)
        for account in ((profile.get("strategy") or {}).get("accounts") or {}).values()
        for order in account.get("orders", [])
        for step in order.get("order_steps", [])
        if str(step.get("step_id")) not in {str(value) for value in order.get("completed_step_ids", [])}
    )
    current_yield = current_ordinary / assets if assets and assets > 0 else None
    projected_yield = projected_ordinary / (assets + planned_cost) if assets and assets + planned_cost > 0 else None
    return DividendSummary(
        current_ordinary_cash_jpy=round(current_ordinary, 2),
        current_special_cash_jpy=round(current_special, 2),
        current_foreign_withholding_jpy=round(current_withholding, 2),
        current_unconfirmed_count=current_unconfirmed,
        projected_ordinary_cash_jpy=round(projected_ordinary, 2),
        projected_special_cash_jpy=round(projected_special, 2),
        projected_unconfirmed_count=projected_unconfirmed,
        plan_increment_ordinary_jpy=round(projected_ordinary - current_ordinary, 2),
        target_annual_dividend_jpy=target,
        target_shortfall_jpy=round(max(0.0, target - current_ordinary), 2) if target is not None else None,
        current_yield=round(current_yield, 6) if current_yield is not None else None,
        projected_yield=round(projected_yield, 6) if projected_yield is not None else None,
        lines=current_lines + projected_lines + plan_unavailable,
    )
