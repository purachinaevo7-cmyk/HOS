"""Discord rendering for HOS Stock Watch.

This module has two deliberately different renderers: the private report sent
to Discord and a value-free public summary for CI logs and GitHub summaries.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Iterable, Mapping

from progress_notification import build_progress_snapshot


ACTIVE_FY_DECISIONS = {"BUY_2026_CORE", "BUY_2026_CONDITIONAL"}
RELEVANT_STATUSES = {"READY", "BLOCKED_AT_LIMIT", "BLOCKED_DAILY_ORDER_LIMIT", "NEAR", "ABOVE_CEILING"}
STATUS_LABELS = {
    "READY": "✅ 購入可",
    "BLOCKED_AT_LIMIT": "🛑 指値到達",
    "BLOCKED_DAILY_ORDER_LIMIT": "⏭️ 注文上限",
    "NEAR": "🟡 指値接近",
    "ABOVE_CEILING": "⏸️ 上限超過",
}
STATUS_RANK = {"READY": 0, "BLOCKED_AT_LIMIT": 1, "BLOCKED_DAILY_ORDER_LIMIT": 2, "NEAR": 3, "ABOVE_CEILING": 4}
BLOCK_LABELS = {
    "ACCOUNT_BUDGET_SECRET_REQUIRED": "口座予算未設定",
    "ACCOUNT_BUYING_POWER_REQUIRED": "買付余力未設定",
    "ACCOUNT_STRATEGY_BUDGET_EXCEEDED": "口座予算超過",
    "ACCOUNT_BUYING_POWER_INSUFFICIENT": "買付余力不足",
    "ACCOUNT_ANNUAL_STOCK_CAP_EXCEEDED": "年間株式上限超過",
    "HOUSEHOLD_TARGET_BUDGET_EXCEEDED": "年度投資枠超過",
    "HOUSEHOLD_RESERVE_BREACH": "生活防衛資金不足",
    "EARNINGS_REVIEW_REQUIRED": "決算確認",
    "ORDER_CONDITION_REVIEW_REQUIRED": "購入条件確認",
    "STEP_CONDITION_REVIEW_REQUIRED": "段階条件確認",
    "BENEFIT_RECHECK_REQUIRED": "優待再確認",
    "PRICE_UNAVAILABLE": "株価未取得",
    "STALE_PRICE": "株価が古い",
    "DAILY_ORDER_LIMIT": "1日注文上限",
    "HOLDING_DATA_REQUIRED": "保有株数未設定",
    "SHARES_UNAVAILABLE": "株数未設定",
    "SHARES_RULE_UNSUPPORTED": "株数ルール未対応",
    "FX_PLANNING_RATE_REQUIRED": "為替レート未設定",
    "STRATEGY_NOT_ACTIVE": "戦略停止中",
    "EXECUTION_RECONCILIATION_REQUIRED": "約定照合が必要",
    "ACCOUNT_TRANSFER_REQUIRED": "補完資金の入金待ち",
    "ACCOUNT_TAXABLE_GIFTS_YTD_REQUIRED": "資金移管累計未設定",
    "GIFT_TAX_REVIEW_REQUIRED": "資金移管の税務確認",
    "CONCENTRATION_AUDIT_REQUIRED": "世帯集中度監査待ち",
    "CONCENTRATION_HARD_LIMIT": "世帯集中度上限超過",
}
USER_ACTION_BLOCKS = {
    "ACCOUNT_BUDGET_SECRET_REQUIRED",
    "ACCOUNT_BUYING_POWER_REQUIRED",
    "ACCOUNT_BUYING_POWER_INSUFFICIENT",
    "ACCOUNT_TRANSFER_REQUIRED",
    "ACCOUNT_TAXABLE_GIFTS_YTD_REQUIRED",
    "GIFT_TAX_REVIEW_REQUIRED",
}


def _money(value: float | None, currency: str = "JPY") -> str:
    if value is None:
        return "未取得"
    return f"${value:,.2f}" if currency == "USD" else f"¥{value:,.0f}"


def _compact_yen(value: float | None) -> str:
    if value is None:
        return "未設定"
    if value >= 100_000_000 and value % 100_000_000 == 0:
        return f"{value / 100_000_000:,.0f}億円"
    if value >= 10_000:
        return f"{value / 10_000:,.1f}万円".replace(".0万円", "万円")
    return f"{value:,.0f}円"


def _percent(current: float | None, target: float | None) -> str | None:
    if current is None or target is None or target <= 0:
        return None
    return f"{current / target * 100:.1f}%"


def _shares(signal: Any) -> str:
    shares = getattr(signal, "shares", None)
    return f"{shares}株" if shares is not None else str(getattr(signal, "shares_rule", None) or "株数未確定")


def _active_account_counts(signals: Iterable[Any]) -> dict[str, int]:
    tickers: dict[str, set[str]] = defaultdict(set)
    for signal in signals:
        if getattr(signal, "fy2026_decision", None) not in ACTIVE_FY_DECISIONS:
            continue
        account = str(getattr(signal, "account", "") or "")
        ticker = str(getattr(signal, "ticker", "") or "")
        if account and ticker:
            tickers[account].add(ticker)
    return {account: len(items) for account, items in tickers.items()}


def _unique_relevant(signals: Iterable[Any], account: str) -> list[Any]:
    rows = [row for row in signals if getattr(row, "account", None) == account and getattr(row, "status", None) in RELEVANT_STATUSES]
    rows.sort(key=lambda row: (STATUS_RANK.get(getattr(row, "status", ""), 9), int(getattr(row, "execution_priority", 99)), float(getattr(row, "distance_to_limit_percent", 999) or 999), int(getattr(row, "step_index", 99))))
    unique: dict[str, Any] = {}
    for row in rows:
        unique.setdefault(str(getattr(row, "ticker", "")), row)
    return list(unique.values())


def _translated_blocks(blocks: Iterable[str]) -> list[str]:
    translated: list[str] = []
    for block in blocks:
        label = BLOCK_LABELS.get(str(block).split(":", 1)[0], "HOS監査待ち")
        if label not in translated:
            translated.append(label)
    return translated


def _strategy_summary(signals: list[Any], account_labels: Mapping[str, str], per_account_limit: int = 3) -> list[str]:
    counts = _active_account_counts(signals)
    lines: list[str] = []
    for account in sorted(counts):
        lines.append(f"【{account_labels.get(account, account)}】")
        relevant = _unique_relevant(signals, account)
        if not relevant:
            lines.append(f"・該当なし（監視 {counts[account]}銘柄）")
            continue
        for signal in relevant[:per_account_limit]:
            status = str(getattr(signal, "status", ""))
            lines.append(f"{STATUS_LABELS.get(status, '・確認')} {getattr(signal, 'ticker', '')} {getattr(signal, 'name', '')}｜{_money(getattr(signal, 'current_price', None), getattr(signal, 'currency', 'JPY'))} → 指値{_money(getattr(signal, 'limit_price', None), getattr(signal, 'currency', 'JPY'))}｜{_shares(signal)}")
            raw_blocks = [str(block) for block in (getattr(signal, "blocks", []) or [])]
            hos_blocks = _translated_blocks(block for block in raw_blocks if block not in USER_ACTION_BLOCKS)
            user_blocks = _translated_blocks(block for block in raw_blocks if block in USER_ACTION_BLOCKS)
            if hos_blocks:
                lines.append(f"   HOS側：{'・'.join(hos_blocks[:3])}")
            if user_blocks:
                lines.append(f"   ユーザー側：{'・'.join(user_blocks[:3])}")
        if len(relevant) > per_account_limit:
            lines.append(f"・ほか {len(relevant) - per_account_limit}件")
    return lines


def _progress_lines(policy: Mapping[str, Any], strategy: Mapping[str, Any], signals: list[Any]) -> list[str]:
    snapshot = build_progress_snapshot(policy, strategy, signals)
    asset_percent = _percent(snapshot["current_assets"], snapshot["target_assets"])
    lines = ["【世帯進捗】", f"資産 {_compact_yen(snapshot['current_assets'])} / {_compact_yen(snapshot['target_assets'])}" + (f"（{asset_percent}）" if asset_percent else "")]
    if snapshot["current_dividend"] is None:
        lines.append(f"配当 現在確認済み 未設定｜目標 {_compact_yen(snapshot['target_dividend'])}/年")
    else:
        dividend_percent = _percent(snapshot["current_dividend"], snapshot["target_dividend"])
        lines.append(f"配当 {_compact_yen(snapshot['current_dividend'])} / {_compact_yen(snapshot['target_dividend'])}/年" + (f"（{dividend_percent}）" if dividend_percent else ""))
    if snapshot["target_investment"] is None:
        lines.append("年度投資 目標額未設定")
    else:
        investment_percent = _percent(snapshot["completed_investment"], snapshot["target_investment"])
        lines.append(f"年度投資 {_compact_yen(snapshot['completed_investment'])} / {_compact_yen(snapshot['target_investment'])}" + (f"（{investment_percent}）" if investment_percent else "") + f"｜残り {_compact_yen(snapshot['remaining_investment'])}")
    return lines


def _market_lines(alerts: Iterable[Any], mode_label: str, limit: int = 2) -> list[str]:
    important = [row for row in alerts if int(getattr(row, "priority", 99)) <= 2 or getattr(row, "status", None) in {"REVIEW_REQUIRED", "DATA_ERROR"}]
    important.sort(key=lambda row: (0 if getattr(row, "status", None) == "REVIEW_REQUIRED" else 1, int(getattr(row, "priority", 99))))
    lines = ["【市場監視】"]
    if not important:
        lines.append("新規アラートなし")
        return lines
    data_errors = [row for row in important if getattr(row, "status", None) == "DATA_ERROR"]
    if data_errors:
        lines.append(f"🚨 日本株データ取得失敗 {len(data_errors)}件")
        lines.append("   朝の再取得まで日本株の購入判定は停止" if "夜" in mode_label else "   朝の再取得でも未解消。日本株の購入判定は停止")
    for row in important[:limit]:
        status, ticker, name = getattr(row, "status", None), getattr(row, "ticker", ""), getattr(row, "company_name", "")
        if status == "REVIEW_REQUIRED":
            lines.append(f"⚠️ {ticker} {name}｜急落理由の確認待ち")
        elif status == "DATA_ERROR":
            lines.append(f"⚠️ {ticker} {name}｜データ取得異常")
        else:
            close, change = _money(getattr(row, "close", None)), getattr(row, "change_percent", None)
            lines.append(f"🟡 {ticker} {name}｜{close}" + (f"（{change:+.2f}%）" if change is not None else ""))
    if len(important) > limit:
        lines.append(f"・ほか {len(important) - limit}件")
    return lines


def render_discord_report(
    policy: Mapping[str, Any],
    strategy: Mapping[str, Any],
    signals: Iterable[Any],
    alerts: Iterable[Any],
    trade_date: date,
    mode_label: str,
    account_labels: Mapping[str, str] | None = None,
    changes: Iterable[Any] | None = None,
    system_notices: Iterable[str] | None = None,
) -> str:
    signal_list, alert_list = list(signals), list(alerts)
    labels = account_labels or {}
    counts = _active_account_counts(signal_list)
    ready = len({(getattr(row, "account", None), getattr(row, "ticker", None)) for row in signal_list if getattr(row, "actionability", None) == "READY"})
    blocked = len({(getattr(row, "account", None), getattr(row, "ticker", None)) for row in signal_list if getattr(row, "status", None) in {"BLOCKED_AT_LIMIT", "BLOCKED_DAILY_ORDER_LIMIT"}})
    near = len({(getattr(row, "account", None), getattr(row, "ticker", None)) for row in signal_list if getattr(row, "status", None) == "NEAR"})
    account_summary = "｜".join(f"{labels.get(account, account)} {counts[account]}銘柄" for account in sorted(counts)) or "設定なし"
    lines = [f"📊 HOS株式監視｜{trade_date.strftime('%m/%d')}終値｜{mode_label}"]
    changes = list(changes or [])
    lines.append("【本日の変更】")
    if changes:
        for change in changes[:6]:
            lines.extend(str(getattr(change, "text", change)).splitlines())
    else:
        lines.append("判断変更なし")
    for notice in list(system_notices or [])[:2]:
        lines.append(str(notice))
    lines.extend(["", f"購入可 {ready}件｜購入停止 {blocked}件｜指値接近 {near}件", f"監視対象：{account_summary}", "※「✅ 購入可」以外は発注禁止", ""])
    lines.extend(_strategy_summary(signal_list, labels))
    lines.extend([""] + _progress_lines(policy, strategy, signal_list) + [""] + _market_lines(alert_list, mode_label) + ["", "発注ルール：成行禁止・固定指値・1日最大1注文・自動発注なし"])
    report = "\n".join(lines)
    return report if len(report) <= 1_980 else f"{report[:1_940].rstrip()}\n…Discord内の詳細は次回更新で再通知"


def render_public_summary(*, trade_date: date, mode_label: str, delivery_confirmed: bool, private_profile_loaded: bool) -> str:
    """Value-free CI/GitHub Summary content. Never include orders or household data."""
    status = "Discord delivery confirmed" if delivery_confirmed else "Discord delivery failed"
    profile = "loaded" if private_profile_loaded else "missing; purchase authority remained fail-closed"
    return "\n".join(["## HOS Stock Watch", f"- Trade date: {trade_date.isoformat()}", f"- Mode: {mode_label}", f"- Private Profile: {profile}", f"- Notification: {status}", "- Household balances, targets, holdings, and order details are intentionally excluded from this summary."])
