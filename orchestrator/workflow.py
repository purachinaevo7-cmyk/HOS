from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml

STATUSES = {"pending","running","completed","failed","skipped","retrying"}
@dataclass
class RetryPolicy:
    max_attempts: int = 1
@dataclass
class WorkflowStep:
    id: str; agent: str; action: str = "execute"; depends_on: list[str] = field(default_factory=list)
    input_mapping: dict[str, Any] = field(default_factory=dict); output_key: str = ""
    condition: str | None = None; validation: dict[str, Any] = field(default_factory=dict)
    retry_policy: dict[str, Any] = field(default_factory=lambda:{"max_attempts":1})
    timeout_seconds: int = 30; continue_on_error: bool = False
@dataclass
class WorkflowDefinition:
    id: str; version: str; max_rework_cycles: int; steps: list[WorkflowStep]; outputs: dict[str,str]

class WorkflowEngine:
    @staticmethod
    def load(root: Path, workflow_id: str) -> WorkflowDefinition:
        raw = yaml.safe_load((root/"workflows"/f"{workflow_id}.yml").read_text(encoding="utf-8"))
        steps = [WorkflowStep(**s) for s in raw["steps"]]
        return WorkflowDefinition(str(raw.get("id") or raw.get("name")), str(raw["version"]), int(raw.get("max_rework_cycles", raw.get("max_reruns",2))), steps, raw["outputs"])
    @staticmethod
    def validate(wf: WorkflowDefinition, registry: Any) -> None:
        ids=[s.id for s in wf.steps]
        if len(ids)!=len(set(ids)): raise ValueError("Duplicate workflow step id")
        for s in wf.steps:
            registry.get(s.agent)
            for dep in s.depends_on:
                if dep not in ids: raise ValueError(f"Step {s.id} depends on unknown step {dep}")
        graph={s.id:s.depends_on for s in wf.steps}; visiting=set(); visited=set()
        def visit(n):
            if n in visiting: raise ValueError(f"Cycle detected at workflow step {n}")
            if n in visited: return
            visiting.add(n)
            for d in graph[n]: visit(d)
            visiting.remove(n); visited.add(n)
        for i in ids: visit(i)
    @staticmethod
    def condition_passes(condition: str|None, context: dict[str,Any]) -> bool:
        if not condition or condition == "always": return True
        if condition == "review_has_critical": return any(o.get("severity")=="critical" for o in context["outputs"].values() if isinstance(o,dict))
        if condition.startswith("output_exists:"): return condition.split(":",1)[1] in context["outputs"]
        return False
