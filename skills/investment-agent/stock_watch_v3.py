"""Stock Watch V3: next-session limit-order planning for HOS.

V3 deliberately separates a price signal from an executable order. It can
show a provisional limit from the latest close, but marks the order READY only
when price, verified facts, portfolio limits and private budget inputs all pass.
The module never sends an order to a broker.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from stock_analyzer import PriceRecord, percent_change

TRIGGERS = {"large": -2.0, "medium": -3.0, "high": -4.0}
DEFAULT_OFFSETS = {
    "large": [0.5, 1.2, 2.0],
    "medium": [1.0, 2.0, 3.5],
    "high": [1.5, 3.0, 5.0],
}
ALERT_STATUSES = {"WATCH", "BUY_CANDIDATE", "BUY", "REVIEW_REQUIRED", "DATA_ERROR"}


@dataclass(frozen=True)
class OrderDecision:
    ticker: str
    company_name: str
    role: str
    sector: str
    priority: int
    owned: bool
    status: str
    actionability: str
    order_plan_status: str
    close: float | None
    previous_close: float | None
    change_percent: float | None
    signal_threshold_percent: float | None
    distance_to_trigger_percent: float | None
    price_as_of: str | None
    fundamentals_as_of: str | None
    valuation_as_of: str | None
    news_as_of: str | None
    data_quality: str
    hard_blocks: list[str]
    reasons: list[str]
    execution_account: str
    order_type: str | None
    order_valid_for_session: str | None
    valid_until: str | None
    limit_price: float | None
    entry_2: float | None
    entry_3: float | None
    recommended_shares: int | None
    order_lot: int | None
    estimated_amount: float | None
    cancel_conditions: list[str]
    generated_at: str
    new_signal: bool = False
    status_changed: bool = False


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_universe(path: Path) -> list[dict[str, Any]]:
    return load_json(path).get("universe", [])


def fetcher_watchlist(universe: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"code": str(row["ticker"]), "name": row["company_name"], "volatility": row.get("volatility", "medium")}
        for row in universe
        if row.get("watch_enabled", True)
    ]


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _boolean(value: Any, default: bool) -> bool:
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def apply_private_budget(policy: dict[str, Any], env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Overlay private account amounts without committing them to the repo."""
    source = env if env is not None else os.environ
    result = json.loads(json.dumps(policy))
    result["execution_account"] = source.get("HOS_EXECUTION_ACCOUNT") or result.get("execution_account") or "maho"
    keys = {
        "HOS_MAHO_BUYING_POWER_JPY": "current_cash_balance",
        "HOS_MONTHLY_STOCK_BUDGET_REMAINING_JPY": "monthly_individual_stock_budget",
        "HOS_ANNUAL_STOCK_BUDGET_REMAINING_JPY": "annual_individual_stock_budget",
    }
    for env_key, policy_key in keys.items():
        if source.get(env_key) not in (None, ""):
            result[policy_key] = _number(source[env_key])
    planning = result.setdefault("order_planning", {})
    if source.get("HOS_MAX_SINGLE_ORDER_JPY") not in (None, ""):
        planning["max_single_order_amount"] = _number(source["HOS_MAX_SINGLE_ORDER_JPY"])
    planning["allow_odd_lot"] = _boolean(source.get("HOS_ALLOW_ODD_LOT"), bool(planning.get("allow_odd_lot", True)))
    return result


def _standard_tick(price: float) -> float:
    """Conservative TSE 'other issues' tick; valid for finer TOPIX500 tables too."""
    bands = [
        (3_000, 1), (5_000, 5), (30_000, 10), (50_000, 50),
        (300_000, 100), (500_000, 500), (3_000_000, 1_000),
        (5_000_000, 5_000), (30_000_000, 10_000),
        (50_000_000, 50_000), (float("inf"), 100_000),
    ]
    return float(next(tick for ceiling, tick in bands if price <= ceiling))


def round_limit_down(raw: float) -> float:
    tick = _standard_tick(raw)
    return float(max(tick, math.floor(raw / tick) * tick))


def entry_levels(close: float | None, volatility: str, policy: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    if close is None:
        return None, None, None
    configured = policy.get("order_planning", {}).get("limit_offsets_percent", {}).get(volatility)
    offsets = configured if isinstance(configured, list) and len(configured) == 3 else DEFAULT_OFFSETS.get(volatility, DEFAULT_OFFSETS["medium"])
    levels = [round_limit_down(close * (1 - float(offset) / 100)) for offset in offsets]
    return levels[0], levels[1], levels[2]


def _verified_date(row: dict[str, Any], date_key: str, verified_key: str) -> str | None:
    value = row.get(date_key)
    return str(value) if value and row.get(verified_key) is True else None


def _portfolio_values(universe: list[dict[str, Any]], prices: dict[str, PriceRecord], policy: dict[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    total = float(policy.get("current_financial_assets") or 0)
    by_ticker: dict[str, float] = {}
    by_sector: dict[str, float] = {}
    if total <= 0:
        return by_ticker, by_sector
    for row in universe:
        shares = row.get("current_shares")
        price = prices.get(str(row["ticker"]))
        if shares is None or price is None:
            continue
        weight = float(shares) * price.close / total
        by_ticker[str(row["ticker"])] = weight
        sector = row.get("sector", "未分類")
        by_sector[sector] = by_sector.get(sector, 0.0) + weight
    return by_ticker, by_sector


def _order_budget(policy: dict[str, Any]) -> float | None:
    values = [
        _number(policy.get("current_cash_balance")),
        _number(policy.get("monthly_individual_stock_budget")),
        _number(policy.get("annual_individual_stock_budget")),
        _number(policy.get("order_planning", {}).get("max_single_order_amount")),
    ]
    return min(values) if values and all(value is not None for value in values) else None


def _first_tranche(limit_price: float | None, row: dict[str, Any], policy: dict[str, Any]) -> tuple[int | None, int | None, float | None]:
    budget = _order_budget(policy)
    if limit_price is None or budget is None:
        return None, None, None
    planning = policy.get("order_planning", {})
    allocations = planning.get("stage_allocations", [0.4, 0.3, 0.3])
    ratio = max(0.0, min(float(allocations[0]), 1.0)) if allocations else 0.4
    odd_lot = bool(planning.get("allow_odd_lot", True))
    lot = int(row.get("minimum_order_lot", 1) if odd_lot else row.get("preferred_order_lot", 100))
    lot = max(1, lot)
    max_orders = max(1, int(planning.get("max_daily_orders", 1)))
    shares = math.floor((budget * ratio / max_orders) / limit_price / lot) * lot
    if shares < lot:
        return 0, lot, 0.0
    return shares, lot, round(shares * limit_price, 2)


def _actionability(blocks: set[str], status: str) -> str:
    if status == "DATA_ERROR" or blocks & {"PRICE_UNAVAILABLE", "STALE_DATA"}:
        return "DATA_ERROR"
    if "CONFIGURATION_ERROR" in blocks:
        return "WATCH_ONLY"
    if blocks & {"SECTOR_LIMIT_EXCEEDED", "SINGLE_STOCK_LIMIT_EXCEEDED"}:
        return "POSITION_LIMIT"
    facts = bool(blocks & {"FUNDAMENTALS_UNAVAILABLE", "VALUATION_UNAVAILABLE", "NEWS_UNAVAILABLE"})
    budget = "PORTFOLIO_DATA_MISSING" in blocks
    if facts and budget:
        return "BUDGET_AND_FACTS_REQUIRED"
    if facts:
        return "FACTS_REQUIRED"
    if budget:
        return "BUDGET_REQUIRED"
    if "BUDGET_TOO_SMALL" in blocks:
        return "BUDGET_TOO_SMALL"
    return "READY" if status == "BUY" else "WAIT"


def decide(
    universe: list[dict[str, Any]],
    prices: list[PriceRecord],
    policy: dict[str, Any],
    topix_change_percent: float | None,
    trade_date: date,
    order_session: date,
) -> list[OrderDecision]:
    now = datetime.now(timezone.utc).isoformat()
    price_map = {price.code: price for price in prices}
    ticker_weights, sector_weights = _portfolio_values(universe, price_map, policy)
    near_margin = float(policy.get("order_planning", {}).get("near_trigger_margin_percent", 1.0))
    strict_facts = bool(policy.get("order_planning", {}).get("strict_fact_gate", True))
    decisions: list[OrderDecision] = []

    for row in universe:
        if not row.get("watch_enabled", True):
            continue
        ticker = str(row["ticker"])
        price = price_map.get(ticker)
        volatility = str(row.get("volatility", "medium"))
        trigger = TRIGGERS.get(volatility, -3.0)
        blocks: set[str] = set()
        reasons: list[str] = []
        if price is None:
            close = previous = change = distance = None
            price_as_of = None
            status = "DATA_ERROR"
            blocks.add("PRICE_UNAVAILABLE")
        else:
            close, previous = price.close, price.previous_close
            change = round(percent_change(close, previous), 2)
            distance = round(max(0.0, change - trigger), 2)
            price_as_of = price.price_date.isoformat()
            if price.price_date != trade_date:
                blocks.add("STALE_DATA")
            reasons.append(f"前日比 {change:.2f}% / 発火基準 {trigger:.1f}%")
            if change <= -8:
                status = "REVIEW_REQUIRED"
                reasons.append("8%以上の急落。理由確認まで購入禁止")
            elif change <= trigger:
                status = "BUY_CANDIDATE"
                reasons.append("価格条件に到達。総合BUYではない")
            elif change <= trigger + near_margin:
                status = "WATCH"
                reasons.append(f"価格条件まで {distance:.2f}ポイント")
            elif row.get("owned"):
                status = "HOLD"
            else:
                status = "NO_ALERT"

        fundamentals_as_of = _verified_date(row, "fundamentals_as_of", "fundamentals_verified")
        valuation_as_of = _verified_date(row, "valuation_as_of", "valuation_verified")
        news_as_of = _verified_date(row, "news_as_of", "news_verified")
        if not fundamentals_as_of:
            blocks.add("FUNDAMENTALS_UNAVAILABLE")
        if not valuation_as_of:
            blocks.add("VALUATION_UNAVAILABLE")
        if not news_as_of:
            blocks.add("NEWS_UNAVAILABLE")
        if _order_budget(policy) is None:
            blocks.add("PORTFOLIO_DATA_MISSING")
        if not row.get("buy_enabled", True):
            blocks.add("CONFIGURATION_ERROR")
        sector = row.get("sector", "未分類")
        sector_max = policy.get("max_sector_weights", {}).get(sector)
        if sector_max is not None and sector_weights.get(sector, 0.0) >= float(sector_max):
            blocks.add("SECTOR_LIMIT_EXCEEDED")
        ticker_max = float(row.get("max_weight_percent") or policy.get("max_single_stock_weight", 0.08))
        if ticker_weights.get(ticker, 0.0) >= ticker_max:
            blocks.add("SINGLE_STOCK_LIMIT_EXCEEDED")

        limit_1, limit_2, limit_3 = entry_levels(close, volatility, policy)
        shares, lot, amount = _first_tranche(limit_1, row, policy)
        if shares == 0 and _order_budget(policy) is not None:
            blocks.add("BUDGET_TOO_SMALL")
        fact_blocks = blocks & {"FUNDAMENTALS_UNAVAILABLE", "VALUATION_UNAVAILABLE", "NEWS_UNAVAILABLE"}
        non_fact_blocks = blocks - fact_blocks
        ready = (
            status == "BUY_CANDIDATE"
            and not non_fact_blocks
            and (not strict_facts or not fact_blocks)
            and shares is not None and shares > 0
        )
        if ready:
            status = "BUY"
        actionability = _actionability(blocks, status)
        deadline = f"{order_session.isoformat()}T15:30:00+09:00" if limit_1 is not None else None
        decisions.append(OrderDecision(
            ticker=ticker,
            company_name=row["company_name"],
            role=row["role"],
            sector=sector,
            priority=int(row.get("priority", 3)),
            owned=bool(row.get("owned")),
            status=status,
            actionability=actionability,
            order_plan_status="READY" if actionability == "READY" else "DRAFT",
            close=close,
            previous_close=previous,
            change_percent=change,
            signal_threshold_percent=trigger,
            distance_to_trigger_percent=distance,
            price_as_of=price_as_of,
            fundamentals_as_of=fundamentals_as_of,
            valuation_as_of=valuation_as_of,
            news_as_of=news_as_of,
            data_quality="ok" if not blocks else "partial",
            hard_blocks=sorted(blocks),
            reasons=reasons,
            execution_account=str(policy.get("execution_account") or "maho"),
            order_type="指値（当日限り）" if limit_1 is not None else None,
            order_valid_for_session=order_session.isoformat() if limit_1 is not None else None,
            valid_until=deadline,
            limit_price=limit_1,
            entry_2=limit_2,
            entry_3=limit_3,
            recommended_shares=shares,
            order_lot=lot,
            estimated_amount=amount,
            cancel_conditions=[
                "決算・適時開示・ニュースで投資前提が崩れた場合",
                f"寄前気配が前日終値比+{float(policy.get('order_planning', {}).get('cancel_if_open_gap_up_percent', 3.0)):.1f}%以上の場合",
                "株価対象日がずれた場合",
                "まほ口座の買付余力または保有上限を超える場合",
                "期限を過ぎた場合は翌営業日の終値で再計算",
            ],
            generated_at=now,
        ))

    max_orders = max(1, int(policy.get("order_planning", {}).get("max_daily_orders", 1)))
    ready_indices = [index for index, row in enumerate(decisions) if row.actionability == "READY"]
    ready_indices.sort(key=lambda index: (
        decisions[index].priority,
        decisions[index].change_percent if decisions[index].change_percent is not None else 999.0,
        decisions[index].ticker,
    ))
    for index in ready_indices[max_orders:]:
        row = decisions[index]
        decisions[index] = replace(
            row,
            status="BUY_CANDIDATE",
            actionability="DAILY_ORDER_LIMIT",
            order_plan_status="DRAFT",
            reasons=row.reasons + [f"1日最大{max_orders}注文のため次点待機"],
        )
    return decisions


def dedupe(decisions: list[OrderDecision], state_path: Path, price_threshold: float = 1.0) -> list[OrderDecision]:
    old: dict[str, Any] = {}
    if state_path.exists():
        try:
            old = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            old = {}
    alerts: list[OrderDecision] = []
    new: dict[str, Any] = {}
    for row in decisions:
        previous = old.get(row.ticker, {})
        prior_close = previous.get("close")
        status_changed = previous.get("status") not in (None, row.status)
        action_changed = previous.get("actionability") not in (None, row.actionability)
        price_changed = row.close is not None and prior_close not in (None, 0) and abs((row.close - float(prior_close)) / float(prior_close) * 100) >= price_threshold
        changed = not previous or status_changed or action_changed or price_changed or previous.get("limit_price") != row.limit_price
        if row.status in ALERT_STATUSES and changed:
            alerts.append(replace(row, new_signal=not bool(previous), status_changed=status_changed))
        new[row.ticker] = {
            "status": row.status, "actionability": row.actionability,
            "close": row.close, "limit_price": row.limit_price,
        }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
    return alerts


def watchlist_review(universe: list[dict[str, Any]]) -> dict[str, Any]:
    enabled = [row for row in universe if row.get("watch_enabled", True)]
    daily_core = [row for row in enabled if row.get("buy_enabled", True) and int(row.get("priority", 3)) == 1]
    secondary = [row for row in enabled if row.get("buy_enabled", True) and int(row.get("priority", 3)) == 2]
    monitor = [row for row in enabled if not row.get("buy_enabled", True) or int(row.get("priority", 3)) >= 3]
    sector_counts: dict[str, int] = {}
    for row in enabled:
        sector = row.get("sector", "未分類")
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
    warnings: list[str] = []
    if len(enabled) > 30:
        warnings.append("40銘柄は調査用として維持し、日次注文候補は優先度1へ絞る")
    finance = sector_counts.get("商社・金融・リース", 0)
    if enabled and finance / len(enabled) >= 0.25:
        warnings.append("商社・金融・リースが25%以上。銘柄数ではなく投資額上限で管理する")
    return {
        "version": 1,
        "watch_enabled_count": len(enabled),
        "daily_core_count": len(daily_core),
        "secondary_count": len(secondary),
        "monitor_only_count": len(monitor),
        "daily_core_tickers": [str(row["ticker"]) for row in daily_core],
        "secondary_tickers": [str(row["ticker"]) for row in secondary],
        "monitor_only_tickers": [str(row["ticker"]) for row in monitor],
        "sector_counts": sector_counts,
        "warnings": warnings,
        "rule": "優先度1を日次主力、優先度2を補完、優先度3-4/WATCH_ONLYを急変・異常監視とする",
    }


def write_outputs(decisions: list[OrderDecision], universe: list[dict[str, Any]], policy: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir.joinpath("stock_watch_decisions.json").write_text(
        json.dumps({"version": 3, "decisions": [asdict(row) for row in decisions]}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    statuses: dict[str, int] = {}
    actions: dict[str, int] = {}
    for row in decisions:
        statuses[row.status] = statuses.get(row.status, 0) + 1
        actions[row.actionability] = actions.get(row.actionability, 0) + 1
    output_dir.joinpath("stock_watch_summary.json").write_text(
        json.dumps({"version": 3, "status_counts": statuses, "actionability_counts": actions, "generated_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    output_dir.joinpath("watchlist_review.json").write_text(
        json.dumps(watchlist_review(universe), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    output_dir.joinpath("portfolio_goal_progress.json").write_text(
        json.dumps({
            "current_financial_assets": policy.get("current_financial_assets"),
            "target_financial_assets": policy.get("target_asset_value_at_age_60"),
            "target_annual_dividend": policy.get("target_annual_dividend"),
            "execution_account": policy.get("execution_account"),
            "missing_private_inputs": [key for key in [
                "current_cash_balance", "monthly_individual_stock_budget", "annual_individual_stock_budget"
            ] if policy.get(key) is None],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _yen(value: float | None) -> str:
    return "未計算" if value is None else f"¥{value:,.0f}"


def _label(actionability: str) -> str:
    return {
        "READY": "✅ 発注条件クリア",
        "BUDGET_REQUIRED": "🛑 まほ口座予算が未設定",
        "FACTS_REQUIRED": "🛑 決算・評価・ニュース未確認",
        "BUDGET_AND_FACTS_REQUIRED": "🛑 予算と決算・評価・ニュース未確認",
        "POSITION_LIMIT": "🛑 保有上限に抵触",
        "DAILY_ORDER_LIMIT": "⏭️ 本日の注文上限により次点待機",
        "BUDGET_TOO_SMALL": "🛑 1回目予算が最小株数未満",
        "WATCH_ONLY": "👀 監視専用",
        "DATA_ERROR": "⚠️ データ異常",
        "WAIT": "⏳ 待機",
    }.get(actionability, actionability)


def render_notification(
    alerts: list[OrderDecision],
    all_decisions: list[OrderDecision],
    trade_date: date,
    mode_label: str,
    notify_no_alert: bool = False,
) -> str | None:
    important = [row for row in alerts if row.priority <= 2 or row.status in {"REVIEW_REQUIRED", "DATA_ERROR"}]
    if not important and not notify_no_alert:
        return None
    order_session = next((row.order_valid_for_session for row in important if row.order_valid_for_session), None)
    date_label = f"{trade_date.strftime('%m/%d')}終値"
    if order_session:
        date_label += f" → {order_session[5:].replace('-', '/')}注文"
    lines = [
        f"📊 株式監視V3｜{date_label}｜{mode_label}",
        f"発注可 {sum(row.actionability == 'READY' for row in all_decisions)}｜要確認 {sum(row.status in {'BUY_CANDIDATE', 'REVIEW_REQUIRED'} for row in all_decisions)}｜接近 {sum(row.status == 'WATCH' for row in all_decisions)}｜異常 {sum(row.status == 'DATA_ERROR' for row in all_decisions)}",
        f"口座: {next((row.execution_account for row in all_decisions), 'maho')}｜成行禁止｜期限超過は再計算",
    ]
    rank = {"READY": 0, "BUDGET_REQUIRED": 1, "FACTS_REQUIRED": 1, "BUDGET_AND_FACTS_REQUIRED": 1, "POSITION_LIMIT": 2, "DAILY_ORDER_LIMIT": 2, "WAIT": 3, "WATCH_ONLY": 4, "DATA_ERROR": 5}
    important.sort(key=lambda row: (rank.get(row.actionability, 9), row.priority, row.change_percent if row.change_percent is not None else 999))
    for row in important[:5]:
        prefix = "NEW " if row.new_signal else "変更 " if row.status_changed else ""
        if row.status == "WATCH":
            lines.append(f"🟡 {prefix}{row.ticker} {row.company_name}｜{_yen(row.close)} ({row.change_percent:+.2f}%)｜発火まで {row.distance_to_trigger_percent:.2f}pt")
        elif row.status in {"BUY_CANDIDATE", "BUY"}:
            shares = "数量未計算" if row.recommended_shares is None else f"{row.recommended_shares}株"
            deadline = row.valid_until[:10].replace("-", "/") + " 15:30" if row.valid_until else "期限未計算"
            plan = "指値" if row.order_plan_status == "READY" else "仮指値"
            lines += [
                f"🟠 {prefix}{row.ticker} {row.company_name}｜終値 {_yen(row.close)} ({row.change_percent:+.2f}%)",
                f"   {_label(row.actionability)}",
                f"   {plan} {_yen(row.limit_price)}以下｜{shares}｜{deadline}まで",
            ]
        elif row.status == "REVIEW_REQUIRED":
            lines.append(f"⚠️ {prefix}{row.ticker} {row.company_name}｜急落理由確認まで発注禁止｜終値 {_yen(row.close)}")
        else:
            lines.append(f"⚠️ {prefix}{row.ticker} {row.company_name}｜データ取得異常｜発注禁止")
    if len(important) > 5:
        lines.append(f"ほか {len(important) - 5}件はJSON/GitHub Summary参照")
    lines.append("結論: まほ口座用の注文案。READY以外は発注せず、朝に決算・適時開示・ニュースを確認。HOSは実発注しません。")
    return "\n".join(lines)[:1_980]
