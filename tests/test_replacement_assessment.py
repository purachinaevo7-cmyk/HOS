from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from replacement_assessment import compare_replacement, evaluate_private_replacement_book, load_policy

POLICY = load_policy(BASE / "config" / "replacement_policy.json")


def scored_candidate(**overrides):
    row = {
        "cash_dividend_contribution": 60,
        "earnings_quality_and_growth": 60,
        "valuation_and_entry_margin": 60,
        "portfolio_diversification": 60,
        "shareholder_return_durability": 60,
        "official_ir_verified": True,
        "role_compatible": True,
        "portfolio_role": "CORE_DIVIDEND",
        "purchase_hard_block": False,
        "turnover_cost_reviewed": True,
    }
    row.update(overrides)
    return row


def test_no_trigger_means_keep_even_for_stronger_challenger():
    incumbent = scored_candidate()
    challenger = scored_candidate(cash_dividend_contribution=100, earnings_quality_and_growth=100)
    verdict = compare_replacement(incumbent, challenger, POLICY)
    assert verdict.decision == "KEEP"
    assert "NO_REPLACEMENT_TRIGGER" in verdict.reasons


def test_negative_earnings_trigger_requires_material_edge():
    incumbent = scored_candidate(earnings_state="NEGATIVE")
    challenger = scored_candidate(cash_dividend_contribution=65)
    verdict = compare_replacement(incumbent, challenger, POLICY)
    assert verdict.decision == "WATCH"
    assert verdict.score_advantage < 15


def test_material_verified_edge_becomes_replace_review_not_auto_trade():
    incumbent = scored_candidate(earnings_state="NEGATIVE", cash_dividend_contribution=30, earnings_quality_and_growth=30, valuation_and_entry_margin=40)
    challenger = scored_candidate(cash_dividend_contribution=90, earnings_quality_and_growth=90, valuation_and_entry_margin=80, portfolio_diversification=80, shareholder_return_durability=90)
    verdict = compare_replacement(incumbent, challenger, POLICY)
    assert verdict.decision == "REPLACE_REVIEW"
    assert verdict.score_advantage >= 15
    assert POLICY["execution"]["auto_sell"] is False
    assert POLICY["execution"]["auto_buy"] is False


def test_unverified_challenger_is_never_recommended():
    incumbent = scored_candidate(earnings_state="NEGATIVE")
    challenger = scored_candidate(official_ir_verified=False, cash_dividend_contribution=100, earnings_quality_and_growth=100)
    verdict = compare_replacement(incumbent, challenger, POLICY)
    assert verdict.decision == "WATCH"
    assert "CHALLENGER_IR_NOT_VERIFIED" in verdict.reasons


def test_dividend_thesis_break_with_verified_superior_candidate_becomes_replace_review():
    incumbent = scored_candidate(dividend_thesis_broken=True, cash_dividend_contribution=20, earnings_quality_and_growth=30)
    challenger = scored_candidate(cash_dividend_contribution=100, earnings_quality_and_growth=90, valuation_and_entry_margin=90, portfolio_diversification=90, shareholder_return_durability=90)
    verdict = compare_replacement(incumbent, challenger, POLICY)
    assert verdict.decision == "REPLACE_REVIEW"
    assert "DIVIDEND_THESIS_BROKEN" in verdict.reasons


def test_structural_break_without_a_verified_challenger_is_reduce_review_not_trade():
    verdict = compare_replacement(scored_candidate(structural_thesis_broken=True), None, POLICY)
    assert verdict.decision == "REDUCE_REVIEW"
    assert "NO_AUTOMATIC_TRADE" in verdict.reasons


def test_private_replacement_book_only_returns_human_review_state():
    profile = {"replacement_reviews": {"1111": {"incumbent": scored_candidate(earnings_state="NEGATIVE"), "challenger": scored_candidate(cash_dividend_contribution=100, earnings_quality_and_growth=100)}}}
    verdict = evaluate_private_replacement_book(profile, POLICY)["1111"]
    assert verdict.decision == "REPLACE_REVIEW"
    assert "NO_AUTOMATIC_TRADE" in verdict.reasons
