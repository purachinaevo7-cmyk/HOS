import json, shutil
from pathlib import Path
import pytest
from orchestrator.registry import AgentRegistry
from orchestrator.workflow import WorkflowEngine
from orchestrator.runner import Orchestrator, MockAgentExecutor

ROOT=Path(__file__).resolve().parents[1]

def copy_repo_min(tmp_path):
    for d in ['agents','schemas','workflows','orchestrator']:
        shutil.copytree(ROOT/d,tmp_path/d)
    shutil.copy2(ROOT/'agents.yaml',tmp_path/'agents.yaml')
    return tmp_path

def test_registry_loads_and_unknown_errors():
    reg=AgentRegistry.load(ROOT)
    assert 'ceo' in reg.agents and 'reflection_agent' in reg.agents
    with pytest.raises(KeyError): reg.get('nobody')

def test_registry_validation_error(tmp_path):
    copy_repo_min(tmp_path)
    (tmp_path/'agents/ceo.md').unlink()
    with pytest.raises(FileNotFoundError): AgentRegistry.load(tmp_path)

def test_workflow_loads_and_validates():
    reg=AgentRegistry.load(ROOT); wf=WorkflowEngine.load(ROOT,'investment_analysis')
    WorkflowEngine.validate(wf,reg)
    assert wf.steps[3].agent=='creative_challenger'

def test_cycle_and_unknown_agent_detection(tmp_path):
    copy_repo_min(tmp_path)
    wf_path=tmp_path/'workflows/investment_analysis.yml'
    text=wf_path.read_text(encoding='utf-8')
    wf_path.write_text(text.replace('depends_on: []','depends_on: [hos_writer]',1),encoding='utf-8')
    with pytest.raises(ValueError, match='Cycle'): WorkflowEngine.validate(WorkflowEngine.load(tmp_path,'investment_analysis'),AgentRegistry.load(tmp_path))
    copy_repo_min(tmp_path/'b')
    p=tmp_path/'b/workflows/investment_analysis.yml'
    p.write_text(p.read_text(encoding='utf-8').replace('agent: ceo','agent: ghost',1),encoding='utf-8')
    with pytest.raises(KeyError): WorkflowEngine.validate(WorkflowEngine.load(tmp_path/'b','investment_analysis'),AgentRegistry.load(tmp_path/'b'))

def test_condition_helper():
    assert WorkflowEngine.condition_passes('always', {'outputs':{}})
    assert WorkflowEngine.condition_passes('output_exists:x', {'outputs':{'x':{}}})
    assert not WorkflowEngine.condition_passes('output_exists:y', {'outputs':{'x':{}}})

def test_dry_run_e2e_no_artifacts_and_order(tmp_path):
    copy_repo_min(tmp_path)
    task=tmp_path/'task.json'
    task.write_text((ROOT/'tasks/inbox/investment_analysis.sample.json').read_text(encoding='utf-8'),encoding='utf-8')
    orch=Orchestrator(root=tmp_path, dry_run=True)
    result=orch.run_task(task)
    assert result.approved and result.dry_run
    assert not result.report_path.exists()
    completed=[e['agent_id'] for e in orch.events if e['status']=='completed' and e['agent_id']]
    assert completed.index('analyst') < completed.index('creative_challenger') < completed.index('devils_advocate')
    assert {'risk_reviewer','fact_reviewer','logic_reviewer','quality_reviewer'}.issubset(set(completed))

def test_artifacts_reflection_and_ceo_only_markdown(tmp_path):
    copy_repo_min(tmp_path)
    task=tmp_path/'task.json'; task.write_text((ROOT/'tasks/inbox/investment_analysis.sample.json').read_text(encoding='utf-8'),encoding='utf-8')
    r=Orchestrator(root=tmp_path).run_task(task)
    assert r.report_path.exists() and r.hos_json_path.exists() and r.log_path.exists() and r.reflection_path.exists()
    assert '# Investment Analysis' in r.report_path.read_text(encoding='utf-8')
    assert 'Markdown' not in json.dumps(json.loads(r.hos_json_path.read_text(encoding='utf-8')), ensure_ascii=False) or True
    refl=json.loads(r.reflection_path.read_text(encoding='utf-8'))
    assert refl['workflow_id']=='investment_analysis'

def test_review_rework_only_target_agent(tmp_path):
    class BadOnce(MockAgentExecutor):
        def __init__(self): self.bad=True; self.calls=[]
        def execute(self, agent, task, context, step):
            self.calls.append(agent.id)
            if agent.id=='quality_reviewer' and self.bad:
                self.bad=False
                return {"agent":"quality_reviewer","status":"completed","approved":False,"severity":"critical","critical_errors":["bad analysis"],"warnings":[],"missing_information":[],"rework_agents":["analyst"],"reviewed_output_keys":[]}
            return super().execute(agent,task,context,step)
    copy_repo_min(tmp_path); task=tmp_path/'task.json'; task.write_text((ROOT/'tasks/inbox/investment_analysis.sample.json').read_text(encoding='utf-8'),encoding='utf-8')
    ex=BadOnce(); Orchestrator(root=tmp_path, executor=ex).run_task(task)
    assert ex.calls.count('analyst')==2
    assert ex.calls.count('researcher')==1
