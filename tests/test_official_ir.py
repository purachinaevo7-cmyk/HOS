from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "investment-agent"))

from earnings_assessment import POSITIVE, assess_snapshot
from official_ir import ingest_official_ir_sources


class Response:
    def __init__(self, body):
        self.body = body

    def read(self, _limit):
        return self.body

    def close(self):
        pass


def official_payload():
    return b'''{"period":"FY Q1","report_date":"2026-08-07","expires_on":"2026-11-01","guidance_status":"UNCHANGED","dividend_status":"RAISED","revenue_yoy_pct":5,"primary_profit_yoy_pct":20,"net_income_yoy_pct":18,"full_year_profit_progress_pct":25}'''


def test_registered_official_json_refreshes_a_positive_assessment():
    profile = {"earnings_ir_sources": {"1111": {"url": "https://ir.example.test/result.json", "official_host": "ir.example.test", "official_source_verified": True, "source_type": "OFFICIAL_IR"}}}
    book, audit = ingest_official_ir_sources(profile, {"reviews": {}}, as_of=date(2026, 8, 21), opener=lambda *_args, **_kwargs: Response(official_payload()))
    assert audit[0].status == "OFFICIAL_IR_REFRESHED"
    assert assess_snapshot("1111", book["reviews"]["1111"], as_of=date(2026, 8, 21)).state == POSITIVE


def test_unofficial_or_failed_source_relocks_instead_of_reusing_positive_review():
    profile = {"earnings_ir_sources": {"1111": {"url": "https://third-party.example.test/result.json", "official_host": "ir.example.test", "official_source_verified": True, "source_type": "OFFICIAL_IR"}}}
    old = {"source_verified": True, "source_url": "https://old.example", "report_date": "2026-08-07", "expires_on": "2026-11-01"}
    book, audit = ingest_official_ir_sources(profile, {"reviews": {"1111": old}}, as_of=date(2026, 8, 21))
    assert audit[0].status == "OFFICIAL_SOURCE_REQUIRED"
    assert assess_snapshot("1111", book["reviews"]["1111"], as_of=date(2026, 8, 21)).state == "NEEDS_DATA"
