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
    "HOUSEHOLD_CASH_REQUIRED": "ä¸–å¸¯ç¾é é‡‘æœªè¨­å®š",
    "PROTECTED_CASH_FLOOR_REQUIRED": "ç¾é‡‘é˜²è¡›ãƒ©ã‚¤ãƒ³æœªè¨­å®š",
    "PROTECTED_CASH_FLOOR_BREACH": "ç¾é‡‘é˜²è¡›ãƒ©ã‚¤ãƒ³å‰²ã‚Œ",
    "EXISTING_POSITION_REQUIRED": "æ—¢å­˜ä¿æœ‰ç¢ºèª",
    "ACCOUNT_TRANSFER_REQUIRED": "è£œå®Œè³‡é‡‘ã®å…¥é‡‘å¾…ã¡",
    "ACCOUNT_TAXABLE_GIFTS_YTD_REQUIRED": "è³‡é‡‘ç§»ç®¡ç´¯è¨ˆæœªè¨­å®š",
    "GIFT_TAX_REVIEW_REQUIRED": "è³‡é‡‘ç§»ç®¡ã®ç¨Žå‹™ç¢ºèª",
    "EARNINGS_AUDIT_REQUIRED": "HOSæ±ºç®—ç›£æŸ»å¾…ã¡",
    "EARNINGS_NEUTRAL": "æ±ºç®—æ§˜å­è¦‹",
    "EARNINGS_NEGATIVE": "æ±ºç®—æ‚ªåŒ–ãƒ»è³¼å…¥åœæ­¢",
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


def _install_household_runtime(profile: dict, dividends, simulation, earnings_ir_audit=()) -> None:
    base_strategy_watchlist = v3.strategy_watchlist
    base_evaluate_strategy = v3.evaluate_strategy
    base_render_v3 = v3._render_v3
    base_progress_lines = discord_report._progress_lines
    private_strategy = load_private_strategy(profile)
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
            if not line.startswith("é…å½“ "):
                continue
            suffix = f"ï½œæœªç¢ºå®šï¼š{dividends.current_unconfirmed_count}ä»¶" if dividends.current_unconfirmed_count else ""
            target = dividends.target_annual_dividend_jpy
            target_text = discord_report._compact_yen(target)
            percent = ""
            if target:
                percent = f"ï¼ˆ{dividends.current_ordinary_cash_jpy / target * 100:.1f}%ï¼‰"
            lines[index] = f"é…å½“ ç¾åœ¨ç¢ºèªæ¸ˆã¿ {discord_report._compact_yen(dividends.current_ordinary_cash_jpy)} / {target_text}/å¹´{percent}{suffix}"
            projected_suffix = f"ï½œæœªç¢ºå®šï¼š{dividends.projected_unconfirmed_count}ä»¶" if dividends.projected_unconfirmed_count else ""
            lines[index + 1:index + 1] = [
                f"è³¼å…¥è¨ˆç”»å®Œäº†å¾Œ {discord_report._compact_yen(dividends.projected_ordinary_cash_jpy)}/å¹´{projected_suffix}",
                f"è¨ˆç”»ã«ã‚ˆã‚‹å¢—åŠ  +{discord_report._compact_yen(dividends.plan_increment_ordinary_jpy)}/å¹´",
            ]
            if dividends.target_shortfall_jpy is not None:
                lines.insert(index + 3, f"ç›®æ¨™ã¾ã§æ®‹ã‚Š {discord_report._compact_yen(dividends.target_shortfall_jpy)}/å¹´")
            plan_cost = discord_report._compact_yen(simulation.plan_cost_jpy)
            plan_assets = discord_report._compact_yen(simulation.plan_financial_assets_jpy)
            lines.insert(index + 4, f"FYè³¼å…¥è¨ˆç”»å®Ÿè¡Œå¾Œï¼ˆè²·ä»˜äºˆå®š {plan_cost}ï½œè³‡ç”£ã¯å†é…åˆ†ã®ãŸã‚ {plan_assets}ï¼‰")
            if simulation.asset_shortfall_jpy is not None:
                lines.insert(index + 5, f"è³‡ç”£ç›®æ¨™ã¾ã§æ®‹ã‚Š {discord_report._compact_yen(simulation.asset_shortfall_jpy)}")
            if simulation.plan_top_holding_weight is not None:
                lines.insert(index + 6, f"è¨ˆç”»å¾Œä¸Šä½éŠ˜æŸ„æ¯”çŽ‡ {simulation.plan_top_holding_weight * 100:.1f}%")
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
        suffix = f"ï½œæœªç¢ºå®šï¼š{missing_count}ä»¶" if missing_count else ""
        lines.insert(2, f"ç¢ºèªæ¸ˆã¿æŠ•è³‡è³‡ç”£ {discord_report._compact_yen(partial)}{suffix}")
        return lines

    def render_discord_with_private_labels(**kwargs):
        current_state = build_private_notification_state(kwargs.get("strategy", {}), kwargs.get("signals", []), dividends, replacement_verdicts)
        # This is retained only in process memory. Persisting notification state
        # is an operator-selected private-store concern, never a git/Actions
        # artifact concern.
        profile["_runtime_notification_state"] = current_state
        changes = diff_private_notification_state(profile.get("notification_state"), current_state)
        return discord_report.render_discord_report(**kwargs, account_labels=account_labels, changes=changes)

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
        "discord_d×]üâÚ$z{-®éÜj×Ý[
ÏH›Ø]
Ý\È™^XÝ]YØ[[Ý[ÚœH—JBˆÛÛ[YBˆÚ\™\ËËÈHÜÚ\™\×Ù›Ü—ÜÝ\
Ü™\‹Ý\
BˆË[[Ý[ÚœKÈHØ[[Ý[×Ù›Ü—ÜÝ\
Ý˜]YÞKÜ™\‹Ý\Ú\™\Ë[ŠBˆYˆ[[Ý[ÚœH\È›Ý›Û™N‚ˆÝ[
ÏH[[Ý[ÚœBˆ™]\›ˆÝ[‚‚™YˆÜ[™[™×Ú[™^
Ü™\ŽˆXÝÜÝ‹[žWJHOˆ[›Û™N‚ˆÛÛ\]YHÙ]
X\
Ý‹Ü™\‹™Ù]
˜ÛÛ\]YÜÝ\ÚYÈ‹×JJJBˆ›Üˆ[™^Ý\[ˆ[[Y\˜]JÜ™\‹™Ù]
›Ü™\—ÜÝ\È‹×JJN‚ˆYˆÝŠÝ\™Ù]
œÝ\ÚYŠJH›Ý[ˆÛÛ\]Y‚ˆ™]\›ˆ[™^ˆ™]\›ˆ›Û™B‚‚™Yˆ]˜[X]WÜÝ˜]YÞJˆÝ˜]YÞNˆXÝÜÝ‹[žWKˆ˜\[™\ÙWÜšXÙ\Îˆ\ÝÔšXÙT™XÛÜ™KˆÛXÞNˆXÝÜÝ‹[žWH›Û™HH›Û™Kˆ[ŽˆX\[™ÖÜÝ‹Ý—H›Û™HH›Û™KŠHOˆ\ÝÔÝ˜]YÞSÜ™\”ÚYÛ˜[N‚ˆÛÝ\˜ÙHH[ˆYˆ[ˆ\È›Ý›Û™H[ÙHÜË™[š\›Û‚ˆšXÙWÛX\HÜ™XÛÜ™˜ÛÙNˆ™XÛÜ™›Üˆ™XÛÜ™[ˆ˜\[™\ÙWÜšXÙ\ßBˆšXÙWÛX\\]JÙ™]ÚÝ\×ÜšXÙ\ÊÝ˜]YÞJJBˆ›ÝÈH]][YK››ÝÊ[Y^›Û™K]ÊKš\ÛÙ›Ü›X]

BˆÚYÛ˜[Îˆ\ÝÔÝ˜]YÞSÜ™\”ÚYÛ˜[HH×BˆÝ˜]YÞWØXÝ]™HHÝŠÝ˜]YÞK™Ù]
œÝ]\ÈŠHÜˆˆŠK\\Š
HOHPÕU‘H‚ˆÛXÞHHÛXÞHÜˆßBˆš[˜[˜ÚX[Ø\ÜÙ]ÈH›Ø]
ÛXÞK™Ù]
˜Ý\œ™[Ùš[˜[˜ÚX[Ø\ÜÙ]ÈŠHÜˆÝ˜]YÞK™Ù]
šÝ\ÙZÛÙÛØ[‹ßJK™Ù]
˜Ý\œ™[Ùš[˜[˜ÚX[Ø\ÜÙ]×ÚœHŠHÜˆ
BˆÛÛ˜Ù[˜][Û—Û[Z]H›Ø]
Ý˜]YÞK™Ù]
šÝ\ÙZÛÙÛØ[‹ßJK™Ù]
›X^ÜÚ[™ÛWÝXÚÙ\—ÝÙZYÚÝØ\›š[™È‹ŒJJBˆÛÛ˜Ù[˜][Û—Ú\™Û[Z]H›Ø]
Ý˜]YÞK™Ù]
šÝ\ÙZÛÙÛØ[‹ßJK™Ù]
›X^ÜÚ[™ÛWÝXÚÙ\—ÝÙZYÚÚ\™‹ÛÛ˜Ù[˜][Û—Û[Z]
JBˆ™YÚ\Ý\™YØ]]Üš]HHÝŠÝ˜]YÞK™Ù]
œ\˜Ú\ÙWØ]]Üš]H‹ßJK™Ù]
›[ÙHŠHÜˆˆŠK\\Š
HOH”‘QÒTÕT‘QÔÕUQÖWÓÓ“H‚‚ˆÝ\ÙZÛØØ\ÚHÙ[—Û[X™\ŠÝ˜]YÞK™Ù]
™[™[™È‹ßJK™Ù]
˜]˜Z[X›WÚ[™\ÝY[ØØ\ÚÚœWÙ[ˆŠKÛÝ\˜ÙJBˆÝ\ÙZÛÝ\™Ù]HÙ[—Û[X™\ŠÝ˜]YÞK™Ù]
™[™[™È‹ßJK™Ù]
\™Ù]Ú[™\ÝY[Ý×ÌŒ×Ì×ÚœWÙ[ˆŠKÛÝ\˜ÙJBˆÝ\ÙZÛÜ™\Ù\™HHÙ[—Û[X™\ŠÝ˜]YÞK™Ù]
™[™[™È‹ßJK™Ù]
œ™\Ù\™WØY\—Ù^XÝ][Û—ÚœWÙ[ˆŠKÛÝ\˜ÙJBˆXØÛÝ[ÜÜ[™HÂˆ˜[YNˆØÛÛ\]YÜÜ[™
Ý˜]YÞKXØÛÝ[ÛÝ\˜ÙJBˆ›Üˆ˜[YKXØÛÝ[[ˆÝ˜]YÞK™Ù]
˜XØÛÝ[È‹ßJKš][\Ê
BˆBˆÝ\ÙZÛÜÜ[™HÝ[JXØÛÝ[ÜÜ[™˜[Y\Ê
JB‚ˆ›ÜˆXØÛÝ[Û˜[YKXØÛÝ[[ˆÝ˜]YÞK™Ù]
˜XØÛÝ[È‹ßJKš][\Ê
N‚ˆXØÛÝ[ØYÙ]HÙ[—Û[X™\ŠXØÛÝ[™Ù]
\™Ù]ØYÙ]ÚœWÙ[ˆŠKÛÝ\˜ÙJBˆ^Z[™×ÜÝÙ\ˆHÙ[—Û[X™\ŠXØÛÝ[™Ù]
˜^Z[™×ÜÝÙ\—ÚœWÙ[ˆŠKÛÝ\˜ÙJBˆ[›X[ÜÝØÚ×ØØ\HÙ[—Û[X™\ŠXØÛÝ[™Ù]
˜[›X[ÜÝØÚ×ØØ\ÚœWÙ[ˆŠKÛÝ\˜ÙJBˆ›ÜˆÜ™\ˆ[ˆXØÛÝ[™Ù]
›Ü™\œÈ‹×JN‚ˆXÚÙ\ˆHÝŠÜ™\–ÈXÚÙ\ˆ—JBˆX\šÙ]HÝŠÜ™\‹™Ù]
›X\šÙ]‹’”ŠJK\\Š
BˆÝ\œ™[˜ÞHHÝŠÜ™\‹™Ù]
˜Ý\œ™[˜ÞH‹’”HŠJK\\Š
BˆXÚ\Ú[ÛˆHÝŠÜ™\‹™Ù]
™žLŒ—ÙXÚ\Ú[ÛˆŠHÜˆ•S”‘U’QUÑQŠBˆ\˜Ú\ÙWØÛ\ÜÈHÝŠÜ™\‹™Ù]
œ\˜Ú\ÙWØÛ\ÜÈŠHÜˆ•SÓTÔÒQ’QQŠBˆš[Üš]HH[
Ü™\‹™Ù]
™^XÝ][Û—Üš[Üš]H‹NJJBˆ™XÛÜ™HšXÙWÛX\™Ù]
XÚÙ\ŠBˆÝ\œ™[ÜšXÙHH›Ø]
™XÛÜ™˜ÛÜÙJHYˆ™XÛÜ™[ÙH›Û™BˆšXÙWÙ]HH™XÛÜ™œšXÙWÙ]Kš\ÛÙ›Ü›X]

HYˆ™XÛÜ™[ÙH›Û™Bˆš[˜[ØÙZ[[™ÈH›Ø]
Ü™\–È™š[˜[ØÙZ[[™È—JHYˆÜ™\‹™Ù]
™š[˜[ØÙZ[[™ÈŠH\È›Ý›Û™H[ÙH›Û™BˆÛÛ\]YHÙ]
X\
Ý‹Ü™\‹™Ù]
˜ÛÛ\]YÜÝ\ÚYÈ‹×JJJBˆ[™[™×Ú[™^HÜ[™[™×Ú[™^
Ü™\ŠB‚ˆ›ÜˆÝ\Ú[™^Ý\[ˆ[[Y\˜]JÜ™\‹™Ù]
›Ü™\—ÜÝ\È‹×JKÝ\LJN‚ˆÝ\ÚYHÝŠÝ\™Ù]
œÝ\ÚYŠHÜˆˆžÝXÚÙ\ŸK^ÜÝ\Ú[™^HŠBˆÚ\™\ËÚ\™\×Ü[KÚ\™WØ›ØÚÜÈHÜÚ\™\×Ù›Ü—ÜÝ\
Ü™\‹Ý\
Bˆ[[Ý[[[Ý[ÚœK[[Ý[Ø›ØÚÜÈHØ[[Ý[×Ù›Ü—ÜÝ\
Ý˜]YÞKÜ™\‹Ý\Ú\™\ËÛÝ\˜ÙJBˆ›ØÚÜÈH\Ý
Ú\™WØ›ØÚÜÊH
È\Ý
[[Ý[Ø›ØÚÜÊBˆØ\›š[™ÜÎˆ\ÝÜÝ—HH×B‚ˆYˆÝ\ÚY[ˆÛÛ\]Y‚ˆÝ]\ÈHÓÓTUQ‚ˆ\˜Ú\ÙWÙ›YÈHÓÓTUQ‚ˆXÝ[Û˜Xš[]HH‘Q•‚ˆ[Yˆ[™[™×Ú[™^\È›Ý›Û™H[™Ý\Ú[™^HHOH[™[™×Ú[™^‚ˆÝ]\ÈH•ÐRUÔ‘U’SÕT×ÔÕT‚ˆ\˜Ú\ÙWÙ›YÈH•ÐRUÔ‘U’SÕT×ÔÕT‚ˆXÝ[Û˜Xš[]HH‘Q•‚ˆ[YˆXÚ\Ú[Ûˆ›Ý[ˆPÕU‘WÑ–WÑPÒTÒSÓ”Î‚ˆÝ]\ÈHXÚ\Ú[Û‚ˆ\˜Ú\ÙWÙ›YÈHXÚ\Ú[Û‚ˆXÝ[Û˜Xš[]HH‘Q•‚ˆ[ÙN‚ˆYˆ›ÝÝ˜]YÞWØXÝ]™N‚ˆ›ØÚÜË˜\[™
”ÕUQÖWÓ“ÕÐPÕU‘HŠBˆYˆXØÛÝ[ØYÙ]\È›Û™N‚ˆ›ØÚÜË˜\[™
PÐÓÕS•Ð•QÑUÔÑPÔ‘UÔ‘TURT‘QŠBˆYˆ^Z[™×ÜÝÙ\ˆ\È›Û™HÜˆ^Z[™×ÜÝÙ\ˆH‚ˆ›ØÚÜË˜\[™
PÐÓÕS•Ð•VRS‘×ÔÕÑT—Ô‘TURT‘QŠBˆYˆ[[Ý[ÚœH\È›Ý›Û™N‚ˆ™^ØXØÛÝ[ÜÜ[™HXØÛÝ[ÜÜ[™™Ù]
XØÛÝ[Û˜[YKŒ
H
È[[Ý[ÚœBˆ™^ÚÝ\ÙZÛÜÜ[™HÝ\ÙZÛÜÜ[™
È[[Ý[ÚœBˆYˆXØÛÝ[ØYÙ]\È›Ý›Û™H[™™^ØXØÛÝ[ÜÜ[™ˆXØÛÝ[ØYÙ]‚ˆ›ØÚÜË˜\[™
PÐÓÕS•ÔÕUQÖWÐ•QÑUÑVÑQQQŠBˆYˆ^Z[™×ÜÝÙ\ˆ\È›Ý›Û™H[™[[Ý[ÚœHˆ^Z[™×ÜÝÙ\Ž‚ˆ›ØÚÜË˜\[™
PÐÓÕS•Ð•VRS‘×ÔÕÑT—ÒS”ÕQ‘’PÒQS•ŠBˆYˆÝ\ÙZÛÝ\™Ù]\È›Ý›Û™H[™™^ÚÝ\ÙZÛÜÜ[™ˆÝ\ÙZÛÝ\™Ù]‚ˆ›ØÚÜË˜\[™
’ÕTÑRÓÕT‘ÑUÐ•QÑUÑVÑQQQŠBˆYˆÝ\ÙZÛØØ\Ú\È›Ý›Û™H[™Ý\ÙZÛÜ™\Ù\™H\È›Ý›Û™H[™™^ÚÝ\ÙZÛÜÜ[™ˆÝ\ÙZÛØØ\ÚHÝ\ÙZÛÜ™\Ù\™N‚ˆ›ØÚÜË˜\[™
’ÕTÑRÓÔ‘TÑT•‘WÐ”‘PPÒŠBˆYˆ[›X[ÜÝØÚ×ØØ\\È›Ý›Û™H[™™^ØXØÛÝ[ÜÜ[™ˆ[›X[ÜÝØÚ×ØØ\‚ˆ›ØÚÜË˜\[™
PÐÓÕS•ÐS“•PSÔÕÐÒ×ÐÐTÑVÑQQQŠBˆYˆÜ™\‹™Ù]
™X\›š[™Ü×ÝØZ]ŠH[™›ÝÜ™\‹™Ù]
™X\›š[™Ü×Ü™]šY]ÙYÛÚÈŠN‚ˆ›ØÚÜË˜\[™
‘PT“’S‘Ô×Ô‘U’QU×Ô‘TURT‘QŠBˆYˆÜ™\‹™Ù]
˜ÛÛ™][Û˜[ŠH[™›ÝÜ™\‹™Ù]
˜ÛÛ™][Û—Ý™\šYšYYŠN‚ˆ›ØÚÜË˜\[™
“Ô‘T—ÐÓÓ‘USÓ—Ô‘U’QU×Ô‘TURT‘QŠBˆYˆÝ\™Ù]
˜ÛÛ™][ÛˆŠH[™›ÝÝ\™Ù]
˜ÛÛ™][Û—Ý™\šYšYYŠN‚ˆ›ØÚÜË˜\[™
”ÕTÐÓÓ‘USÓ—Ô‘U’QU×Ô‘TURT‘QŠBˆYˆÜ™\‹™Ù]
˜™[™Yš]Ý™\šYšXØ][Û—ÜÝ]\ÈŠHOH”T•PSŽ‚ˆ›ØÚÜË˜\[™
‘S‘Q’UÔ‘PÒPÒ×Ô‘TURT‘QŠBˆYˆ™XÛÜ™\È›Û™N‚ˆ›ØÚÜË˜\[™
”’PÑWÕSURSP“HŠBˆ[Yˆ
]][YK››ÝÊ[Y^›Û™K]ÊK™]J
HH™XÛÜ™œšXÙWÙ]JK™^\ÈˆN‚ˆ›ØÚÜË˜\[™
”ÕSWÔ’PÑHŠB‚ˆYˆš[˜[˜ÚX[Ø\ÜÙ]Èˆ[™Ý\œ™[ÜšXÙH\È›Ý›Û™N‚ˆ\™Ù]ÜÚ\™\ÈHÜ™\‹™Ù]
šÝ\ÙZÛÝ\™Ù]ØY\—ØÛÛ\][ÛˆŠHÜˆÜ™\‹™Ù]
\™Ù]ÜÚ\™\ÈŠHÜˆÜ™\‹™Ù]
\™Ù]ÝÝ[ÜÚ\™\ÈŠBˆYˆ\™Ù]ÜÚ\™\È\È›Ý›Û™N‚ˆ›Ú™XÝYÝÙZYÚH›Ø]
\™Ù]ÜÚ\™\ÊH
ˆÝ\œ™[ÜšXÙHÈš[˜[˜ÚX[Ø\ÜÙ]ÂˆYˆ›Ú™XÝYÝÙZYÚˆÛÛ˜Ù[˜][Û—Ú\™Û[Z]‚ˆ›ØÚÜË˜\[™
ˆÓÓÑS•USÓ—ÒT‘ÓSRUžÜ›Ú™XÝYÝÙZYÚ‹Œ‰_HŠBˆ[Yˆ›Ú™XÝYÝÙZYÚˆÛÛ˜Ù[˜][Û—Û[Z]‚ˆØ\›š[™ÜË˜\[™
ˆÓÓÑS•USÓ—ÕÐT“’S‘ÎžÜ›Ú™XÝYÝÙZYÚ‹Œ‰_HŠBˆ[Yˆ™YÚ\Ý\™YØ]]Üš]N‚ˆÈHš]˜]H™YÚ\Ý\™YÝ˜]YÞH™\]Z\™\ÈHÛÛ\]KˆÈÝ\œ™[Ý\ÙZÛ\ÜÙ][›ÛZ[˜]Ü‹ˆH\X[[BˆÈØ[››Ý™H\ÙYÈÛX\ˆ\ÈØY™]HØ]K‚ˆ›ØÚÜË˜\[™
ÓÓÑS•USÓ—ÐUQUÔ‘TURT‘QŠB‚ˆYˆÝ\œ™[ÜšXÙH\È›Û™N‚ˆ\Ý[˜ÙHH›Û™BˆÝ]\ÈH‘UWÑT”“Ôˆ‚ˆ\˜Ú\ÙWÙ›YÈH‘UWÑT”“Ôˆ‚ˆ[ÙN‚ˆ\Ý[˜ÙHH›Ý[™

Ý\œ™[ÜšXÙHH›Ø]
Ý\È›[Z]ÜšXÙH—JJHÈ›Ø]
Ý\È›[Z]ÜšXÙH—JH
ˆLŠBˆ]ÛÜ—Ø™[ÝÈHÝ\œ™[ÜšXÙHH›Ø]
Ý\È›[Z]ÜšXÙH—JBˆ™X\ˆHÝ\œ™[ÜšXÙHH›Ø]
Ý\È›[Z]ÜšXÙH—JH
ˆKŒBˆX›Ý™WØÙZ[[™ÈHš[˜[ØÙZ[[™È\È›Ý›Û™H[™Ý\œ™[ÜšXÙHˆš[˜[ØÙZ[[™ÂˆYˆX›Ý™WØÙZ[[™Î‚ˆÝ]\ÈHP“Õ‘WÐÑRSS‘È‚ˆ\˜Ú\ÙWÙ›YÈH•ÐRUÔ’PÑH‚ˆ[Yˆ]ÛÜ—Ø™[ÝÈ[™›ØÚÜÎ‚ˆÝ]\ÈH“ÐÒÑQÐUÓSRU‚ˆ\˜Ú\ÙWÙ›YÈH”‘U’QU×Ô‘TURT‘Q‚ˆ[Yˆ]ÛÜ—Ø™[ÝÎ‚ˆÝ]\ÈH”‘PQH‚ˆ\˜Ú\ÙWÙ›YÈH”TÒTÑWÔ‘PQH‚ˆ[Yˆ™X\Ž‚ˆÝ]\ÈH“‘PTˆ‚ˆ\˜Ú\ÙWÙ›YÈH•ÐRUÔ’PÑH‚ˆ[ÙN‚ˆÝ]\ÈH•ÐRU‚ˆ\˜Ú\ÙWÙ›YÈH•ÐRUÔ’PÑH‚ˆXÝ[Û˜Xš[]HH”‘PQHˆYˆ\˜Ú\ÙWÙ›YÈOH”TÒTÑWÔ‘PQHˆ[™›Ý›ØÚÜÈ[ÙH‘Q•‚‚ˆYˆÝ\œ™[ÜšXÙH\È›Û™N‚ˆ\Ý[˜ÙHH›Û™Bˆ[Yˆ	Ù\Ý[˜ÙIÈ›Ý[ˆØØ[Ê
HÜˆÝ\ÚY[ˆÛÛ\]YÜˆ
[™[™×Ú[™^\È›Ý›Û™H[™Ý\Ú[™^HHOH[™[™×Ú[™^
HÜˆXÚ\Ú[Ûˆ›Ý[ˆPÕU‘WÑ–WÑPÒTÒSÓ”Î‚ˆ\Ý[˜ÙHH›Ý[™

Ý\œ™[ÜšXÙHH›Ø]
Ý\È›[Z]ÜšXÙH—JJHÈ›Ø]
Ý\È›[Z]ÜšXÙH—JH
ˆLŠB‚ˆ›ÝWÜ\ÈHÂˆÝŠÜ™\‹™Ù]
››ÝHŠHÜˆˆŠKœÝš\

KˆÝŠÜ™\‹™Ù]
œ[HŠHÜˆˆŠKœÝš\

KˆÝŠÜ™\‹™Ù]
˜ÛÛ˜Ù[˜][Û—ÝØ\›š[™ÈŠHÜˆˆŠKœÝš\

KˆBˆÚYÛ˜[Ë˜\[™
Ý˜]YÞSÜ™\”ÚYÛ˜[
ˆÝ˜]YÞWÚY\ÝŠÝ˜]YÞVÈœÝ˜]YÞWÚY—JKˆXØÛÝ[XXØÛÝ[Û˜[YKˆXÚÙ\]XÚÙ\‹ˆ˜[YO\ÝŠÜ™\‹™Ù]
›˜[YHŠHÜˆXÚÙ\ŠKˆX\šÙ][X\šÙ]ˆÝ\œ™[˜ÞOXÝ\œ™[˜ÞKˆ\œÜÙO\ÝŠÜ™\‹™Ù]
œ\œÜÙHŠHÜˆˆŠKˆžLŒ—ÙXÚ\Ú[ÛYXÚ\Ú[Û‹ˆ\˜Ú\ÙWØÛ\ÜÏ\\˜Ú\ÙWØÛ\ÜËˆ^XÝ][Û—Üš[Üš]O\š[Üš]KˆÝ\ÚY\Ý\ÚYˆÝ\Ú[™^\Ý\Ú[™^ˆÚ\™\Ï\Ú\™\ËˆÚ\™\×Ü[O\Ú\™\×Ü[Kˆ[Z]ÜšXÙOY›Ø]
Ý\È›[Z]ÜšXÙH—JKˆÝ\œ™[ÜšXÙOXÝ\œ™[ÜšXÙKˆšXÙWÙ]O\šXÙWÙ]Kˆ\Ý[˜ÙWÝ×Û[Z]Ü\˜Ù[Y\Ý[˜ÙKˆÝ]\Ï\Ý]\Ëˆ\˜Ú\ÙWÙ›YÏ\\˜Ú\ÙWÙ›YËˆXÝ[Û˜Xš[]OXXÝ[Û˜Xš[]Kˆ›ØÚÜÏ\ÛÜY
Ù]
›ØÚÜÊJKˆØ\›š[™ÜÏ\ÛÜY
Ù]
Ø\›š[™ÜÊJKˆÛÛ\][Û—ÙXY[™O[Ü™\‹™Ù]
˜ÛÛ\][Û—ÙXY[™HŠKˆš[˜[ØÙZ[[™ÏYš[˜[ØÙZ[[™Ëˆ\Ý[X]YØ[[Ý[X[[Ý[ˆ\Ý[X]YØ[[Ý[ÚœOX[[Ý[ÚœKˆ›ÝOHˆÈ‹š›Ú[Š\›Üˆ\[ˆ›ÝWÜ\ÈYˆ\
HÜˆ›Û™KˆÙ[™\˜]YØ][›ÝËˆ
JBˆYˆ	Ù\Ý[˜ÙIÈ[ˆØØ[Ê
N‚ˆ[\Ý[˜ÙB‚ˆX^ÙZ[WÛÜ™\œÈHX^
K[
ÛÝ\˜ÙK™Ù]
’Ô×ÔÕUQÖWÓPVÑRSWÓÔ‘T”È‹Ý˜]YÞK™Ù]
œ\˜Ú\ÙWØ]]Üš]H‹ßJK™Ù]
›X^ÚÝ\ÙZÛÛÜ™\œ×Ü\—Ù^H‹JJJJBˆ™XYWÚ[™XÙ\ÈHÚ[™^›Üˆ[™^ÚYÛ˜[[ˆ[[Y\˜]JÚYÛ˜[ÊHYˆÚYÛ˜[˜XÝ[Û˜Xš[]HOH”‘PQH—Bˆ™XYWÚ[™XÙ\ËœÛÜ
Ù^O[[X™H[™^ˆ
ˆÚYÛ˜[ÖÚ[™^K™^XÝ][Û—Üš[Üš]KˆÚYÛ˜[ÖÚ[™^K˜XØÛÝ[ˆÚYÛ˜[ÖÚ[™^K™\Ý[˜ÙWÝ×Û[Z]Ü\˜Ù[YˆÚYÛ˜[ÖÚ[™^K™\Ý[˜ÙWÝ×Û[Z]Ü\˜Ù[\È›Ý›Û™H[ÙHNNKˆÚYÛ˜[ÖÚ[™^KXÚÙ\‹ˆ
JBˆ›Üˆ[™^[ˆ™XYWÚ[™XÙ\ÖÛX^ÙZ[WÛÜ™\œÎ—N‚ˆÚYÛ˜[HÚYÛ˜[ÖÚ[™^BˆÚYÛ˜[ÖÚ[™^HH™\XÙJˆÚYÛ˜[ˆÝ]\ÏH“ÐÒÑQÑRSWÓÔ‘T—ÓSRU‹ˆ\˜Ú\ÙWÙ›YÏH•ÐRUÑRSWÓSRU‹ˆXÝ[Û˜Xš[]OH‘Q•‹ˆ›ØÚÜÏ\ÛÜY
Ù]
ÚYÛ˜[˜›ØÚÜÈ
ÈÈ‘RSWÓÔ‘T—ÓSRU—JJKˆ
Bˆ™]\›ˆÚYÛ˜[Â‚‚™YˆÜš]WÜÝ˜]YÞWÛÝ]]
ÚYÛ˜[Îˆ\ÝÔÝ˜]YÞSÜ™\”ÚYÛ˜[KÝ]]Ü]ˆ]
HOˆ›Û™N‚ˆÝ]]Ü]œ\™[›ZÙ\Š\™[ÏUYK^\ÝÛÚÏUYJBˆÝ]]Ü]Üš]WÝ^
œÛÛ‹™[\ÊÂˆ™\œÚ[ÛˆŽˆ‹ˆœÝ˜]YÞWÚYŽˆÚYÛ˜[ÖÌKœÝ˜]YÞWÚYYˆÚYÛ˜[È[ÙH›Û™KˆœÚYÛ˜[ÈŽˆØ\ÙXÝ
ÚYÛ˜[
H›ÜˆÚYÛ˜[[ˆÚYÛ˜[×Kˆ™Ù[™\˜]YØ]Žˆ]][YK››ÝÊ[Y^›Û™K]ÊKš\ÛÙ›Ü›X]

KˆK[œÝ\™WØ\ØÚZOQ˜[ÙK[™[LŠK[˜ÛÙ[™ÏH]‹NŠB‚‚™YˆÛ[Û™^J˜[YNˆ›Ø]›Û™KÝ\œ™[˜ÞNˆÝŠHOˆÝŽ‚ˆYˆ˜[YH\È›Û™N‚ˆ™]\›ˆ¹§*¹cå¹o¥È‚ˆÞ[X›ÛH°©HˆYˆÝ\œ™[˜ÞHOH’”Hˆ[ÙH‰‚ˆXÚ[X[ÈHYˆÝ\œ™[˜ÞHOH’”Hˆ[ÙH‚ˆ™]\›ˆˆžÜÞ[X›Û^Ý˜[YN‹žÙXÚ[X[ßYŸH‚‚‚™Yˆ™[™\—ÜÝ˜]YÞWÛ›ÝYšXØ][ÛŠÚYÛ˜[Îˆ\ÝÔÝ˜]YÞSÜ™\”ÚYÛ˜[K[Z]ˆ[HJHOˆÝˆ›Û™N‚ˆ™[]˜[HÜÚYÛ˜[›ÜˆÚYÛ˜[[ˆÚYÛ˜[ÈYˆÚYÛ˜[œÝ]\È[ˆÈ”‘PQH‹“ÐÒÑQÐUÓSRU‹“‘PTˆ‹P“Õ‘WÐÑRSS‘È‹“ÐÒÑQÑRSWÓÔ‘T—ÓSRUŸWBˆYˆ›Ý™[]˜[‚ˆ™]\›ˆ›Û™Bˆ˜[šÈHÈ”‘PQHŽˆ“ÐÒÑQÐUÓSRUŽˆK“ÐÒÑQÑRSWÓÔ‘T—ÓSRUŽˆ‹“‘PTˆŽˆËP“Õ‘WÐÑRSS‘ÈŽˆBˆ™[]˜[œÛÜ
Ù^O[[X™HÚYÛ˜[ˆ
ˆ˜[šË™Ù]
ÚYÛ˜[œÝ]\ËJKˆÚYÛ˜[™^XÝ][Û—Üš[Üš]KˆÚYÛ˜[˜XØÛÝ[ˆÚYÛ˜[™\Ý[˜ÙWÝ×Û[Z]Ü\˜Ù[YˆÚYÛ˜[™\Ý[˜ÙWÝ×Û[Z]Ü\˜Ù[\È›Ý›Û™H[ÙHNNKˆ
JBˆ[™\ÈHÂˆˆ¼'ã«È9ænúc,¹¢)¹åiHÜ™[]˜[ÌKœÝ˜]YÞWÚYH‹ˆ”TÒTÑWÔ‘PQy.éyi%¸àkùæn¹¬ê9é y«h»ïg9fî¹k¦¹£!ù`)8àîùcèùn©ù.¢9ë¥øàîù¬n¹ë¥ùæèù§îøà¤¹a*¹ab‹ˆBˆX™[ÈHÂˆ”‘PQHŽˆ¸§!HTÒTÑWÔ‘PQH‹ˆ“ÐÒÑQÐUÓSRUŽˆ¼'æäH9£!ù`)9b,:`e8àîùè®º*£yo¡xàhH‹ˆ“ÐÒÑQÑRSWÓÔ‘T—ÓSRUŽˆ¸£ë{î#È9§+9¥éxàk¹¬ê9¥¡ù."ºfd‹ˆ“‘PTˆŽˆ¼'çèH9£!ù`)9£©z/äH‹ˆP“Õ‘WÐÑRSS‘ÈŽˆ¸£î;î#È9."ºfd:-¡z`cˆ‹ˆBˆ›ÜˆÚYÛ˜[[ˆ™[]˜[Î›[Z]N‚ˆÚ\™\ÈHˆžÜÚYÛ˜[œÚ\™\ßy¨*ˆˆYˆÚYÛ˜[œÚ\™\È\È›Ý›Û™H[ÙH
ÚYÛ˜[œÚ\™\×Ü[HÜˆ¹¨*¹¥l9§*¹è®¹k¦ˆŠBˆ[™\Ë˜\[™
ˆˆžÛX™[ÖÜÚYÛ˜[œÝ]\×_{ïgÜÚYÛ˜[˜XØÛÝ[{ïgÜÚYÛ˜[XÚÙ\ŸHÜÚYÛ˜[›˜[Y_{ïg‚ˆˆ¹ãï¹g*×Û[Û™^JÚYÛ˜[˜Ý\œ™[ÜšXÙKÚYÛ˜[˜Ý\œ™[˜ÞJ_HÈ9£!ù`)×Û[Û™^JÚYÛ˜[›[Z]ÜšXÙKÚYÛ˜[˜Ý\œ™[˜ÞJ_{ïgÜÚ\™\ßH‚ˆ
BˆYˆÚYÛ˜[˜›ØÚÜÈ[™ÚYÛ˜[œÝ]\È[ˆÈ“ÐÒÑQÐUÓSRU‹“ÐÒÑQÑRSWÓÔ‘T—ÓSRUŸN‚ˆ[™\Ë˜\[™
ˆˆ9§*¹è®º*£NˆÉË	Ëš›Ú[ŠÚYÛ˜[˜›ØÚÜÖÎŒ×J_HŠBˆYˆ[Š™[]˜[
Hˆ[Z]‚ˆ[™\Ë˜\[™
ˆ¸ànøàbÈÛ[Š™[]˜[
HH[Z]y.í¸àkÈÝ]]ËÜÝ˜]YÞWÛÜ™\—Ü[‹šœÛÛˆŠBˆ™]\›ˆ—ˆ‹š›Ú[Š[™\ÊB