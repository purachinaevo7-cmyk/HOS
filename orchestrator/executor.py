from __future__ import annotations
import json, os, socket, time
from pathlib import Path
from typing import Any
from urllib import request, error
from orchestrator.schemas import envelope, validate_agent_output_envelope
from orchestrator.security import redact_secret
class ExecutorError(Exception): pass
class RateLimitError(ExecutorError): pass
class QuotaExhaustedError(RateLimitError): pass
class ExecutorTimeout(ExecutorError): pass
class InvalidExecutorJSON(ExecutorError): pass
class DeterministicMockExecutor:
    scenarios={'success','partial','failed','invalid_json','timeout','critical_review','rate_limit','quota_exhausted'}
    def __init__(self, scenario='success', fixture_dir: Path|None=None): self.scenario=scenario; self.fixture_dir=fixture_dir
    def execute(self, agent, task: dict[str,Any], context: dict[str,Any], step) -> dict[str,Any]:
        if not hasattr(self,'scenario'): self.scenario='success'
        if self.scenario=='timeout': raise ExecutorTimeout('mock timeout')
        if self.scenario=='rate_limit': raise RateLimitError('mock 429 rate limit')
        if self.scenario=='quota_exhausted': raise QuotaExhaustedError('mock quota exhausted')
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
        if aid in {'ceo_planner','ceo'}: return {'summary':f'{name} の依頼を分解しました','assignments':['research','analysis','review'],'approval_gates':['external_actions']}
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
        except (TimeoutError, socket.timeout) as e: raise ExecutorTimeout('openai timeout') from e
        parsed=json.loads(raw); content=parsed['choices'][0]['message']['content']; data=json.loads(content)
        out=data if data.get('schema_version') else envelope(agent.id, agent.version, context.get('run_id',''), task.get('task_id','compat'), step.id, 'completed', data)
        validate_agent_output_envelope(out); return out
class GeminiProviderError(ExecutorError):
    def __init__(self, message, *, status_code=None, error_kind=None, retry_after=None, body=''):
        super().__init__(message); self.status_code=status_code; self.error_kind=error_kind; self.retry_after=retry_after; self.body=body
class OutputTruncatedError(InvalidExecutorJSON): pass

class GeminiExecutor:
    DEFAULT_TIMEOUT_SECONDS=90
    MIN_TIMEOUT_SECONDS=30
    MAX_TIMEOUT_SECONDS=300
    DEFAULT_MODEL='gemini-2.5-flash'
    AGENT_TOKEN_DEFAULTS={'ceo_planner':1200,'researcher':2000,'base_analyst':2400,'devils_advocate':1600,'ceo_integrator':3000}
    DATA_SCHEMAS={
        'ceo_planner':{'type':'object','required':['summary','assignments','approval_gates'],'properties':{'summary':{'type':'string'},'assignments':{'type':'array','items':{'type':'string'}},'approval_gates':{'type':'array','items':{'type':'string'}}}},
        'researcher':{'type':'object','required':['findings','data_availability'],'properties':{'findings':{'type':'array','items':{'type':'object','properties':{'topic':{'type':'string'},'detail':{'type':'string'},'freshness':{'type':'string'}},'required':['topic','detail']}},'data_availability':{'type':'string'}}},
        'base_analyst':{'type':'object','required':['company_evaluation','price_evaluation','overall_judgment','bull_case','base_case','bear_case','current_action','next_checkpoints','confidence'],'properties':{'company_evaluation':{'type':'object','properties':{'score':{'type':'number'},'rank':{'type':'string'},'comment':{'type':'string'}},'required':['score','rank','comment']},'price_evaluation':{'type':'object','properties':{'score':{'type':'number'},'rank':{'type':'string'},'comment':{'type':'string'}},'required':['score','rank','comment']},'overall_judgment':{'type':'string'},'bull_case':{'type':'string'},'base_case':{'type':'string'},'bear_case':{'type':'string'},'current_action':{'type':'string'},'next_checkpoints':{'type':'array','items':{'type':'string'}},'confidence':{'type':'string','enum':['low','medium','high']}}},
        'devils_advocate':{'type':'object','required':['rejection_reasons','disconfirming_signals'],'properties':{'rejection_reasons':{'type':'array','items':{'type':'string'}},'disconfirming_signals':{'type':'array','items':{'type':'string'}}}},
        'ceo_integrator':{'type':'object','required':['final_report_sections','decision'],'properties':{'final_report_sections':{'type':'array','items':{'type':'string'}},'decision':{'type':'string'}}},
    }
    def __init__(self):
        self.api_key=os.getenv('GEMINI_API_KEY',''); self.model=os.getenv('GEMINI_MODEL',self.DEFAULT_MODEL).strip()
        if not self.api_key: raise ExecutorError('GEMINI_API_KEY is required for gemini executor; refusing to auto-switch to mock or paid OpenAI')
        if not self.model: raise ExecutorError('GEMINI_MODEL must not be empty')
        self.usage=[]; self.validate_model()
    @classmethod
    def configured_timeout_seconds(cls, agent_timeout_seconds:int|None=None)->int:
        raw=os.getenv('GEMINI_TIMEOUT_SECONDS')
        if raw is None or str(raw).strip()=='': return cls.DEFAULT_TIMEOUT_SECONDS
        try: value=int(str(raw).strip())
        except (TypeError, ValueError) as e: raise ExecutorError('GEMINI_TIMEOUT_SECONDS must be an integer number of seconds') from e
        return max(cls.MIN_TIMEOUT_SECONDS,min(cls.MAX_TIMEOUT_SECONDS,value))
    @classmethod
    def schema_for_agent(cls, agent_id):
        if agent_id not in cls.DATA_SCHEMAS: raise ExecutorError(f'No Gemini data JSON Schema configured for agent={agent_id}; refusing prompt-only JSON')
        return cls.DATA_SCHEMAS[agent_id]
    @staticmethod
    def extract_json(text:str)->dict[str,Any]:
        s=(text or '').lstrip('\ufeff').strip()
        if s.startswith('```') and s.endswith('```'):
            inner=s[3:-3].strip()
            if inner.lower().startswith('json'): inner=inner[4:].strip()
            s=inner
        try: return json.loads(s)
        except json.JSONDecodeError as e: raise InvalidExecutorJSON(f'gemini response did not contain valid JSON at line={e.lineno} column={e.colno}') from e
    @staticmethod
    def _sha(text):
        import hashlib; return hashlib.sha256((text or '').encode()).hexdigest()
    @staticmethod
    def _sanitize(text):
        return redact_secret((text or '').replace(os.getenv('GEMINI_API_KEY',''),'<redacted>'))
    def _diagnostic(self, context, step, agent, attempt, meta, text, exc=None, output_token_limit=None):
        run_dir=Path(context.get('run_dir') or Path('runs')/str(context.get('run_id','unknown'))); d=run_dir/'diagnostics'; d.mkdir(parents=True,exist_ok=True)
        p=d/f'gemini_{step.id}_{attempt}.json'; safe=self._sanitize(text or '')
        doc={'provider':'gemini','model':self.model,'agent_id':agent.id,'step_id':step.id,'attempt':attempt,'finish_reason':meta.get('finish_reason'),'finish_message':meta.get('finish_message'),'response_length':len(text or ''),'response_sha256':self._sha(text or ''),'usage_metadata':meta.get('usage_metadata') or {},'sanitized_response_prefix':safe[:1000],'sanitized_response_suffix':safe[-1000:],'output_token_limit':output_token_limit,'candidate_count':meta.get('candidate_count'),'safety_ratings':meta.get('safety_ratings') or []}
        if isinstance(exc,json.JSONDecodeError): doc.update({'parse_error_line':exc.lineno,'parse_error_column':exc.colno,'parse_error_position':exc.pos})
        p.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8'); return str(p)
    def _prompt(self, agent, task, context, step, compact=False):
        prompt=Path(agent.prompt_path).read_text(encoding='utf-8') if Path(agent.prompt_path).exists() else ''
        compact_outputs={k:{'status':v.get('status'),'data':v.get('data',{})} for k,v in context.get('outputs',{}).items() if isinstance(v,dict)}
        return prompt+'\nGenerate only the agent-specific data object. Do not generate HOS envelope fields. Be concise.'+('\nUse the shortest useful answer.' if compact else '')+'\n'+json.dumps({'task':task,'context_outputs':compact_outputs,'step':step.id,'agent_id':agent.id},ensure_ascii=False)
    def max_tokens_for(self, agent):
        env_specific=os.getenv('GEMINI_MAX_OUTPUT_TOKENS_'+agent.id.upper())
        raw=env_specific or os.getenv('HOS_MAX_OUTPUT_TOKENS_PER_AGENT') or os.getenv('GEMINI_MAX_OUTPUT_TOKENS_DEFAULT') or self.AGENT_TOKEN_DEFAULTS.get(agent.id) or getattr(agent,'max_output_tokens',2048)
        if agent.id=='ceo_integrator': raw=os.getenv('GEMINI_MAX_OUTPUT_TOKENS_CEO') or raw
        return int(raw)
    def validate_model(self):
        if os.getenv('GEMINI_SKIP_MODEL_VALIDATION','').lower()=='true': return True
        if os.getenv('PYTEST_CURRENT_TEST'): return True
        url=f'https://generativelanguage.googleapis.com/v1beta/models?key={self.api_key}'
        try:
            with request.urlopen(request.Request(url),timeout=15) as res: data=json.loads(res.read().decode())
            names=[m.get('name','').split('/')[-1] for m in data.get('models',[]) if 'generateContent' in m.get('supportedGenerationMethods',[])]
            if self.model not in names: raise ExecutorError(f'GEMINI_MODEL {self.model} is not available for generateContent. Available candidates: {names[:10]}')
        except ExecutorError: raise
        except Exception as e: raise ExecutorError(f'Unable to validate GEMINI_MODEL before run: {type(e).__name__}') from e
        return True
    def _post_once(self, body, timeout_seconds):
        url=f'https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}'
        req=request.Request(url,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
        try:
            with request.urlopen(req,timeout=timeout_seconds) as res: return res.read().decode()
        except error.HTTPError as e:
            msg=e.read().decode(errors='ignore'); low=(msg+' '+str(e)).lower(); retry_after=e.headers.get('Retry-After') if e.headers else None
            if e.code==429 and any(x in low for x in ['quota','exhausted','resource_exhausted']): raise QuotaExhaustedError('gemini quota exhausted (429); not switching executor')
            if e.code==429: raise RateLimitError('gemini 429 rate limit')
            if e.code==503:
                kind='temporary_overload' if 'overload' in low else ('model_unavailable' if 'unavailable' in low and 'model' in low else ('service_unavailable' if 'unavailable' in low else 'unknown_503'))
                raise GeminiProviderError(f'gemini 503 {kind}; retry_after={retry_after}',status_code=503,error_kind=kind,retry_after=retry_after,body=self._sanitize(msg))
            if e.code>=500: raise GeminiProviderError(f'gemini provider error {e.code}',status_code=e.code,error_kind='internal_provider_error',body=self._sanitize(msg))
            raise ExecutorError(f'gemini http error {e.code}: {redact_secret(msg[:500])}')
    def execute(self, agent, task, context, step):
        schema=self.schema_for_agent(agent.id); max_tokens=self.max_tokens_for(agent); timeout_seconds=self.configured_timeout_seconds(getattr(agent,'timeout_seconds',None)); attempt=int(context.get('attempt_number') or 1)
        body={'contents':[{'role':'user','parts':[{'text':self._prompt(agent,task,context,step,attempt>1)}]}],'generationConfig':{'temperature':agent.temperature,'maxOutputTokens':max_tokens,'responseMimeType':'application/json','responseSchema':schema}}
        try: raw=self._post_once(body,timeout_seconds)
        except (TimeoutError, socket.timeout) as e: raise ExecutorTimeout(f'gemini timeout after {timeout_seconds}s (agent={agent.id}, attempt={attempt})') from e
        parsed=json.loads(raw); usage=parsed.get('usageMetadata') or {}; candidates=parsed.get('candidates') or []
        meta={'usage_metadata':usage,'candidate_count':len(candidates)}; text=''
        if not candidates:
            diag=self._diagnostic(context,step,agent,attempt,meta,text,output_token_limit=max_tokens); raise InvalidExecutorJSON(f'gemini response missing candidate; diagnostic={diag}')
        cand=candidates[0]; meta.update({'finish_reason':cand.get('finishReason'),'finish_message':cand.get('finishMessage'),'safety_ratings':cand.get('safetyRatings') or []})
        parts=((cand.get('content') or {}).get('parts') or [])
        text=''.join(p.get('text','') for p in parts if isinstance(p,dict))
        if not (cand.get('content')) or not parts or not text:
            diag=self._diagnostic(context,step,agent,attempt,meta,text,output_token_limit=max_tokens); raise InvalidExecutorJSON(f'gemini response missing content text; finishReason={meta.get("finish_reason")}; diagnostic={diag}')
        fr=meta.get('finish_reason') or 'OTHER'
        if fr=='MAX_TOKENS':
            diag=self._diagnostic(context,step,agent,attempt,meta,text,output_token_limit=max_tokens); raise OutputTruncatedError(f'OUTPUT_TRUNCATED agent={agent.id} finishReason=MAX_TOKENS responseLength={len(text)} tokenLimit={max_tokens} diagnostic={diag}')
        if fr in {'SAFETY','RECITATION','MALFORMED_RESPONSE'}:
            diag=self._diagnostic(context,step,agent,attempt,meta,text,output_token_limit=max_tokens); raise InvalidExecutorJSON(f'INVALID_PROVIDER_RESPONSE agent={agent.id} finishReason={fr} diagnostic={diag}')
        try: data=self.extract_json(text)
        except InvalidExecutorJSON as e:
            cause=e.__cause__ if isinstance(e.__cause__,json.JSONDecodeError) else None; diag=self._diagnostic(context,step,agent,attempt,meta,text,cause,output_token_limit=max_tokens); raise InvalidExecutorJSON(f'INVALID_PROVIDER_RESPONSE agent={agent.id} finishReason={fr} responseLength={len(text)} tokenLimit={max_tokens} diagnostic={diag}') from e
        out=envelope(agent.id, agent.version, context.get('run_id',''), task.get('task_id','compat'), step.id, 'completed', data, warnings=[], errors=[])
        out['usage_metadata']=usage; validate_agent_output_envelope(out)
        self.usage.append({'agent_id':agent.id,'step_id':step.id,'provider':'gemini','model':self.model,'timeout_seconds':timeout_seconds,'finish_reason':fr,'response_length':len(text),'output_token_limit':max_tokens,'usage_metadata':usage})
        return out
class ReplayExecutor:
    def __init__(self, run_dir: Path): self.run_dir=run_dir
    def execute(self, agent, task, context, step):
        p=self.run_dir/'steps'/f'{step.id}.json'
        if not p.exists(): raise ExecutorError(f'missing replay step {step.id}')
        return json.loads(p.read_text(encoding='utf-8'))
def build_executor(kind: str, scenario='success', replay_run: str|None=None):
    if kind=='mock': return DeterministicMockExecutor(scenario=scenario)
    if kind=='openai': return OpenAICompatibleExecutor()
    if kind=='gemini': return GeminiExecutor()
    if kind=='replay': return ReplayExecutor(Path(replay_run or ''))
    raise ExecutorError(f'Unknown executor: {redact_secret(kind)}')
