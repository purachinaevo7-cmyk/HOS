"""Private, non-executing household portfolio completion simulation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import math
from typing import Any, Mapping


@dataclass(frozen=True)
class ReturnScenario:
    annual_return: float
    projected_assets_without_additional_jpy: float | None
    required_annual_additional_investment_jpy: float | None


@dataclass(frozen=True)
class PortfolioSimulation:
    current_financial_assets_jpy: float | None
    plan_financial_assets_jpy: float | None
    plan_cost_jpy: float | None
    current_annual_dividend_jpy: float
    plan_annual_dividend_jpy: float
    current_dividend_yield: float | None
    plan_dividend_yield: float | None
    current_sector_weights: dict[str, float] | None
    plan_sector_weights: dict[str, float] | None
    current_top_holding_weight: float | None
    plan_top_holding_weight: float | None
    dividend_shortfall_jpy: float | None
    asset_shortfall_jpy: float | None
    years_to_target: float | None
    required_average_return: float | None
    scenarios: list[ReturnScenario]
    incomplete_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "scenarios": [asdict(row) for row in self.scenarios]}


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _years(profile: Mapping[str, Any], today: date) -> float | None:
    target = _date((profile.get("goals") or {}).get("target_date"))
    if target is None or target <= today:
        return None
    return round((target - today).days / 365.25, 4)


def _plan_cost(profile: Mapping[str, Any], today: date) -> tuple[float | None, list[str]]:
    total, missing = 0.0, []
    strategy = profile.get("strategy", {}) if isinstance(profile, Mapping) else {}
    for account in (strategy.get("accounts", {}) if isinstance(strategy, Mapping) else {}).values():
        for order in account.get("orders", []) if isinstance(account, Mapping) else []:
            if order.get("execution_reconciliation_required"):
                missing.append("PLAN_EXECUTION_RECONCILIATION_REQUIRED")
                continue
            completed = {str(step_id) for step_id in order.get("completed_step_ids", [])}
            currency = str(order.get("currency") or "JPY").upper()
            fx = 1.0
            if currency != "JPY":
                row = (profile.get("fx_rates") or {}).get(currency, {})
                expiry = _date(row.get("expires_on")) if isinstance(row, Mapping) else None
                fx = _num(row.get("jpy_per_unit")) if isinstance(row, Mapping) and row.get("source_verified") and expiry and expiry >= today else None
                if fx is None:
                    missing.append("PLAN_FX_UNVERIFIED_OR_STALE")
                    continue
            for step in order.get("order_steps", []):
                if str(step.get("step_id") or "") in completed:
                    continue
                shares, price = _num(step.get("shares")), _num(step.get("limit_price"))
                if shares is None or price is None:
                    missing.append("PLAN_STEP_AMOUNT_MISSING")
                    continue
                total += shares * price * fx
    return (round(total, 2) if not missing else None), sorted(set(missing))


def _weights(profile: Mapping[str, Any], *, plan: bool) -> tuple[dict[str, float] | None, float | None, list[str]]:
    values: list[tuple[str, str, float]] = []
    reasons: list[str] = []
    for holding in profile.get("holdings", []) if isinstance(profile, Mapping) else []:
        if not isinstance(holding, Mapping) or not holding.get("verified"):
            reasons.append("HOLDING_VALUE_UNVERIFIED")
            continue
        value = _num(holding.get("market_value_jpy"))
        if value is None:
            reasons.append("HOLDING_MARKET_VALUE_MISSING")
            continue
        values.append((str(holding.get("ticker") or "UNKNOWN"), str(holding.get("sector") or "UNCLASSIFIED"), value))
    if reasons:
        return None, None, sorted(set(reasons))
    if not values:
        return None, None, ["HOLDING_VALUE_MISSING"]
    if plan:
        strategy = profile.get("strategy", {}) if isinstance(profile, Mapping) else {}
        for account in (strategy.get("accounts", {}) if isinstance(strategy, Mapping) else {}).values():
            for order in account.get("orders", []) if isinstance(account, Mapping) else []:
                if order.get("execution_reconciliation_required"):
                    continue
                completed = {str(step_id) for step_id in order.get("completed_step_ids", [])}
                cost = sum((_num(step.get("shares")) or 0) * (_num(step.get("limit_price")) or 0) for step in order.get("order_steps", []) if str(step.get("step_id") or "") not in completed)
                if cost:
                    values.append((str(order.get("ticker") or "UNKNOWN"), str(order.get("sector") or "UNCLASSIFIED"), cost))
    total = sum(value for _, _, value in values)
    if total <= 0:
        return None, None, ["HOLDING_VALUE_MISSING"]
    sectors: dict[str, float] = {}
    positions: dict[str, float] = {}
    for ticker, sector, value in values:
        sectors[sector] = sectors.get(sector, 0) + value
        positions[ticker] = positions.get(ticker, 0) + value
    return ({key: round(value / total, 6) for key, value in sorted(sectors.items())}, round(max(positions.values()) / total, 6), [])


def _contribution_needed(current: float, target: float, annual_return: float, years: float) -> float:
    factor = (1 + annual_return) ** years
    shortfall = target - current * factor
    if shortfall <= 0:
        return 0.0
    annuity = years if annual_return == 0 else (factor - 1) / annual_return
    return round(shortfall / annuity, 2)


def _required_return(current: float, target: float, annual_contribution: float, years: float) -> float | None:
    if current >= target:
        return 0.0
    lo, hi = 0.0, 1.0
    def outcome(rate: float) -> float:
        factor = (1 + rate) ** years
        annuity = years if rate == 0 else (factor - 1) / rate
        return current * factor + annual_contribution * annuity
    if outcome(hi) < target:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if outcome(mid) >= target:
            hi = mid
        else:
            lo = mid
    return round(hi, 6)


def simulate_completion(profile: Mapping[str, Any], dividends: Any, *, as_of: date | None = None) -> PortfolioSimulation:
    today = as_of or date.today()
    progress = profile.get("progress", {}) if isinstance(profile, Mapping) else {}
    current_assets = _num(progress.get("financial_assets_jpy")) if isinstance(progress, Mapping) and progress.get("financial_assets_verified") else None
    reasons = [] if current_assets is not None else ["FINANCIAL_ASSETS_UNVERIFIED"]
    plan_cost, cost_reasons = _plan_cost(profile, today)
    reasons.extend(cost_reasons)
    current_sector, current_top, weight_reasons = _weights(profile, plan=False)
    plan_sector, plan_top, plan_weight_reasons = _weights(profile, plan=True)
    reasons.extend(weight_reasons + plan_weight_reasons)
    goals = profile.get("goals", {}) if isinstance(profile, Mapping) else {}
    target_assets, target_dividend = _num(goals.get("target_financial_assets_jpy")), _num(goals.get("target_annual_dividend_jpy"))
    years = _years(profile, today)
    annual_additional = _num((profile.get("simulation_assumptions") or {}).get("annual_additional_investment_jpy"))
    scenarios: list[ReturnScenario] = []
    required_return = None
    if current_assets is not None and target_assets is not None and years is not None:
        for annual_return in (0.03, 0.05, 0.07):
            projected = round(current_assets * (1 + annual_return) ** years, 2)
            scenarios.append(ReturnScenario(annual_return, projected, _contribution_needed(current_assets, target_assets, annual_return, years)))
        if annual_additional is not None:
            required_return = _required_return(current_assets, target_assets, annual_additional, years)
    elif target_assets is not None:
        reasons.append("TARGET_DATE_REQUIRED_FOR_RETURN_SCENARIOS")
    return PortfolioSimulation(
        current_financial_assets_jpy=current_assets,
        plan_financial_assets_jpy=current_assets,  # buying reallocates cash to securities; it is not a gain.
        plan_cost_jpy=plan_cost,
        current_annual_dividend_jpy=float(getattr(dividends, "current_ordinary_cash_jpy", 0) or 0),
        plan_annual_dividend_jpy=float(getattr(dividends, "projected_ordinary_cash_jpy", 0) or 0),
        current_dividend_yield=getattr(dividends, "current_yield", None),
        plan_dividend_yield=getattr(dividends, "projected_yield", None),
        current_sector_weights=current_sector,
        plan_sector_weights=plan_sector,
        current_top_holding_weight=current_top,
        plan_top_holding_weight=plan_top,
        dividend_shortfall_jpy=round(max(0, target_dividend - float(getattr(dividends, "current_ordinary_cash_jpy", 0) or 0)), 2) if target_dividend is not None else None,
        asset_shortfall_jpy=round(max(0, target_assets - current_assets), 2) if target_assets is not None and current_assets is not None else None,
        years_to_target=years,
        required_average_return=required_return,
        scenarios=scenarios,
        incomplete_reasons=sorted(set(reasons)),
    )
