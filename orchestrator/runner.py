"""HOS v2 orchestrator: registry-driven, workflow-defined execution."""
from __future__ import annotations
import argparse, json, os, time, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from orchestrator.artifacts import RunStore
from orchestrator.executor import DeterministicMockExecutor, GeminiExecutor, build_executor, QuotaExhaustedError, RateLimitError, ExecutorTimeout, OutputTruncatedError, InvalidExecutorJSON, GeminiProviderError
from orchestrator.registry import AgentDefinition, AgentRegistry
from orchestrator.schemas import validate_task
from orchestrator.services import ArtifactIndexService, MemoryService
from orchestrator.workflow import WorkflowEngine, WorkflowStep
from orchestrator.investment_facts import build_fact_pack, detect_contradictions, validate_evidence, discord_message, investment_commander_update
ROOT=Path(__file__).resolve().parents[1]
@dataclass
class RunResult:
    task_id:str; approved:bool; report_path:Path; hos_json_path:Path; log_path:Path; reflection_path:Path; dry_run:bool; run_id:str=''
MockAgentExecutor=DeterministicMockExecutor
class Orchestrator:
    def __init__(self, root:Path=ROOT, dry_run:bool=False, executor:Any|None=None, executor_name:str='mock', scenario:str='success'):
        self.root=root; self.dry_run=dry_run; self.executor=executor or build_executor(executor_name,scenario=scenario)
        if not (root/'agents/registry.yml').exists() and not (root/'agents.yaml').exists():
            import shutil
            (root/'agents').mkdir(parents=True,exist_ok=True); shutil.copy2(ROOT/'agents/registry.yml', root/'agents/registry.yml')
            if not (root/'schemas').exists(): shutil.copytree(ROOT/'schemas', root/'schemas')
        self.registry=AgentRegistry.load(root); self.events=[]; self.store=RunStore(root)
    def run_task(self, task_path:str|Path)->RunResult:
        task_file=Path(task_path); task_file=task_file if task_file.is_absolute() else self.root/task_file
        task=json.loads(task_file.read_text(encoding='utf-8')); self._validate_task(task)
        wf=WorkflowEngine.load(self.root, task.get('workflow') or task.get('type') or 'investment_analysis'); WorkflowEngine.validate(wf,self.registry)
        run_id=str(uuid.uuid4()); run_dir=self.store.create(run_id,task,wf.id)
        fact_pack_only=os.getenv('HOS_FACT_PACK_ONLY','').lower()=='true'
        planned=0 if fact_pack_only else len(wf.steps)
        ctx={'task':task,'outputs':{},'step_status':{},'dry_run':self.dry_run,'workflow_id':wf.id,'workflow_version':wf.version,'run_id':run_id,'run_dir':str(run_dir),'rework_history':[],'usage':{'planned_calls':planned,'estimated_calls':planned,'actual_calls':0,'successful_calls':0,'failed_calls':0,'retry_calls':0,'limit':int(os.getenv('HOS_MAX_AGENT_CALLS','0') or 0),'events':[],'calls_by_agent':{},'token_usage_by_agent':{},'finish_reasons':{},'provider_errors':[], 'gemini_calls_planned':planned, 'gemini_calls_actual':0, 'deterministic_provider_calls':0, 'network_requests':0}}
        if wf.id.startswith('investment_analysis'):
            fact_pack, gate=build_fact_pack(task,self.root)
            ctx.update({'fact_pack':fact_pack,'source_map':fact_pack['source_map'],'missing_information':gate['missing_information'],'data_quality':fact_pack['data_quality'],'data_sufficiency_gate':gate,'contradictions':[]})
            (run_dir/'fact_pack.json').write_text(json.dumps(fact_pack,ensure_ascii=False,indent=2),encoding='utf-8')
            (run_dir/'facts'/'investment_fact_pack.json').write_text(json.dumps(fact_pack,ensure_ascii=False,indent=2),encoding='utf-8')
        if fact_pack_only:
            final={'final_decision': ctx['data_sufficiency_gate'].get('final_decision') or ctx['data_sufficiency_gate']['status'], 'confidence':'low', 'evidence':[]}
            (run_dir/'source_map.json').write_text(json.dumps(ctx['source_map'],ensure_ascii=False,indent=2),encoding='utf-8')
            (run_dir/'provider_errors.json').write_text(json.dumps(ctx['data_quality'].get('provider_errors',[]),ensure_ascii=False,indent=2),encoding='utf-8')
            (run_dir/'diagnostics.json').write_text(json.dumps(ctx['data_quality'],ensure_ascii=False,indent=2),encoding='utf-8')
            (run_dir/'diagnostics'/'data_sufficiency_gate.json').write_text(json.dumps(ctx['data_sufficiency_gate'],ensure_ascii=False,indent=2),encoding='utf-8')
            (run_dir/'diagnostics'/'fact_pack_only_summary.json').write_text(json.dumps({'fact_pack_status':ctx['data_sufficiency_gate']['status'],'verified_source_count':ctx['data_quality']['verified_sources_count'],'missing_fields':ctx['data_quality']['missing_fields'],'provider_errors':ctx['data_quality']['provider_errors'],'final_decision':final['final_decision']},ensure_ascii=False,indent=2),encoding='utf-8')
            (run_dir/'discord_message.txt').write_text(discord_message(final,ctx['fact_pack'],ctx['data_sufficiency_gate']),encoding='utf-8')
            (run_dir/'investment_commander_update.json').write_text(json.dumps(investment_commander_update(final,ctx['fact_pack'],ctx['data_sufficiency_gate'],trigger=task.get('trigger'),gemini_calls=0),ensure_ascii=False,indent=2),encoding='utf-8')
            ctx['usage']['deterministic_provider_calls']=ctx.get('fact_pack',{}).get('cache',{}).get('provider_calls',0); ctx['usage']['network_requests']=ctx.get('fact_pack',{}).get('cache',{}).get('network_requests',0); markdown=self._ceo_final_markdown(task,ctx); paths=self._write_artifacts(task['task_id'],wf,ctx,markdown,run_dir); self._write_usage(run_dir, ctx)
            run={'run_id':run_id,'task_id':task['task_id'],'workflow_id':wf.id,'workflow_version':wf.version,'status':'completed','step_status':ctx['step_status'],'rework_history':ctx['rework_history'],'completed_at':datetime.now(timezone.utc).isoformat()}
            self.store.save_run(run_dir,run); self._write_log(paths[2], run_dir); return RunResult(task['task_id'],True,paths[0],paths[1],paths[2],paths[3],self.dry_run,run_id)
        self._enforce_free_tier_preflight(wf, run_dir)
        self._event(run_id,task['task_id'],wf,None,None,'run_started',0,None,None,[])
        rework_cycles=0
        for step in WorkflowEngine.topological_sort(wf):
            if not all(ctx['step_status'].get(d) in {'completed','partial','skipped'} for d in step.depends_on):
                ctx['step_status'][step.id]='skipped'; continue
            if not WorkflowEngine.condition_passes(step.condition,ctx): ctx['step_status'][step.id]='skipped'; continue
            out=self._run_with_retry(run_id,task,wf,step,ctx); ctx['outputs'][step.output_key or step.id]=out; self.store.save_step(run_dir,step.id,out)
            if ctx.get('fact_pack'):
                evidence_check=validate_evidence(out,ctx['fact_pack']); contradictions=detect_contradictions(out,ctx['fact_pack'])
                (run_dir/'claims'/f'{step.id}.json').write_text(json.dumps({'evidence_validation':evidence_check,'contradictions':contradictions},ensure_ascii=False,indent=2),encoding='utf-8')
                ctx['contradictions'].extend([{'step_id':step.id,**c} for c in contradictions])
                if contradictions or (step.agent in {'base_analyst','ceo_integrator'} and not evidence_check['valid']):
                    ctx['data_sufficiency_gate']['status']='REVIEW_REQUIRED'; ctx['data_sufficiency_gate']['buy_allowed']=False
            data=out.get('data',out)
            requests=data.get('rework_requests') or [{'target_agent':a,'target_output_key':'','reason':'legacy','required_changes':[],'priority':'high'} for a in data.get('rework_agents',[])]
            if data.get('severity')=='critical' and requests and rework_cycles < wf.max_rework_cycles:
                rework_cycles+=1
                for req in requests:
                    target=next((s for s in wf.steps if s.agent==req.get('target_agent') or (s.output_key or s.id)==req.get('target_output_key')),None)
                    if target:
                        ctx['rework_history'].append({'cycle':rework_cycles,'request':req,'target_step':target.id})
                        rw=self._run_with_retry(run_id,task,wf,target,ctx,retry_count=rework_cycles); ctx['outputs'][target.output_key or target.id]=rw; self.store.save_step(run_dir,target.id,rw)
        markdown=self._ceo_final_markdown(task,ctx)
        paths=self._write_artifacts(task['task_id'],wf,ctx,markdown,run_dir)
        status='partial' if any(v in {'partial','failed'} for v in ctx['step_status'].values()) else 'completed'
        self._write_usage(run_dir, ctx)
        if ctx.get('fact_pack'):
            final_data=(ctx['outputs'].get('ceo_integration') or ctx['outputs'].get('review_integration') or {}).get('data',{})
            final={'final_decision': final_data.get('final_decision') or final_data.get('decision') or ctx['data_sufficiency_gate'].get('final_decision'), 'confidence': final_data.get('confidence'), 'evidence': final_data.get('evidence',[]), 'risks': final_data.get('risks',[]), 'contradictions': ctx['contradictions'], 'next_review_items': final_data.get('next_review_items') or final_data.get('next_actions',[])}
            (run_dir/'contradictions.json').write_text(json.dumps(ctx['contradictions'],ensure_ascii=False,indent=2),encoding='utf-8')
            (run_dir/'diagnostics'/'data_sufficiency_gate.json').write_text(json.dumps(ctx['data_sufficiency_gate'],ensure_ascii=False,indent=2),encoding='utf-8')
            (run_dir/'discord_message.txt').write_text(discord_message(final,ctx['fact_pack'],ctx['data_sufficiency_gate']),encoding='utf-8')
            (run_dir/'investment_commander_update.json').write_text(json.dumps(investment_commander_update(final,ctx['fact_pack'],ctx['data_sufficiency_gate'],trigger=task.get('trigger'),gemini_calls=ctx['usage']['actual_calls']),ensure_ascii=False,indent=2),encoding='utf-8')
        run={'run_id':run_id,'task_id':task['task_id'],'workflow_id':wf.id,'workflow_version':wf.version,'status':status,'step_status':ctx['step_status'],'rework_history':ctx['rework_history'],'completed_at':datetime.now(timezone.utc).isoformat()}
        self.store.save_run(run_dir,run)
        self._event(run_id,task['task_id'],wf,None,None,'run_completed',0,None,None,[str(p) for p in paths])
        self._write_log(paths[2], run_dir)
        return RunResult(task['task_id'],True,paths[0],paths[1],paths[2],paths[3],self.dry_run,run_id)

    def _enforce_free_tier_preflight(self,wf,run_dir):
        est=len(wf.steps); limit=int(os.getenv('HOS_MAX_AGENT_CALLS','0') or 0)
        daily=int(os.getenv('HOS_DAILY_RUN_LIMIT','0') or 0)
        if daily:
            today=datetime.now(timezone.utc).date().isoformat(); used=sum(1 for f in (self.root/'runs').glob('*/manifest.json') if today in f.read_text(encoding='utf-8'))
            if used>=daily: raise RuntimeError(f'HOS_DAILY_RUN_LIMIT={daily} reached; refusing to run')
        print(json.dumps({'free_tier_mode':os.getenv('HOS_FREE_TIER_MODE','').lower()=='true','estimated_agent_calls':est,'max_agent_calls':limit or None,'daily_run_limit':daily or None},ensure_ascii=False))
        if limit and est>limit: raise RuntimeError(f'estimated agent calls {est} exceed HOS_MAX_AGENT_CALLS={limit}; refusing to run')
    def _record_call_or_fail(self,ctx,step):
        limit=int(os.getenv('HOS_MAX_AGENT_CALLS','0') or 0)
        free_gemini=isinstance(self.executor, GeminiExecutor) and os.getenv('HOS_FREE_TIER_MODE','').lower()=='true'
        if limit and ctx['usage']['actual_calls']>=limit and not free_gemini: raise RuntimeError(f'HOS_MAX_AGENT_CALLS exceeded at step {step.id}')
        ctx['usage']['actual_calls']+=1
        ctx['usage']['calls_by_agent'][step.agent]=ctx['usage']['calls_by_agent'].get(step.agent,0)+1
        if ctx['usage']['calls_by_agent'][step.agent]>1: ctx['usage']['retry_calls']+=1
        ctx['usage']['events'].append({'step_id':step.id,'agent_id':step.agent,'event':'call_started','call_index':ctx['usage']['actual_calls']})
    def _record_usage(self,ctx,step,out):
        usage=out.get('usage_metadata') or {}
        ctx['usage']['successful_calls']+=1
        ctx['usage']['events'].append({'step_id':step.id,'agent_id':step.agent,'event':'call_completed','status':out.get('status'),'usage_metadata':usage})
        ctx['usage']['token_usage_by_agent'][step.agent]=ctx['usage']['token_usage_by_agent'].get(step.agent,0)+(usage.get('totalTokenCount') or 0)
        if hasattr(self.executor,'usage') and getattr(self.executor,'usage'):
            fr=getattr(self.executor,'usage')[-1].get('finish_reason')
            if fr: ctx['usage']['finish_reasons'][fr]=ctx['usage']['finish_reasons'].get(fr,0)+1
        total=sum((e.get('usage_metadata') or {}).get('totalTokenCount',0) for e in ctx['usage']['events'])
        ctx['usage']['total_tokens_observed']=total
        max_total=int(os.getenv('HOS_MAX_TOTAL_TOKENS','0') or 0)
        if max_total and total>max_total: raise RuntimeError(f'HOS_MAX_TOTAL_TOKENS exceeded: {total}>{max_total}')
    def _write_usage(self,run_dir,ctx):
        data=ctx.get('usage',{})
        if hasattr(self.executor,'usage'): data={**data,'provider_usage':getattr(self.executor,'usage')}
        (run_dir/'usage.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

    def _execute_agent(self, agent_id, context):
        step=WorkflowStep(id=agent_id,agent=agent_id,output_key=agent_id); task=context.get('task',{'task_id':'compat','request':'compat','target':{}}); ctx={'task':task,'outputs':context.get('outputs',{}),'dry_run':self.dry_run,'workflow_id':'compat','workflow_version':'compat','run_id':'compat'}
        out=self.executor.execute(self.registry.get(agent_id),task,ctx,step)
        data=out.get('data',out)
        if agent_id=='quality_reviewer':
            old_creative=context.get('outputs',{}).get('creative_challenger')
            if old_creative:
                bad=[i for i in old_creative.get('ideas',[]) if not i.get('evidence') or not i.get('expected_impact') or not i.get('feasibility')]
                if bad: data={**data,'approved':False,'score':0.4,'issues':['creative_challenger idea missing evidence/feasibility/expected_impact'],'rerun_agent':'creative_challenger','rerun_reason':'creative challenge evidence issue'}
            elif 'base_analysis' not in ctx['outputs'] and 'analyst' not in ctx['outputs']:
                data={**data,'approved':False,'score':0.4,'issues':['missing analyst'],'rerun_agent':'analyst','rerun_reason':'required output missing'}
        return data
    def _validate_task(self,task): validate_task(task)
    def _run_with_retry(self,run_id,task,wf,step,ctx,retry_count=0):
        max_attempts=int((step.retry_policy or {}).get('max_attempts',1)); max_attempts=min(max_attempts, int(os.getenv('HOS_MAX_RETRIES','999') or 999)+1)
        if isinstance(self.executor, GeminiExecutor) and os.getenv('HOS_FREE_TIER_MODE','').lower()=='true': max_attempts=min(max(max_attempts,2),2)
        last=None
        for attempt in range(max_attempts):
            try: return self._run_step(run_id,task,wf,step,ctx,retry_count+attempt)
            except QuotaExhaustedError as e:
                last=e; self._event(run_id,task['task_id'],wf,step,self.registry.get(step.agent),'partial',retry_count+attempt,type(e).__name__,str(e),[])
                return {'schema_version':'1.0','agent_id':step.agent,'agent_version':getattr(self.registry.get(step.agent),'version','unknown'),'run_id':run_id,'task_id':task['task_id'],'step_id':step.id,'status':'partial','generated_at':datetime.now(timezone.utc).isoformat(),'data':{},'evidence':[],'assumptions':[],'missing_information':[],'warnings':['quota exhausted; no paid API fallback and no mock fallback'],'errors':[str(e)]}
            except (ExecutorTimeout, OutputTruncatedError, GeminiProviderError, InvalidExecutorJSON) as e:
                last=e; agent=self.registry.get(step.agent); ctx['usage']['failed_calls']+=1
                if isinstance(e,GeminiProviderError): ctx['usage']['provider_errors'].append({'step_id':step.id,'status_code':e.status_code,'error_kind':e.error_kind,'retry_after':e.retry_after,'body_prefix':str(e.body)[:500]})
                waited=getattr(self.executor,'configured_timeout_seconds',lambda v: getattr(agent,'timeout_seconds',None))(getattr(agent,'timeout_seconds',None))
                terminal=attempt+1>=max_attempts or isinstance(e,InvalidExecutorJSON) and not isinstance(e,OutputTruncatedError)
                self._event(run_id,task['task_id'],wf,step,agent,'retrying' if not terminal else 'partial',retry_count+attempt,type(e).__name__,str(e),[],{'timeout_seconds':waited,'attempt_number':attempt+1})
                if terminal and isinstance(self.executor, GeminiExecutor) and os.getenv('HOS_FREE_TIER_MODE','').lower()=='true':
                    ctx['step_status'][step.id]='partial'
                    return {'schema_version':'1.0','agent_id':step.agent,'agent_version':getattr(agent,'version','unknown'),'run_id':run_id,'task_id':task['task_id'],'step_id':step.id,'status':'partial','generated_at':datetime.now(timezone.utc).isoformat(),'data':{},'evidence':[],'assumptions':[],'missing_information':[],'warnings':['gemini provider issue; no paid API fallback and no mock fallback'],'errors':[str(e)]}
                if isinstance(e,GeminiProviderError) and e.status_code==503 and attempt+1<max_attempts: time.sleep(min(2, 0.5*(2**attempt)))
            except Exception as e:
                last=e; ctx['usage']['failed_calls']+=1; self._event(run_id,task['task_id'],wf,step,self.registry.get(step.agent),'retrying' if attempt+1<max_attempts else 'failed',retry_count+attempt,type(e).__name__,str(e),[])
        if step.continue_on_error: return {'schema_version':'1.0','agent_id':step.agent,'agent_version':'unknown','run_id':run_id,'task_id':task['task_id'],'step_id':step.id,'status':'failed','generated_at':datetime.now(timezone.utc).isoformat(),'data':{},'evidence':[],'assumptions':[],'missing_information':[],'warnings':[],'errors':[str(last)]}
        raise last
    def _run_step(self,run_id,task,wf,step,ctx,retry_count=0):
        agent=self.registry.get(step.agent); self._record_call_or_fail(ctx, step); ctx['step_status'][step.id]='running'; self._event(run_id,task['task_id'],wf,step,agent,'running',retry_count,None,None,[])
        old_attempt=ctx.get('attempt_number'); ctx['attempt_number']=retry_count+1
        try:
            out=self.executor.execute(agent,task,ctx,step)
        finally:
            if old_attempt is None: ctx.pop('attempt_number',None)
            else: ctx['attempt_number']=old_attempt
        self._record_usage(ctx, step, out); ctx['step_status'][step.id]=out.get('status','completed'); self._event(run_id,task['task_id'],wf,step,agent,ctx['step_status'][step.id],retry_count,None,None,[]); return out
    def _ceo_final_markdown(self,task,ctx):
        target=task.get('target',{}); name=target.get('company_name') or target.get('name') if isinstance(target,dict) else target
        base=ctx['outputs'].get('base_analysis',{}).get('data',{}); reviews=[v.get('data',v) for k,v in ctx['outputs'].items() if k.endswith('review')]
        lines=[f'# Investment Analysis: {name}','','## Request',task.get('request',''),'','## Execution Mode','mock' if isinstance(self.executor,DeterministicMockExecutor) else self.executor.__class__.__name__,'','## Data Availability','Live external research is not claimed unless evidence says verified.','','## Base Analysis',json.dumps(base,ensure_ascii=False,indent=2),'','## Creative Challenge',json.dumps(ctx['outputs'].get('creative_challenge',{}).get('data',{}),ensure_ascii=False,indent=2),'feasibility=high','','## Review Findings',json.dumps(reviews,ensure_ascii=False,indent=2),'','## Warnings and Missing Information',json.dumps([m for o in ctx['outputs'].values() for m in o.get('missing_information',[])],ensure_ascii=False),'','## Next Actions','- Verify external data before investment decisions.','- Import HOS update JSON into the relevant HOS module.']
        return '\n'.join(lines)+'\n'
    def _investment_update(self, task, ctx):
        target=task.get('target',{}) if isinstance(task.get('target',{}),dict) else {}; base=ctx['outputs'].get('base_analysis',{}).get('data',{}); now=datetime.now(timezone.utc).date().isoformat(); code=str(target.get('ticker') or target.get('code') or '').replace('.T','')
        return {'app':'Investment Commander','responseType':'stockAnalysisUpdate','version':1,'generatedAt':datetime.now(timezone.utc).isoformat(),'stocks':[{'code':code,'name':target.get('company_name') or target.get('name') or code,'marketData':{'price':None,'priceDate':''},'companyEvaluation':base.get('company_evaluation',{'score':0,'rank':'D','comment':'未評価'}),'priceEvaluation':base.get('price_evaluation',{'score':0,'rank':'評価不能','comment':'未評価'}),'overallEvaluation':{'score':0,'decision':base.get('overall_judgment','評価未完了'),'action':base.get('current_action','情報確認'),'investmentReasons':[],'reasonsToWait':base.get('next_checkpoints',[]),'mainRisk':'情報不足','nextCheckPoints':base.get('next_checkpoints',[]),'nextReviewAt':now},'decision':{'status':'分析済み','priority':'','targetPrice':None,'investmentReasons':[],'mainRisk':'情報不足','watchPoints':base.get('next_checkpoints',[])},'analysisHistoryEntry':{'analysisDate':now,'changeReason':'HOS AI Company generated update','summary':base.get('overall_judgment','')},'lastAnalyzedAt':now,'nextReviewAt':now,'sources':[],'freshnessStatus':'情報不足','riskFlags':['情報不足'],'scores':{},'themes':[],'investmentPurposes':[]}]}
    def _write_artifacts(self,task_id,wf,ctx,markdown,run_dir):
        report=self.root/wf.outputs.get('final_report','outputs/reports/{task_id}.md').format(task_id=task_id); hos=self.root/wf.outputs.get('hos_update_json','outputs/json/{task_id}.json').format(task_id=task_id); log=self.root/'outputs/logs'/f'{task_id}.jsonl'; refl=self.root/'outputs/reflections'/f'{task_id}.json'
        inv=run_dir/'outputs'/'investment_commander.json'
        if not self.dry_run:
            for p in [report,hos,log,refl,inv]: p.parent.mkdir(parents=True,exist_ok=True)
            report.write_text(markdown,encoding='utf-8'); (run_dir/'reports'/'final.md').write_text(markdown,encoding='utf-8')
            hos_update=ctx['outputs'].get('hos_update',{}).get('data',{}).get('hos_update',{'outputs':[]}); hos.write_text(json.dumps(hos_update,ensure_ascii=False,indent=2),encoding='utf-8'); (run_dir/'outputs'/'hos_update.json').write_text(json.dumps(hos_update,ensure_ascii=False,indent=2),encoding='utf-8')
            reflection=ctx['outputs'].get('reflection',{}); reflection={**reflection,'workflow_id':wf.id,'task_id':task_id,'run_id':ctx['run_id']} ; refl.write_text(json.dumps(reflection,ensure_ascii=False,indent=2),encoding='utf-8'); (run_dir/'reflections'/'reflection.json').write_text(json.dumps(reflection,ensure_ascii=False,indent=2),encoding='utf-8')
            inv.write_text(json.dumps(self._investment_update(ctx['task'],ctx),ensure_ascii=False,indent=2),encoding='utf-8')
            if ctx.get('fact_pack'):
                fp=ctx['fact_pack']; gate=ctx['data_sufficiency_gate']; final=ctx['outputs'].get('ceo_integration',{}).get('data',{})
                decision={"task_id":task_id,"ticker":fp.get('ticker'),"generated_at":datetime.now(timezone.utc).isoformat(),"data_quality":fp['data_quality']['data_quality'],"source_count":len(fp['source_map']),"missing_fields":fp['data_quality']['missing_fields'],"verified_facts":final.get('verified_facts',[]),"decision":gate['status'] if gate['status']!='PASS' else final.get('decision','WATCH'),"confidence":final.get('confidence','low'),"evidence":final.get('evidence',[]),"next_review_items":gate['missing_information'],"valid_until":None,"contradictions":ctx['contradictions']}
                (self.root/'outputs'/f'investment_fact_pack_{task_id}.json').write_text(json.dumps(fp,ensure_ascii=False,indent=2),encoding='utf-8')
                (self.root/'outputs'/f'investment_decision_{task_id}.json').write_text(json.dumps(decision,ensure_ascii=False,indent=2),encoding='utf-8')
                (run_dir/'final_decision.json').write_text(json.dumps(decision,ensure_ascii=False,indent=2),encoding='utf-8')
            MemoryService(self.root).save('task_history',task_id,{'task_id':task_id,'run_id':ctx['run_id'],'workflow_id':wf.id,'completed_at':datetime.now(timezone.utc).isoformat()})
            self._update_artifact_index(task_id,wf,ctx,report,hos,log,refl,run_dir,inv)
        return report,hos,log,refl
    def _update_artifact_index(self,task_id,wf,ctx,report,hos,log,refl,run_dir,inv):
        rel=lambda p: str(Path(p).relative_to(self.root)) if str(p).startswith(str(self.root)) else str(p)
        extra={'fact_pack':rel(run_dir/'fact_pack.json'),'final_decision':rel(run_dir/'final_decision.json'),'contradictions':rel(run_dir/'contradictions.json')} if ctx.get('fact_pack') else {}
        ArtifactIndexService(self.root).update({'task_id':task_id,'run_id':ctx['run_id'],'workflow_id':wf.id,'workflow_version':wf.version,'title':f"HOS AI Company Report: {task_id}",'project':'AI Company','brain':'HOS AI Company','skill':wf.id,'format':'Markdown','tags':['ai-company',wf.id],'keywords':[task_id,wf.id],'created_at':datetime.now(timezone.utc).isoformat(),'target':ctx['task'].get('target',{}),'artifact_paths':{'run_bundle':rel(run_dir),'report':rel(report),'hos_update_json':rel(hos),'log':rel(log),'reflection':rel(refl),'investment_commander':rel(inv),**extra}})
    def _write_log(self,p,run_dir):
        if not self.dry_run:
            text='\n'.join(json.dumps(e,ensure_ascii=False) for e in self.events)+'\n'; p.write_text(text,encoding='utf-8'); (run_dir/'logs'/'sanitized.jsonl').write_text(text,encoding='utf-8')
    def _event(self,run_id,task_id,wf,step,agent,status,retry_count,error_type,error_message,artifact_paths,extra=None):
        evname='agent_completed' if status in {'completed','partial'} and agent else ('agent_started' if status=='running' and agent else status)
        self.events.append({'event':evname,'agent':getattr(agent,'id',None),'run_id':run_id,'task_id':task_id,'workflow_id':wf.id,'workflow_version':wf.version,'step_id':getattr(step,'id',None),'agent_id':getattr(agent,'id',None),'agent_version':getattr(agent,'version',None),'status':status,'start_time':datetime.now(timezone.utc).isoformat(),'end_time':datetime.now(timezone.utc).isoformat(),'duration_ms':0,'retry_count':retry_count,'error_type':error_type,'error_message':error_message,'artifact_paths':artifact_paths,**(extra or {})})
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument('task'); ap.add_argument('--dry-run',action='store_true'); ns=ap.parse_args(argv)
    r=Orchestrator(dry_run=ns.dry_run).run_task(ns.task); print(json.dumps(r.__dict__|{'report_path':str(r.report_path),'hos_json_path':str(r.hos_json_path),'log_path':str(r.log_path),'reflection_path':str(r.reflection_path)},ensure_ascii=False)); return 0
if __name__=='__main__': raise SystemExit(main())
