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
