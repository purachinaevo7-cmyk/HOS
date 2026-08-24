"""Private household runtime integration for HOS Stock Watch.

The public repository intentionally contains no live household targets, account
names, balances, holdings, order plans, or execution state. They are supplied
at runtime through ``HOS_PRIVATE_PROFILE_JSON`` and are never written to the
public diagnostic, GitHub Actions summary, or exception text.
"""
from __future__ import annotations

from dataclasses import replace
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Mapping

from stock_analyzer import PriceRecord


FUNDING_EXCEPTION = "TRANSFER_EXISTING_POSITION_COMPLETION"
ACTIVE_FY_DECISIONS = {"BUY_2026_CORE", "BUY_2026_CONDITIONAL"}
ACCOUNT_ID_RE = re.compile(r"^member_[a-z0-9_]+$")

ENV_PATHS = {
    "HOS_MONTHLY_STOCK_BUDGET_REMAINING_JPY": ("budgets", "monthly_stock_budget_remaining_jpy"),
    "HOS_ANNUAL_STOCK_BUDGET_REMAINING_JPY": ("budgets", "annual_stock_budget_remaining_jpy"),
    "HOS_MAX_SINGLE_ORDER_JPY": ("budgets", "max_single_order_jpy"),
    "HOS_TARGET_INVESTMENT_JPY": ("budgets", "target_investment_jpy"),
    "HOS_PROTECTED_CASH_FLOOR_JPY": ("cash_policy", "protected_cash_floor_jpy"),
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


def account_env_key(account_id: str, field: str) -> str:
    """Return an internal-only environment key for a generic account id."""
    normalized = re.sub(r"[^A-Z0-9_]", "_", account_id.upper())
    return f"HOS_ACCOUNT_{normalized}_{field}"


def _accounts(profile: Mapping[str, Any]) -> Mapping[str, Any]:
    accounts = profile.get("accounts", {}) if isinstance(profile, Mapping) else {}
    return accounts if isinstance(accounts, Mapping) else {}


def _verified_cash_total(profile: Mapping[str, Any]) -> float | None:
    values: list[float] = []
    for balance in profile.get("balances", []) if isinstance(profile, Mapping) else []:
        if not isinstance(balance, Mapping) or str(balance.get("category") or "").lower() != "cash":
            continue
        if not balance.get("verified"):
            continue
        value = _finite_number(balance.get("value_jpy"))
        if value is not None:
            values.append(value)
    return sum(values) if values else None


def load_private_profile(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    source = env if env is not None else os.environ
    raw = str(source.get("HOS_PRIVATE_PROFILE_JSON", "") or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        # Do not echo parser text: provider error wrappers can include input.
        raise RuntimeError("Private Profile JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Private Profile must be a JSON object")
    return payload


def private_account_labels(profile: Mapping[str, Any]) -> dict[str, str]:
    """Return display labels only for the private Discord rendering path."""
    labels: dict[str, str] = {}
    for account_id, account in _accounts(profile).items():
        if not ACCOUNT_ID_RE.fullmatch(str(account_id)) or not isinstance(account, Mapping):
            continue
        label = str(account.get("display_name") or account_id).strip()
        labels[str(account_id)] = label or str(account_id)
    return labels


def hydrate_environment(profile: Mapping[str, Any], env: dict[str, str] | None = None) -> dict[str, str]:
    """Populate process-local gate values without logging their values."""
    target = env if env is not None else os.environ
    for env_key, path in ENV_PATHS.items():
        if str(target.get(env_key, "") or "").strip():
            continue
        value = _nested(profile, path)
        if value is not None:
            target[env_key] = "true" if value is True else "false" if value is False else str(value)

    for account_id, account in _accounts(profile).items():
        if not ACCOUNT_ID_RE.fullmatch(str(account_id)) or not isinstance(account, Mapping):
            continue
        for field, profile_key in (
            ("BUYING_POWER_JPY", "buying_power_jpy"),
            ("STRATEGY_BUDGET_JPY", "strategy_budget_jpy"),
            ("ANNUAL_STOCK_CAP_JPY", "annual_stock_cap_jpy"),
            ("TAXABLE_GIFTS_YTD_JPY", "taxable_gifts_ytd_jpy"),
            ("GIFT_TAX_REVIEWED", "gift_tax_reviewed"),
        ):
            env_key = account_env_key(str(account_id), field)
            if str(target.get(env_key, "") or "").strip() or profile_key not in account:
                continue
            value = account.get(profile_key)
            target[env_key] = "true" if value is True else "false" if value is False else str(value)

    # Verified bank cash and broker buying power are deliberately separate.
    if not str(target.get("HOS_CURRENT_HOUSEHOLD_CASH_JPY", "") or "").strip():
        cash_total = _verified_cash_total(profile)
        if cash_total is not None:
            target["HOS_CURRENT_HOUSEHOLD_CASH_JPY"] = str(cash_total)
    return target


def apply_private_policy(policy: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    """Merge only runtime-private goals into the public, safe policy template."""
    result = dict(policy)
    goals = profile.get("goals", {}) if isinstance(profile, Mapping) else {}
    if isinstance(goals, Mapping):
        mapping = {
            "target_financial_assets_jpy": "target_asset_value_at_age_60",
            "target_annual_dividend_jpy": "target_annual_dividend",
            "target_age": "target_age",
            "target_date": "target_date",
        }
        for private_key, policy_key in mapping.items():
            if goals.get(private_key) is not None:
                result[policy_key] = goals[private_key]
    result["current_values_verified"] = False
    result.pop("current_financial_assets", None)
    result.pop("current_annual_dividend", None)
    result.pop("execution_account", None)
    return result


def load_private_strategy(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Return the real strategy only from the private profile, never a repo file."""
    strategy = profile.get("strategy") if isinstance(profile, Mapping) else None
    if not isinstance(strategy, Mapping):
        return _locked_strategy("PRIVATE_PROFILE_REQUIRED")
    result = json.loads(json.dumps(strategy))
    accounts = result.get("accounts", {})
    if not isinstance(accounts, Mapping) or any(not ACCOUNT_ID_RE.fullmatch(str(key)) for key in accounts):
        return _locked_strategy("PRIVATE_PROFILE_INVALID")
    authority = result.get("purchase_authority", {})
    if (
        not isinstance(authority, Mapping)
        or str(authority.get("mode") or "").upper() != "REGISTERED_STRATEGY_ONLY"
        or _bool(authority.get("auto_order"))
        or _bool(authority.get("auto_sell"))
    ):
        return _locked_strategy("PRIVATE_PURCHASE_AUTHORITY_INVALID")
    return result


def _locked_strategy(strategy_id: str) -> dict[str, Any]:
    return {
        "strategy_id": strategy_id,
        "status": "DRAFT",
        "purchase_authority": {"mode": "REGISTERED_STRATEGY_ONLY", "max_household_orders_per_day": 1},
        "accounts": {},
    }


def load_private_earnings_book(profile: Mapping[str, Any]) -> dict[str, Any]:
    book = profile.get("earnings_assessments") if isinstance(profile, Mapping) else None
    if not isinstance(book, Mapping):
        return {"version": 1, "reviews": {}}
    reviews = book.get("reviews", {})
    return {"version": book.get("version", 1), "reviews": reviews if isinstance(reviews, Mapping) else {}}


def apply_strategy_overrides(strategy: dict[str, Any], override_path: Path) -> dict[str, Any]:
    """Compatibility helper for dummy fixtures; production does not call it."""
    if not override_path.exists():
        return strategy
    overrides = json.loads(override_path.read_text(encoding="utf-8"))
    for key in ("revision", "as_of", "status"):
        if key in overrides:
            strategy[key] = overrides[key]
    for section in ("funding", "purchase_authority", "household_goal"):
        if isinstance(overrides.get(section), dict):
            strategy.setdefault(section, {}).update(overrides[section])
    for account_name, patch in (overrides.get("accounts") or {}).items():
        account = strategy.setdefault("accounts", {}).setdefault(account_name, {})
        for key, value in patch.items():
            if key != "orders":
                account[key] = value
        order_map = {str(order.get("ticker")): order for order in account.get("orders", [])}
        for ticker, order_patch in (patch.get("orders") or {}).items():
            if str(ticker) in order_map:
                order_map[str(ticker)].update(order_patch)
    return strategy


def private_jp_watchlist(profile: Mapping[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for holding in profile.get("holdings", []) if isinstance(profile, Mapping) else []:
        if not isinstance(holding, Mapping) or str(holding.get("market", "JP")).upper() != "JP":
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


def apply_household_funding_gates(signals: list[Any], strategy: Mapping[str, Any], env: Mapping[str, str] | None = None) -> list[Any]:
    """Add household gates only; this function can never make a draft READY."""
    source = env if env is not None else os.environ
    funding = strategy.get("funding", {})
    cash_key = str(funding.get("current_household_cash_jpy_env") or "HOS_CURRENT_HOUSEHOLD_CASH_JPY")
    floor_key = str(funding.get("protected_cash_floor_jpy_env") or "HOS_PROTECTED_CASH_FLOOR_JPY")
    cash_total = _finite_number(source.get(cash_key))
    protected_floor = _finite_number(source.get(floor_key))
    gift_limit = _finite_number(funding.get("gift_tax_basic_deduction_jpy")) or 1_100_000
    order_lookup = _order_lookup(strategy)

    updated: list[Any] = []
    for signal in signals:
        if getattr(signal, "fy2026_decision", None) not in ACTIVE_FY_DECISIONS:
            updated.append(signal)
            continue
        blocks = list(getattr(signal, "blocks", []) or [])
        amount_jpy = _finite_number(getattr(signal, "estimated_amount_jpy", None))
        account_id = str(getattr(signal, "account", "") or "")
        if cash_total is None:
            blocks.append("HOUSEHOLD_CASH_REQUIRED")
        if protected_floor is None:
            blocks.append("PROTECTED_CASH_FLOOR_REQUIRED")
        if cash_total is not None and protected_floor is not None and cash_total < protected_floor:
            blocks.append("PROTECTED_CASH_FLOOR_BREACH")

        order = order_lookup.get((account_id, str(getattr(signal, "ticker", ""))), {})
        if str(order.get("funding_source") or "") == FUNDING_EXCEPTION:
            current_shares = int(order.get("current_shares") or 0)
            if not order.get("existing_position_completion") or current_shares <= 0:
                blocks.append("EXISTING_POSITION_REQUIRED")
            buying_power = _finite_number(source.get(account_env_key(account_id, "BUYING_POWER_JPY")))
            blocks = [block for block in blocks if block != "ACCOUNT_BUYING_POWER_REQUIRED"]
            if buying_power is None or buying_power <= 0:
                blocks.append("ACCOUNT_TRANSFER_REQUIRED")
            elif amount_jpy is not None and amount_jpy > buying_power:
                blocks.append("ACCOUNT_BUYING_POWER_INSUFFICIENT")
            gifts_ytd = _finite_number(source.get(account_env_key(account_id, "TAXABLE_GIFTS_YTD_JPY")))
            gift_reviewed = _bool(source.get(account_env_key(account_id, "GIFT_TAX_REVIEWED")))
            if gifts_ytd is None:
                blocks.append("ACCOUNT_TAXABLE_GIFTS_YTD_REQUIRED")
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
            status, purchase_flag, actionability = "BLOCKED_AT_LIMIT", "REVIEW_REQUIRED", "DRAFT"
        updated.append(replace(signal, status=status, purchase_flag=purchase_flag, actionability=actionability, blocks=blocks))
    return updated


def _fetch_us_prices(profile: Mapping[str, Any]) -> dict[str, float]:
    symbols = sorted({
        str(holding.get("ticker"))
        for holding in profile.get("holdings", [])
        if isinstance(holding, Mapping)
        and str(holding.get("market", "")).upper() == "US"
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
            if not history.empty:
                result[symbol] = float(history.iloc[-1]["Close"])
        except Exception:
            continue
    return result


def _fetch_usd_jpy(default: float) -> float:
    try:
        import yfinance as {{¶‰Ëkºwµçw"æ÷B†öÆF–ærævWB‚'fW&–f–VB"ÂG'VR“ ¢Ö—76–æræVæB‚&†öÆF–ær"¢6öçF–çVP¢6†&W2Òöf–æ—FUöçVÖ&W"††öÆF–ærævWB‚'6†&W2"’¢F–6¶W"Ò7G"††öÆF–ærævWB‚'F–6¶W""’÷"""¢–b6†&W2—2æöæR÷"æ÷BF–6¶W# ¢Ö—76–æræVæB‚&†öÆF–ær"¢6öçF–çVP¢Ö&¶WBÒ7G"††öÆF–ærævWB‚&Ö&¶WB"Â$¥"’’çWW"‚¢–bÖ&¶WBÓÒ$¥# ¢&–6RÒ§öÖævWB‡F–6¶W"¢–b&–6R—2æöæS ¢Ö—76–æræVæB†b'&–6S§·F–6¶W'Ò"¢VÇ6S ¢F÷FÂ³Ò6†&W2¢&–6P¢VÆ–bÖ&¶WBÓÒ%U2# ¢&–6RÒW5öÖævWB‡F–6¶W"¢ÖçVÂÒöf–æ—FUöçVÖ&W"††öÆF–ærævWB‚&ÖçVÅ÷fÇVUö§’"’¢–b&–6R—2æ÷BæöæS ¢F÷FÂ³Ò6†&W2¢&–6R¢g€¢VÆ–bÖçVÂ—2æ÷BæöæS ¢F÷FÂ³ÒÖçVÀ¢VÇ6S ¢Ö—76–æræVæB†b'&–6S§·F–6¶W'Ò"¢VÇ6S ¢ÖçVÂÒöf–æ—FUöçVÖ&W"††öÆF–ærævWB‚&ÖçVÅ÷fÇVUö§’"’¢–bÖçVÂ—2æöæS ¢Ö—76–æræVæB†b'&–6S§·F–6¶W'Ò"¢VÇ6S ¢F÷FÂ³ÒÖçVÀ ¢F&vWE²$„õ5ô4ôäd•$ÔTEô”ådU5DTEô54UE5ô¥’%ÒÒb'·F÷FÃ¢ãgÒ ¢F&vWE²$„õ5ôd”ää4”Åô54UE5ôÔ•54”äuô•DTÕ2%ÒÒ"Â"æ¦ö–â†Ö—76–ær¢–bæ÷BÖ—76–æræBæ÷B7G"‡F&vWBævWB‚$„õ5ô5U%$TåEôd”ää4”Åô54UE5ô¥’"Â""’÷"""’ç7G&—‚“ ¢F&vWE²$„õ5ô5U%$TåEôd”ää4”Åô54UE5ô¥’%ÒÒb'·F÷FÃ¢ãgÒ ¢&WGW&â°¢&6ö×ÆWFR#¢æ÷BÖ—76–ærÀ¢&6öæf—&ÖVE÷'F–Åö§’#¢&÷VæB‡F÷FÂÂ"’À¢&7W'&VçEöf–ææ6–Åö76WG5ö§’#¢&÷VæB‡F÷FÂÂ"’–bæ÷BÖ—76–ærVÇ6RæöæRÀ¢&Ö—76–ær#¢Ö—76–ærÀ¢Ğ