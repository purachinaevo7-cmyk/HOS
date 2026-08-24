"""Non-mutating reconciliation between private holdings and HOS step records."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import math
from typing import Any, Mapping


@dataclass(frozen=True)
class ReconciliationFinding:
    account: str
    ticker: str
    expected_shares: int | None
    actual_shares: int | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _whole(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        return None
    return int(number)


def _holding_shares(profile: Mapping[str, Any]) -> dict[tuple[str, str], int | None]:
    values: dict[tuple[str, str], int | None] = {}
    for holding in profile.get("holdings", []) if isinstance(profile, Mapping) else []:
        if not isinstance(holding, Mapping):
            continue
        owner, ticker = str(holding.get("owner") or ""), str(holding.get("ticker") or holding.get("id") or "")
        if not owner or not ticker:
            continue
        values[(owner, ticker)] = _whole(holding.get("shares")) if holding.get("verified") else None
    return values


def _expected_shares(order: Mapping[str, Any]) -> tuple[int | None, str | None]:
    baseline = _whole(order.get("strategy_start_shares"))
    if baseline is None:
        baseline = _whole(order.get("current_shares"))
    if baseline is None:
        return None, "STRATEGY_BASELINE_REQUIRED"
    completed = {str(step_id) for step_id in order.get("completed_step_ids", [])}
    total = baseline
    for step in order.get("order_steps", []):
        if str(step.get("step_id") or "") not in completed:
            continue
        shares = _whole(step.get("shares"))
        if shares is None:
            return None, "COMPLETED_STEP_SHARES_UNCONFIRMED"
        total += shares
    return total, None


def reconcile_private_holdings(profile: Mapping[str, Any], strategy: Mapping[str, Any]) -> tuple[dict[str, Any], list[ReconciliationFinding]]:
    """Annotate a copied strategy; never mark a step completed automatically."""
    result = deepcopy(dict(strategy))
    actuals = _holding_shares(profile)
    findings: list[ReconciliationFinding] = []
    for account, account_data in result.get("accounts", {}).items():
        for order in account_data.get("orders", []):
            ticker = str(order.get("ticker") or "")
            expected, error = _expected_shares(order)
            actual = actuals.get((str(account), ticker))
            if error:
                finding = ReconciliationFinding(str(account), ticker, expected, actual, error)
            elif (str(account), ticker) not in actuals:
                finding = ReconciliationFinding(str(account), ticker, expected, None, "HOLDING_SNAPSHOT_REQUIRED")
            elif actual is None:
                finding = ReconciliationFinding(str(account), ticker, expected, None, "HOLDING_SNAPSHOT_UNVERIFIED")
            elif actual != expected:
                finding = ReconciliationFinding(str(account), ticker, expected, actual, "HOLDING_AND_EXECUTION_MISMATCH")
            else:
                order["execution_reconciliation_required"] = False
                continue
            order["execution_reconciliation_required"] = True
            order["execution_reconciliation_reason"] = finding.reason
            findings.append(finding)
    return result, findings
