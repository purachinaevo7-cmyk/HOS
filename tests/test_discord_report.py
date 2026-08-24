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
