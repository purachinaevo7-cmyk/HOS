from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json, yaml
STATUSES={"pending","running","completed","failed","skipped","retrying","partial","cancelled"}
@dataclass
class WorkflowStep:
    id:str; agent:str; action:str="execute"; depends_on:list[str]=field(default_factory=list); input_mapping:dict[str,Any]=field(default_factory=dict); output_key:str=""; condition:str|None="always"; validation:dict[str,Any]=field(default_factory=dict); retry_policy:dict[str,Any]=field(default_factory=lambda:{"max_attempts":1}); timeout_seconds:int=30; continue_on_error:bool=False; optional:bool=False; concurrency_group:str="default"; approval_gate:bool=False; name:str=""
@dataclass
class WorkflowDefinition:
    id:str; version:str; max_rework_cycles:int; steps:list[WorkflowStep]; outputs:dict[str,str]; name:str=""
class WorkflowEngine:
    @staticmethod
    def load(root:Path, workflow_id:str)->WorkflowDefinition:
        raw=yaml.safe_load((root/'workflows'/f'{workflow_id}.yml').read_text(encoding='utf-8'))
        steps=[WorkflowStep(**s) for s in raw['steps']]
        return WorkflowDefinition(str(raw.get('id') or raw.get('name')),str(raw['version']),int(raw.get('max_rework_cycles',raw.get('max_reruns',2))),steps,raw.get('outputs',{}),raw.get('name',''))
    @staticmethod
    def validate(wf:WorkflowDefinition, registry:Any)->None:
        ids=[s.id for s in wf.steps]
        if len(ids)!=len(set(ids)): raise ValueError('Duplicate workflow step id')
        keys=[s.output_key or s.id for s in wf.steps]
        if len(keys)!=len(set(keys)): raise ValueError('Duplicate workflow output_key')
        known=set(ids)
        for s in wf.steps:
            registry.get(s.agent)
            for dep in s.depends_on:
                if dep not in known: raise ValueError(f'Step {s.id} depends on unknown step {dep}')
            if s.condition and not WorkflowEngine.condition_valid(s.condition): raise ValueError(f'Invalid condition for {s.id}: {s.condition}')
        WorkflowEngine.topological_sort(wf)
    @staticmethod
    def topological_sort(wf:WorkflowDefinition)->list[WorkflowStep]:
        by={s.id:s for s in wf.steps}; visiting=set(); visited=set(); order=[]
        def visit(n):
            if n in visiting: raise ValueError(f'Cycle detected at workflow step {n}')
            if n in visited: return
            visiting.add(n)
            for d in by[n].depends_on: visit(d)
            visiting.remove(n); visited.add(n); order.append(by[n])
        for s in wf.steps: visit(s.id)
        return order
    @staticmethod
    def condition_valid(condition:str|None)->bool:
        if not condition: return True
        return condition=='always' or condition=='review_has_critical' or condition.startswith('output_exists:') or condition.startswith('env:')
    @staticmethod
    def condition_passes(condition:str|None, context:dict[str,Any])->bool:
        if not condition or condition=='always': return True
        if condition=='review_has_critical': return any((o.get('data',o).get('severity') if isinstance(o.get('data',o),dict) else None)=='critical' for o in context['outputs'].values() if isinstance(o,dict))
        if condition.startswith('output_exists:'): return condition.split(':',1)[1] in context['outputs']
        if condition.startswith('env:'):
            import os; return bool(os.getenv(condition.split(':',1)[1]))
        return False
    @staticmethod
    def runnable_steps(wf:WorkflowDefinition, step_status:dict[str,str])->list[WorkflowStep]:
        return [s for s in wf.steps if step_status.get(s.id,'pending')=='pending' and all(step_status.get(d) in {'completed','partial','skipped'} for d in s.depends_on)]
    @staticmethod
    def export_ui(root:Path, path:Path)->Path:
        workflows=[]
        for p in sorted((root/'workflows').glob('*.yml')):
            wf=WorkflowEngine.load(root,p.stem)
            workflows.append({'id':wf.id,'name':wf.name or wf.id,'version':wf.version,'steps':[s.__dict__ for s in wf.steps],'outputs':wf.outputs})
        path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps({'workflows':workflows},ensure_ascii=False,indent=2),encoding='utf-8'); return path
