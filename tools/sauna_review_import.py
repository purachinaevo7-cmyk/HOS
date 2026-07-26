#!/usr/bin/env python3
"""Import one sauna review template into HOS canonical JSON data.

Accepts the Japanese copy/paste template used in ChatGPT conversations.
The importer is deterministic, dependency-free, duplicate-safe, and keeps
legacy score-only records alongside detailed visit logs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "sauna" / "reviews.json"
DEFAULT_SUMMARY = ROOT / "data" / "sauna" / "summary.json"

FIELD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("facility", re.compile(r"^\s*(?:[-*]\s*)?施設名\s*[：:]\s*(.*)$")),
    ("visited_at", re.compile(r"^\s*(?:[-*]\s*)?訪問日\s*[：:]\s*(.*)$")),
    ("catchcopy", re.compile(r"^\s*(?:[-*]\s*)?🔥?\s*一言まとめ(?:（キャッチコピー）)?\s*[：:]\s*(.*)$")),
    ("score", re.compile(r"^\s*(?:[-*]\s*)?総合評価(?:（10点満点）)?\s*[：:]\s*(.*)$")),
    ("sauna", re.compile(r"^\s*(?:[-*]\s*)?#サウナ\s*[：:]\s*(.*)$")),
    ("cold_bath", re.compile(r"^\s*(?:[-*]\s*)?#水風呂\s*[：:]\s*(.*)$")),
    ("rest", re.compile(r"^\s*(?:[-*]\s*)?#外気浴\s*[：:]\s*(.*)$")),
    ("flow", re.compile(r"^\s*(?:[-*]\s*)?#導線\s*[：:]\s*(.*)$")),
    ("crowd", re.compile(r"^\s*(?:[-*]\s*)?#混み具合\s*[：:]\s*(.*)$")),
    ("drawbacks", re.compile(r"^\s*(?:[-*]\s*)?微妙だった点\s*[：:]\s*(.*)$")),
    ("crowd_time", re.compile(r"^\s*(?:[-*]\s*)?混雑（時間帯）\s*[：:]\s*(.*)$")),
    ("memo", re.compile(r"^\s*(?:[-*]\s*)?メモ（次回の入り方・持ち物・リピ条件）\s*[：:]\s*(.*)$")),
]

TAG_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("ケロ", re.compile(r"ケロ", re.I)),
    ("バレル", re.compile(r"バレル", re.I)),
    ("ロウリュ", re.compile(r"ロウリュ|アウフグース", re.I)),
    ("高湿度", re.compile(r"湿度|しっとり", re.I)),
    ("高温", re.compile(r"激アツ|高温|100℃|100度|体感は?100", re.I)),
    ("グルシン", re.compile(r"グルシン|シングル|(?:^|\D)[1-9](?:℃|度)", re.I)),
    ("チラー", re.compile(r"チラー", re.I)),
    ("岩水風呂", re.compile(r"岩.*水風呂|水風呂.*岩", re.I)),
    ("外気浴", re.compile(r"外気浴|屋上", re.I)),
    ("ブレインスリープ", re.compile(r"ブレインスリープ", re.I)),
    ("畳", re.compile(r"畳", re.I)),
    ("景観", re.compile(r"景色|外が見える|秘境|都会の景色", re.I)),
    ("二重扉", re.compile(r"二重扉", re.I)),
    ("好導線", re.compile(r"導線.*(?:良|完璧|近)|目の前", re.I)),
    ("混雑", re.compile(r"混ん|満員|行列|並び", re.I)),
    ("少人数向け", re.compile(r"1人しか|椅子一つ|椅子1|キャパ", re.I)),
]

def _clean_line(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^\s*[-*]\s*", "", value)
    return value.strip()

def parse_review_text(text: str) -> dict[str, Any]:
    values: dict[str, list[str]] = {key: [] for key, _ in FIELD_PATTERNS}
    current: str | None = None

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        matched = False
        for key, pattern in FIELD_PATTERNS:
            match = pattern.match(raw_line)
            if match:
                current = key
                initial = _clean_line(match.group(1))
                if initial:
                    values[key].append(initial)
                matched = True
                break
        if matched:
            continue

        stripped = raw_line.strip()
        if not stripped:
            continue
        if re.match(r"^\s*[-*]\s*好きだった点\s*$", raw_line):
            current = None
            continue
        if stripped.startswith("### "):
            current = None
            continue
        if current:
            continuation = _clean_line(raw_line)
            if continuation:
                values[current].append(continuation)

    flattened = {key: "\n".join(parts).strip() for key, parts in values.items()}
    facility = flattened["facility"]
    if not facility:
        raise ValueError("施設名が見つかりません。『施設名：』を含むテンプレートを貼り付けてください。")

    score_match = re.search(r"\d+(?:\.\d+)?", flattened["score"])
    if not score_match:
        raise ValueError("総合評価が見つかりません。0〜10の数値を入力してください。")
    score = float(score_match.group(0))
    if not 0 <= score <= 10:
        raise ValueError(f"総合評価は0〜10で入力してください: {score}")
    if score.is_integer():
        score = int(score)

    parsed: dict[str, Any] = {
        "facility": facility,
        "visited_at": normalize_date(flattened["visited_at"]) if flattened["visited_at"] else None,
        "score": score,
        "catchcopy": flattened["catchcopy"],
        "sauna": flattened["sauna"],
        "cold_bath": flattened["cold_bath"],
        "rest": flattened["rest"],
        "flow": flattened["flow"],
        "crowd": flattened["crowd"],
        "drawbacks": flattened["drawbacks"],
        "crowd_time": flattened["crowd_time"],
        "memo": flattened["memo"],
    }
    return parsed

def normalize_date(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    value = value.replace("/", "-").replace(".", "-")
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    if not match:
        raise ValueError(f"訪問日はYYYY-MM-DD形式で入力してください: {value}")
    year, month, day = map(int, match.groups())
    return datetime(year, month, day).date().isoformat()

def derive_tags(review: dict[str, Any]) -> list[str]:
    haystack = " ".join(str(review.get(k, "")) for k in (
        "catchcopy", "sauna", "cold_bath", "rest", "flow",
        "crowd", "drawbacks", "crowd_time", "memo"
    ))
    return [tag for tag, pattern in TAG_RULES if pattern.search(haystack)]

def review_hash(review: dict[str, Any]) -> str:
    canonical = json.dumps(
        {k: review.get(k) for k in (
            "facility", "visited_at", "score", "catchcopy", "sauna", "cold_bath",
            "rest", "flow", "crowd", "drawbacks", "crowd_time", "memo"
        )},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def make_review_id(review: dict[str, Any], digest: str) -> str:
    date_part = (review.get("visited_at") or datetime.now(timezone.utc).date().isoformat()).replace("-", "")
    return f"sauna-{date_part}-{digest[:10]}"

def load_dataset(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "updated_at": None, "reviews": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("reviews"), list):
        raise ValueError(f"不正なデータ形式です: {path}")
    return data

def build_summary(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in reviews if isinstance(r.get("score"), (int, float))]
    facilities: dict[str, list[dict[str, Any]]] = {}
    for review in scored:
        facilities.setdefault(review["facility"], []).append(review)

    rankings = []
    for facility, items in facilities.items():
        items_sorted = sorted(
            items,
            key=lambda r: (
                r.get("visited_at") or (r.get("logged_at") or "")[:10],
                r.get("logged_at") or "",
            ),
            reverse=True,
        )
        rankings.append({
            "facility": facility,
            "average_score": round(sum(float(x["score"]) for x in items) / len(items), 2),
            "latest_score": items_sorted[0]["score"],
            "visits": len(items),
            "latest_visit": items_sorted[0].get("visited_at"),
            "tags": sorted({tag for item in items for tag in item.get("tags", [])}),
        })
    rankings.sort(key=lambda x: (-x["average_score"], -x["visits"], x["facility"]))

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "review_count": len(reviews),
        "facility_count": len(facilities),
        "average_score": round(sum(float(r["score"]) for r in scored) / len(scored), 2) if scored else None,
        "score_9_or_more": sum(1 for r in scored if float(r["score"]) >= 9),
        "rankings": rankings,
    }

def import_review(
    input_path: Path,
    data_path: Path,
    summary_path: Path,
    visited_at: str | None,
    source: str,
) -> tuple[dict[str, Any], bool]:
    review = parse_review_text(input_path.read_text(encoding="utf-8"))
    if visited_at:
        review["visited_at"] = normalize_date(visited_at)

    digest = review_hash(review)
    dataset = load_dataset(data_path)
    existing = next((r for r in dataset["reviews"] if r.get("review_hash") == digest), None)
    if existing:
        return existing, False

    now = datetime.now(timezone.utc).isoformat()
    detailed_fields = sum(bool(review.get(k)) for k in (
        "catchcopy", "sauna", "cold_bath", "rest", "flow", "crowd",
        "drawbacks", "crowd_time", "memo"
    ))
    record = {
        "id": make_review_id(review, digest),
        **review,
        "tags": derive_tags(review),
        "detail_level": "detailed" if detailed_fields >= 4 else "partial",
        "source": source,
        "logged_at": now,
        "review_hash": digest,
    }
    dataset["reviews"].append(record)
    dataset["reviews"].sort(
        key=lambda r: (
            r.get("visited_at") or (r.get("logged_at") or "")[:10],
            r.get("logged_at") or "",
        ),
        reverse=True,
    )
    dataset["updated_at"] = now

    data_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(
        json.dumps(build_summary(dataset["reviews"]), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return record, True

def main() -> int:
    parser = argparse.ArgumentParser(description="HOSへサウナレビューを追加します。")
    parser.add_argument("--input", required=True, type=Path, help="レビュー本文のテキストファイル")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--date", help="訪問日 YYYY-MM-DD。本文の訪問日より優先")
    parser.add_argument("--source", default="manual")
    parser.add_argument("--check", action="store_true", help="解析のみでファイルを更新しない")
    args = parser.parse_args()

    try:
        if args.check:
            parsed = parse_review_text(args.input.read_text(encoding="utf-8"))
            if args.date:
                parsed["visited_at"] = normalize_date(args.date)
            parsed["tags"] = derive_tags(parsed)
            print(json.dumps(parsed, ensure_ascii=False, indent=2))
            return 0

        record, created = import_review(
            args.input, args.data, args.summary, args.date, args.source
        )
        print(json.dumps({
            "status": "created" if created else "duplicate",
            "id": record["id"],
            "facility": record["facility"],
            "score": record["score"],
            "visited_at": record.get("visited_at"),
        }, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
