import json, pytest
from orchestrator.runner import Orchestrator
from orchestrator.executor import build_executor

def test_call_limit_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv('HOS_MAX_AGENT_CALLS','1')
    task={'task_id':'x','workflow':'investment_analysis_free','request':'r','target':{}}
    p=tmp_path/'t.json'; p.write_text(json.dumps(task))
    with pytest.raises(RuntimeError): Orchestrator(executor=build_executor('mock')).run_task(p)

def test_usage_json_generated(monkeypatch):
    monkeypatch.setenv('HOS_MAX_AGENT_CALLS','5')
    task={'task_id':'usage-free','workflow':'investment_analysis_free','request':'r','target':{}}
    p=__import__('pathlib').Path('tasks/working/usage-free.json'); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(task))
    r=Orchestrator(executor=build_executor('mock')).run_task(p)
    usage=json.load(open(f'runs/{r.run_id}/usage.json'))
    assert usage['actual_calls'] > 0
