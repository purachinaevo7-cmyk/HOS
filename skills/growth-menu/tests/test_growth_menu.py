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

    def test_offline_fixture_validates(self):
        data = generator.offline_fixture(self.target_date, self.feedback)
        generator.validate_content(data, self.config, self.target_date)

    def test_generate_and_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            data = generator.offline_fixture(self.target_date, self.feedback)
            generator.validate_content(data, self.config, self.target_date)
            generator.write_outputs(data, self.config, output_dir)
            report = auditor.audit(output_dir, self.target_date.isoformat())
            self.assertEqual(report["status"], "pass", json.dumps(report, ensure_ascii=False, indent=2))

    def test_excluded_learning_apps_are_rejected(self):
        data = generator.offline_fixture(self.target_date, self.feedback)
        data["focus_summary"] += " Duolingo"
        with self.assertRaises(ValueError):
            generator.validate_content(data, self.config, self.target_date)

    def test_raw_output_feedback_is_rejected(self):
        feedback = dict(self.feedback)
        feedback["raw_output"] = "private answer"
        with self.assertRaises(ValueError):
            recorder.validate_feedback(feedback, self.config)


if __name__ == "__main__":
    unittest.main()
