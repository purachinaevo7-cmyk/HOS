from datetime import date
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "skills" / "investment-agent"
sys.path.insert(0, str(BASE))

from discord_report import render_discord_report


def signal(**kwargs):
    defaults = {
        "account": "member_b",
        "ticker": "4262",
        "name": "ニフティライフスタイル",
        "currency": "JPY",
        "fy2026_decision": "BUY_2026_CONDITIONAL",
        "execution_priority": 1,
        "step_index": 1,
        "shares": 100,
        "shares_rule": None,
        "limit_price": 1400,
        "current_price": 1360,
        "distance_to_limit_percent": -2.86,
        "status": "BLOCKED_AT_LIMIT",
        "actionability": "DRAFT",
        "blocks": [
            "ACCOUNT_BUDGET_SECRET_REQUIRED",
            "ACCOUNT_BUYING_POWER_REQUIRED",
            "EARNINGS_REVIEW_REQUIRED",
        ],
        "estimated_amount_jpy": 140000,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def logic_candidate(**kwargs):
    defaults = {
        "ticker": "1111",
        "name": "Example Income Co",
        "currency": "JPY",
        "execution_priority": 1,
        "step_index": 1,
        "shares": 10,
        "shares_rule": None,
        "limit_price": 100,
        "current_price": 95,
        "distance_to_limit_percent": -5.0,
        "status": "BUY_CONSIDER",
        "blocks": [],
        "warnings": [],
        "entry_status": "BUY_ZONE",
        "earnings_state": "POSITIVE",
        "thesis_state": "VALIDATED",
        "dividend_state": "CONFIRMED",
        "dividend_yield": 0.04,
        "projected_weight": 0.012,
        "investment_score": 72,
        "planned_step_count": 1,
        "combined_pending_shares": 10,
        # A malicious/incorrect caller must not be able to make this renderer
        # print either field as purchase authority.
        "account": "private_account_must_not_render",
        "purchase_flag": "PURCHASE_READY",
        "actionability": "READY",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_report_separates_accounts_and_translates_internal_codes():
    signals = [
        signal(),
        signal(step_index=2, status="NEAR", limit_price=1300, blocks=[]),
        signal(
            account="member_a",
            ticker="8593",
            name="三菱HCキャピタル",
            fy2026_decision="BUY_2026_CORE",
            current_price=1420,
            limit_price=1400,
            status="NEAR",
            blocks=[],
        ),
    ]
    alerts = [
        SimpleNamespace(
            priority=1,
            status="REVIEW_REQUIRED",
            ticker="4063",
            company_name="信越化学工業",
            close=6146,
            change_percent=-3.2,
        )
    ]
    policy = {
        "current_financial_assets": 25_270_000,
        "target_asset_value_at_age_60": 200_000_000,
        "target_annual_dividend": 6_000_000,
    }
    strategy = {"funding": {}}

    report = render_discord_report(
        policy,
        strategy,
        signals,
        alerts,
        date(2026, 7, 27),
        "夜の注文案",
    )

    assert "【member_b】" in report
    assert "【member_a】" in report
    assert "HOS側：決算確認" in report
    assert "ユーザー側：口座予算未設定・買付余力未設定" in report
    assert "ACCOUNT_BUDGET" not in report
    assert "PURCHASE_READY" not in report
    assert "現在確認済み 未設定" in report
    assert report.count("4262 ニフティライフスタイル") == 1
    assert "【世帯進捗】" in report
    assert "【市場監視】" in report
    assert len(report) <= 1980


def test_manual_logic_panel_is_not_purchase_authority_or_account_disclosure():
    report = render_discord_report(
        policy={},
        strategy={"funding": {}},
        signals=[],
        alerts=[],
        trade_date=date(2026, 8, 31),
        mode_label="夜の注文案",
        logic_candidates=[logic_candidate()],
    )

    assert "発注可 0件｜手動買い検討 1件" in report
    assert "監視対象：総合買い判断 1銘柄（口座別発注安全判定は保留）" in report
    assert "【総合買い判断（手動確認用）】" in report
    assert "🟢 買い検討可 1111 Example Income Co" in report
    assert "HOSの発注可ではありません" in report
    assert "PURCHASE_READY" not in report
    assert "✅ 購入可" not in report
    assert "private_account_must_not_render" not in report
    assert len(report) <= 1980


def test_manual_logic_panel_explains_no_pass_without_hiding_data_errors():
    report = render_discord_report(
        policy={},
        strategy={"funding": {}},
        signals=[],
        alerts=[],
        trade_date=date(2026, 8, 31),
        mode_label="朝の確認",
        logic_candidates=[
            logic_candidate(status="REVIEW_REQUIRED", blocks=["EARNINGS_AUDIT_REQUIRED"], warnings=["INVESTMENT_REVIEW_NOT_REGISTERED"]),
            logic_candidate(ticker="2222", status="DATA_REQUIRED", current_price=None, blocks=["PRICE_UNAVAILABLE"]),
        ],
    )

    assert "🟢 検討可 0件" in report
    assert "⚪ 要確認 1111" in report
    assert "確認事項：HOS決算監査待ち" in report
    assert "🚨 データ確認 2222" in report
    assert "株価未取得" in report


def test_manual_review_keeps_all_ideas_visible_even_when_details_are_ranked():
    candidates = [
        logic_candidate(ticker=f"{index:04d}", name=f"Example {index}", execution_priority=index)
        for index in range(1, 7)
    ]
    report = render_discord_report(
        policy={},
        strategy={"funding": {}},
        signals=[],
        alerts=[],
        trade_date=date(2026, 8, 31),
        mode_label="夜の注文案",
        logic_candidates=candidates,
    )

    assert "🟢 検討可 6件" in report
    assert "・ほか 2銘柄：検討可 2件（0005,0006）" in report
    assert "1日注文上限" not in report.split("【総合買い判断（手動確認用）】", 1)[1].split("【世帯進捗】", 1)[0]


def test_manual_review_does_not_suggest_a_quantity_for_conflicting_duplicate_plans():
    report = render_discord_report(
        policy={},
        strategy={"funding": {}},
        signals=[],
        alerts=[],
        trade_date=date(2026, 8, 31),
        mode_label="夜の注文案",
        logic_candidates=[logic_candidate(
            status="REVIEW_REQUIRED",
            shares=None,
            planned_step_count=2,
            combined_pending_shares=None,
            blocks=["PLAN_CONFLICT"],
        )],
    )

    assert "株数未確定" in report
    assert "次Step: 2件・整合性確認" in report
    assert "登録戦略の整合性を確認" in report
    assert "買い検討可 1111" not in report
