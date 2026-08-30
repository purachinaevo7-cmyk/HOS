"""Production entrypoint for HOS Stock Watch.

This is the only production entrypoint. It keeps public code and private
household data separate: the private profile is loaded in memory, Discord is
the sole detailed destination, and CI/log/diagnostic outputs are value-free.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import daily_stock_check as legacy
import daily_stock_check_v3 as v3
import discord_report
import stock_fetcher
from dividend_tracker import annual_dividend_summary
from earnings_assessment import apply_earnings_assessments
from execution_reconciliation import reconcile_private_holdings
from official_ir import ingest_official_ir_sources
from notification_diff import build_private_notification_state, diff_private_notification_state
from portfolio_simulation import simulate_completion
from replacement_assessment import evaluate_private_replacement_book, load_policy as load_replacement_policy
from household_runtime import (
    apply_household_funding_gates,
    apply_private_policy,
    hydrate_environment,
    load_private_earnings_book,
    load_private_profile,
    load_private_strategy,
    private_account_labels,
    private_jp_watchlist,
    publish_runtime_asset_snapshot,
)
from jpx_trade_date import is_jpx_cash_session, latest_finished_jpx_cash_session
from notifier import DiscordNotifier, GitHubSummaryNotifier


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]
DATA_DIR = BASE_DIR / "data" / "daily_prices"
DIAGNOSTIC_PATH = ROOT_DIR / "outputs" / "stock-watch-diagnostic.json"
PUBLIC_POLICY_PATH = BASE_DIR / "config" / "portfolio_policy.json"
PUBLIC_STRATEGY_TEMPLATE_PATH = BASE_DIR / "config" / "strategies" / "strategy.example.json"
REPLACEMENT_POLICY_PATH = BASE_DIR / "config" / "replacement_policy.json"

HOUSEHOLD_BLOCK_LABELS = {
    "HOUSEHOLD_CASH_REQUIRED": "世帯現預金未設定",
    "PROTECTED_CASH_FLOOR_REQUIRED": "現金防衛ライン未設定",
    "PROTECTED_CASH_FLOOR_BREACH": "現金防衛ライン割れ",
    "EXISTING_POSITION_REQUIRED": "既存保有確認",
    "ACCOUNT_TRANSFER_REQUIRED": "補完資金の入金待ち",
    "ACCOUNT_TAXABLE_GIFTS_YTD_REQUIRED": "資金移管累計未設定",
    "GIFT_TAX_REVIEW_REQUIRED": "資金移管の税務確認",
    "EARNINGS_AUDIT_REQUIRED": "HOS決算監査待ち",
    "EARNINGS_NEUTRAL": "決算様子見",
    "EARNINGS_NEGATIVE": "決算悪化・購入停止",
}


def _install_calendar_guard() -> None:
    legacy._is_jpx_session = is_jpx_cash_session
    stock_fetcher._is_jpx_session = is_jpx_cash_session


def _public_decision_fingerprint(profile_revision: str = "") -> str:
    """Hash public logic plus an operator-declared, non-financial revision.

    The private profile itself is never fingerprinted. ``notification_revision``
    is intentionally a manual opaque value so an operator can request a same-day
    re-evaluation after changing private facts without leaking those facts.
    """
    digest = hashlib.sha256()
    for path in (
        Path(__file__),
        BASE_DIR / "earnings_assessment.py",
        BASE_DIR / "household_runtime.py",
        BASE_DIR / "strategy_plan.py",
        BASE_DIR / "discord_report.py",
        PUBLIC_POLICY_PATH,
        PUBLIC_STRATEGY_TEMPLATE_PATH,
    ):
        try:
            digest.update(str(path.relative_to(ROOT_DIR)).encode("utf-8"))
            digest.update(path.read_bytes())
        except OSError:
            digest.update(f"MISSING:{path.name}".encode("utf-8"))
    digest.update(f"PRIVATE_PROFILE_REVISION:{profile_revision}".encode("utf-8"))
    return digest.hexdigest()[:16]


def _annotate_live_household_targets(strategy: dict, profile: dict) -> dict:
    """Use verified private holdings for concentration calculations in memory."""
    household: dict[str, int] = {}
    by_owner: dict[tuple[str, str], int] = {}
    for holding in profile.get("holdings", []) if isinstance(profile, dict) else []:
        if not holding.get("verified", True):
            continue
        ticker, owner = str(holding.get("ticker") or ""), str(holding.get("owner") or "")
        try:
            shares = int(float(holding.get("shares") or 0))
        except (TypeError, ValueError):
            continue
        if not ticker:
            continue
        household[ticker] = household.get(ticker, 0) + shares
        by_owner[(owner, ticker)] = by_owner.get((owner, ticker), 0) + shares
    for account_name, account in strategy.get("accounts", {}).items():
        for order in account.get("orders", []):
            ticker = str(order.get("ticker") or "")
            existing_household = household.get(ticker, 0)
            existing_account = by_owner.get((str(account_name), ticker), 0)
            order["household_existing_shares_live"] = existing_household
            if order.get("household_target_after_completion") is not None:
                continue
            if order.get("target_additional_shares") is not None:
                target = existing_household + int(order["target_additional_shares"])
            elif order.get("target_total_shares") is not None:
                target = existing_household - existing_account + int(order["target_total_shares"])
            elif order.get("target_shares") is not None:
                target = existing_household - existing_account + int(order["target_shares"])
            else:
                continue
            order["household_target_after_completion"] = max(0, target)
    return strategy


def _postprocess_earnings_blocks(signals, strategy):
    """Translate assessment states into additional blocks; never clear a gate."""
    lookup = {(str(account_name), str(order.get("ticker"))): order for account_name, account in strategy.get("accounts", {}).items() for order in account.get("orders", [])}
    result = []
    for signal in signals:
        order = lookup.get((str(getattr(signal, "account", "")), str(getattr(signal, "ticker", ""))), {})
        review_state = str(order.get("earnings_review_status") or "")
        blocks = [block for block in (getattr(signal, "blocks", []) or []) if block != "EARNINGS_REVIEW_REQUIRED"]
        if order.get("earnings_wait") and not order.get("earnings_reviewed_ok"):
            blocks.append({"NEGATIVE": "EARNINGS_NEGATIVE", "NEUTRAL": "EARNINGS_NEUTRAL"}.get(review_state, "EARNINGS_AUDIT_REQUIRED"))
        result.append(replace(signal, blocks=sorted(set(blocks))))
    return result


def _postprocess_execution_reconciliation(signals, strategy):
    """Stop every pending step for an unconfirmed execution mismatch."""
    lookup = {
        (str(account), str(order.get("ticker") or "")): order
        for account, account_data in strategy.get("accounts", {}).items()
        for order in account_data.get("orders", [])
    }
    result = []
    for signal in signals:
        order = lookup.get((str(getattr(signal, "account", "")), str(getattr(signal, "ticker", ""))), {})
        if not order.get("execution_reconciliation_required") or getattr(signal, "status", "") == "COMPLETED":
            result.append(signal)
            continue
        blocks = sorted(set(list(getattr(signal, "blocks", []) or []) + ["EXECUTION_RECONCILIATION_REQUIRED"]))
        if getattr(signal, "actionability", "") == "READY":
            result.append(replace(signal, status="BLOCKED_AT_LIMIT", purchase_flag="REVIEW_REQUIRED", actionability="DRAFT", blocks=blocks))
        else:
            result.append(replace(signal, actionability="DRAFT", blocks=blocks))
    return result


def _private_profile_runtime_notices(profile: dict, strategy: dict) -> list[str]:
    """Return only non-financial, non-identifying migration notices for Discord."""
    import_state = str(profile.get("_runtime_private_strategy_import_state") or "")
    if import_state == "INVALID":
        return ["⚠️ HOS側：登録戦略Secretの形式不備のため、購入判定を安全停止中"]
    if import_state == "ACCOUNT_BINDING_REQUIRED":
        return ["⚠️ HOS側：登録戦略SecretとPrivate Profileの口座照合が必要なため、購入判定を安全停止中"]
    lock_reason = str(strategy.get("runtime_profile_lock_reason") or "")
    if lock_reason:
        return ["⚠️ HOS側：Private Profileの登録戦略が未移行のため、購入判定を安全停止中"]
    if profile.get("_runtime_profile_migration_state") == "LEGACY_ACCOUNT_IDS_NORMALIZED":
        return ["ℹ️ HOS側：旧口座IDを内部で安全に移行済み。次回Secret更新時にProfile v2へ更新してください"]
    if profile.get("_runtime_profile_migration_state") == "ACCOUNT_ID_MIGRATION_REQUIRED":
        return ["⚠️ HOS側：Private Profileの口座ID移行が必要なため、購入判定を安全停止中"]
    return []


def _install_household_runtime(profile: dict, dividends, simulation, earnings_ir_audit=()) -> None:
    base_strategy_watchlist = v3.strategy_watchlist
    base_evaluate_strategy = v3.evaluate_strategy
    base_render_v3 = v3._render_v3
    base_progress_lines = discord_report._progress_lines
    private_strategy = load_private_strategy(profile)
    runtime_notices = _private_profile_runtime_notices(profile, private_strategy)
    private_strategy, reconciliation_audit = reconcile_private_holdings(profile, private_strategy)
    private_strategy["execution_reconciliation_audit"] = [finding.to_dict() for finding in reconciliation_audit]
    replacement_verdicts = {
        ticker: verdict.decision
        for ticker, verdict in evaluate_private_replacement_book(profile, load_replacement_policy(REPLACEMENT_POLICY_PATH)).items()
    }
    earnings_book, _ = ingest_official_ir_sources(profile, load_private_earnings_book(profile))
    account_labels = private_account_labels(profile)

    def load_private_strategy_only(_path):
        strategy = _annotate_live_household_targets(json.loads(json.dumps(private_strategy)), profile)
        return apply_earnings_assessments(strategy, earnings_book)

    def strategy_watchlist_with_private(strategy):
        return v3.merge_watchlists(base_strategy_watchlist(strategy), private_jp_watchlist(profile))

    def evaluate_strategy_with_household_gates(strategy, japanese_prices, policy=None, env=None):
        snapshot = publish_runtime_asset_snapshot(profile, japanese_prices)
        effective_policy = dict(policy or {})
        live_assets = snapshot.get("current_financial_assets_jpy") or snapshot.get("confirmed_partial_jpy")
        if live_assets is not None:
            effective_policy["current_financial_assets"] = float(live_assets)
        signals = base_evaluate_strategy(strategy, japanese_prices, policy=effective_policy, env=env)
        processed = _postprocess_earnings_blocks(signals, strategy)
        processed = _postprocess_execution_reconciliation(processed, strategy)
        return apply_household_funding_gates(processed, strategy, env=env)

    def render_with_private_context(universe, policy, strategy, result, mode, data_dir):
        publish_runtime_asset_snapshot(profile, result.prices)
        return base_render_v3(universe, apply_private_policy(policy, profile), strategy, result, mode, data_dir)

    def progress_lines_with_confirmed_partial(policy, strategy, signals):
        lines = base_progress_lines(policy, strategy, signals)
        for index, line in enumerate(lines):
            if not line.startswith("配当 "):
                continue
            suffix = f"｜未確定：{dividends.current_unconfirmed_count}件" if dividends.current_unconfirmed_count else ""
            target = dividends.target_annual_dividend_jpy
            target_text = discord_report._compact_yen(target)
            percent = ""
            if target:
                percent = f"（{dividends.current_ordinary_cash_jpy / target * 100:.1f}%）"
            lines[index] = f"配当 現在確認済み {discord_report._compact_yen(dividends.current_ordinary_cash_jpy)} / {target_text}/年{percent}{suffix}"
            projected_suffix = f"｜未確定：{dividends.projected_unconfirmed_count}件" if dividends.projected_unconfirmed_count else ""
            lines[index + 1:index + 1] = [
                f"購入計画完了後 {discord_report._compact_yen(dividends.projected_ordinary_cash_jpy)}/年{projected_suffix}",
                f"計画による増加 +{discord_report._compact_yen(dividends.plan_increment_ordinary_jpy)}/年",
            ]
            if dividends.target_shortfall_jpy is not None:
                lines.insert(index + 3, f"目標まで残り {discord_report._compact_yen(dividends.target_shortfall_jpy)}/年")
            plan_cost = discord_report._compact_yen(simulation.plan_cost_jpy)
            plan_assets = discord_report._compact_yen(simulation.plan_financial_assets_jpy)
            lines.insert(index + 4, f"FY購入計画実行後（買付予定 {plan_cost}｜資産は再配分のため {plan_assets}）")
            if simulation.asset_shortfall_jpy is not None:
                lines.insert(index + 5, f"資産目標まで残り {discord_report._compact_yen(simulation.asset_shortfall_jpy)}")
            if simulation.plan_top_holding_weight is not None:
                lines.insert(index + 6, f"計画後上位銘柄比率 {simulation.plan_top_holding_weight * 100:.1f}%")
            break
        if os.getenv("HOS_CURRENT_FINANCIAL_ASSETS_JPY", "").strip():
            return lines
        partial_raw = os.getenv("HOS_CONFIRMED_INVESTED_ASSETS_JPY", "").strip()
        if not partial_raw:
            return lines
        try:
            partial = float(partial_raw)
        except ValueError:
            return lines
        missing_count = len([item for item in os.getenv("HOS_FINANCIAL_ASSETS_MISSING_ITEMS", "").split(",") if item])
        suffix = f"｜未確定：{missing_count}件" if missing_count else ""
        lines.insert(2, f"確認済み投資資産 {discord_report._compact_yen(partial)}{suffix}")
        return lines

    def render_discord_with_private_labels(**kwargs):
        current_state = build_private_notification_state(kwargs.get("strategy", {}), kwargs.get("signals", []), dividends, replacement_verdicts)
        # This is retained only in process memory. Persisting notification state
        # is an operator-selected private-store concern, never a git/Actions
        # artifact concern.
        profile["_runtime_notification_state"] = current_state
        changes = diff_private_notification_state(profile.get("notification_state"), current_state)
        return discord_report.render_discord_report(
            **kwargs,
            account_labels=account_labels,
            changes=changes,
            system_notices=runtime_notices,
        )

    discord_report.BLOCK_LABELS.update(HOUSEHOLD_BLOCK_LABELS)
    discord_report._progress_lines = progress_lines_with_confirmed_partial
    v3.load_strategy = load_private_strategy_only
    v3.strategy_watchlist = strategy_watchlist_with_private
    v3.evaluate_strategy = evaluate_strategy_with_household_gates
    v3._render_v3 = render_with_private_context
    v3.render_discord_report = render_discord_with_private_labels


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _already_complete(slot: str, fingerprint: str) -> bool:
    current = _load_json(DIAGNOSTIC_PATH)
    return current.get("slot") == slot and current.get("decision_fingerprint") == fingerprint and current.get("status") == "success"


def _write_diagnostic(*, slot: str, mode: str, trade_date, decision_fingerprint: str, delivery_confirmed: bool, private_profile_loaded: bool) -> dict:
    daily = _load_json(DATA_DIR / f"{trade_date.isoformat()}.json")
    prices, missing = daily.get("prices") or [], daily.get("missing") or []
    payload = {
        "slot": slot,
        "mode": mode,
        "decision_fingerprint": decision_fingerprint,
        "checked_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        "status": "success" if delivery_confirmed and prices and not missing else "degraded" if delivery_confirmed else "failure",
        "discord_delivery_confirmed": delivery_confirmed,
        "private_profile_loaded": private_profile_loaded,
        "trade_date": trade_date.isoformat(),
        "market_price_count": len(prices),
        "market_missing_count": len(missing),
        "market_data_status": "complete" if prices and not missing else "incomplete",
        "retry_required": bool(missing) or not bool(prices),
        "privacy": "no-household-values-or-identifiers",
    }
    DIAGNOSTIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIAGNOSTIC_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def run(mode: str, force: bool = False) -> int:
    _install_calendar_guard()
    profile = load_private_profile()
    hydrate_environment(profile)
    dividends = annual_dividend_summary(profile)
    simulation = simulate_completion(profile, dividends)
    if profile:
        os.environ["HOS_CURRENT_ANNUAL_DIVIDEND_JPY"] = f"{dividends.current_ordinary_cash_jpy:.0f}"
    # Any registered official IR source is refreshed before assessment. A
    # retrieval/validation failure produces NEEDS_DATA and therefore closes the
    # earnings gate; no third-party source can clear it.
    _install_household_runtime(profile, dividends, simulation)
    now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))
    trade_date = latest_finished_jpx_cash_session(now_jst)
    profile_revision = str(profile.get("notification_revision") or "") if isinstance(profile, dict) else ""
    slot, fingerprint = f"{trade_date.isoformat()}-{mode}", _public_decision_fingerprint(profile_revision)
    print(f"Stock Watch production runner: trade_date={trade_date} mode={mode}")
    if not force and _already_complete(slot, fingerprint):
        print("Duplicate notification skipped for the completed trade-date slot.")
        return 0

    report = v3.run(mode=mode, trade_date=trade_date)
    delivered = False
    try:
        DiscordNotifier().notify(report)
        delivered = True
    except Exception:
        # Do not include exception bodies: a provider can reflect request context.
        delivered = False
    mode_label = "morning-retry" if mode == v3.MORNING_RETRY else "evening"
    diagnostic = _write_diagnostic(slot=slot, mode=mode, trade_date=trade_date, decision_fingerprint=fingerprint, delivery_confirmed=delivered, private_profile_loaded=bool(profile))
    GitHubSummaryNotifier().notify(discord_report.render_public_summary(trade_date=trade_date, mode_label=mode_label, delivery_confirmed=delivered, private_profile_loaded=bool(profile)))
    print(json.dumps(diagnostic, ensure_ascii=False))
    if not delivered:
        raise RuntimeError("Discord delivery failed")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=[v3.EVENING, v3.MORNING_RETRY], required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(args.mode, args.force))


if __name__ == "__main__":
    main()
