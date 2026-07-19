from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


generator = load_module("growth_generator", SKILL_DIR / "generate_growth_menu.py")
auditor = load_module("growth_auditor", SKILL_DIR / "audit_growth_menu.py")
recorder = load_module("growth_recorder", SKILL_DIR / "record_feedback.py")


class GrowthMenuTests(unittest.TestCase):
    def setUp(self):
        self.config = generator.load_json(SKILL_DIR / "config.json")
        self.feedback = generator.load_json(SKILL_DIR / "feedback" / "latest.json")
        self.target_date = date(2026, 7, 20)
        modules = generator.load_json(SKILL_DIR / "curriculum_seeds.json")["modules"]
        self.seed = next(item for item in modules if item["id"] == "ksf_vs_advantage")

    def test_deterministic_lesson_validates(self):
        data = generator.deterministic_lesson(self.target_date, self.feedback, self.seed)
        generator.validate_content(data, self.config, self.target_date)
        self.assertEqual(data["generation"]["provider"], "offline")
        self.assertEqual(data["case_profile"]["name"], "ニトリホールディングス")
        self.assertIn(data["case_profile"]["name"], data["focus_summary"])

    def test_generate_and_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            data = generator.deterministic_lesson(self.target_date, self.feedback, self.seed)
            generator.validate_content(data, self.config, self.target_date)
            generator.write_outputs(data, self.config, output_dir)
            report = auditor.audit(output_dir, self.target_date.isoformat())
            self.assertEqual(report["status"], "pass", json.dumps(report, ensure_ascii=False, indent=2))

    def test_pdf_is_lesson_not_submission_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            data = generator.deterministic_lesson(self.target_date, self.feedback, self.seed)
            generator.write_outputs(data, self.config, output_dir)
            pdf_text, _, page_count, _ = auditor.pdf_text_and_fonts(output_dir / "latest.pdf")
            self.assertEqual(page_count, 5)
            self.assertIn("会社スナップショット", pdf_text)
            self.assertIn("ニトリホールディングス", pdf_text)
            self.assertIn("基本概念", pdf_text)
            self.assertIn("ケースの状況", pdf_text)
            self.assertIn("英文法の授業", pdf_text)
            for forbidden in self.config["output"]["forbidden_deck_phrases"]:
                self.assertNotIn(forbidden, pdf_text)

    def test_pdf_and_preview_are_primary_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            data = generator.deterministic_lesson(self.target_date, self.feedback, self.seed)
            outputs = generator.write_outputs(data, self.config, output_dir)
            self.assertTrue(outputs["latest_pdf"].exists())
            self.assertTrue(outputs["preview"].exists())
            self.assertFalse((output_dir / "latest.pptx").exists())
            notification = outputs["notification"].read_text(encoding="utf-8")
            self.assertIn("latest.pdf", notification)
            self.assertIn("latest-preview.png", notification)
            self.assertNotIn("latest.pptx", notification)

    def test_company_profile_requires_official_source(self):
        data = generator.deterministic_lesson(self.target_date, self.feedback, self.seed)
        data["case_profile"]["source_url"] = ""
        with self.assertRaises(ValueError):
            generator.validate_content(data, self.config, self.target_date)

    def test_excluded_learning_apps_are_rejected(self):
        data = generator.deterministic_lesson(self.target_date, self.feedback, self.seed)
        data["focus_summary"] += " Duolingo"
        with self.assertRaises(ValueError):
            generator.validate_content(data, self.config, self.target_date)

    def test_openai_provider_is_rejected(self):
        data = generator.deterministic_lesson(self.target_date, self.feedback, self.seed)
        data["generation"]["provider"] = "openai"
        with self.assertRaises(ValueError):
            generator.validate_content(data, self.config, self.target_date)

    def test_raw_output_feedback_is_rejected(self):
        feedback = dict(self.feedback)
        feedback["raw_output"] = "private answer"
        with self.assertRaises(ValueError):
            recorder.validate_feedback(feedback, self.config)


if __name__ == "__main__":
    unittest.main()
