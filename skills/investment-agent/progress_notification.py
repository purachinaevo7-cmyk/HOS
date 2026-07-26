"""Compact household progress block for Discord investment notifications."""
from __future__ import annotations

import math
import os
from typing import Any, Iterable, Mapping


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _env_number(key: str | None, env: Mapping[str, str]) -> float | None:
    return _number(env.get(key)) if key else None


def _progress_bar(current: float | None, target: float | None, width: int = 10) -> str:
    if current is None or target is None or target <= 0:
        return "??????????"
    ratio = max(0.0, min(current / target, 1.0))
    filled = min(width, int(ratio * width))
    return "■" * filled + "□" * (width - filled)


def _percent(current: float | None, target: float | None) -> str:
    if current is None or target is None or target <= 0:
        return "未設定"
    return f"{current / target * 100:.1f}%"


def _compact_yen(value: float | None) -> str:
    if value is None:
        return "未設定"
    if value >= 100_000_000 and value % 100_000_000 == 0:
        return f"{value / 100_000_000:,.0f}億円"
    if value >= 10_000:
        return f"{value / 10_000:,.1f}万円".replace(".0万円", "万円")
    return f"{value:,.0f}円"


def build_progress_snapshot(
    policy: Mapping[str, Any],
    strategy: Mapping[str, Any],
    signals: Iterable[Any],
    env: Mapping[str, str] | None = None,
) -> dict[str, float | None]:
    source = env if env is not None else os.environ
    current_assets = _number(policy.get("current_financial_assets"))
    target_assets = _number(policy.get("target_asset_value_at_age_60"))
    current_dividend = _env_number("HOS_CURRENT_ANNUAL_DIVIDEND_JPY", source)
    if current_dividend is None:
        current_dividend = _number(policy.get("current_annual_dividend"))
    target_dividend = _number(policy.get("target_annual_dividend"))

    target_investment = _env_number(
        strategy.get("funding", {}).get("target_investment_to_2027_03_jpy_env"),
        source,
    )
    completed_investment = sum(
        float(getattr(signal, "estimated_amount_jpy", 0) or 0)
        for signal in signals
        if getattr(signal, "status", None) == "COMPLETED"
    )
    remaining_investment = (
        max(0.0, target_investment - completed_investment)
        if target_investment is not None
        else None
    )
    return {
        "current_assets": current_assets,
        "target_assets": target_assets,
        "current_dividend": current_dividend,
        "target_dividend": target_dividend,
        "completed_investment": completed_investment,
        "target_investment": target_investment,
        "remaining_investment": remaining_investment,
    }


def render_goal_progress(
    policy: Mapping[str, Any],
    strategy: Mapping[str, Any],
    signals: Iterable[Any],
    env: Mapping[str, str] | None = None,
) -> str:
    snapshot = build_progress_snapshot(policy, strategy, list(signals), env)
    assets_bar = _progress_bar(snapshot["current_assets"], snapshot["target_assets"])
    dividend_bar = _progress_bar(snapshot["current_dividend"], snapshot["target_dividend"])
    investment_bar = _progress_bar(snapshot["completed_investment"], snapshot["target_investment"])

    lines = [
        "📈 世帯目標の進捗",
        f"資産 {assets_bar} {_percent(snapshot['current_assets'], snapshot['target_assets'])}｜{_compact_yen(snapshot['current_assets'])} / {_compact_yen(snapshot['target_assets'])}",
    ]
    if snapshot["current_dividend"] is None:
        lines.append(f"配当 {dividend_bar} 現在額未設定｜目標 {_compact_yen(snapshot['target_dividend'])}/年")
    else:
        lines.append(
            f"配当 {dividend_bar} {_percent(snapshot['current_dividend'], snapshot['target_dividend'])}｜"
            f"{_compact_yen(snapshot['current_dividend'])} / {_compact_yen(snapshot['target_dividend'])}/年"
        )
    if snapshot["target_investment"] is not None:
        lines.append(
            f"年度投資 {investment_bar} {_percent(snapshot['completed_investment'], snapshot['target_investment'])}｜"
            f"実行 {_compact_yen(snapshot['completed_investment'])} / {_compact_yen(snapshot['target_investment'])}｜"
            f"残り {_compact_yen(snapshot['remaining_investment'])}"
        )
    else:
        lines.append("年度投資 ?????????? 目標額未設定")
    return "\n".join(lines)
