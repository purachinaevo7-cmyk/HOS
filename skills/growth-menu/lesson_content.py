from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "growth-menu"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def jst_today() -> date:
    return datetime.now(ZoneInfo("Asia/Tokyo")).date()


def read_recent_module_ids(output_dir: Path, limit: int = 7) -> list[str]:
    history = output_dir / "history"
    ids: list[str] = []
    if not history.exists():
        return ids
    for path in sorted(history.glob("*.json"), reverse=True):
        try:
            module_id = str(load_json(path).get("generation", {}).get("seed_id", "")).strip()
            if module_id:
                ids.append(module_id)
        except (OSError, json.JSONDecodeError):
            continue
        if len(ids) >= limit:
            break
    return ids


def select_seed(target_date: date, feedback: dict[str, Any], recent_ids: list[str]) -> dict[str, Any]:
    modules = load_json(SKILL_DIR / "curriculum_seeds.json")["modules"]
    candidates = [item for item in modules if item["id"] not in recent_ids] or modules
    focus = " ".join(feedback.get("business", {}).get("next_focus", []))
    scored = []
    for item in candidates:
        score = sum(2 for tag in item.get("tags", []) if tag.lower() in focus.lower())
        score += int(item["domain"] in focus)
        scored.append((score, item))
    best_score = max(score for score, _ in scored)
    best = [item for score, item in scored if score == best_score] if best_score else candidates
    return sorted(best, key=lambda item: item["id"])[target_date.toordinal() % len(best)]


def grammar_seed(feedback: dict[str, Any], business_seed: dict[str, Any]) -> dict[str, Any]:
    data = load_json(SKILL_DIR / "grammar_seeds.json")
    requested = str(feedback.get("english", {}).get("next_grammar") or "主語と動詞の骨格")
    selected = data["modules"].get(requested, data["modules"]["主語と動詞の骨格"])
    vocabulary = []
    for tag in business_seed.get("tags", []):
        pair = data["business_vocabulary"].get(tag)
        if pair and len(vocabulary) < 3:
            vocabulary.append({
                "word": pair[0],
                "meaning": pair[1],
                "example": f"{pair[0].capitalize()} shapes business performance."
            })
    for item in data["default_vocabulary"]:
        if len(vocabulary) >= 5:
            break
        if item["word"] not in {v["word"] for v in vocabulary}:
            vocabulary.append(item)
    return {
        **selected,
        "vocabulary": vocabulary[:5],
        "worked_example_ja": f"{business_seed['case_name']}では、最も重要な点は因果関係を明確にすることです。",
        "worked_example_en": "The most important point is that the company connects its capabilities to customer value.",
        "practice_prompt": f"「{business_seed['case_takeaway']}」の要旨を、今日の型を使って英語2文で表現する。"
    }


def deterministic_lesson(target_date: date, feedback: dict[str, Any], seed: dict[str, Any]) -> dict[str, Any]:
    grammar = grammar_seed(feedback, seed)
    return {
        "date": target_date.isoformat(),
        "title": f"{target_date.month}月{target_date.day}日の朝学習",
        "focus_summary": f"{seed['title']}を理論とケースの両方から理解する",
        "estimated_minutes": 25,
        "previous_feedback_summary": feedback.get("redacted_summary") or "初回のため、基本概念から始めます。",
        "business_lesson": {
            "title": f"{seed['domain']}の授業：{seed['title']}",
            "concept": seed["concept"],
            "definition": seed["concept"],
            "why_it_matters": f"{seed['common_confusion']}を避け、分析から戦略判断までをつなげるためです。",
            "learning_points": seed["learning_points"],
            "cause_effect_chain": seed["cause_effect_chain"],
            "common_confusion": seed["common_confusion"]
        },
        "case_lesson": {
            "title": f"ケースで理解：{seed['case_name']}",
            "context": seed["case_context"],
            "observations": seed["case_observations"],
            "interpretation": [
                f"観察事実から、{seed['learning_points'][0]}必要があります。",
                f"次に、{seed['learning_points'][1]}ことで構造を整理できます。",
                f"最後に、{seed['learning_points'][2]}ことで戦略上の意味が見えます。"
            ],
            "takeaway": seed["case_takeaway"],
            "reference_label": "HOS curated evergreen case"
        },
        "english_lesson": {
            "title": f"英文法の授業：{grammar['title']}",
            "grammar_pattern": grammar["pattern"],
            "rule_points": grammar["rule_points"],
            "bad_example": grammar["bad_example"],
            "correct_example": grammar["correct_example"],
            "example_breakdown": grammar["breakdown"],
            "vocabulary": grammar["vocabulary"],
            "worked_example_ja": grammar["worked_example_ja"],
            "worked_example_en": grammar["worked_example_en"],
            "practice_prompt": grammar["practice_prompt"]
        },
        "notification": {
            "headline": f"{target_date.month}月{target_date.day}日の朝学習PowerPoint",
            "summary": f"今日は「{seed['title']}」を理論→ケース→英語の順で学びます。",
            "duration": "約25分"
        },
        "generation": {"provider": "offline", "model": None, "seed_id": seed["id"]}
    }


def system_prompt() -> str:
    return (SKILL_DIR / "prompts" / "generator_system.md").read_text(encoding="utf-8")


def gemini_user_prompt(target_date: date, feedback: dict[str, Any], seed: dict[str, Any], grammar: dict[str, Any]) -> str:
    return (
        f"対象日: {target_date.isoformat()}\n"
        f"匿名化済みの前回評価: {json.dumps(feedback, ensure_ascii=False)}\n"
        f"今日の経営教材シード: {json.dumps(seed, ensure_ascii=False)}\n"
        f"今日の英文法シード: {json.dumps(grammar, ensure_ascii=False)}\n"
        "教材シードに書かれた事実だけを使い、説明を分かりやすく整えてください。\n"
        "PowerPointは授業資料です。提出用紙、回答欄、完了条件、採点表は作らないでください。\n"
        "3点配列は各3件、vocabularyは5件にしてください。"
    )


def extract_gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini response has no candidates")
    candidate = candidates[0]
    if candidate.get("finishReason") not in {None, "STOP"}:
        raise RuntimeError(f"Gemini generation did not finish normally: {candidate.get('finishReason')}")
    text = "\n".join(
        str(part.get("text", ""))
        for part in candidate.get("content", {}).get("parts", [])
        if part.get("text")
    )
    if not text.strip():
        raise RuntimeError("Gemini response did not contain text")
    return text


def call_gemini(target_date: date, feedback: dict[str, Any], seed: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required unless --offline is used")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    grammar = grammar_seed(feedback, seed)
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt()}]},
        "contents": [{"role": "user", "parts": [{"text": gemini_user_prompt(target_date, feedback, seed, grammar)}]}],
        "generationConfig": {
            "temperature": 0.35,
            "maxOutputTokens": int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "4096")),
            "responseMimeType": "application/json",
            "responseSchema": load_json(SKILL_DIR / "gemini_response_schema.json")
        }
    }
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=body,
        timeout=180
    )
    if not response.ok:
        retry_after = response.headers.get("Retry-After")
        suffix = f" Retry-After={retry_after}" if retry_after else ""
        raise RuntimeError(f"Gemini API error {response.status_code}:{suffix} {response.text[:1000]}")
    data = json.loads(extract_gemini_text(response.json()))
    data["date"] = target_date.isoformat()
    data["title"] = f"{target_date.month}月{target_date.day}日の朝学習"
    data["case_lesson"].update({
        "title": f"ケースで理解：{seed['case_name']}",
        "context": seed["case_context"],
        "observations": seed["case_observations"],
        "takeaway": seed["case_takeaway"],
        "reference_label": "HOS curated evergreen case"
    })
    data["generation"] = {"provider": "gemini_free_tier", "model": model, "seed_id": seed["id"]}
    return data


def validate_content(data: dict[str, Any], config: dict[str, Any], target_date: date) -> None:
    schema = load_json(SKILL_DIR / "schema.json")
    missing = [key for key in schema["required"] if key not in data]
    if missing:
        raise ValueError(f"Missing root fields: {missing}")
    if data["date"] != target_date.isoformat():
        raise ValueError(f"Date mismatch: {data['date']} != {target_date.isoformat()}")
    groups = (
        ("business_lesson", schema["business_lesson_required"]),
        ("case_lesson", schema["case_lesson_required"]),
        ("english_lesson", schema["english_lesson_required"])
    )
    for group, required in groups:
        for key in required:
            if key not in data[group]:
                raise ValueError(f"Missing {group} field: {key}")
    arrays = [
        data["business_lesson"].get("learning_points", []),
        data["business_lesson"].get("cause_effect_chain", []),
        data["case_lesson"].get("observations", []),
        data["case_lesson"].get("interpretation", []),
        data["english_lesson"].get("rule_points", []),
        data["english_lesson"].get("example_breakdown", [])
    ]
    if any(len(items) != 3 for items in arrays):
        raise ValueError("All lesson three-point arrays must contain exactly 3 items")
    if len(data["english_lesson"].get("vocabulary", [])) != 5:
        raise ValueError("english_lesson.vocabulary must contain exactly 5 items")
    minutes = int(data["estimated_minutes"])
    if not config["output"]["estimated_minutes_min"] <= minutes <= config["output"]["estimated_minutes_max"]:
        raise ValueError("estimated_minutes outside configured range")
    full_text = json.dumps(data, ensure_ascii=False).lower()
    for excluded in config["curriculum"]["explicit_exclusions"]:
        if excluded.lower() in full_text:
            raise ValueError(f"Excluded curriculum item found: {excluded}")
    lesson_text = json.dumps(
        {key: data[key] for key in ("business_lesson", "case_lesson", "english_lesson")},
        ensure_ascii=False
    )
    for forbidden in config["output"]["forbidden_deck_phrases"]:
        if forbidden in lesson_text:
            raise ValueError(f"Deck contains submission-form phrase: {forbidden}")
    provider = data.get("generation", {}).get("provider")
    if provider not in {"offline", "gemini_free_tier"}:
        raise ValueError(f"Unsupported generation provider: {provider}")
    if "openai" in json.dumps(data.get("generation", {}), ensure_ascii=False).lower():
        raise ValueError("OpenAI provider must not be used")
