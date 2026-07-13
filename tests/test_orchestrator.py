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
    assert "Investment Analysis: Test Corp" in result.report_path.read_text(encoding="utf-8")
    hos_json = json.loads(result.hos_json_path.read_text(encoding="utf-8"))
    assert hos_json["outputs"][0]["skill"] == "investment_analysis"
    assert result.log_path.exists()


def test_quality_reviewer_requests_rerun_for_missing_output():
    orchestrator = Orchestrator(dry_run=True)
    context = {"task": {"target": "X"}, "outputs": {"ceo": {}, "researcher": {}, "risk_reviewer": {}}, "reruns": {}}

    quality = orchestrator._execute_agent("quality_reviewer", context)

    assert quality["approved"] is False
    assert quality["rerun_agent"] == "analyst"
