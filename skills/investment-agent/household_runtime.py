"""Private household runtime integration for HOS Stock Watch.

Sensitive balances and full holdings are read from the HOS_PRIVATE_PROFILE_JSON
GitHub Actions secret. The public repository contains only code/schema, never the
household's exact private profile.
"""
from __future__ import annotations

from dataclasses import replace
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from stock_analyzer import PriceRecord

FUNDING_EXCEPTION = "MAHO_TRANSFER_EXISTING_POSITION_COMPLETION"
ACTIVE_FY_DECISIONS = {"BUY_2026_CORE", "BUY_2026_CONDITIONAL"}

ENV_PATHS = {
    "HOS_MAHO_BUYING_POWER_JPY": ("buying_power", "maho_jpy"),
    "HOS_HIRO_BUYING_POWER_JPY": ("buying_power", "hiro_jpy"),
    "HOS_MONTHLY_STOCK_BUDGET_REMAINING_JPY": ("budgets", "monthly_stock_budget_remaining_jpy"),
    "HOS_ANNUAL_STOCK_BUDGET_REMAINING_JPY": ("budgets", "annual_stock_budget_remaining_jpy"),
    "HOS_MAX_SINGLE_ORDER_JPY": ("budgets", "max_single_order_jpy"),
    "HOS_TARGET_INVESTMENT_TO_2027_03_JPY": ("budgets", "target_investment_to_2027_03_jpy"),
    "HOS_MAHO_2026_STOCK_CAP_JPY": ("budgets", "maho_2026_stock_cap_jpy"),
    "HOS_MAHO_STRATEGY_BUDGET_JPY": ("budgets", "maho_strategy_budget_jpy"),
    "HOS_HIRO_STRATEGY_BUDGET_JPY": ("budgets", "hiro_strategy_budget_jpy"),
    "HOS_CURRENT_HOUSEHOLD_CASH_JPY": ("cash_policy", "current_household_cash_jpy"),
    "HOS_PROTECTED_CASH_FLOOR_JPY": ("cash_policy", "protected_cash_floor_jpy"),
    "HOS_HIRO_TAXABLE_GIFTS_YTD_JPY": ("transfers", "hiro_taxable_gifts_ytd_jpy"),
    "HOS_HIRO_GIFT_TAX_REVIEWED": ("transfers", "hiro_gift_tax_reviewed"),
    "HOS_CURRENT_ANNUAL_DIVIDEND_JPY": ("progress", "current_annual_dividend_jpy"),
}


def _nested(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _finite_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def load_private_profile(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    source = env if env is not None else os.environ
    raw = str(source.get("HOS_PRIVATE_PROFILE_JSON", "") or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"HOS_PRIVATE_PROFILE_JSON is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("HOS_PRIVATE_PROFILE_JSON must contain a JSON object")
    return payload


def hydrate_environment(profile: Mapping[str, Any], env: dict[str, str] | None = None) -> dict[str, str]:
    target = env if env is not None else os.environ
    for env_key, path in ENV_PATHS.items():
        if str(target.get(env_key, "") or "").strip():
            continue
        value = _nested(profile, path)
        if value is None:
            continue
        target[env_key] = "true" if value is True else "false" if value is False else str(value)
    # Preserve compatibility with the old household budget gate. The new
    # current-cash/protected-floor gate below is authoritative.
    if not str(target.get("HOS_HOUSEHOLD_AVAILABLE_CASH_JPY", "") or "").strip():
        value = _nested(profile, ("budgets", "target_investment_to_2027_03_jpy"))
        if value is not None:
            target["HOS_HOUSEHOLD_AVAILABLE_CASH_JPY"] = str(value)
    if not str(target.get("HOS_RESERVE_AFTER_EXECUTION_JPY", "") or "").strip():
        target["HOS_RESERVE_AFTER_EXECUTION_JPY"] = "0"
    return target


def apply_strategy_overrides(strategy: dict[str, Any], override_path: Path) -> dict[str, Any]:
    if not override_path.exists():
        return strategy
    overrides = json.loads(override_path.read_text(encoding="utf-8"))
    for key in ("revision", "as_of", "status"):
        if key in overrides:
            strategy[key] = overrides[key]
    for section in ("funding", "purchase_authority", "household_goal"):
        if isinstance(overrides.get(section), dict):
            strategy.setdefault(section, {}).update(overrides[section])
    account_overrides = overrides.get("accounts", {})
    for account_name, patch in account_overrides.items():
        account = strategy.setdefault("accounts", {}).setdefault(account_name, {})
        for key, value in patch.items():
            if key == "orders":
                continue
            account[key] = value
        order_map = {str(order.get("ticker")): order for order in account.get("orders", [])}
        for ticker, order_patch in (patch.get("orders") or {}).items():
            order = order_map.get(str(ticker))
            if order is None:
                continue
            order.update(order_patch)
    append_rules = list(overrides.get("monitoring_rules_append") or [])
    if append_rules:
        existing = strategy.setdefault("monitoring_rules", [])
        for rule in append_rules:
            if rule not in existing:
                existing.append(rule)
    return strategy


def private_jp_watchlist(profile: Mapping[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for holding in profile.get("holdings", []) if isinstance(profile, Mapping) else []:
        if str(holding.get("market", "JP")).upper() != "JP":
            continue
        ticker = str(holding.get("ticker") or "")
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        rows.append({
            "code": ticker,
            "name": str(holding.get("name") or ticker),
            "volatility": str(holding.get("volatility") or "medium"),
        })
    return rows


def _order_lookup(strategy: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for account_name, account in strategy.get("accounts", {}).items():
        for order in account.get("orders", []):
            result[(str(account_name), str(order.get("ticker")))] = order
    return result


def apply_household_funding_gates(
    signals: list[Any],
    strategy: Mapping[str, Any],
    env: Mapping[str, str] | None = None,
) -> list[Any]:
    source = env if env is not None else os.environ
    funding = strategy.get("funding", {})
    cash_key = str(funding.get("current_household_cash_jpy_env") or "HOS_CURRENT_HOUSEHOLD_CASH_JPY")
    floor_key = str(funding.get("protected_cash_floor_jpy_env") or "HOS_PROTECTED_CASH_FLOOR_JPY")
    gifts_key = str(funding.get("hiro_taxable_gifts_ytd_jpy_env") or "HOS_HIRO_TAXABLE_GIFTS_YTD_JPY")
    review_key = str(funding.get("hiro_gift_tax_reviewed_env") or "HOS_HIRO_GIFT_TAX_REVIEWED")
    cash_total = _finite_number(source.get(cash_key))
    protected_floor = _finite_number(source.get(floor_key))
    gifts_ytd = _finite_number(source.get(gifts_key))
    gift_reviewed = _bool(source.get(review_key))
    gift_limit = _finite_number(funding.get("gift_tax_basic_deduction_jpy")) or 1_100_000
    order_lookup = _order_lookup(strategy)

    updated: list[Any] = []
    for signal in signals:
        if getattr(signal, "fy2026_decision", None) not in ACTIVE_FY_DECISIONS:
            updated.append(signal)
            continue
        blocks = list(getattr(signal, "blocks", []) or [])
        amount_jpy = _finite_number(getattr(signal, "estimated_amount_jpy", None))

        if cash_total is None:
            blocks.append("HOUSEHOLD_CASH_REQUIRED")
        if protected_floor is None:
            blocks.append("PROTECTED_CASH_FLOOR_REQUIRED")
        if cash_total is not None and protected_floor is not None and amount_jpy is not None:
            if cash_total - amount_jpy < protected_floor:
                blocks.append("PROTECTED_CASH_FLOOR_BREACH")

        order = order_lookup.get((str(getattr(signal, "account", "")), str(getattr(signal, "ticker", ""))), {})
        if str(order.get("funding_source") or "") == FUNDING_EXCEPTION:
            current_shares = int(order.get("current_shares") or 0)
            if not order.get("existing_position_completion") or current_shares <= 0:
                blocks.append("EXISTING_POSITION_REQUIRED")
            buying_power = _finite_number(source.get("HOS_HIRO_BUYING_POWER_JPY"))
            blocks = [block for block in blocks if block != "ACCOUNT_BUYING_POWER_REQUIRED"]
            if buying_power is None or buying_power <= 0:
                blocks.append("HIRO_COMPLETION_TRANSFER_REQUIRED")
            elif amount_jpy is not None and amount_jpy > buying_power:
                blocks.append("ACCOUNT_BUYING_POWER_INSUFFICIENT")
            if gifts_ytd is None:
                blocks.append("HIRO_TAXABLE_GIFTS_YTD_REQUIRED")
            elif gifts_ytd > gift_limit and not gift_reviewed:
                blocks.append("GIFT_TAX_REVIEW_REQUIRED")

        blocks = sorted(set(blocks))
        status = getattr(signal, "status", None)
        purchase_flag = getattr(signal, "purchase_flag", None)
        actionability = getattr(signal, "actionability", None)
        current_price = _finite_number(getattr(signal, "current_price", None))
        limit_price = _finite_number(getattr(signal, "limit_price", None))
        at_limit = current_price is not None and limit_price is not None and current_price <= limit_price
        if blocks and at_limit and actionability == "READY":
            status = "BLOCKED_AT_LIMIT"
            purchase_flag = "REVIEW_REQUIRED"
            actionability = "DRAFT"
        updated.append(replace(
            signal,
            status=status,
            purchase_flag=purchase_flag,
            actionability=actionability,
            blocks=blocks,
        ))
    return updated


def _fetch_us_prices(profile: Mapping[str, Any]) -> dict[str, float]:
    symbols = sorted({
        str(holding.get("ticker"))
        for holding in profile.get("holdings", [])
        if str(holding.get("market", "")).upper() == "US"
        and not holding.get("manual_value_jpy")
        and holding.get("ticker")
    })
    if not symbols:
        return {}
    try:
        import yfinance as yf
    except Exception:
        return {}
    result: dict[str, float] = {}
    for symbol in symbols:
        try:
            history = yf.Ticker(symbol).history(period="5d", auto_adjust=False).dropna(subset=["Close"])
            if history.empty:
                continue
            result[symbol] = float(history.iloc[-1]["Close"])
        except Exception:
            continue
    return result


def _fetch_usd_jpy(default: float) -> float:
    try:
        import yfinance as yf
        history = yf.Ticker("JPY=X").history(period="5d", auto_adjust=False).dropna(subset=["Close"])
        if not history.empty:
            value = float(history.iloc[-1]["Close"])
            if math.isfinite(value) and value > 0:
                return value
    except Exception:
        pass
    return default


def publish_runtime_asset_snapshot(
    profile: Mapping[str, Any],
    japanese_prices: list[PriceRecord],
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    target = env if env is not None else os.environ
    if not profile:
        return {"complete": False, "confirmed_partial_jpy": None, "missing": ["PRIVATE_PROFILE"]}

    total = 0.0
    missing: list[str] = []
    for balance in profile.get("balances", []):
        if not balance.get("include_in_financial_assets", True):
            continue
        value = _finite_number(balance.get("value_jpy"))
        if not balance.get("verified") or value is None:
            missing.append(str(balance.get("id") or "balance"))
            continue
        total += value

    jp_map = {str(record.code): float(record.close) for record in japanese_prices}
    us_map = _fetch_us_prices(profile)
    planning_fx = _finite_number(target.get("HOS_USDJPY_PLANNING_RATE")) or 160.0
    fx = _fetch_usd_jpy(planning_fx)
    target["HOS_CURRENT_USDJPY_JPY"] = f"{fx:.4f}"
    for holding in profile.get("holdings", []):
        if not holding.get("verified", True):
            missing.append(f"holding:{holding.get('ticker')}")
            continue
        shares = _finite_number(holding.get("shares"))
        if shares is None:
            missing.append(f"holding:{holding.get('ticker')}")
            continue
        ticker = str(holding.get("ticker") or "")
        market = str(holding.get("market", "JP")).upper()
        if market == "JP":
            price = jp_map.get(ticker)
            if price is None:
                missing.append(f"price:{ticker}")
                continue
            total += shares * price
        elif market == "US":
            price = us_map.get(ticker)
            if price is not None:
                total += shares * price * fx
                continue
            manual = _finite_number(holding.get("manual_value_jpy"))
            if manual is not None:
                total += manual
            else:
                missing.append(f"price:{ticker}")
        else:
            manual = _finite_number(holding.get("manual_value_jpy"))
            if manual is not None:
                total += manual
            else:
                missing.append(f"price:{ticker}")

    target["HOS_CONFIRMED_INVESTED_ASSETS_JPY"] = f"{total:.0f}"
    target["HOS_FINANCIAL_ASSETS_MISSING_ITEMS"] = ",".join(missing)
    if not missing and not str(target.get("HOS_CURRENT_FINANCIAL_ASSETS_JPY", "") or "").strip():
        target["HOS_CURRENT_FINANCIAL_ASSETS_JPY"] = f"{total:.0f}"
    return {
        "complete": not missing,
        "confirmed_partial_jpy": round(total, 2),
        "current_financial_assets_jpy": round(total, 2) if not missing else None,
        "missing": missing,
    }
