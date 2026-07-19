from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import fitz

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "growth-menu"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def check(condition: bool, name: str, details: str, results: list[dict[str, Any]]) -> None:
    results.append({"name": name, "status": "pass" if condition else "fail", "details": details})


def pdf_text_and_fonts(path: Path) -> tuple[str, set[str], int, bool]:
    document = fitz.open(path)
    texts = [page.get_text("text") for page in document]
    fonts: set[str] = set()
    for page in document:
        for font in page.get_fonts(full=True):
            if len(font) > 3 and font[3]:
                fonts.add(str(font[3]))
    page_count = document.page_count
    encrypted = bool(document.needs_pass)
    document.close()
    return "\n".join(texts), fonts, page_count, encrypted


def audit(output_dir: Path, expected_date: str | None = None) -> dict[str, Any]:
    config = load_json(SKILL_DIR / "config.json")
    latest_json = output_dir / "latest.json"
    latest_pdf = output_dir / "latest.pdf"
    preview = output_dir / "latest-preview.png"
    notification = output_dir / "latest_notification.md"
    results: list[dict[str, Any]] = []

    check(latest_json.exists(), "latest_json_exists", str(latest_json), results)
    check(latest_pdf.exists(), "latest_pdf_exists", str(latest_pdf), results)
    check(preview.exists(), "preview_exists", str(preview), results)
    check(notification.exists(), "notification_exists", str(notification), results)
    if not latest_json.exists() or not latest_pdf.exists():
        return {"status": "fail", "checked_date": expected_date, "checks": results}

    data = load_json(latest_json)
    target_date = expected_date or data.get("date")
    check(data.get("date") == target_date, "date_matches", f"actual={data.get('date')} expected={target_date}", results)

    pdf_text, fonts, page_count, encrypted = pdf_text_and_fonts(latest_pdf)
    check(
        page_count == config["output"]["page_count"],
        "page_count",
        f"actual={page_count} expected={config['output']['page_count']}",
        results,
    )
    check(not encrypted, "pdf_not_encrypted", "PDF opens without a password", results)
    check(len(pdf_text.strip()) > 500, "pdf_text_present", f"characters={len(pdf_text.strip())}", results)
    check(any("Noto" in font or "YuGothic" in font for font in fonts), "japanese_font_present", f"fonts={sorted(fonts)}", results)

    for forbidden in config["curriculum"]["explicit_exclusions"]:
        check(forbidden.lower() not in pdf_text.lower(), f"excluded_{forbidden}", "not present", results)
    for forbidden in config["output"]["forbidden_deck_phrases"]:
        check(forbidden not in pdf_text, f"not_submission_form_{forbidden}", "not present in PDF", results)

    required_teaching_markers = [
        "会社スナップショット" if data["case_profile"]["profile_type"] == "company" else "事業スナップショット",
        "顧客と提供価値",
        "ビジネスモデル",
        "基本概念",
        "ケースの状況",
        "理論で読み解くと",
        "今日の型",
    ]
    for marker in required_teaching_markers:
        check(marker in pdf_text, f"teaching_marker_{marker}", "present", results)

    profile = data.get("case_profile", {})
    check(profile.get("name") in pdf_text, "profile_name_in_pdf", str(profile.get("name")), results)
    check(profile.get("as_of") in pdf_text, "profile_as_of_in_pdf", str(profile.get("as_of")), results)
    check(len(profile.get("value_chain", [])) == 5, "five_value_chain_steps", "exactly 5", results)
    check(len(profile.get("scale_indicators", [])) == 3, "three_scale_indicators", "exactly 3", results)
    if profile.get("profile_type") == "company":
        check(str(profile.get("source_url", "")).startswith("https://"), "official_company_source", str(profile.get("source_url")), results)
        check(bool(profile.get("verified_on")), "company_profile_verified_on", str(profile.get("verified_on")), results)

    check(len(data.get("business_lesson", {}).get("learning_points", [])) == 3, "three_learning_points", "exactly 3", results)
    check(len(data.get("business_lesson", {}).get("cause_effect_chain", [])) == 3, "three_cause_effect_steps", "exactly 3", results)
    check(len(data.get("case_lesson", {}).get("observations", [])) == 3, "three_case_observations", "exactly 3", results)
    check(len(data.get("case_lesson", {}).get("interpretation", [])) == 3, "three_case_interpretations", "exactly 3", results)
    check(len(data.get("english_lesson", {}).get("vocabulary", [])) == 5, "five_vocabulary_items", "exactly 5", results)

    generation = data.get("generation", {})
    provider = generation.get("provider")
    check(provider in {"offline", "gemini_free_tier"}, "allowed_provider", str(provider), results)
    check("openai" not in json.dumps(generation, ensure_ascii=False).lower(), "openai_not_used", "no OpenAI API provider", results)
    check(config["provider"]["allow_paid_fallback"] is False, "paid_fallback_disabled", "paid fallback is disabled", results)
    check(config["provider"]["allow_search_grounding"] is False, "search_grounding_disabled", "no paid/search grounding", results)

    privacy = config["privacy"]
    feedback = load_json(SKILL_DIR / "feedback" / "latest.json")
    privacy_ok = (
        feedback.get("privacy_check", {}).get("raw_output_stored") is False
        and feedback.get("privacy_check", {}).get("confidential_details_removed") is True
    )
    check(privacy_ok, "feedback_privacy", "raw output is not stored in the public repository", results)
    check(privacy["repository_is_public"] is True, "public_repo_awareness", "privacy guard enabled", results)

    if preview.exists():
        image = fitz.Pixmap(str(preview))
        check(image.width >= 1000 and image.height >= 500, "preview_resolution", f"{image.width}x{image.height}", results)

    notification_text = notification.read_text(encoding="utf-8") if notification.exists() else ""
    check("latest.pdf" in notification_text, "stable_pdf_link", "notification links to latest.pdf", results)
    check("latest-preview.png" in notification_text, "stable_preview_link", "notification links to preview image", results)
    check("latest.pptx" not in notification_text, "pptx_not_distributed", "PowerPoint is not the user-facing format", results)
    check("このチャット" in notification_text, "feedback_return_path", "submission returns to ChatGPT", results)
    check("5ページ目の英作文" in notification_text, "notification_submission_guide", "submission instructions stay outside PDF", results)

    failures = [item for item in results if item["status"] == "fail"]
    return {
        "status": "pass" if not failures else "fail",
        "checked_date": target_date,
        "generated_at": date.today().isoformat(),
        "checks": results,
        "failure_count": len(failures),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit generated HOS morning lesson PDF outputs")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--date", help="Expected content date in YYYY-MM-DD")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit(args.output_dir, args.date)
    if args.write_report:
        audit_dir = args.output_dir / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        (audit_dir / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if report.get("checked_date"):
            (audit_dir / f"{report['checked_date']}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
