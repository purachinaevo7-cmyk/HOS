from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent

FORBIDDEN_PATTERNS = [
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\b0\d{1,4}-\d{1,4}-\d{3,4}\b"),
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_feedback(data: dict[str, Any], config: dict[str, Any]) -> None:
    if "raw_output" in data:
        raise ValueError("raw_output must never be stored in the public repository")
    serialized = json.dumps(data, ensure_ascii=False)
    for pattern in FORBIDDEN_PATTERNS:
        if pattern.search(serialized):
            raise ValueError("feedback contains personal contact information")
    for label in config["privacy"]["forbidden_feedback_content"]:
        if label in serialized:
            raise ValueError(f"feedback contains forbidden content label: {label}")
    privacy = data.get("privacy_check", {})
    if privacy.get("raw_output_stored") is not False:
        raise ValueError("privacy_check.raw_output_stored must be false")
    if privacy.get("confidential_details_removed") is not True:
        raise ValueError("privacy_check.confidential_details_removed must be true")
    if not data.get("redacted_summary"):
        raise ValueError("redacted_summary is required")


def main() -> int:
    parser = argparse.ArgumentParser(description="Record redacted growth-menu feedback")
    parser.add_argument("feedback_json", type=Path)
    args = parser.parse_args()

    config = load_json(SKILL_DIR / "config.json")
    data = load_json(args.feedback_json)
    validate_feedback(data, config)
    submission_date = data.get("submission_date") or date.today().isoformat()
    data["submission_date"] = submission_date

    feedback_dir = SKILL_DIR / "feedback"
    history_dir = feedback_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    (feedback_dir / "latest.json").write_text(payload, encoding="utf-8")
    (history_dir / f"{submission_date}.json").write_text(payload, encoding="utf-8")
    print(json.dumps({"status": "recorded", "submission_date": submission_date}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
