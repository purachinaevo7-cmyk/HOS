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
            output = {"agent": agent, "status": "completed", "summary": f"{target}の投資分析を分解しました。", "assignments": [{"agent": "researcher", "task": "投資調査", "inputs": {"target": target}}, {"agent": "analyst", "task": "投資仮説分析", "inputs": {"target": target}}, {"agent": "creative_challenger", "task": "通常分析後の前提見直し・反対仮説・代替案提示", "inputs": {"base_analysis": "analyst", "research_findings": "researcher"}}], "assumptions": ["外部APIを使う場合はAPIキーを環境変数から読む。", "creative_challengerの案は新規性、根拠、意思決定への影響でCEOが選別する。"], "next_agents": ["researcher", "analyst", "creative_challenger", "risk_reviewer"]}
        elif agent == "researcher":
            output = {"agent": agent, "status": "completed", "findings": [{"topic": "対象", "detail": f"対象は{target}。依頼内容: {request}", "source_required": False}], "data_gaps": ["最新価格・財務データは外部データソースで確認する。"], "handoff_to": "analyst"}
        elif agent == "analyst":
            output = {"agent": agent, "status": "completed", "investment_view": f"{target}は定量データ確認後に判断する候補。", "scenarios": {"bull": "成長率と利益率が改善する。", "base": "現状トレンドが継続する。", "bear": "需要悪化またはバリュエーション低下。"}, "key_metrics": ["売上成長率", "営業利益率", "ROIC", "FCF", "PER/EV-EBITDA"], "open_questions": ["安全域は十分か。"]}
        elif agent == "creative_challenger":
            analyst_output = context["outputs"].get("analyst", {})
            researcher_output = context["outputs"].get("researcher", {})
            output = {
                "agent": agent,
                "status": "completed",
                "input_summary": {
                    "base_analysis_used": bool(analyst_output),
                    "research_findings_used": bool(researcher_output),
                    "other_inputs": ["ceo_plan"],
                },
                "challenged_assumptions": [
                    {
                        "assumption": "現状トレンドが継続する",
                        "challenge": "需要構造や競争条件が変化するとbaseシナリオの前提が崩れる可能性がある。",
                        "evidence": "analystのbaseシナリオとresearcherのdata_gapsを照合し、未確認データを主要な不確実性として扱う。",
                        "evidence_strength": "medium",
                        "decision_relevance": "安全域、追加調査、ポジションサイズの判断に影響する。",
                    }
                ],
                "ideas": [
                    {
                        "title": "反対仮説として需要悪化時の勝ち筋を検証",
                        "type": "contrarian",
                        "hypothesis": f"{target}は弱気局面でもコスト構造または競争優位が確認できれば投資候補に残る。",
                        "rationale": "通常分析のbearシナリオを単なる下振れではなく、競合脱落や価格決定力確認の機会として再解釈する。",
                        "evidence": "base_analysisのbearシナリオとkey_metricsを根拠に、利益率・FCF・ROICを検証対象にする。",
                        "evidence_strength": "medium",
                        "feasibility": "high",
                        "expected_impact": "medium",
                        "decision_impact": "下落時に見送るだけでなく、追加購入条件または撤退条件を明確化できる。",
                        "validation_steps": ["景気後退期の利益率推移を確認する", "競合とのFCF耐性を比較する"],
                        "risks_or_limits": ["最新財務データが未確認の場合は結論を保留する"],
                    },
                    {
                        "title": "サブスクリプション業界の継続率モデルで類推",
                        "type": "cross_industry_analogy",
                        "hypothesis": "顧客維持率やスイッチングコストに相当する指標が高ければ、短期バリュエーションより長期LTVを重視できる。",
                        "rationale": "異業種のLTV/CAC的な見方を使い、単年度利益だけでは見えない耐久性を検証する。",
                        "evidence": "research_findingsで未確認の市場・顧客データを検証候補として扱う。",
                        "evidence_strength": "low",
                        "feasibility": "medium",
                        "expected_impact": "medium",
                        "decision_impact": "比較指標をPER中心から顧客基盤の質へ広げるか判断できる。",
                        "validation_steps": ["解約率・更新率・リピート率に近い開示指標を探す", "同業他社と顧客維持指標を比較する"],
                        "risks_or_limits": ["対象業界に継続率モデルが適用できない可能性がある"],
                    },
                ],
                "ceo_selection_guidance": {
                    "do_not_auto_adopt": True,
                    "selection_criteria": ["novelty", "evidence", "decision_impact"],
                    "recommended_shortlist": ["反対仮説として需要悪化時の勝ち筋を検証"],
                },
                "handoff_to": "risk_reviewer",
            }
        elif agent == "risk_reviewer":
            creative_output = context["outputs"].get("creative_challenger", {})
            creative_risk = "創造性担当の案は根拠と実行可能性を確認してから採用する。" if creative_output else "創造性担当のレビュー未実施。"
            output = {"agent": agent, "status": "completed", "risks": [{"level": "medium", "description": "最新市場データ未確認", "mitigation": "データ取得エージェントまたは手動確認を追加する。"}, {"level": "low" if creative_output else "medium", "description": creative_risk, "mitigation": "quality_reviewerで根拠不足・事実誤認を確認する。"}], "blocking_issues": []}
        elif agent == "quality_reviewer":
            required = ["ceo", "researcher", "analyst", "creative_challenger", "risk_reviewer"]
            missing = [name for name in required if name not in context["outputs"]]
            issues = [f"missing {name}" for name in missing]
            creative = context["outputs"].get("creative_challenger", {})
            for index, idea in enumerate(creative.get("ideas", []), start=1):
                for field in ("evidence", "feasibility", "expected_impact"):
                    if not idea.get(field):
                        issues.append(f"creative_challenger idea {index} missing {field}")
            if creative and not creative.get("ceo_selection_guidance", {}).get("do_not_auto_adopt"):
                issues.append("creative_challenger must tell CEO not to auto-adopt ideas")
            rerun_agent = missing[0] if missing else ("creative_challenger" if any(issue.startswith("creative_challenger") for issue in issues) else None)
            output = {"agent": agent, "status": "completed", "approved": not issues, "score": 0.95 if not issues else 0.4, "issues": issues, "rerun_agent": rerun_agent, "rerun_reason": "required output missing or creative challenge evidence issue" if issues else None}
        elif agent == "hos_writer":
            output = self._build_hos_output(context)
        else:
            raise ValueError(f"Unknown agent: {agent}")
        self._event("agent_completed", agent=agent, output=output)
        return output

    def _build_hos_output(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context["task"]
        target = task.get("target", "未指定")
        creative_ideas = context["outputs"].get("creative_challenger", {}).get("ideas", [])
        creative_section = "\n".join(
            f"- {idea.get('title', '')}: feasibility={idea.get('feasibility', '')}, expected_impact={idea.get('expected_impact', '')}"
            for idea in creative_ideas
        )
        report = f"# Investment Analysis: {target}\n\n## Request\n{task.get('request', '')}\n\n## Investment View\n{context['outputs'].get('analyst', {}).get('investment_view', '')}\n\n## Creative Challenge\n{creative_section}\n\n## Risks\n- " + "\n- ".join(r.get("description", "") for r in context["outputs"].get("risk_reviewer", {}).get("risks", [])) + "\n"
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
        "agents": ["ceo", "researcher", "analyst", "creative_challenger", "risk_reviewer", "quality_reviewer", "hos_writer"],
        "steps": [
            {"id": "plan", "agent": "ceo"},
            {"id": "research", "agent": "researcher"},
            {"id": "analyze", "agent": "analyst"},
            {"id": "creative_challenge", "agent": "creative_challenger"},
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

