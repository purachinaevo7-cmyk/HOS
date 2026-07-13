from __future__ import annotations
import json, os, time
from pathlib import Path
from typing import Any
from urllib import request, error
from orchestrator.schemas import envelope
from orchestrator.security import redact_secret
class ExecutorError(Exception): pass
class RateLimitError(ExecutorError): pass
class ExecutorTimeout(ExecutorError): pass
class DeterministicMockExecutor:
    scenarios={'success','partial','failed','invalid_json','timeout','critical_review','rate_limit'}
    def __init__(self, scenario='success', fixture_dir: Path|None=None): self.scenario=scenario; self.fixture_dir=fixture_dir
    def execute(self, agent, task: dict[str,Any], context: dict[str,Any], step) -> dict[str,Any]:
        if not hasattr(self,'scenario'): self.scenario='success'
        if self.scenario=='timeout': raise ExecutorTimeout('mock timeout')
        if self.scenario=='rate_limit': raise RateLimitError('mock 429 rate limit')
        if self.scenario=='invalid_json': return {'not':'an envelope'}
        target=task.get('target',{}); name=target.get('company_name') if isinstance(target,dict) else str(target); ticker=target.get('ticker','') if isinstance(target,dict) else ''
        missing=['latest price','latest earnings','verified news','valuation multiples']
        status='partial' if self.scenario=='partial' else ('failed' if self.scenario=='failed' else 'completed')
        data=self._data(agent.id, step.output_key or step.id, name, ticker, target, context, missing)
        warnings=[]; errors=[]
        if agent.id.endswith('reviewer') and self.scenario=='critical_review':
            data.update({'approved':False,'severity':'critical','critical_errors':['injected critical review'],'rework_requests':[{'target_agent':'base_analyst','target_output_key':'base_analysis','reason':'injected','required_changes':['add evidence'],'priority':'high'}]})
        return envelope(agent.id, getattr(agent,'version','1.0.0'), context.get('run_id',''), task.get('task_id','compat'), step.id, status, data, missing_information=missing if agent.id in {'researcher','market_analyst','financial_analyst'} else [], warnings=warnings, errors=errors)
    def _data(self, aid, key, name, ticker, target, context, missing):
        if aid=='ceo_planner' or aid=='ceo': return {'summary':f'{name} の依頼を分解しました','assignments':['research','analysis','review'],'approval_gates':['external_actions']}
        if aid in {'researcher','market_analyst','financial_analyst','industry_analyst'}: return {'findings':[{'topic':aid,'detail':'mock fixture; not verified live data','freshness':'sample'}],'data_availability':'sample_only'}
        if aid in {'base_analyst','analyst'}: return {'company_evaluation':{'score':55,'rank':'C','comment':'sample_only; verified data required'},'price_evaluation':{'score':0,'rank':'評価不能','comment':'latest price unavailable'},'overall_judgment':'情報不足のため保留','bull_case':'市況回復','base_case':'確認待ち','bear_case':'需給悪化','current_action':'最新データ取得後に再評価','next_checkpoints':['最新決算','現在株価'],'confidence':'low'}
        if aid=='creative_challenger': return {'input_summary':{'base_analysis_used':bool(context.get('outputs',{}).get('base_analysis') or context.get('outputs',{}).get('analyst')),'research_findings_used':bool(context.get('outputs',{}).get('research') or context.get('outputs',{}).get('researcher'))},'ideas':[{'title':'先行指標で段階判断','evidence':'mock evidence placeholder; not verified live data','evidence_strength':'low','feasibility':'high','expected_impact':'medium'}],'ceo_selection_guidance':{'do_not_auto_adopt':True}}
        if aid=='devils_advocate': return {'rejection_reasons':['最新データなしでは投資判断不可'],'disconfirming_signals':['粗利率悪化','在庫増加']}
        if aid in {'risk_reviewer','fact_reviewer','logic_reviewer','quality_reviewer'}: return {'approved':True,'severity':'warning','review_scope':[key],'critical_errors':[],'warnings':['mock実行のため最新情報は未検証'],'missing_information':missing,'contradictions':[],'unsupported_claims':[],'rework_requests':[]}
        if aid=='hos_writer': return {'hos_update':{'outputs':[{'title':f'AI Company Report: {name}','project':'AI Company','brain':'HOS AI Company','skill':context.get('workflow_id','workflow'),'format':'Markdown','tags':['ai-company',ticker,name],'keywords':[ticker,name]}]}}
        if aid=='ceo_integrator': return {'final_report_sections':['Request','Findings','Review','Next Actions'],'decision':'partial_until_verified'}
        if aid=='reflection_agent': return {'what_worked':['workflow completed'],'what_failed':['live research disabled'],'knowledge_candidates':[],'follow_up_tasks':['verify live data']}
        return {'message':f'{aid} completed'}
class OpenAICompatibleExecutor:
    def __init__(self):
        self.api_key=os.getenv('OPENAI_API_KEY',''); self.base_url=os.getenv('OPENAI_BASE_URL','https://api.openai.com/v1')
        if not self.api_key: raise ExecutorError('OPENAI_API_KEY is required for openai executor; refusing to auto-switch to mock')
    def execute(self, agent, task, context, step):
        prompt=Path(agent.prompt_path).read_text(encoding='utf-8') if Path(agent.prompt_path).exists() else ''
        body=json.dumps({'model':agent.model,'messages':[{'role':'system','content':prompt},{'role':'user','content':json.dumps({'task':task,'context_outputs':context.get('outputs',{}),'step':step.id},ensure_ascii=False)}],'response_format':{'type':'json_object'},'temperature':agent.temperature,'max_tokens':agent.max_output_tokens}).encode()
        req=request.Request(self.base_url.rstrip('/')+'/chat/completions',data=body,headers={'Authorization':'Bearer '+self.api_key,'Content-Type':'application/json'},method='POST')
        try:
            with request.urlopen(req,timeout=agent.timeout_seconds) as res: raw=res.read().decode()
        except error.HTTPError as e:
            if e.code==429: raise RateLimitError('openai 429 rate limit')
            if e.code>=500: raise ExecutorError(f'openai server error {e.code}')
            raise ExecutorError(f'openai http error {e.code}')
        except TimeoutError as e: raise ExecutorTimeout('openai timeout') from e
        parsed=json.loads(raw); content=parsed['choices'][0]['message']['content']; data=json.loads(content)
        return data if data.get('schema_version') else envelope(agent.id, agent.version, context.get('run_id',''), task.get('task_id','compat'), step.id, 'completed', data)
class ReplayExecutor:
    def __init__(self, run_dir: Path): self.run_dir=run_dir
    def execute(self, agent, task, context, step):
        p=self.run_dir/'steps'/f'{step.id}.json'
        if not p.exists(): raise ExecutorError(f'missing replay step {step.id}')
        return json.loads(p.read_text(encoding='utf-8'))
def build_executor(kind: str, scenario='success', replay_run: str|None=None):
    if kind=='mock': return DeterministicMockExecutor(scenario=scenario)
    if kind=='openai': return OpenAICompatibleExecutor()
    if kind=='replay': return ReplayExecutor(Path(replay_run or ''))
    raise ExecutorError(f'Unknown executor: {redact_secret(kind)}')
