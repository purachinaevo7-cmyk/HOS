from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_DIR))

from lesson_content import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    deterministic_lesson,
    jst_today,
    load_json,
    read_recent_module_ids,
    select_seed,
    call_gemini,
    validate_content,
)
from lesson_render import write_outputs  # noqa: E402

__all__ = [
    "DEFAULT_OUTPUT_DIR",
    "deterministic_lesson",
    "jst_today",
    "load_json",
    "read_recent_module_ids",
    "select_seed",
    "call_gemini",
    "validate_content",
    "write_outputs",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the HOS morning lesson PowerPoint")
    parser.add_argument("--date", help="Target date in YYYY-MM-DD; defaults to today in Asia/Tokyo")
    parser.add_argument("--offline", action="store_true", help="Use deterministic curated lesson and skip Gemini")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_date = date.fromisoformat(args.date) if args.date else jst_today()
    config = load_json(SKILL_DIR / "config.json")
    feedback = load_json(SKILL_DIR / "feedback" / "latest.json")
    recent_ids = read_recent_module_ids(args.output_dir)
    seed = select_seed(target_date, feedback, recent_ids)
    data = deterministic_lesson(target_date, feedback, seed) if args.offline else call_gemini(target_date, feedback, seed)
    validate_content(data, config, target_date)
    outputs = write_outputs(data, config, args.output_dir)
    print(json.dumps({
        "status": "generated",
        "date": target_date.isoformat(),
        "provider": data["generation"]["provider"],
        "seed_id": data["generation"]["seed_id"],
        "outputs": {key: str(value) for key, value in outputs.items()}
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"growth-menu generation failed: {exc}", file=sys.stderr)
        raise
