"""Account-specific order planning for HOS Stock Watch V3.

Registered strategy orders are authoritative. Generic daily-drop signals remain
context only and can never become executable for a strategy-controlled ticker.
The planner never sends an order to a broker.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from stock_analyzer import PriceRecord


ACTIVE_FY_DECISIONS = {"BUY_2026_CORE", "BUY_2026_CONDITIONAL"}


@dataclass(frozen=True)
class StrategyOrderSignal:
    strategy_id: str
    account: str
    ticker: str
    name: str
    market: str
    currency: str
    purpose: str
    fy2026_decision: str
    purchase_class: str
    execution_priority: int
    step_id: str
    step_index: int
    shares: int | None
    shares_rule: str | None
    limit_price: float
    current_price: float | None
    price_date: str | None
    distance_to_limit_percent: float | None
    status: str
    purchase_flag: str
    actionability: str
    blocks: list[str]
    warnings: list[str]
    completion_deadline: str | None
    final_ceiling: float | None
    estimated_amount: float | None
    estimated_amount_jpy: float | None
    note: str | None
    generated_at: str


def load_strategy(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def strategy_tickers(strategy: dict[str, Any]) -> set[str]:
    return {
        str(order["ticker"])
        for account in strategy.get("accounts", {}).values()
        for order in account.get("orders", [])
    }


def strategy_watchlist(strategy: dict[str, Any]) -> list[dict[str, str]]:
    """Return unique Japanese tickers needed by the strategy price fetcher."""
    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    for account in strategy.get("accounts", {}).values():
        for order in account.get("orders", []):
            if str(order.get("market", "JP")).upper() != "JP":
                continue
            ticker = str(order["ticker"])
            if ticker in seen:
                continue
            seen.add(ticker)
            rows.append({
                "code": ticker,
                "name": str(order.get("name") or ticker),
                "volatility": str(order.get("volatility") or "medium"),
            })
    return rows


def merge_watchlists(*watchlists: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    merged: list[dict[str, str]] = []
    for watchlist in watchlists:
        for row in watchlist:
            code = str(row["code"])
            if code in seen:
                continue
            seen.add(code)
            merged.append(row)
    return merged


def suppress_generic_buy_for_strategy(decisions: list[Any], strategy: dict[str, Any]) -> list[Any]:
    """A strategy ticker may be alerted by the generic scanner, but never bought from it."""
    controlled = strategy_tickers(strategy)
    result: list[Any] = []
    for row in decisions:
        if row.ticker in controlled and (row.status in {"BUY", "BUY_CANDIDATE"} or row.actionability == "READY"):
            result.append(replace(
                row,
                status="BUY_CANDIDATE",
                actionability="STRATEGY_CONTROLLED",
                order_plan_status="DRAFT",
                limit_price=None,
                entry_2=None,
                entry_3=None,
                recommended_shares=None,
                estimated_amount=None,
                reasons=row.reasons + ["登録戦略銘柄。日次下落率は補助情報であり、固定指値・口座別監査を優先"],
            ))
        else:
            result.append(row)
    return result


def _env_number(key: str | None, env: Mapping[str, str]) -> float | None:
    if not key:
        return None
    raw = env.get(key)
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _fetch_us_prices(strategy: dict[str, Any]) -> dict[str, PriceRecord]:
    symbols = sorted({
        str(order["ticker"])
        for account in strategy.get("accounts", {}).values()
        for order in account.get("orders", [])
        if str(order.get("market", "JP")).upper() == "US"
    })
    if not symbols:
        return {}
    try:
        import yfinance as yf
    except Exception:
        return {}

    records: dict[str, PriceRecord] = {}
    for symbol in symbols:
        try:
            history = yf.Ticker(symbol).history(period="10d", auto_adjust=False)
            history = history.dropna(subset=["Close"])
            if len(history) < 2:
                continue
            latest = history.iloc[-1]
            previous = history.iloc[-2]
            index_value = history.index[-1]
            price_date = index_value.date() if hasattr(index_value, "date") else date.fromisoformat(str(index_value)[:10])
            records[symbol] = PriceRecord(
                symbol,
                symbol,
                float(latest["Close"]),
                float(previous["Close"]),
                price_date,
                "Yahoo Finance US",
                "medium",
            )
        except Exception:
            continue
    return records


def _shares_for_step(order: dict[str, Any], step: dict[str, Any]) -> tuple[int | None, str | None, list[str]]:
    if step.get("shares") is not None:
        return int(step["shares"]), None, []
    rule = str(step.get("shares_rule") or "") or None
    if not rule:
        return None, None, ["SHARES_UNAVAILABLE"]
    current = order.get("current_shares")
    target = order.get("target_total_shares")
    if current is None or target is None:
        return None, rule, ["HOLDING_DATA_REQUIRED"]
    remaining = max(0, int(target) - int(current))
    if rule == "不足株数の半分":
        return math.ceil(remaining / 2), rule, []
    if rule == "残り不足株数":
        return remaining, rule, []
    return None, rule, ["SHARES_RULE_UNSUPPORTED"]


def _fx_rate(strategy: dict[str, Any], currency: str, env: Mapping[str, str]) -> float | None:
    if currency == "JPY":
        return 1.0
    if currency != "USD":
        return None
    funding = strategy.get("funding", {})
    rate = _env_number(funding.get("usd_jpy_planning_rate_env"), env)
    if rate is not None:
        return rate
    default = funding.get("usd_jpy_planning_rate_default")
    try:
        return float(default) if default is not None else None
    except (TypeError, ValueError):
        return None


def _amounts_for_step(
    strategy: dict[str, Any],
    order: dict[str, Any],
    step: dict[str, Any],
    shares: int | None,
    env: Mapping[str, str],
) -> tuple[float | None, float | None, list[str]]:
    if shares is None:
        return None, None, []
    amount = round(shares * float(step["limit_price"]), 2)
    currency = str(order.get("currency", "JPY")).upper()
    fx = _fx_rate(strategy, currency, env)
    if fx is None:
        return amount, None, ["FX_PLANNING_RATE_REQUIRED"]
    return amount, round(amount * fx, 2), []


def _completed_spend(
    strategy: dict[str, Any],
    account: dict[str, Any],
    env: Mapping[str, str],
) -> float:
    total = 0.0
    for order in account.get("orders", []):
        completed = set(map(str, order.get("completed_step_ids", [])))
        for step in order.get("order_steps", []):
            if str(step.get("step_id")) not in completed:
                continue
            if step.get("executed_amount_jpy") is not None:
                total += float(step["executed_amount_jpy"])
                continue
            shares, _, _ = _shares_for_step(order, step)
            _, amount_jpy, _ = _amounts_for_step(strategy, order, step, shares, env)
            if amount_jpy is not None:
                total += amount_jpy
    return total


def _pending_index(order: dict[str, Any]) -> int | None:
    completed = set(map(str, order.get("completed_step_ids", [])))
    for index, step in enumerate(order.get("order_steps", [])):
        if str(step.get("step_id")) not in completed:
            return index
    return None


def evaluate_strategy(
    strategy: dict[str, Any],
    japanese_prices: list[PriceRecord],
    policy: dict[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> list[StrategyOrderSignal]:
    source = env if env is not None else os.environ
    price_map = {record.code: record for record in japanese_prices}
    price_map.update(_fetch_us_prices(strategy))
    now = datetime.now(timezone.utc).isoformat()
    signals: list[StrategyOrderSignal] = []
    strategy_active = str(strategy.get("status") or "").upper() == "ACTIVE"
    policy = policy or {}
    financial_assets = float(policy.get("current_financial_assets") or strategy.get("household_goal", {}).get("current_financial_assets_jpy") or 0)
    concentration_limit = float(strategy.get("household_goal", {}).get("max_single_ticker_weight_warning", 0.05))
    concentration_hard_limit = float(strategy.get("household_goal", {}).get("max_single_ticker_weight_hard", concentration_limit))
    registered_authority = str(strategy.get("purchase_authority", {}).get("mode") or "").upper() == "REGISTERED_STRATEGY_ONLY"

    household_cash = _env_number(strategy.get("funding", {}).get("available_investment_cash_jpy_env"), source)
    household_target = _env_number(strategy.get("funding", {}).get("target_investment_to_2027_03_jpy_env"), source)
    household_reserve = _env_number(strategy.get("funding", {}).get("reserve_after_execution_jpy_env"), source)
    account_spend = {
        name: _completed_spend(strategy, account, source)
        for name, account in strategy.get("accounts", {}).items()
    }
    household_spend = sum(account_spend.values())

    for account_name, account in strategy.get("accounts", {}).items():
        account_budget = _env_number(account.get("target_budget_jpy_env"), source)
        buying_power = _env_number(account.get("buying_power_jpy_env"), source)
        annual_stock_cap = _env_number(account.get("annual_stock_cap_jpy_env"), source)
        for order in account.get("orders", []):
            ticker = str(order["ticker"])
            market = str(order.get("market", "JP")).upper()
            currency = str(order.get("currency", "JPY")).upper()
            decision = str(order.get("fy2026_decision") or "UNREVIEWED")
            purchase_class = str(order.get("purchase_class") or "UNCLASSIFIED")
            priority = int(order.get("execution_priority", 99))
            record = price_map.get(ticker)
            current_price = float(record.close) if record else None
            price_date = record.price_date.isoformat() if record else None
            final_ceiling = float(order["final_ceiling"]) if order.get("final_ceiling") is not None else None
            completed = set(map(str, order.get("completed_step_ids", [])))
            pending_index = _pending_index(order)

            for step_index, step in enumerate(order.get("order_steps", []), start=1):
                step_id = str(step.get("step_id") or f"{ticker}-{step_index}")
                shares, shares_rule, share_blocks = _shares_for_step(order, step)
                amount, amount_jpy, amount_blocks = _amounts_for_step(strategy, order, step, shares, source)
                blocks = list(share_blocks) + list(amount_blocks)
                warnings: list[str] = []

                if step_id in completed:
                    status = "COMPLETED"
                    purchase_flag = "COMPLETED"
                    actionability = "DRAFT"
                elif pending_index is not None and step_index - 1 != pending_index:
                    status = "WAIT_PREVIOUS_STEP"
                    purchase_flag = "WAIT_PREVIOUS_STEP"
                    actionability = "DRAFT"
                elif decision not in ACTIVE_FY_DECISIONS:
                    status = decision
                    purchase_flag = decision
                    actionability = "DRAFT"
                else:
                    if not strategy_active:
                        blocks.append("STRATEGY_NOT_ACTIVE")
                    if account_budget is None:
                        blocks.append("ACCOUNT_BUDGET_SECRET_REQUIRED")
                    if buying_power is None or buying_power <= 0:
                        blocks.append("ACCOUNT_BUYING_POWER_REQUIRED")
                    if amount_jpy is not None:
                        next_account_spend = account_spend.get(account_name, 0.0) + amount_jpy
                        next_household_spend = household_spend + amount_jpy
                        if account_budget is not None and next_account_spend > account_budget:
                            blocks.append("ACCOUNT_STRATEGY_BUDGET_EXCEEDED")
                        if buying_power is not None and amount_jpy > buying_power:
                            blocks.append("ACCOUNT_BUYING_POWER_INSUFFICIENT")
                        if household_target is not None and next_household_spend > household_target:
                            blocks.append("HOUSEHOLD_TARGET_BUDGET_EXCEEDED")
                        if household_cash is not None and household_reserve is not None and next_household_spend > household_cash - household_reserve:
                            blocks.append("HOUSEHOLD_RESERVE_BREACH")
                        if annual_stock_cap is not None and next_account_spend > annual_stock_cap:
                            blocks.append("ACCOUNT_ANNUAL_STOCK_CAP_EXCEEDED")
                    if order.get("earnings_wait") and not order.get("earnings_reviewed_ok"):
                        blocks.append("EARNINGS_REVIEW_REQUIRED")
                    if order.get("conditional") and not order.get("condition_verified"):
                        blocks.append("ORDER_CONDITION_REVIEW_REQUIRED")
                    if step.get("condition") and not step.get("condition_verified"):
                        blocks.append("STEP_CONDITION_REVIEW_REQUIRED")
                    if order.get("benefit_verification_status") == "PARTIAL":
                        blocks.append("BENEFIT_RECHECK_REQUIRED")
                    if record is None:
                        blocks.append("PRICE_UNAVAILABLE")
                    elif (datetime.now(timezone.utc).date() - record.price_date).days > 5:
                        blocks.append("STALE_PRICE")

                    if financial_assets > 0 and current_price is not None:
                        target_shares = order.get("household_target_after_completion") or order.get("target_shares") or order.get("target_total_shares")
                        if target_shares is not None:
                            projected_weight = float(target_shares) * current_price / financial_assets
                            if projected_weight > concentration_hard_limit:
                                blocks.append(f"CONCENTRATION_HARD_LIMIT:{projected_weight:.2%}")
                            elif projected_weight > concentration_limit:
                                warnings.append(f"CONCENTRATION_WARNING:{projected_weight:.2%}")
                    elif registered_authority:
                        # A private registered strategy requires a complete,
                        # current household asset denominator. A partial tally
                        # cannot be used to clear this safety gate.
                        blocks.append("CONCENTRATION_AUDIT_REQUIRED")

                    if current_price is None:
                        distance = None
                        status = "DATA_ERROR"
                        purchase_flag = "DATA_ERROR"
                    else:
                        distance = round((current_price - float(step["limit_price"])) / float(step["limit_price"]) * 100, 2)
                        at_or_below = current_price <= float(step["limit_price"])
                        near = current_price <= float(step["limit_price"]) * 1.05
                        above_ceiling = final_ceiling is not None and current_price > final_ceiling
                        if above_ceiling:
                            status = "ABOVE_CEILING"
                            purchase_flag = "WAIT_PRICE"
                        elif at_or_below and blocks:
                            status = "BLOCKED_AT_LIMIT"
                            purchase_flag = "REVIEW_REQUIRED"
                        elif at_or_below:
                            status = "READY"
                            purchase_flag = "PURCHASE_READY"
                        elif near:
                            status = "NEAR"
                            purchase_flag = "WAIT_PRICE"
                        else:
                            status = "WAIT"
                            purchase_flag = "WAIT_PRICE"
                    actionability = "READY" if purchase_flag == "PURCHASE_READY" and not blocks else "DRAFT"

                if current_price is None:
                    distance = None
                elif 'distance' not in locals() or step_id in completed or (pending_index is not None and step_index - 1 != pending_index) or decision not in ACTIVE_FY_DECISIONS:
                    distance = round((current_price - float(step["limit_price"])) / float(step["limit_price"]) * 100, 2)

                note_parts = [
                    str(order.get("note") or "").strip(),
                    str(order.get("rule") or "").strip(),
                    str(order.get("concentration_warning") or "").strip(),
                ]
                signals.append(StrategyOrderSignal(
                    strategy_id=str(strategy["strategy_id"]),
                    account=account_name,
                    ticker=ticker,
                    name=str(order.get("name") or ticker),
                    market=market,
                    currency=currency,
                    purpose=str(order.get("purpose") or ""),
                    fy2026_decision=decision,
                    purchase_class=purchase_class,
                    execution_priority=priority,
                    step_id=step_id,
                    step_index=step_index,
                    shares=shares,
                    shares_rule=shares_rule,
                    limit_price=float(step["limit_price"]),
                    current_price=current_price,
                    price_date=price_date,
                    distance_to_limit_percent=distance,
                    status=status,
                    purchase_flag=purchase_flag,
                    actionability=actionability,
                    blocks=sorted(set(blocks)),
                    warnings=sorted(set(warnings)),
                    completion_deadline=order.get("completion_deadline"),
                    final_ceiling=final_ceiling,
                    estimated_amount=amount,
                    estimated_amount_jpy=amount_jpy,
                    note=" / ".join(part for part in note_parts if part) or None,
                    generated_at=now,
                ))
                if 'distance' in locals():
                    del distance

    max_daily_orders = max(1, int(source.get("HOS_STRATEGY_MAX_DAILY_ORDERS", strategy.get("purchase_authority", {}).get("max_household_orders_per_day", 1))))
    ready_indices = [index for index, signal in enumerate(signals) if signal.actionability == "READY"]
    ready_indices.sort(key=lambda index: (
        signals[index].execution_priority,
        signals[index].account,
        signals[index].distance_to_limit_percent if signals[index].distance_to_limit_percent is not None else 999,
        signals[index].ticker,
    ))
    for index in ready_indices[max_daily_orders:]:
        signal = signals[index]
        signals[index] = replace(
            signal,
            status="BLOCKED_DAILY_ORDER_LIMIT",
            purchase_flag="WAIT_DAILY_LIMIT",
            actionability="DRAFT",
            blocks=sorted(set(signal.blocks + ["DAILY_ORDER_LIMIT"])),
        )
    return signals


def write_strategy_output(signals: list[StrategyOrderSignal], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({
        "version": 2,
        "strategy_id": signals[0].strategy_id if signals else None,
        "signals": [asdict(signal) for signal in signals],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _money(value: float | None, currency: str) -> str:
    if value is None:
        return "未取得"
    symbol = "¥" if currency == "JPY" else "$"
    decimals = 0 if currency == "JPY" else 2
    return f"{symbol}{value:,.{decimals}f}"


def render_strategy_notification(signals: list[StrategyOrderSignal], limit: int = 5) -> str | None:
    relevant = [signal for signal in signals if signal.status in {"READY", "BLOCKED_AT_LIMIT", "NEAR", "ABOVE_CEILING", "BLOCKED_DAILY_ORDER_LIMIT"}]
    if not relevant:
        return None
    rank = {"READY": 0, "BLOCKED_AT_LIMIT": 1, "BLOCKED_DAILY_ORDER_LIMIT": 2, "NEAR": 3, "ABOVE_CEILING": 4}
    relevant.sort(key=lambda signal: (
        rank.get(signal.status, 9),
        signal.execution_priority,
        signal.account,
        signal.distance_to_limit_percent if signal.distance_to_limit_percent is not None else 999,
    ))
    lines = [
        f"🎯 登録戦略 {relevant[0].strategy_id}",
        "PURCHASE_READY以外は発注禁止｜固定指値・口座予算・決算監査を優先",
    ]
    labels = {
        "READY": "✅ PURCHASE_READY",
        "BLOCKED_AT_LIMIT": "🛑 指値到達・確認待ち",
        "BLOCKED_DAILY_ORDER_LIMIT": "⏭️ 本日の注文上限",
        "NEAR": "🟡 指値接近",
        "ABOVE_CEILING": "⏸️ 上限超過",
    }
    for signal in relevant[:limit]:
        shares = f"{signal.shares}株" if signal.shares is not None else (signal.shares_rule or "株数未確定")
        lines.append(
            f"{labels[signal.status]}｜{signal.account}｜{signal.ticker} {signal.name}｜"
            f"現在 {_money(signal.current_price, signal.currency)} / 指値 {_money(signal.limit_price, signal.currency)}｜{shares}"
        )
        if signal.blocks and signal.status in {"BLOCKED_AT_LIMIT", "BLOCKED_DAILY_ORDER_LIMIT"}:
            lines.append(f"   未確認: {', '.join(signal.blocks[:3])}")
    if len(relevant) > limit:
        lines.append(f"ほか {len(relevant) - limit}件は outputs/strategy_order_plan.json")
    return "\n".join(lines)
