import json, os, socket
from types import SimpleNamespace
import pytest
from urllib import error
from orchestrator.executor import GeminiExecutor, ExecutorError, QuotaExhaustedError, RateLimitError, ExecutorTimeout, InvalidExecutorJSON
from orchestrator.workflow import WorkflowStep

class Resp:
    def __init__(self, data): self.data=data
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def read(self): return self.data.encode()

def agent(): return SimpleNamespace(id='researcher', version='1.0.0', prompt_path='missing.md', model='x', temperature=0.1, max_output_tokens=50, timeout_seconds=1)
def ctx(): return {'run_id':'r1','outputs':{},'workflow_id':'w'}
def task(): return {'task_id':'t1','request':'r','target':{}}
def step(): return WorkflowStep(id='s1', agent='researcher')
def env(monkeypatch): monkeypatch.setenv('GEMINI_API_KEY','secret'); monkeypatch.setenv('GEMINI_MODEL','gemini-test')

def test_extract_json_fenced():
    assert GeminiExecutor.extract_json('```json\n{"a":1}\n```') == {'a':1}

def test_missing_api_key(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    with pytest.raises(ExecutorError): GeminiExecutor()

def test_usage_metadata(monkeypatch):
    env(monkeypatch)
    body={'candidates':[{'content':{'parts':[{'text':json.dumps({'data':{'ok':True}})}]}}],'usageMetadata':{'totalTokenCount':7}}
    monkeypatch.setattr('orchestrator.executor.request.urlopen', lambda *a,**k: Resp(json.dumps(body)))
    out=GeminiExecutor().execute(agent(), task(), ctx(), step())
    assert out['usage_metadata']['totalTokenCount']==7

def test_invalid_json(monkeypatch):
    env(monkeypatch)
    body={'candidates':[{'content':{'parts':[{'text':'not json'}]}}]}
    monkeypatch.setattr('orchestrator.executor.request.urlopen', lambda *a,**k: Resp(json.dumps(body)))
    with pytest.raises(InvalidExecutorJSON): GeminiExecutor().execute(agent(), task(), ctx(), step())

def test_429_and_quota(monkeypatch):
    env(monkeypatch)
    def boom(*a,**k): raise error.HTTPError('u',429,'Too Many',{},None)
    monkeypatch.setattr('orchestrator.executor.request.urlopen', boom)
    with pytest.raises(RateLimitError): GeminiExecutor().execute(agent(), task(), ctx(), step())
    def quota(*a,**k):
        raise error.HTTPError('u',429,'quota exhausted',{},None)
    monkeypatch.setattr('orchestrator.executor.request.urlopen', quota)
    with pytest.raises(QuotaExhaustedError): GeminiExecutor().execute(agent(), task(), ctx(), step())

def test_timeout(monkeypatch):
    env(monkeypatch)
    monkeypatch.setattr('orchestrator.executor.request.urlopen', lambda *a,**k: (_ for _ in ()).throw(socket.timeout()))
    with pytest.raises(ExecutorTimeout): GeminiExecutor().execute(agent(), task(), ctx(), step())


def test_timeout_env_default_and_override(monkeypatch):
    env(monkeypatch)
    monkeypatch.delenv('GEMINI_TIMEOUT_SECONDS', raising=False)
    assert GeminiExecutor.configured_timeout_seconds(1) == 90
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS','90')
    assert GeminiExecutor.configured_timeout_seconds(30) == 90


def test_timeout_invalid_and_clamped(monkeypatch):
    env(monkeypatch)
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS','invalid')
    with pytest.raises(ExecutorError): GeminiExecutor.configured_timeout_seconds(30)
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS','999')
    assert GeminiExecutor.configured_timeout_seconds(30) == 300
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS','1')
    assert GeminiExecutor.configured_timeout_seconds(30) == 30


def test_urlopen_uses_gemini_timeout_env(monkeypatch):
    env(monkeypatch)
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS','90')
    seen={}
    body={'candidates':[{'content':{'parts':[{'text':json.dumps({'data':{'ok':True}})}]}}]}
    def fake_urlopen(*a, **k):
        seen['timeout']=k.get('timeout')
        return Resp(json.dumps(body))
    monkeypatch.setattr('orchestrator.executor.request.urlopen', fake_urlopen)
    GeminiExecutor().execute(agent(), task(), ctx(), step())
    assert seen['timeout'] == 90
