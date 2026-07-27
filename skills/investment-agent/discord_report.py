"""Readable Discord layout for household Stock Watch notifications."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Iterable, Mapping

from progress_notification import build_progress_snapshot

ACTIVE_FY_DECISIONS = {"BUY_2026_CORE", "BUY_2026_CONDITIONAL"}
ACCOUNT_LABELS = {"maho": "まほ", "hiro": "ひろ"}
RELEVANT_STATUSES = {
    "READY",
    "BLOCKED_AT_LIMIT",
    "BLOCKED_DAILY_ORDER_LIMIT",
    "NEAR",
    "ABOVE_CEILING",
}
STATUS_LABELS = {
    "READY": "✅ 購入可",
    "BLOCKED_AT_LIMIT": "🛑 指値到達",
    "BLOCKED_DAILY_ORDER_LIMIT": "⏭️ 注文上限",
    "NEAR": "🟡 指値接近",
    "ABOVE_CEILING": "⏸️ 上限超過",
}
STATUS_RANK = {
    "READY": 0,
    "BLOCKED_AT_LIMIT": 1,
    "BLOCKED_DAILY_ORDER_LIMIT": 2,
    "NEAR": 3,
    "ABOVE_CEILING": 4,
}
BLOCK_LABELS = {
    "ACCOUNT_BUDGET_SECRET_REQUIRED": "口座予算未設定",
    "ACCOUNT_BUYING_POWER_REQUIRED": "買付余力未設定",
    "ACCOUNT_STRATEGY_BUDGET_EXCEEDED": "口座予算超過",
    "ACCOUNT_BUYING_POWER_INSUFFICIENT": "買付余力不足",
    "HOUSEHOLD_TARGET_BUDGET_EXCEEDED": "年度投資枠超過",
    "HOUSEHOLD_RESERVE_BREACH": "生活防衛資金不足",
    "MAHO_2026_CAP_EXCEEDED": "まほ年間上限超過",
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
}


def _money(value: float | None, currency: str = "JPY") -> str:
    if value is None:
        return "未取得"
    if currency == "USD":
        return f"${value:,.2f}"
    return f"¥{value:,.0f}"


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
    if shares is not None:
        return f"{shares}株"
    return str(getattr(signal, "shares_rule", None) or "株数未確定")


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
    rows = [
        signal for signal in signals
        if getattr(signal, "account", None) == account
        and getattr(signal, "status", None) in RELEVANT_STATUSES
    ]
    rows.sort(key=lambda signal: (
        STATUS_RANK.get(getattr(signal, "status", ""), 9),
        int(getattr(signal, "execution_priority", 99)),
        float(getattr(signal, "distance_to_limit_percent", 999) or 999),
        int(getattr(signal, "step_index", 99)),
    ))
    unique: dict[str, Any] = {}
    for row in rows:
        unique.setdefault(str(getattr(row, "ticker", "")), row)
    return list(unique.values())


def _translated_blocks(blocks: Iterable[str]) -> list[str]:
    translated: list[str] = []
    for block in blocks:
        label = BLOCK_LABELS.get(str(block), "設定確認")
        if label not in translated:
            translated.append(label)
    return translated


def _strategy_summary(signals: list[Any], per_account_limit: int = 3) -> list[str]:
    counts = _active_account_counts(signals)
    lines: list[str] = []
    for account in ("maho", "hiro"):
        label = ACCOUNT_LABELS[account]
        lines.append(f"【{label}口座】")
        relevant = _unique_relevant(signals, account)
        if not relevant:
            lines.append(f"・該当なし（監視 {counts.get(account, 0)}銘柄）")
            continue
        for signal in relevant[:per_account_limit]:
            status = str(getattr(signal, "status", ""))
            lines.append(
                f"{STATUS_LABELS.get(status, '・確認')} "
                f"{getattr(signal, 'ticker', '')} {getattr(signal, 'name', '')}｜"
                f"{_money(getattr(signal, 'current_price', None), getattr(signal, 'currency', 'JPY'))}"
                f" → 指値{_money(getattr(signal, 'limit_price', None), getattr(signal, 'currency', 'JPY'))}｜"
                f"{_shares(signal)}"
            )
            blocks = _translated_blocks(getattr(signal, "blocks", []) or [])
            if blocks:
                lines.append(f"   確認待ち：{'・'.join(blocks[:3])}")
        if len(relevant) > per_account_limit:
            lines.append(f"・ほか {len(relevant) - per_account_limit}件")
    return lines


def _progress_lines(
    policy: Mapping[str, Any],
    strategy: Mapping[str, Any],
    signals: list[Any],
) -> list[str]:
    snapshot = build_progress_snapshot(policy, strategy, signals)
    asset_percent = _percent(snapshot["current_assets"], snapshot["target_assets"])
    lines = [
        "【世帯進捗】",
        f"資産 {_compact_yen(snapshot['current_assets'])} / {_compact_yen(snapshot['target_assets'])}"
        + (f"（{asset_percent}）" if asset_percent else ""),
    ]
    if snapshot["current_dividend"] is None:
        lines.append(f"配当 現在額未設定 / 目標 {_compact_yen(snapshot['target_dividend'])}/年")
    else:
        dividend_percent = _percent(snapshot["current_dividend"], snapshot["target_dividend"])
        lines.append(
            f"配当 {_compact_yen(snapshot['current_dividend'])} / {_compact_yen(snapshot['target_dividend'])}/年"
            + (f"（{dividend_percent}）" if dividend_percent else "")
        )
    if snapshot["target_investment"] is None:
        lines.append("年度投資 目標額未設定")
    else:
        investment_percent = _percent(snapshot["completed_investment"], snapshot["target_investment"])
        lines.append(
            f"年度投資 {_compact_yen(snapshot['completed_investment'])} / "
            f"{_compact_yen(snapshot['target_investment'])}"
            + (f"（{investment_percent}）" if investment_percent else "")
            + f"｜残り {_compact_yen(snapshot['remaining_investment'])}"
        )
    return lines


def _market_lines(alerts: Iterable[Any], limit: int = 2) -> list[str]:
    important = [
        row for row in alerts
        if int(getattr(row, "priority", 99)) <= 2
        or getattr(row, "status", None) in {"REVIEW_REQUIRED", "DATA_ERROR"}
    ]
    important.sort(key=lambda row: (
        0 if getattr(row, "status", None) == "REVIEW_REQUIRED" else 1,
        int(getattr(row, "priority", 99)),
    ))
    lines = ["【市場監視】"]
    if not important:
        lines.append("新規アラートなし")
        return lines
    for row in important[:limit]:
        status = getattr(row, "status", None)
        ticker = getattr(row, "ticker", "")
        name = getattr(row, "company_name", "")
        if status == "REVIEW_REQUIRED":
            lines.append(f"⚠️ {ticker} {name}｜急落理由の確認待ち")
        elif status == "DATA_ERROR":
            lines.append(f"⚠️ {ticker} {name}｜データ取得異常")
        elif status == "WATCH":
            close = _money(getattr(row, "close", None))
            change = getattr(row, "change_percent", None)
            suffix = f"（{change:+.2f}%）" if change is not None else ""
            lines.append(f"🟡 {ticker} {name}｜{close}{suffix}")
        else:
            lines.append(f"🟠 {ticker} {name}｜通常監視で要確認")
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
) -> str:
    signal_list = list(signals)
    alert_list = list(alerts)
    counts = _active_account_counts(signal_list)
    ready = len({
        (getattr(row, "account", None), getattr(row, "ticker", None))
        for row in signal_list
        if getattr(row, "actionability", None) == "READY"
    })
    blocked = len({
        (getattr(row, "account", None), getattr(row, "ticker", None))
        for row in signal_list
        if getattr(row, "status", None) in {"BLOCKED_AT_LIMIT", "BLOCKED_DAILY_ORDER_LIMIT"}
    })
    near = len({
        (getattr(row, "account", None), getattr(row, "ticker", None))
        for row in signal_list
        if getattr(row, "status", None) == "NEAR"
    })

    lines = [
        f"📊 HOS株式監視｜{trade_date.strftime('%m/%d')}終値｜{mode_label}",
        f"購入可 {ready}件｜確認待ち {blocked}件｜指値接近 {near}件",
        f"監視対象：まほ {counts.get('maho', 0)}銘柄｜ひろ {counts.get('hiro', 0)}銘柄",
        "※「✅ 購入可」以外は発注禁止",
        "",
    ]
    lines.extend(_strategy_summary(signal_list))
    lines.append("")
    lines.extend(_progress_lines(policy, strategy, signal_list))
    lines.append("")
    lines.extend(_market_lines(alert_list))
    lines.append("")
    lines.append("発注ルール：成行禁止・固定指値・1日最大1注文")

    report = "\n".join(lines)
    if len(report) > 1_980:
        return f"{report[:1_940].rstrip()}\n…詳細はGitHub出力を確認"
    return report
