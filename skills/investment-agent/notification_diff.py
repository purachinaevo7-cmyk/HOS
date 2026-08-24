"""Private, diff-first notification state for HOS Discord reports.

The state intentionally lives only in the private profile (or another private
state store selected by the operator). This public repository never writes the
state to Actions artifacts, git, logs, or summaries.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class NotificationChange:
    priority: int
    category: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _key(account: Any, ticker: Any) -> str:
    return f"{str(account)}:{str(ticker)}"


def _orders(strategy: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {
        (str(account), str(order.get("ticker") or "")): order
        for account, account_data in strategy.get("accounts", {}).items()
        for order in account_data.get("orders", [])
    }


def build_private_notification_state(strategy: Mapping[str, Any], signals: Iterable[Any], dividends: Any, replacements: Mapping[str, Any] | None = None) -> dict[str, Any]:
    order_map = _orders(strategy)
    signal_state: dict[str, dict[str, Any]] = {}
    for signal in signals:
        if getattr(signal, "status", "") == "COMPLETED":
            continue
        account, ticker = str(getattr(signal, "account", "")), str(getattr(signal, "ticker", ""))
        key = _key(account, ticker)
        current = signal_state.get(key)
        # Step 1 is the meaningful summary when later steps are intentionally
        # waiting. A READY or explicit stop wins if present.
        row = {
            "account": account,
            "ticker": ticker,
            "name": str(getattr(signal, "name", "") or ticker),
            "status": str(getattr(signal, "status", "")),
            "actionability": str(getattr(signal, "actionability", "")),
            "earnings": str(order_map.get((account, ticker), {}).get("earnings_review_status") or "NEEDS_DATA"),
            "blocks": sorted(str(item) for item in (getattr(signal, "blocks", []) or [])),
        }
        if current is None or row["actionability"] == "READY" or ("EARNINGS_NEGATIVE" in row["blocks"] and "EARNINGS_NEGATIVE" not in current["blocks"]):
            signal_state[key] = row
    dividend_state: dict[str, float] = {}
    for line in getattr(dividends, "lines", []):
        if getattr(line, "scope", "CURRENT") != "CURRENT" or getattr(line, "status", "") != "CONFIRMED":
            continue
        key = _key(getattr(line, "owner", ""), getattr(line, "ticker", ""))
        dividend_state[key] = round(dividend_state.get(key, 0.0) + float(getattr(line, "ordinary_cash_jpy", 0) or 0), 2)
    reconciliation = {
        _key(item.get("account"), item.get("ticker")): {
            "expected_shares": item.get("expected_shares"),
            "actual_shares": item.get("actual_shares"),
            "reason": item.get("reason"),
        }
        for item in strategy.get("execution_reconciliation_audit", [])
        if isinstance(item, Mapping)
    }
    return {"version": 1, "signals": signal_state, "dividends": dividend_state, "reconciliation": reconciliation, "replacements": dict(replacements or {})}


def _previous(previous: Mapping[str, Any] | None, section: str) -> Mapping[str, Any]:
    value = previous.get(section, {}) if isinstance(previous, Mapping) else {}
    return value if isinstance(value, Mapping) else {}


def diff_private_notification_state(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> list[NotificationChange]:
    """Return only judgment changes, ordered by purchase safety priority."""
    old_signals, new_signals = _previous(previous, "signals"), _previous(current, "signals")
    changes: list[NotificationChange] = []
    for key, row in new_signals.items():
        if not isinstance(row, Mapping):
            continue
        old = old_signals.get(key, {}) if isinstance(old_signals.get(key), Mapping) else {}
        name = str(row.get("name") or row.get("ticker") or "銘柄")
        if row.get("actionability") == "READY" and old.get("actionability") != "READY":
            changes.append(NotificationChange(1, "PURCHASE_READY", f"✅ {name}\n{old.get('status') or '監視'} → PURCHASE_READY\n※固定指値・買付余力・予算等の全ゲートは継続"))
        new_blocks, old_blocks = set(row.get("blocks") or []), set(old.get("blocks") or [])
        if ("EARNINGS_NEGATIVE" in new_blocks and "EARNINGS_NEGATIVE" not in old_blocks) or ("EARNINGS_NEUTRAL" in new_blocks and "EARNINGS_NEUTRAL" not in old_blocks):
            decision = "NEGATIVE" if "EARNINGS_NEGATIVE" in new_blocks else "NEUTRAL"
            changes.append(NotificationChange(2, "PURCHASE_STOP", f"🛑 {name}\n{old.get('status') or '購入候補'} → 決算{decision}\n→ 購入停止・入替監査"))
        if row.get("earnings") != old.get("earnings"):
            state = str(row.get("earnings") or "NEEDS_DATA")
            if state == "POSITIVE":
                changes.append(NotificationChange(3, "EARNINGS", f"✅ {name}\n{old.get('earnings') or 'HOS決算監査待ち'} → 決算POSITIVE\n→ 購入候補維持"))
            elif state == "NEEDS_DATA":
                changes.append(NotificationChange(3, "EARNINGS", f"⚠️ {name}\n{old.get('earnings') or '決算評価'} → HOS決算監査待ち\n→ 購入停止"))
        if row.get("status") == "NEAR" and old.get("status") != "NEAR":
            changes.append(NotificationChange(6, "LIMIT_NEAR", f"🟡 {name}\n指値接近。購入可否は全ゲート通過時のみ判定"))
    old_dividends, new_dividends = _previous(previous, "dividends"), _previous(current, "dividends")
    for key, value in new_dividends.items():
        old = old_dividends.get(key)
        if old is None or float(old) == float(value):
            continue
        row = new_signals.get(key, {}) if isinstance(new_signals.get(key), Mapping) else {}
        name = str(row.get("name") or key.split(":", 1)[-1])
        delta = float(value) - float(old)
        changes.append(NotificationChange(4, "DIVIDEND", f"⬆ {name}\n年間予想配当 {float(old):,.0f}円 → {float(value):,.0f}円\n世帯年間配当 {delta:+,.0f}円"))
    old_recon, new_recon = _previous(previous, "reconciliation"), _previous(current, "reconciliation")
    for key, row in new_recon.items():
        if key in old_recon or not isinstance(row, Mapping):
            continue
        ticker = key.split(":", 1)[-1]
        expected, actual = row.get("expected_shares"), row.get("actual_shares")
        detail = f"HOS記録 {expected}株｜現在保有 {actual}株" if expected is not None and actual is not None else "保有株数またはHOS記録の照合が必要"
        changes.append(NotificationChange(2, "RECONCILIATION", f"⚠️ {ticker}\n{detail}\n→ 約定確認が完了するまで次Stepを停止"))
    old_replacements, new_replacements = _previous(previous, "replacements"), _previous(current, "replacements")
    for ticker, decision in new_replacements.items():
        if decision == "REPLACE_REVIEW" and old_replacements.get(ticker) != decision:
            changes.append(NotificationChange(5, "REPLACEMENT", f"🔎 {ticker}\nREPLACE_REVIEW：人間による入替監査候補\n※自動売却・自動注文は行いません"))
    return sorted(changes, key=lambda item: (item.priority, item.category, item.text))
