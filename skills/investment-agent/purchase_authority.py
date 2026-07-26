"""Final purchase-authority gate for Stock Watch V3.

The generic scanner may detect price events, but only an audited registered
strategy step can emit PURCHASE_READY. This module is intentionally small so the
safety rule is easy to review and hard to accidentally bypass.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any


def _registered_tickers(strategy: dict[str, Any]) -> set[str]:
    return {
        str(order["ticker"])
        for account in strategy.get("accounts", {}).values()
        for order in account.get("orders", [])
    }


def enforce_registered_strategy_only(decisions: list[Any], strategy: dict[str, Any]) -> list[Any]:
    mode = str(strategy.get("purchase_authority", {}).get("mode") or "").upper()
    if mode != "REGISTERED_STRATEGY_ONLY":
        return decisions

    registered = _registered_tickers(strategy)
    result: list[Any] = []
    for row in decisions:
        generic_buy = row.status in {"BUY", "BUY_CANDIDATE"} or row.actionability == "READY"
        if not generic_buy:
            result.append(row)
            continue
        controlled = row.ticker in registered
        result.append(replace(
            row,
            status="BUY_CANDIDATE",
            actionability="STRATEGY_CONTROLLED" if controlled else "RESEARCH_ONLY",
            order_plan_status="DRAFT",
            limit_price=None,
            entry_2=None,
            entry_3=None,
            recommended_shares=None,
            estimated_amount=None,
            reasons=row.reasons + [
                "登録戦略のPURCHASE_READY以外は発注禁止。"
                + ("口座別固定指値を参照" if controlled else "監視外候補は再分析して戦略登録が必要")
            ],
        ))
    return result
