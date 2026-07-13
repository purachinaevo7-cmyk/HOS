import json
from pathlib import Path

from orchestrator.runner import Orchestrator


def test_dry_run_does_not_write_artifacts(tmp_path):
    task = tmp_path / "task.json"
    task.write_text(json.dumps({
        "task_id": "dry-run-test",
        "workflow": "investment_analysis",
        "request": "Analyze Example Corp",
        "target": "Example Corp",
    }), encoding="utf-8")

    result = Orchestrator(dry_run=True).run_task(task)

    assert result.approved is True
    assert result.dry_run is True
    assert not result.report_path.exists()
    assert not result.hos_json_path.exists()


def test_run_writes_report_json_and_log(tmp_path):
    root = tmp_path
    for directory in ["agents", "workflows", "outputs/reports", "outputs/json", "logs", "tasks/completed"]:
        (root / directory).mkdir(parents=True, exist_ok=True)

    source_root = Path(__file__).resolve().parents[1]
    for agent_file in (source_root / "agents").glob("*.md"):
        (root / "agents" / agent_file.name).write_text(agent_file.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "workflows" / "investment_analysis.yml").write_text(
        (source_root / "workflows" / "investment_analysis.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    task = root / "task.json"
    task.write_text(json.dumps({
        "task_id": "write-test",
        "workflow": "investment_analysis",
        "request": "Analyze Test Corp",
        "target": "Test Corp",
    }), encoding="utf-8")

    result = Orchestrator(root=root).run_task(task)

    assert result.approved is True
    assert result.report_path.exists()
    report = result.report_path.read_text(encoding="utf-8")
    assert "Investment Analysis: Test Corp" in report
    assert "## Creative Challenge" in report
    assert "feasibility=high" in report
    hos_json = json.loads(result.hos_json_path.read_text(encoding="utf-8"))
    assert hos_json["outputs"][0]["skill"] == "investment_analysis"
    assert result.log_path.exists()


def test_quality_reviewer_requests_rerun_for_missing_output():
    orchestrator = Orchestrator(dry_run=True)
    context = {"task": {"target": "X"}, "outputs": {"ceo": {}, "researcher": {}, "risk_reviewer": {}}, "reruns": {}}

    quality = orchestrator._execute_agent("quality_reviewer", context)

    assert quality["approved"] is False
    assert quality["rerun_agent"] == "analyst"


def test_creative_challenger_runs_after_analysis_before_risk_review():
    orchestrator = Orchestrator(dry_run=True)
    task = Path(__file__).resolve().parents[1] / "tasks/inbox/investment_analysis.sample.json"

    result = orchestrator.run_task(task)

    assert result.approved is True
    completed_agents = [
        event["agent"]
        for event in orchestrator.events
        if event["event"] == "agent_completed"
    ]
    assert completed_agents.index("analyst") < completed_agents.index("creative_challenger")
    assert completed_agents.index("creative_challenger") < completed_agents.index("risk_reviewer")


def test_creative_challenger_output_is_structured_and_quality_checked():
    orchestrator = Orchestrator(dry_run=True)
    context = {
        "task": {"target": "X"},
        "outputs": {
            "ceo": {},
            "researcher": {"findings": []},
            "analyst": {"investment_view": "base", "scenarios": {"base": "trend"}},
        },
        "reruns": {},
    }

    creative = orchestrator._execute_agent("creative_challenger", context)

    assert creative["input_summary"]["base_analysis_used"] is True
    assert creative["input_summary"]["research_findings_used"] is True
    assert creative["ceo_selection_guidance"]["do_not_auto_adopt"] is True
    for idea in creative["ideas"]:
        assert idea["evidence"]
        assert idea["feasibility"] in {"high", "medium", "low"}
        assert idea["expected_impact"] in {"high", "medium", "low"}

    context["outputs"]["creative_challenger"] = {
        "agent": "creative_challenger",
        "status": "completed",
        "ideas": [{"title": "weak idea", "evidence": "", "feasibility": "high"}],
        "ceo_selection_guidance": {"do_not_auto_adopt": True},
    }
    context["outputs"]["risk_reviewer"] = {}
    quality = orchestrator._execute_agent("quality_reviewer", context)

    assert quality["approved"] is False
    assert quality["rerun_agent"] == "creative_challenger"
