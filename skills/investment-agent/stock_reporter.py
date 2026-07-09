"""通知文生成 for HOS Investment Agent."""
from __future__ import annotations

from datetime import date
from typing import Any

from stock_analyzer import AnalyzedStock, MissingRecord, PriceRecord

REFERENCE_STATUS = "代替（TOPIX ETF中央値）"


def _fmt_pct(value: float | None) -> str:
    return "要確認" if value is None else f"{value:.2f}%"


def _stock_line(stock: AnalyzedStock) -> str:
    return (
        f"- {stock.code} {stock.name}: 終値 {stock.close:,.2f} / 前日終値 {stock.previous_close:,.2f} / "
        f"下落率 {stock.change_percent:.2f}% / 買いレンジ {stock.buy_range_low:,.2f}〜{stock.buy_range_high:,.2f}"
    )


def _section(title: str, stocks: list[AnalyzedStock], topix_pending: bool) -> list[str]:
    lines = [title]
    if topix_pending:
        lines.append("- A/B判定保留（TOPIXデータ不整合・要確認）")
    elif not stocks:
        lines.append("- 該当銘柄なし（取得済みデータ内での判定）")
    else:
        lines.extend(_stock_line(stock) for stock in stocks)
    return lines


def _is_reference_judgement(topix_source_status: str) -> bool:
    return topix_source_status == REFERENCE_STATUS


def generate_report(
    trade_date: date,
    topix_change_percent: float | None,
    topix_source_status: str,
    analysis: dict[str, Any],
    fetched: list[PriceRecord],
    missing: list[MissingRecord],
    topix_missing: list[str] | None = None,
    mode_label: str | None = None,
    morning_retry_incomplete: bool | None = None,
) -> str:
    reference_judgement = _is_reference_judgement(topix_source_status)
    topix_pending = analysis["topix_category"] is None
    lines: list[str] = [
        trade_date.strftime("%Y/%m/%d"),
        f"TOPIX前日比：{_fmt_pct(topix_change_percent)}",
        f"指数ソース：{topix_source_status}",
        *( [f"取得モード：{mode_label}"] if mode_label else [] ),
        "",
    ]
    if reference_judgement:
        lines.extend([
            "参考判定",
            "- TOPIX本体未取得のため参考判定（TOPIX ETF中央値を暫定指数として使用）",
            "",
        ])
    lines.extend(_section("(A) 相場要因の下げ", analysis["market_drop"], topix_pending))
    lines.append("")
    lines.extend(_section("(B) 個別要因っぽい下げ", analysis["individual_drop"], topix_pending))
    lines.extend([
        "",
        "全銘柄確認状況",
        "- 取得済み",
    ])
    if fetched:
        lines.extend(f"  - {record.code} {record.name}: 取得日 {record.price_date.isoformat()} / Provider {record.source}" for record in fetched)
    else:
        lines.append("  - 要確認（データ未取得）")
    lines.append("- 未取得")
    if missing:
        lines.extend(f"  - {record.code} {record.name}: 要確認（データ未取得） - {record.reason}" for record in missing)
    else:
        lines.append("  - なし")
    if topix_missing:
        lines.extend(["", "TOPIX取得ログ"])
        lines.extend(f"- {reason}" for reason in topix_missing)
    lines.extend([
        "",
        "翌営業日の買い方",
        "- 寄りは避けて指値分割。買いレンジ内で複数回に分け、データ未取得銘柄は約定前に必ず再確認する。",
        "",
        "本日の結論",
    ])
    mmdd = trade_date.strftime("%m/%d")
    if morning_retry_incomplete is False:
        conclusion = f"{mmdd}のニュースだよ。朝補完取得で判定更新。"
    elif morning_retry_incomplete is True:
        conclusion = f"{mmdd}のニュースだよ。要確認（データ未取得）。朝補完後も不足あり。"
    elif reference_judgement:
        conclusion = f"{mmdd}のニュースだよ。参考判定：TOPIX本体未取得のため参考判定。TOPIX ETF中央値による暫定A/B判定として扱い、正式判断前にTOPIX本体を再確認してね。"
    elif missing or topix_source_status != "一致":
        conclusion = f"{mmdd}のニュースだよ。要確認（データ未取得）を最優先。取得済み銘柄だけで暫定判定し、未取得銘柄は断定しない。"
    elif analysis["market_drop"]:
        conclusion = f"{mmdd}のニュースだよ。相場要因の下げ候補あり。寄りは避けて指値分割で買いレンジを確認。"
    elif analysis["individual_drop"]:
        conclusion = f"{mmdd}のニュースだよ。個別要因っぽい下げ候補あり。材料確認後に指値分割。"
    else:
        conclusion = f"{mmdd}のニュースだよ。取得済みデータでは大きな下げ候補は限定的。データ不足時は断定しない。"
    lines.append(conclusion)
    return "\n".join(lines)
