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
    "CONCENTRATION_WARNING": "世帯集中度注意",
    "EARNINGS_AUDIT_REQUIRED": "HOS決算監査待ち",
    "EARNINGS_NEUTRAL": "決算様子見",
    "EARNINGS_NEGATIVE": "決算悪化・購入停止",
    "EARNINGS_EVENT_REVIEW_REQUIRED": "決算直前・新決算確認",
    "EARNINGS_REVIEW_EXPIRED": "決算レビュー期限切れ",
    "EARNINGS_NOT_CURRENTLY_AUDITED": "直近決算の自動評価未登録",
    "OFFICIAL_IR_FETCH_WARNING": "公式IR取得を再確認",
    "OFFICIAL_IR_SOURCE_REQUIRED": "公式IRソース未登録",
    "INVESTMENT_REVIEW_NOT_REGISTERED": "将来性・割安度レビュー未登録",
    "INVESTMENT_REVIEW_UNVERIFIED": "投資レビューの根拠未確認",
    "INVESTMENT_REVIEW_DATE_MISSING": "投資レビュー日未設定",
    "INVESTMENT_REVIEW_EVIDENCE_MISSING": "投資レビュー根拠未登録",
    "INVESTMENT_REVIEW_VALIDITY_MISSING": "投資レビュー期限未設定",
    "INVESTMENT_REVIEW_EXPIRED": "投資レビュー期限切れ",
    "INVESTMENT_REVIEW_SCORE_MISSING": "総合レビュー点未入力",
    "INVESTMENT_REVIEW_SCORE_INCOMPLETE": "総合レビューの一部未入力",
    "INVESTMENT_REVIEW_INVALID": "総合レビュー値を再確認",
    "INVESTMENT_REVIEW_SCORE_TOO_LOW": "総合レビューが基準未満",
    "INVESTMENT_THESIS_BROKEN": "投資仮説の破綻",
    "INVESTMENT_THESIS_STATUS_MISSING": "投資仮説の状態未入力",
    "INVESTMENT_THESIS_REVIEW_REQUIRED": "投資仮説の再確認",
    "VALUATION_STATUS_MISSING": "バリュエーション状態未入力",
    "VALUATION_REVIEW_REQUIRED": "割高・バリュエーション再確認",
    "BUSINESS_QUALITY_STATUS_MISSING": "事業品質の状態未入力",
    "BUSINESS_QUALITY_REVIEW_REQUIRED": "事業品質の再確認",
    "DIVIDEND_THESIS_BROKEN": "配当仮説の破綻",
    "DIVIDEND_OUTLOOK_MISSING": "配当見通し未入力",
    "DIVIDEND_DURABILITY_REVIEW_REQUIRED": "配当持続性の再確認",
    "DIVIDEND_FORECAST_REVIEW_REQUIRED": "公式配当予想を確認",
    "DIVIDEND_FORECAST_UNCONFIRMED": "公式配当予想未確認",
    "ORDINARY_DIVIDEND_REVIEW_REQUIRED": "普通配当を再確認",
    "FIXED_LIMIT_REQUIRED": "固定指値未設定",
    "MANUAL_STEP_SHARES_REQUIRED": "Step株数未確定",
    "MULTIPLE_REGISTERED_PLANS": "同一銘柄の登録計画が複数",
    "MULTIPLE_REGISTERED_STEPS": "複数登録Stepを合算評価",
    "PLAN_CONFLICT": "登録戦略の整合性を確認",
    "PURCHASE_AUTHORITY_INVALID": "登録戦略Authority不備",
    "FY_DECISION_NOT_ACTIVE": "当年度購入計画外",
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


LOGIC_STATUS_RANK = {
    "BUY_CONSIDER": 0,
    "CONDITIONAL_CONSIDER": 1,
    "REVIEW_REQUIRED": 2,
    "NEAR": 3,
    "WAIT_PRICE": 4,
    "ABOVE_CEILING": 5,
    "PAUSE": 6,
    "DATA_REQUIRED": 7,
    # Backward-compatible rendering for an in-flight private runtime only.
    "LOGIC_PASS": 0,
    "BLOCKED": 6,
    "DATA_ERROR": 7,
}


def _logic_rows(candidates: Iterable[Any]) -> list[Any]:
    """Select private manual-logic rows without exposing account identifiers."""
    rows = [
        row for row in candidates
        if getattr(row, "status", None) in LOGIC_STATUS_RANK or getattr(row, "blocks", None)
    ]
    rows.sort(key=lambda row: (
        LOGIC_STATUS_RANK.get(str(getattr(row, "status", "")), 99),
        int(getattr(row, "execution_priority", 99) or 99),
        float(getattr(row, "distance_to_limit_percent", 999) or 999),
        str(getattr(row, "ticker", "")),
        int(getattr(row, "step_index", 99) or 99),
    ))
    unique: dict[str, Any] = {}
    for row in rows:
        unique.setdefault(str(getattr(row, "ticker", "")), row)
    return list(unique.values())


def _logic_dimension_line(row: Any) -> str:
    entry = {
        "BUY_ZONE": "価格: 指値圏内",
        "NEAR": "価格: 指値接近",
        "WAIT_PRICE": "価格: 指値圏外",
        "ABOVE_CEILING": "価格: 買付上限超過",
        "DATA_REQUIRED": "価格: 要再取得",
    }.get(str(getattr(row, "entry_status", "")), "価格: 要確認")
    earnings = {
        "POSITIVE": "決算: POSITIVE",
        "NEUTRAL": "決算: 様子見",
        "NEGATIVE": "決算: 悪化",
        "EVENT_REVIEW": "決算: 発表前後",
        "REVIEW_EXPIRED": "決算: レビュー期限切れ",
        "AUDIT_REQUIRED": "決算: 明示的な確認待ち",
        "UNREVIEWED": "決算: 自動評価未登録",
    }.get(str(getattr(row, "earnings_state", "")), "決算: 要確認")
    thesis = {
        "VALIDATED": "将来性・割安度: 確認済み",
        "REGISTERED_PLAN": "将来性・割安度: 登録戦略ベース",
        "PARTIAL": "将来性・割安度: 再確認あり",
    }.get(str(getattr(row, "thesis_state", "")), "将来性・割安度: 要確認")
    return f"   {entry}｜{earnings}｜{thesis}"


def _logic_portfolio_line(row: Any) -> str | None:
    parts: list[str] = []
    dividend_yield = getattr(row, "dividend_yield", None)
    if dividend_yield is not None:
        parts.append(f"普通配当利回り: {float(dividend_yield) * 100:.1f}%")
    elif str(getattr(row, "dividend_state", "")) == "UNCONFIRMED":
        parts.append("普通配当: 未確認")
    weight = getattr(row, "projected_weight", None)
    if weight is not None:
        parts.append(f"購入後集中度: {float(weight) * 100:.1f}%")
    score = getattr(row, "investment_score", None)
    if score is not None:
        parts.append(f"総合レビュー: {float(score):.0f}/100")
    count = int(getattr(row, "planned_step_count", 1) or 1)
    if count > 1:
        combined = getattr(row, "combined_pending_shares", None)
        parts.append(f"次Step: {count}件・合算 {combined}株" if combined is not None else f"次Step: {count}件・整合性確認")
    return f"   {'｜'.join(parts)}" if parts else None


def _logic_summary(candidates: Iterable[Any], per_limit: int = 4) -> list[str]:
    """Render the human investment judgement without implying order approval."""
    relevant = _logic_rows(candidates)
    counts = {status: sum(getattr(row, "status", None) == status for row in relevant) for status in LOGIC_STATUS_RANK}
    lines = [
        "【総合買い判断（手動確認用）】",
        f"🟢 検討可 {counts['BUY_CONSIDER']}件｜🟡 条件付き {counts['CONDITIONAL_CONSIDER']}件｜要確認 {counts['REVIEW_REQUIRED']}件｜価格待ち {counts['NEAR'] + counts['WAIT_PRICE'] + counts['ABOVE_CEILING']}件｜停止 {counts['PAUSE']}件",
    ]
    if not relevant:
        lines.append("該当する未完了の登録Stepなし")
    else:
        labels = {
            "BUY_CONSIDER": "🟢 買い検討可",
            "CONDITIONAL_CONSIDER": "🟡 条件付き検討可",
            "REVIEW_REQUIRED": "⚪ 要確認",
            "NEAR": "🟡 価格接近",
            "WAIT_PRICE": "⏳ 価格待ち",
            "ABOVE_CEILING": "⏸️ 買付上限超過",
            "PAUSE": "🛑 購入停止",
            "DATA_REQUIRED": "🚨 データ確認",
            "LOGIC_PASS": "🟢 買い検討可",
            "BLOCKED": "🛑 購入停止",
            "DATA_ERROR": "🚨 データ確認",
        }
        for row in relevant[:per_limit]:
            lines.append(
                f"{labels.get(str(getattr(row, 'status', '')), '・確認')} "
                f"{getattr(row, 'ticker', '')} {getattr(row, 'name', '')}｜"
                f"{_money(getattr(row, 'current_price', None), getattr(row, 'currency', 'JPY'))} → "
                f"指値{_money(getattr(row, 'limit_price', None), getattr(row, 'currency', 'JPY'))}｜{_shares(row)}"
            )
            lines.append(_logic_dimension_line(row))
            portfolio = _logic_portfolio_line(row)
            if portfolio:
                lines.append(portfolio)
            blocks = _translated_blocks(getattr(row, "blocks", []) or [])
            warnings = _translated_blocks(getattr(row, "warnings", []) or [])
            if blocks:
                heading = "購入停止理由" if str(getattr(row, "status", "")) == "PAUSE" else "確認事項"
                lines.append(f"   {heading}：{'・'.join(blocks[:2])}")
            if warnings:
                lines.append(f"   手動確認：{'・'.join(warnings[:2])}")
        if len(relevant) > per_limit:
            overflow = relevant[per_limit:]
            grouped: dict[str, list[str]] = defaultdict(list)
            for row in overflow:
                grouped[str(getattr(row, "status", ""))].append(str(getattr(row, "ticker", "")))
            short_labels = {
                "BUY_CONSIDER": "検討可",
                "CONDITIONAL_CONSIDER": "条件付き",
                "REVIEW_REQUIRED": "要確認",
                "NEAR": "接近",
                "WAIT_PRICE": "価格待ち",
                "ABOVE_CEILING": "上限超過",
                "PAUSE": "停止",
                "DATA_REQUIRED": "データ確認",
            }
            compact = "｜".join(
                f"{short_labels.get(status, '確認')} {len(tickers)}件（{','.join(tickers)}）"
                for status, tickers in grouped.items()
            )
            lines.append(f"・ほか {len(overflow)}銘柄：{compact}")
    lines.extend([
        "※ 検討可はHOSの発注可ではありません。",
        "※実注文前に、固定指値・当日開示・買付余力・予算・現金防衛・前Step・1日1注文を各自で確認。",
    ])
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
    logic_candidates: Iterable[Any] | None = None,
) -> str:
    signal_list, alert_list = list(signals), list(alerts)
    logic_list = list(logic_candidates or [])
    labels = account_labels or {}
    counts = _active_account_counts(signal_list)
    ready = len({(getattr(row, "account", None), getattr(row, "ticker", None)) for row in signal_list if getattr(row, "actionability", None) == "READY"})
    blocked = len({(getattr(row, "account", None), getattr(row, "ticker", None)) for row in signal_list if getattr(row, "status", None) in {"BLOCKED_AT_LIMIT", "BLOCKED_DAILY_ORDER_LIMIT"}})
    near = len({(getattr(row, "account", None), getattr(row, "ticker", None)) for row in signal_list if getattr(row, "status", None) == "NEAR"})
    logic_consider = len({str(getattr(row, "ticker", "")) for row in logic_list if getattr(row, "status", None) in {"BUY_CONSIDER", "CONDITIONAL_CONSIDER", "LOGIC_PASS"}})
    logic_tickers = {str(getattr(row, "ticker", "")) for row in logic_list if str(getattr(row, "ticker", ""))}
    account_summary = "｜".join(f"{labels.get(account, account)} {counts[account]}銘柄" for account in sorted(counts))
    if not account_summary:
        account_summary = f"総合買い判断 {len(logic_tickers)}銘柄（口座別発注安全判定は保留）" if logic_tickers else "設定なし"
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
    lines.extend(["", f"発注可 {ready}件｜手動買い検討 {logic_consider}件｜購入停止 {blocked}件｜指値接近 {near}件", f"監視対象：{account_summary}", "※ HOSの「発注可」以外は発注禁止", ""])
    if logic_list:
        lines.extend(_logic_summary(logic_list) + [""])
    lines.extend(_strategy_summary(signal_list, labels))
    lines.extend([""] + _progress_lines(policy, strategy, signal_list) + [""] + _market_lines(alert_list, mode_label) + ["", "発注ルール：成行禁止・固定指値・1日最大1注文・自動発注なし"])
    report = "\n".join(lines)
    return report if len(report) <= 1_980 else f"{report[:1_940].rstrip()}\n…Discord内の詳細は次回更新で再通知"


def render_public_summary(*, trade_date: date, mode_label: str, delivery_confirmed: bool, private_profile_loaded: bool) -> str:
    """Value-free CI/GitHub Summary content. Never include orders or household data."""
    status = "Discord delivery confirmed" if delivery_confirmed else "Discord delivery failed"
    profile = "loaded" if private_profile_loaded else "missing; purchase authority remained fail-closed"
    return "\n".join(["## HOS Stock Watch", f"- Trade date: {trade_date.isoformat()}", f"- Mode: {mode_label}", f"- Private Profile: {profile}", f"- Notification: {status}", "- Household balances, targets, holdings, and order details are intentionally excluded from this summary."])
