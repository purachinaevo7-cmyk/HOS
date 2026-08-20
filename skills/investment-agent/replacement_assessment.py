"""Advisory-only incumbent vs challenger replacement assessment for HOS.

The engine is intentionally disabled for execution. It can rank and explain a
possible replacement, but it never sells or buys anything. A challenger must
improve the household goal materially, not merely look exciting this week.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class ReplacementVerdict:
    decision: str
    incumbent_score: float | None
    challenger_score: float | None
    score_advantage: float | None
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_policy(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def replacement_triggered(incumbent: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[bool, list[str]]:
    triggers = policy.get("triggers", {})
    reasons: list[str] = []
    if triggers.get("earnings_negative") and incumbent.get("earnings_state") == "NEGATIVE":
        reasons.append("EARNINGS_NEGATIVE")
    if triggers.get("dividend_cut_or_suspension") and incumbent.get("dividend_thesis_broken"):
        reasons.append("DIVIDEND_THESIS_BROKEN")
    if triggers.get("structural_thesis_break") and incumbent.get("structural_thesis_broken"):
        reasons.append("STRUCTURAL_THESIS_BROKEN")
    if triggers.get("two_consecutive_neutral_earnings") and int(incumbent.get("consecutive_neutral_earnings") or 0) >= 2:
        reasons.append("TWO_CONSECUTIVE_NEUTRAL_EARNINGS")
    if triggers.get("hard_concentration_breach") and incumbent.get("hard_concentration_breach"):
        reasons.append("HARD_CONCENTRATION_BREACH")
    return bool(reasons), reasons


def _score(candidate: Mapping[str, Any], weights: Mapping[str, Any]) -> tuple[float | None, list[str]]:
    required = {
        "cash_dividend_contribution": "cash_dividend_contribution",
        "earnings_quality_and_growth": "earnings_quality_and_growth",
        "valuation_and_entry_margin": "valuation_and_entry_margin",
        "portfolio_diversification": "portfolio_diversification",
        "shareholder_return_durability": "shareholder_return_durability",
    }
    missing = [field for field in required.values() if candidate.get(field) is None]
    if missing:
        return None, [f"MISSING_SCORE:{field}" for field in missing]
    total_weight = sum(float(weights.get(key, 0)) for key in required)
    if total_weight <= 0:
        return None, ["INVALID_SCORE_WEIGHTS"]
    weighted = 0.0
    for key, field in required.items():
        value = float(candidate[field])
        if not 0 <= value <= 100:
            return None, [f"INVALID_SCORE_RANGE:{field}"]
        weighted += value * float(weights.get(key, 0))
    return round(weighted / total_weight, 1), []


def compare_replacement(
    incumbent: Mapping[str, Any],
    challenger: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> ReplacementVerdict:
    """Compare only after a legitimate replacement trigger exists."""
    triggered, trigger_reasons = replacement_triggered(incumbent, policy)
    if not triggered:
        return ReplacementVerdict("KEEP", None, None, None, ["NO_REPLACEMENT_TRIGGER"])

    requirements = policy.get("candidate_requirements", {})
    blockers: list[str] = []
    if requirements.get("official_ir_verified") and not challenger.get("official_ir_verified"):
        blockers.append("CHALLENGER_IR_NOT_VERIFIED")
    if requirements.get("same_or_better_portfolio_role") and not challenger.get("role_compatible"):
        blockers.append("PORTFOLIO_ROLE_MISMATCH")
    if requirements.get("no_purchase_hard_block") and challenger.get("purchase_hard_block"):
        blockers.append("CHALLENGER_PURCHASE_HARD_BLOCK")
    if requirements.get("turnover_cost_check_required") and not challenger.get("turnover_cost_reviewed"):
        blockers.append("TURNOVER_COST_NOT_REVIEWED")
    if blockers:
        return ReplacementVerdict("WATCH", None, None, None, trigger_reasons + blockers)

    weights = policy.get("score_weights", {})
    incumbent_score, incumbent_errors = _score(incumbent, weights)
    challenger_score, challenger_errors = _score(challenger, weights)
    if incumbent_errors or challenger_errors:
        return ReplacementVerdict("WATCH", incumbent_score, challenger_score, None, trigger_reasons + incumbent_errors + challenger_errors)

    assert incumbent_score is not None and challenger_score is not None
    advantage = round(challenger_score - incumbent_score, 1)
    min_advantage = float(requirements.get("minimum_score_advantage", 15))
    min_quality = float(requirements.get("minimum_quality_score", 55))
    if challenger_score < min_quality:
        return ReplacementVerdict("WATCH", incumbent_score, challenger_score, advantage, trigger_reasons + ["CHALLENGER_QUALITY_TOO_LOW"])
    if advantage < min_advantage:
        return ReplacementVerdict("KEEP", incumbent_score, challenger_score, advantage, trigger_reasons + ["INSUFFICIENT_REPLACEMENT_EDGE"])

    decision = "EXIT_REVIEW" if incumbent.get("structural_thesis_broken") or incumbent.get("dividend_thesis_broken") else "REPLACE_CANDIDATE"
    return ReplacementVerdict(decision, incumbent_score, challenger_score, advantage, trigger_reasons + ["MATERIAL_CHALLENGER_EDGE"])
