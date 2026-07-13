from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json, yaml
REQUIRED={"id","display_name","role","prompt_path","version","enabled","model","temperature","max_output_tokens","timeout_seconds","allowed_tools","output_schema","tags"}
CANONICAL="agents/registry.yml"
VALID_EXECUTORS={"mock","openai","replay"}; VALID_PROVIDERS={"mock","openai","openai-compatible","replay"}
@dataclass(frozen=True)
class AgentDefinition:
    id:str; display_name:str; role:str; prompt_path:str; version:str; enabled:bool
    model:str; temperature:float; max_output_tokens:int; timeout_seconds:int; allowed_tools:list[str]; output_schema:str; tags:list[str]
    description:str=""; input_schema:str="schemas/agent_input.schema.json"; executor:str="mock"; provider:str="mock"; max_retries:int=1
    model_provider:str|None=None
class AgentRegistry:
    def __init__(self, agents:dict[str,AgentDefinition], root:Path, all_agents:dict[str,AgentDefinition]|None=None): self.agents=agents; self.all_agents=all_agents or agents; self.root=root
    @classmethod
    def load(cls, root:Path, path:str|None=None)->"AgentRegistry":
        rel=path or (CANONICAL if (root/CANONICAL).exists() else "agents.yaml")
        data=yaml.safe_load((root/rel).read_text(encoding='utf-8')) or {}; agents={}; all_agents={}; seen=set(); errors=[]
        for raw in data.get('agents',[]):
            if raw.get('id') in seen: errors.append(f"Duplicate agent id: {raw.get('id')}"); continue
            seen.add(raw.get('id'))
            normalized=dict(raw)
            if 'provider' not in normalized and 'model_provider' in normalized: normalized['provider']=normalized['model_provider']
            if 'executor' not in normalized: normalized['executor']='mock' if normalized.get('provider','mock')=='mock' else 'openai'
            if 'description' not in normalized: normalized['description']=normalized.get('role','')
            if 'input_schema' not in normalized: normalized['input_schema']='schemas/agent_input.schema.json'
            if 'max_retries' not in normalized: normalized['max_retries']=1
            missing=REQUIRED-normalized.keys()
            if missing: errors.append(f"Agent {raw.get('id','<unknown>')} missing fields: {sorted(missing)}"); continue
            if normalized['executor'] not in VALID_EXECUTORS: errors.append(f"Agent {normalized['id']} invalid executor: {normalized['executor']}")
            if normalized['provider'] not in VALID_PROVIDERS: errors.append(f"Agent {normalized['id']} invalid provider: {normalized['provider']}")
            if not normalized.get('model'): errors.append(f"Agent {normalized['id']} model is required")
            agent=AgentDefinition(**{k:v for k,v in normalized.items() if k in AgentDefinition.__dataclass_fields__})
            all_agents[agent.id]=agent
            if agent.enabled: agents[agent.id]=agent
        if errors: raise ValueError('; '.join(errors))
        reg=cls(agents,root,all_agents); reg.validate_files(); return reg
    def validate_files(self)->None:
        errors=[]
        for a in self.all_agents.values():
            if not (self.root/a.prompt_path).is_file(): errors.append(f"{a.id} prompt missing: {a.prompt_path}")
            if not (self.root/a.output_schema).is_file(): errors.append(f"{a.id} output schema missing: {a.output_schema}")
            if a.input_schema and not (self.root/a.input_schema).is_file(): errors.append(f"{a.id} input schema missing: {a.input_schema}")
        if errors: raise FileNotFoundError('; '.join(errors))
    def get(self,agent_id:str)->AgentDefinition:
        if agent_id in self.agents: return self.agents[agent_id]
        if agent_id in self.all_agents: raise KeyError(f"Disabled agent id referenced: {agent_id}")
        raise KeyError(f"Unknown agent id: {agent_id}")
    def require_all(self,ids:list[str])->None:
        for i in ids: self.get(i)
    def to_ui(self)->dict[str,Any]:
        return {'agents':[a.__dict__ for a in self.all_agents.values()]}
    def export_ui(self,path:Path)->Path:
        path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(self.to_ui(),ensure_ascii=False,indent=2),encoding='utf-8'); return path
