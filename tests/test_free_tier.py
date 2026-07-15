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

from orchestrator.executor import GeminiExecutor, ExecutorTimeout

class TimeoutGeminiExecutor(GeminiExecutor):
    def __init__(self):
        self.usage=[]; self.calls=0; self.model='gemini-test'
    def execute(self, agent, task, context, step):
        self.calls += 1
        raise ExecutorTimeout(f'gemini timeout after 30s (agent={agent.id}, attempt={context.get("attempt_number")})')


def test_gemini_free_timeout_retries_once_and_returns_partial(monkeypatch, tmp_path):
    monkeypatch.setenv('HOS_FREE_TIER_MODE','true')
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS','30')
    monkeypatch.delenv('HOS_MAX_AGENT_CALLS', raising=False)
    task={'task_id':'timeout-free','workflow':'investment_analysis_free','request':'r','target':{}}
    p=tmp_path/'t.json'; p.write_text(json.dumps(task))
    ex=TimeoutGeminiExecutor()
    r=Orchestrator(executor=ex).run_task(p)
    assert ex.calls == 10
    run=json.load(open(f'runs/{r.run_id}/run.json'))
    assert run['status'] == 'partial'
    events=[json.loads(line) for line in open(f'runs/{r.run_id}/logs/sanitized.jsonl')]
    timeout_events=[e for e in events if e.get('error_type') == 'ExecutorTimeout']
    assert len(timeout_events) == 10
    assert set(e['attempt_number'] for e in timeout_events) == {1, 2}
    assert all(e['timeout_seconds'] == 30 for e in timeout_events)
