from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml

REQUIRED = {"id","display_name","role","prompt_path","version","enabled","model_provider","model","temperature","max_output_tokens","timeout_seconds","allowed_tools","output_schema","tags"}

@dataclass(frozen=True)
class AgentDefinition:
    id: str; display_name: str; role: str; prompt_path: str; version: str; enabled: bool
    model_provider: str; model: str; temperature: float; max_output_tokens: int; timeout_seconds: int
    allowed_tools: list[str]; output_schema: str; tags: list[str]

class AgentRegistry:
    def __init__(self, agents: dict[str, AgentDefinition], root: Path):
        self.agents = agents; self.root = root
    @classmethod
    def load(cls, root: Path, path: str = "agents.yaml") -> "AgentRegistry":
        data = yaml.safe_load((root/path).read_text(encoding="utf-8")) or {}
        agents = {}
        for raw in data.get("agents", []):
            missing = REQUIRED - raw.keys()
            if missing: raise ValueError(f"Agent {raw.get('id','<unknown>')} missing fields: {sorted(missing)}")
            agent = AgentDefinition(**raw)
            if agent.enabled: agents[agent.id] = agent
        reg = cls(agents, root); reg.validate_files(); return reg
    def validate_files(self) -> None:
        errors=[]
        for a in self.agents.values():
            if not (self.root/a.prompt_path).is_file(): errors.append(f"{a.id} prompt missing: {a.prompt_path}")
            if not (self.root/a.output_schema).is_file(): errors.append(f"{a.id} schema missing: {a.output_schema}")
        if errors: raise FileNotFoundError("; ".join(errors))
    def get(self, agent_id: str) -> AgentDefinition:
        try: return self.agents[agent_id]
        except KeyError as e: raise KeyError(f"Unknown or disabled agent id: {agent_id}") from e
    def require_all(self, ids: list[str]) -> None:
        for i in ids: self.get(i)
