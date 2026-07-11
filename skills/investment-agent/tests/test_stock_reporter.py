from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_reporter import generate_report


def test_report_includes_topix_missing_providers():
    report = generate_report(
        date(2026, 7, 9),
        None,
        "要確認（TOPIX 1ソースのみ）",
        {"topix_category": None, "market_drop": [], "individual_drop": []},
        [],
        [],
        ["TradingView: データなし", "Investing.com: HTTP 403"],
    )

    assert "指数ソース：要確認（TOPIX 1ソースのみ）" in report
    assert "TOPIX取得ログ" in report
    assert "- TradingView: データなし" in report
    assert "- Investing.com: HTTP 403" in report


def test_report_marks_etf_median_as_reference_judgement():
    report = generate_report(
        date(2026, 7, 9),
        -1.0,
        "代替（TOPIX ETF中央値）",
        {"topix_category": "A", "market_drop": [], "individual_drop": []},
        [],
        [],
        ["TOPIX ETF 1306: 成功（取得日 2026-07-09, 終値 99.00, 前日終値 100.00, 前日比 -1.00%, 取得方法 TOPIX連動ETFを指数プロキシとして使用, 失敗理由 -）"],
    )

    assert "指数ソース：代替（TOPIX ETF中央値）" in report
    assert "参考判定" in report
    assert "TOPIX本体未取得のため参考判定" in report


def test_report_reference_judgement_without_ab_match_is_not_pending():
    report = generate_report(
        date(2026, 7, 9),
        0.72,
        "参考判定",
        {"topix_category": None, "market_drop": [], "individual_drop": []},
        [],
        [],
        [],
    )

    assert "指数ソース：TOPIX ETF中央値（参考判定）" in report
    assert "- 該当銘柄なし（参考判定）" in report
    assert "A/B判定保留" not in report
