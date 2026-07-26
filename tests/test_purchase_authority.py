from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from purchase_authority import enforce_registered_strategy_only


@dataclass(frozen=True)
class FakeDecision:
    ticker: str
    status: str
    actionability: str
    order_plan_status: str = "READY"
    limit_price: float | None = 1000
    entry_2: float | None = 900
    entry_3: float | None = 800
    recommended_shares: int | None = 100
    estimated_amount: float | None = 100000
    reasons: list[str] = None

    def __post_init__(self):
        if self.reasons is None:
            object.__setattr__(self, "reasons", [])


def strategy():
    return {
        "purchase_authority": {"mode": "REGISTERED_STRATEGY_ONLY"},
        "accounts": {
            "maho": {"orders": [{"ticker": "8316"}]},
        },
    }


def test_registered_generic_buy_becomes_strategy_controlled_draft():
    row = FakeDecision("8316", "BUY", "READY")
    result = enforce_registered_strategy_only([row], strategy())[0]
    assert result.actionability == "STRATEGY_CONTROLLED"
    assert result.order_plan_status == "DRAFT"
    assert result.recommended_shares is None
    assert result.limit_price is None


def test_unregistered_generic_buy_becomes_research_only_not_order():
    row = FakeDecision("9999", "BUY_CANDIDATE", "READY")
    result = enforce_registered_strategy_only([row], strategy())[0]
    assert result.actionability == "RESEARCH_ONLY"
    assert result.order_plan_status == "DRAFT"
    assert result.recommended_shares is None


def test_non_buy_signal_is_unchanged():
    row = FakeDecision("9999", "WATCH", "WAIT", order_plan_status="DRAFT")
    result = enforce_registered_strategy_only([row], strategy())[0]
    assert result == row
