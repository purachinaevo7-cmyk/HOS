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
        self.seed = generator.select_seed(self.target_date, self.feedback, [])

    def test_deterministic_lesson_validates(self):
        data = generator.deterministic_lesson(self.target_date, self.feedback, self.seed)
        generator.validate_content(data, self.config, self.target_date)
        self.assertEqual(data["generation"]["provider"], "offline")

    def test_generate_and_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            data = generator.deterministic_lesson(self.target_date, self.feedback, self.seed)
            generator.validate_content(data, self.config, self.target_date)
            generator.write_outputs(data, self.config, output_dir)
            report = auditor.audit(output_dir, self.target_date.isoformat())
            self.assertEqual(report["status"], "pass", json.dumps(report, ensure_ascii=False, indent=2))

    def test_powerpoint_is_lesson_not_submission_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            data = generator.deterministic_lesson(self.target_date, self.feedback, self.seed)
            generator.write_outputs(data, self.config, output_dir)
            ppt_text, _ = auditor.pptx_text_and_fonts(output_dir / "latest.pptx")
            self.assertIn("基本概念", ppt_text)
            self.assertIn("ケースの状況", ppt_text)
            self.assertIn("英文法の授業", ppt_text)
            for forbidden in self.config["output"]["forbidden_deck_phrases"]:
                self.assertNotIn(forbidden, ppt_text)

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
