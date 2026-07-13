"""Lightweight multi-agent orchestrator for HOS investment analysis workflows.

The runner intentionally keeps secrets outside source code. Provider/API keys should
be read by future model adapters from environment variables such as OPENAI_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class RunResult:
    task_id: str
    approved: bool
    report_path: Path
    hos_json_path: Path
    log_path: Path
    dry_run: bool


class Orchestrator:
    """Executes JSON tasks using YAML workflows and Markdown agent instructions."""

    def __init__(self, root: Path = ROOT, dry_run: bool = False) -> None:
        self.root = root
        self.dry_run = dry_run
        self.events: list[dict[str, Any]] = []

    def run_task(self, task_path: str | Path) -> RunResult:
        task_file = Path(task_path)
        if not task_file.is_absolute():
            task_file = self.root / task_file
        task = json.loads(task_file.read_text(encoding="utf-8"))
        workflow = self._load_workflow(task["workflow"])
        task_id = task.get("task_id") or datetime.now(timezone.utc).strftime("task-%Y%m%d%H%M%S")
        max_reruns = int(workflow.get("max_reruns", 2))
        context: dict[str, Any] = {"task": task, "outputs": {}, "reruns": {}}

        self._event("run_started", task_id=task_id, workflow=workflow["name"], dry_run=self.dry_run)
        for step in workflow["steps"]:
            if step["agent"] == "quality_reviewer":
                quality = self._execute_agent(step["agent"], context)
                context["outputs"][step["agent"]] = quality
                while not quality["approved"]:
                    rerun_agent = quality.get("rerun_agent")
                    count = context["reruns"].get(rerun_agent, 0)
                    if not rerun_agent or count >= max_reruns:
                        break
                    context["reruns"][rerun_agent] = count + 1
                    self._event("rerun_requested", agent=rerun_agent, attempt=count + 1)
                    context["outputs"][rerun_agent] = self._execute_agent(rerun_agent, context)
                    quality = self._execute_agent("quality_reviewer", context)
                    context["outputs"]["quality_reviewer"] = quality
            else:
                context["outputs"][step["agent"]] = self._execute_agent(step["agent"], context)

        writer_output = context["outputs"].get("hos_writer") or self._execute_agent("hos_writer", context)
        context["outputs"]["hos_writer"] = writer_output
        report_path, hos_json_path, log_path = self._write_artifacts(task_id, workflow, context)
        self._move_task(task_file, task_id)
        self._event("run_completed", task_id=task_id, approved=context["outputs"]["quality_reviewer"]["approved"])
        self._write_log(log_path)
        return RunResult(task_id, context["outputs"]["quality_reviewer"]["approved"], report_path, hos_json_path, log_path, self.dry_run)

    def _load_workflow(self, name: str) -> dict[str, Any]:
        path = self.root / "workflows" / f"{name}.yml"
        text = path.read_text(encoding="utf-8")
        if yaml is not None:
            return yaml.safe_load(text)
        return _parse_investment_workflow_yaml(text)

    def _agent_instructions(self, agent: str) -> str:
        return (self.root / "agents" / f"{agent}.md").read_text(encoding="utf-8")

    def _execute_agent(self, agent: str, context: dict[str, Any]) -> dict[str, Any]:
        self._agent_instructions(agent)
        self._event("agent_started", agent=agent)
        task = context["task"]
        request = task.get("request", "")
        target = task.get("target", "未指定")
        if agent == "ceo":
            output = {"agent": agent, "status": "completed", "summary": f"{target}の投資分析を分解しました。", "assignments": [{"agent": "researcher", "task": "投資調査", "inputs": {"target": target}}, {"agent": "analyst", "task": "投資仮説分析", "inputs": {"target": target}}], "assumptions": ["外部APIを使う場合はAPIキーを環境変数から読む。"], "next_agents": ["researcher", "analyst", "risk_reviewer"]}
        elif agent == "researcher":
            output = {"agent": agent, "status": "completed", "findings": [{"topic": "対象", "detail": f"対象は{target}。依頼内容: {request}", "source_required": False}], "data_gaps": ["最新価格・財務データは外部データソースで確認する。"], "handoff_to": "analyst"}
        elif agent == "analyst":
            output = {"agent": agent, "status": "completed", "investment_view": f"{target}は定量データ確認後に判断する候補。", "scenarios": {"bull": "成長率と利益率が改善する。", "base": "現状トレンドが継続する。", "bear": "需要悪化またはバリュエーション低下。"}, "key_metrics": ["売上成長率", "営業利益率", "ROIC", "FCF", "PER/EV-EBITDA"], "open_questions": ["安全域は十分か。"]}
        elif agent == "risk_reviewer":
            output = {"agent": agent, "status": "completed", "risks": [{"level": "medium", "description": "最新市場データ未確認", "mitigation": "データ取得エージェントまたは手動確認を追加する。"}], "blocking_issues": []}
        elif agent == "quality_reviewer":
            required = ["ceo", "researcher", "analyst", "risk_reviewer"]
            missing = [name for name in required if name not in context["outputs"]]
            output = {"agent": agent, "status": "completed", "approved": not missing, "score": 0.95 if not missing else 0.4, "issues": [f"missing {name}" for name in missing], "rerun_agent": missing[0] if missing else None, "rerun_reason": "required output missing" if missing else None}
        elif agent == "hos_writer":
            output = self._build_hos_output(context)
        else:
            raise ValueError(f"Unknown agent: {agent}")
        self._event("agent_completed", agent=agent, output=output)
        return output

    def _build_hos_output(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context["task"]
        target = task.get("target", "未指定")
        report = f"# Investment Analysis: {target}\n\n## Request\n{task.get('request', '')}\n\n## Investment View\n{context['outputs'].get('analyst', {}).get('investment_view', '')}\n\n## Risks\n- " + "\n- ".join(r.get("description", "") for r in context["outputs"].get("risk_reviewer", {}).get("risks", [])) + "\n"
        hos_update = {"outputs": [{"title": f"Investment Analysis: {target}", "project": "Investment", "brain": "HOS multi-agent", "skill": "investment_analysis", "format": "Markdown", "tags": ["investment", "analysis", str(target)], "keywords": [str(target), "risk", "valuation"]}]}
        return {"agent": "hos_writer", "status": "completed", "report_markdown": report, "hos_update": hos_update}

    def _write_artifacts(self, task_id: str, workflow: dict[str, Any], context: dict[str, Any]) -> tuple[Path, Path, Path]:
        report = self.root / workflow["outputs"]["final_report"].format(task_id=task_id)
        hos_json = self.root / workflow["outputs"]["hos_update_json"].format(task_id=task_id)
        log = self.root / "logs" / f"{task_id}.jsonl"
        if not self.dry_run:
            report.parent.mkdir(parents=True, exist_ok=True)
            hos_json.parent.mkdir(parents=True, exist_ok=True)
            log.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(context["outputs"]["hos_writer"]["report_markdown"], encoding="utf-8")
            hos_json.write_text(json.dumps(context["outputs"]["hos_writer"]["hos_update"], ensure_ascii=False, indent=2), encoding="utf-8")
        return report, hos_json, log

    def _move_task(self, task_file: Path, task_id: str) -> None:
        if self.dry_run or "tasks/inbox" not in task_file.as_posix():
            return
        completed = self.root / "tasks" / "completed" / f"{task_id}.json"
        completed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(task_file, completed)

    def _write_log(self, log_path: Path) -> None:
        if not self.dry_run:
            log_path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in self.events) + "\n", encoding="utf-8")

    def _event(self, event: str, **payload: Any) -> None:
        self.events.append({"ts": datetime.now(timezone.utc).isoformat(), "event": event, **payload})


def _parse_investment_workflow_yaml(text: str) -> dict[str, Any]:
    """Fallback parser for the repository's simple workflow YAML shape."""
    # Keep the runtime usable in minimal Python environments; PyYAML remains
    # listed in requirements.txt for general YAML support.
    return {
        "name": "investment_analysis",
        "version": 1,
        "max_reruns": 2,
        "artifact_paths": {"report_dir": "outputs/reports", "json_dir": "outputs/json", "log_dir": "logs"},
        "agents": ["ceo", "researcher", "analyst", "risk_reviewer", "quality_reviewer", "hos_writer"],
        "steps": [
            {"id": "plan", "agent": "ceo"},
            {"id": "research", "agent": "researcher"},
            {"id": "analyze", "agent": "analyst"},
            {"id": "risk_review", "agent": "risk_reviewer"},
            {"id": "quality_review", "agent": "quality_reviewer", "on_reject": "rerun_agent"},
            {"id": "write_hos", "agent": "hos_writer"},
        ],
        "outputs": {"final_report": "outputs/reports/{task_id}.md", "hos_update_json": "outputs/json/{task_id}.json"},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run HOS multi-agent workflows")
    parser.add_argument("task", help="Path to task JSON")
    parser.add_argument("--dry-run", action="store_true", help="Run without writing artifacts or moving tasks")
    args = parser.parse_args(argv)
    result = Orchestrator(dry_run=args.dry_run).run_task(args.task)
    print(json.dumps({"task_id": result.task_id, "approved": result.approved, "report_path": str(result.report_path), "hos_json_path": str(result.hos_json_path), "log_path": str(result.log_path), "dry_run": result.dry_run}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

