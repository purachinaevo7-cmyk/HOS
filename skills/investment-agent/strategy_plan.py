"""Account-specific order plan support for HOS Stock Watch V3.

The public repository stores the strategy and fixed order rules, while exact cash
balances and account budgets remain in GitHub Actions secrets. The planner never
sends orders. It only emits READY when price, account funding and all explicit
review gates are satisfied.
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


@dataclass(frozen=True)
class StrategyOrderSignal:
    strategy_id: str
    account: str
    ticker: str
    name: str
    market: str
    currency: str
    purpose: str
    step_index: int
    shares: int | None
    shares_rule: str | None
    limit_price: float
    current_price: float | None
    price_date: str | None
    distance_to_limit_percent: float | None
    status: str
    actionability: str
    blocks: list[str]
    completion_deadline: str | None
    final_ceiling: float | None
    estimated_amount: float | None
    note: str | None
    generated_at: str


def load_strategy(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def evaluate_strategy(
    strategy: dict[str, Any],
    japanese_prices: list[PriceRecord],
    env: Mapping[str, str] | None = None,
) -> list[StrategyOrderSignal]:
    source = env if env is not None else os.environ
    price_map = {record.code: record for record in japanese_prices}
    price_map.update(_fetch_us_prices(strategy))
    now = datetime.now(timezone.utc).isoformat()
    signals: list[StrategyOrderSignal] = []
    strategy_needs_review = str(strategy.get("status") or "").upper() != "ACTIVE"

    for account_name, account in strategy.get("accounts", {}).items():
        account_budget = _env_number(account.get("target_budget_jpy_env"), source)
        buying_power = _env_number(account.get("buying_power_jpy_env"), source)
        for order in account.get("orders", []):
            ticker = str(order["ticker"])
            market = str(order.get("market", "JP")).upper()
            currency = str(order.get("currency", "JPY")).upper()
            record = price_map.get(ticker)
            current_price = float(record.close) if record else None
            price_date = record.price_date.isoformat() if record else None
            final_ceiling = float(order["final_ceiling"]) if order.get("final_ceiling") is not None else None

            for step_index, step in enumerate(order.get("order_steps", []), start=1):
                limit_price = float(step["limit_price"])
                shares, shares_rule, share_blocks = _shares_for_step(order, step)
                estimated_amount = round(shares * limit_price, 2) if shares is not None else None
                blocks = list(share_blocks)

                if strategy_needs_review:
                    blocks.append("STRATEGY_REVALIDATION_REQUIRED")
                if account_budget is None:
                    blocks.append("ACCOUNT_BUDGET_SECRET_REQUIRED")
                if buying_power is None or buying_power <= 0:
                    blocks.append("ACCOUNT_BUYING_POWER_REQUIRED")
                if currency == "JPY" and estimated_amount is not None:
                    if account_budget is not None and estimated_amount > account_budget:
                        blocks.append("ACCOUNT_STRATEGY_BUDGET_INSUFFICIENT")
                    if buying_power is not None and estimated_amount > buying_power:
                        blocks.append("ACCOUNT_BUYING_POWER_INSUFFICIENT")
                if order.get("earnings_wait") and not order.get("earnings_reviewed_ok"):
                    blocks.append("EARNINGS_REVIEW_REQUIRED")
                if order.get("conditional") and not order.get("condition_verified"):
                    blocks.append("ORDER_CONDITION_REVIEW_REQUIRED")
                if step.get("condition") and not step.get("condition_verified"):
                    blocks.append("STEP_CONDITION_REVIEW_REQUIRED")
                if record is None:
                    blocks.append("PRICE_UNAVAILABLE")

                if current_price is None:
                    distance = None
                    status = "DATA_ERROR"
                else:
                    distance = round((current_price - limit_price) / limit_price * 100, 2)
                    at_or_below = current_price <= limit_price
                    near = current_price <= limit_price * 1.05
                    above_ceiling = final_ceiling is not None and current_price > final_ceiling
                    if above_ceiling:
                        status = "ABOVE_CEILING"
                    elif at_or_below and blocks:
                        status = "BLOCKED_AT_LIMIT"
                    elif at_or_below:
                        status = "READY"
                    elif near:
                        status = "NEAR"
                    else:
                        status = "WAIT"

                actionability = "READY" if status == "READY" and not blocks else "DRAFT"
                note_parts = [str(order.get("note") or "").strip(), str(order.get("rule") or "").strip()]
                note = " / ".join(part for part in note_parts if part) or None
                signals.append(StrategyOrderSignal(
                    strategy_id=str(strategy["strategy_id"]),
                    account=account_name,
                    ticker=ticker,
                    name=str(order.get("name") or ticker),
                    market=market,
                    currency=currency,
                    purpose=str(order.get("purpose") or ""),
                    step_index=step_index,
                    shares=shares,
                    shares_rule=shares_rule,
                    limit_price=limit_price,
                    current_price=current_price,
                    price_date=price_date,
                    distance_to_limit_percent=distance,
                    status=status,
                    actionability=actionability,
                    blocks=sorted(set(blocks)),
                    completion_deadline=order.get("completion_deadline"),
                    final_ceiling=final_ceiling,
                    estimated_amount=estimated_amount,
                    note=note,
                    generated_at=now,
                ))

    max_daily_orders = max(1, int(source.get("HOS_STRATEGY_MAX_DAILY_ORDERS", "1")))
    ready_indices = [index for index, signal in enumerate(signals) if signal.actionability == "READY"]
    ready_indices.sort(key=lambda index: (
        1 if signals[index].account == "hiro" else 0,
        signals[index].distance_to_limit_percent if signals[index].distance_to_limit_percent is not None else 999,
        signals[index].ticker,
        signals[index].step_index,
    ))
    for index in ready_indices[max_daily_orders:]:
        signal = signals[index]
        signals[index] = replace(
            signal,
            status="BLOCKED_DAILY_ORDER_LIMIT",
            actionability="DRAFT",
            blocks=sorted(set(signal.blocks + ["DAILY_ORDER_LIMIT"])),
        )
    return signals


def write_strategy_output(signals: list[StrategyOrderSignal], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({
        "version": 1,
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


def render_strategy_notification(signals: list[StrategyOrderSignal], limit: int = 4) -> str | None:
    relevant = [signal for signal in signals if signal.status in {"READY", "BLOCKED_AT_LIMIT", "NEAR", "ABOVE_CEILING", "BLOCKED_DAILY_ORDER_LIMIT"}]
    if not relevant:
        return None
    rank = {"READY": 0, "BLOCKED_AT_LIMIT": 1, "BLOCKED_DAILY_ORDER_LIMIT": 2, "NEAR": 3, "ABOVE_CEILING": 4}
    relevant.sort(key=lambda signal: (
        rank.get(signal.status, 9),
        signal.account,
        signal.distance_to_limit_percent if signal.distance_to_limit_percent is not None else 999,
        signal.ticker,
        signal.step_index,
    ))
    lines = [
        f"🎯 登録戦略 {relevant[0].strategy_id}",
        "READY以外は発注禁止｜固定指値は追いかけず再検証",
    ]
    labels = {
        "READY": "✅ 指値条件到達",
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
