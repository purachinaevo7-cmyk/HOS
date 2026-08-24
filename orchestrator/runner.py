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
        task=json.loads(task_file.read_text(encoding='utf-8'))
        requested_fact_pack_only=os.getenv('HOS_FACT_PACK_ONLY','').lower()=='true' if os.getenv('HOS_FACT_PACK_ONLY','') else bool(task.get('fact_pack_only') or task.get('effective_fact_pack_only'))
        if os.getenv('HOS_FACT_PACK_ONLY',''):
            task['requested_fact_pack_only']=requested_fact_pack_only
            task['effective_fact_pack_only']=requested_fact_pack_only
            task['fact_pack_only']=requested_fact_pack_only
        self._validate_task(task)
        wf=WorkflowEngine.load(self.root, task.get('workflow') or task.get('type') or 'investment_analysis'); WorkflowEngine.validate(wf,self.registry)
        run_id=str(uuid.uuid4()); run_dir=self.store.create(run_id,task,wf.id)
        fact_pack_only=bool(task.get('effective_fact_pack_only')) if 'effective_fact_pack_only' in task else os.getenv('HOS_FACT_PACK_ONLY','').lower()=='true'
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
            run={'run_id':run_id,'task_id':task['task_id'],'workflow_id':wf.id,'workflow_version':wf.version,'status':'completed','step_status':ctx['step_status'],'rework_history':ctx['rework_history'],'completed_at':datetime.now(timezone.utc).isoformat(),'requested_fact_pack_only':task.get('requested_fact_pack_only'),'effective_fact_pack_only':fact_pack_only}
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
        run={'run_id':run_id,'task_id':task['task_id'],'workflow_id':wf.id,'workflow_version':wf.version,'status':status,'step_status':ctx['step_status'],'rework_history':ctx['rework_history'],'completed_at':datetime.now(timezone.utc).isoformat(),'requested_fact_pack_only':task.get('requested_fact_pack_only'),'effective_fact_pack_only':fact_pack_only}
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
                if bad: data={**data,'approved':False,'score':0.4,'issues':['creative_challenger idea missing evidence/feasibility/expeczßmm¢G§²ÚîÆ­yĞ¥í¥˜ …Ñ•áÑññÑ•áĞ¹ÍÑ…ÉÑÍ]¥Ñ  ‹¾ò#OO¬ˆ¤¥É•ÑÕÉ¸í½¹ÍĞ•¹ÑÉ¥•ÌõÉ•…‘)Í½¸ ‰¡½Í%¹‰½á¹ÑÉ¥•Ìˆ±mt¤í•¹ÑÉ¥•Ì¹Õ¹Í¡¥™Ğ¡íÑ•áĞ±É•…Ñ•‘Ğé¹•Ü…Ñ” ¤¹Ñ½%M=MÑÉ¥¹œ ¤±ÍÑ…ÑÕÌè‰½Á•¸‰ô¤íİÉ¥Ñ•)Í½¸ ‰¡½Í%¹‰½á¹ÑÉ¥•Ìˆ±•¹ÑÉ¥•Ì¹Í±¥” À°ÔÀ¤¥ô)™Õ¹Ñ¥½¸É•½É‘M­¥±±UÍ…”¡ÁÉ½µÁÑ%¥í½¹ÍĞÍ­¥±±5…Àõì‰ÁÉ½µÁĞµ¡½¹‘„ˆè‹’òš–·–"šzAM­¥±°ˆ°‰ÁÉ½µÁĞµ‰•¹•™¥ÑÌˆè‰I='šVÓBM­¥±°ˆ°‰ÁÉ½µÁĞµ±½‰¥Ìˆè‹šVgšvC–2YM­¥±°ˆ±¥¹‰½áAÉ½µÁĞè‰%¹‰½ãšVÓBM­¥±°‰ôí½¹ÍĞÍ­¥±°õÍ­¥±±5…ÁmÁÉ½µÁÑ%‘uñğ‹_·Ï_#šÒïR¡M­¥±°ˆí½¹ÍĞÍ­¥±±ÌõÉ•…‘)Í½¸ ‰¡½ÍI••¹ÑM­¥±±Ìˆ±mt¤¹™¥±Ñ•È¡¥Ñ•´ôù¥Ñ•´¹¹…µ”„ôõÍ­¥±°¤íÍ­¥±±Ì¹Õ¹Í¡¥™Ğ¡í¹…µ”éÍ­¥±°±ÕÍ•‘Ğé¹•Ü…Ñ” ¤¹Ñ½%M=MÑÉ¥¹œ ¥ô¤íİÉ¥Ñ•)Í½¸ ‰¡½ÍI••¹ÑM­¥±±Ìˆ±Í­¥±±Ì¹Í±¥” À°Ø¤¥ô)™Õ¹Ñ¥½¸É•Í•Ñ…Í¡‰½…É‘1½…±…Ñ„ ¥í±½…±MÑ½É…”¹É•µ½Ù•%Ñ•´ ‰¡½Í%¹‰½á¹ÑÉ¥•Ìˆ¤í±½…±MÑ½É…”¹É•µ½Ù•%Ñ•´ ‰¡½ÍI••¹ÑM­¥±±Ìˆ¤í±½…±MÑ½É…”¹É•µ½Ù•%Ñ•´ ‰¡½ÍQ½‘…åAÉ½©•Ğˆ¤íÉ•¹‘•É…Í¡‰½…É ¤íÍ¡½İQ½…ÍĞ ‰…Í¡‰½…É“»·ó
¯¯*Ûš/
K–"wšr–2[_û_|ˆ¥ô)™Õ¹Ñ¥½¸™½Éµ…Ñ…Ñ”¡Ù…±Õ”¥íÉ•ÑÕÉ¸¹•Ü%¹Ñ°¹…Ñ•Q¥µ•½Éµ…Ğ ‰©„µ)@ˆ±íµ½¹Ñ è‰¹Õµ•É¥Œˆ±‘…äè‰¹Õµ•É¥Œ‰ô¤¹™½Éµ…Ğ¡¹•Ü…Ñ”¡Ù…±Õ”¤¥ô)™Õ¹Ñ¥½¸ÕÉÉ•¹Ñ]••­Q¡•µ”¡ÁÉ½©•Ğ¥í½¹ÍĞİ••¬õ5…Ñ ¹™±½½È ¡…Ñ”¹¹½Ü ¤µ¹•Ü…Ñ”¡¹•Ü…Ñ” ¤¹•ÑÕ±±e•…È ¤°À°Ä¤¹•ÑQ¥µ” ¤¤¼ Ü¨ÈĞ¨ØÀ¨ØÀ¨ÄÀÀÀ¤¤íÉ•ÑÕÉ¸!=M}AI=)QMl¡!=M}AI=)QL¹™¥¹‘%¹‘•à¡ÀôùÀ¹¥ôôõÁÉ½©•Ğ¹¥¤­İ••¬¤•!=M}AI=)QL¹±•¹Ñ¡uô)™Õ¹Ñ¥½¸É•¹‘•É…Í¡‰½…É ¥í½¹ÍĞÍ•±•Ğõ‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰Ñ½‘…åAÉ½©•ÑM•±•Ğˆ¤í¥˜ …Í•±•Ğ¥É•ÑÕÉ¸íÍ•±•Ğ¹¥¹¹•É!Q50õ!=M}AI=)QL¹µ…À¡Àôù€ñ½ÁÑ¥½¸Ù…±Õ”ôˆ‘íÀ¹¥‘ôˆø‘íÀ¹•µ½©¥ô€‘íÀ¹Ñ¥Ñ±•ôğ½½ÁÑ¥½¸ù€¤¹©½¥¸ ˆˆ¤í½¹ÍĞÍ…Ù•õ±½…±MÑ½É…”¹•Ñ%Ñ•´ ‰¡½ÍQ½‘…åAÉ½©•Ğˆ¥ññ!=M}AI=)QMlÁt¹¥íÍ•±•Ğ¹Ù…±Õ”õ!=M}AI=)QL¹Í½µ”¡ÀôùÀ¹¥ôôõÍ…Ù•¤ıÍ…Ù•é!=M}AI=)QMlÁt¹¥í½¹ÍĞÉ•¹‘•ÉAÉ½©•Ğô ¤ôùí½¹ÍĞÁÉ½©•Ğõ!=M}AI=)QL¹™¥¹¡ÀôùÀ¹¥ôôõÍ•±•Ğ¹Ù…±Õ”¥ññ!=M}AI=)QMlÁtí±½…±MÑ½É…”¹Í•Ñ%Ñ•´ ‰¡½ÍQ½‘…åAÉ½©•Ğˆ±ÁÉ½©•Ğ¹¥¤í‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰Ñ½‘…åAÉ½©•ÑQ¥Ñ±”ˆ¤¹Ñ•áÑ½¹Ñ•¹Ğõ€‘íÁÉ½©•Ğ¹•µ½©¥ô€‘íÁÉ½©•Ğ¹Ñ¥Ñ±•õ€í‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰Ñ½‘…åAÉ½©•ÑMÕµµ…Éäˆ¤¹Ñ•áÑ½¹Ñ•¹ĞõÁÉ½©•Ğ¹ÍÕµµ…Éäí‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰Ñ½‘…åAÉ½©•Ñ1¥¹¬ˆ¤¹¡É•˜õÁÉ½©•Ğ¹ÕÉ°í½¹ÍĞÑ¡•µ”õÕÉÉ•¹Ñ]••­Q¡•µ”¡ÁÉ½©•Ğ¤í‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰İ••­Q¡•µ•Q¥Ñ±”ˆ¤¹Ñ•áÑ½¹Ñ•¹ĞõÑ¡•µ”¹Ñ¡•µ”í‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰İ••­Q¡•µ•MÕµµ…Éäˆ¤¹Ñ•áÑ½¹Ñ•¹Ğõ€‘íÑ¡•µ”¹Ñ¥Ñ±•÷
K–—–>¯‘íÑ¡•µ”¹‰É…¥¹÷œÇ“»š"Cšzs&§ã–’'š>og
/	€í‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰İ••­Q¡•µ•	…‘”ˆ¤¹Ñ•áÑ½¹Ñ•¹ĞõÑ¡•µ”¹Í­¥±°í‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰¹•áÑEÕ•ÍÑ¥½¹Ìˆ¤¹¥¹¹•É!Q50õÁÉ½©•Ğ¹ÅÕ•ÍÑ¥½¹Ì¹µ…À¡Äôù€ñ±¤ø‘í•Í…Á•!Ñµ°¡Ä¥ôğ½±¤ù€¤¹©½¥¸ ˆˆ¥ôíÍ•±•Ğ¹½¹¡…¹”õÉ•¹‘•ÉAÉ½©•ĞíÉ•¹‘•ÉAÉ½©•Ğ ¤í‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰É••¹ÑUÁ‘…Ñ•Ìˆ¤¹¥¹¹•É!Q50õ!=M}AI=)QL¹µ…À¡Àôù€ñ„±…ÍÌô‰µ¥¹¤µÉ½Üˆ¡É•˜ôˆ‘íÀ¹ÕÉ±ôˆøñÍÑÉ½¹œø‘íÀ¹•µ½©¥ô€‘í•Í…Á•!Ñµ°¡À¹Ñ¥Ñ±”¥ôğ½ÍÑÉ½¹œøñÍÁ…¸ø‘í™½Éµ…Ñ…Ñ”¡À¹ÕÁ‘…Ñ•¥ôƒšnÓšZÀƒ
Ü€‘í•Í…Á•!Ñµ°¡À¹Í­¥±°¥ôğ½ÍÁ…¸øğ½„ù€¤¹©½¥¸ ˆˆ¤í‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰É••¹Ñ-¹½İ±•‘”ˆ¤¹¥¹¹•É!Q50õ!=M}I9Q}-9=]1¹µ…À¡¬ôù€ñ„±…ÍÌô‰µ¥¹¤µÉ½Üˆ¡É•˜ôˆ‘í¬¹ÕÉ±ôˆøñÍÑÉ½¹œø‘í•Í…Á•!Ñµ°¡¬¹Ñ¥Ñ±”¥ôğ½ÍÑÉ½¹œøñÍÁ…¸ø‘í•Í…Á•!Ñµ°¡¬¹ÍÕµµ…Éä¥ôğ½ÍÁ…¸øğ½„ù€¤¹©½¥¸ ˆˆ¤í½¹ÍĞ¥¹‰½àõÉ•…‘)Í½¸ ‰¡½Í%¹‰½á¹ÑÉ¥•Ìˆ±mt¤¹™¥±Ñ•È¡¥Ñ•´ôù¥Ñ•´¹ÍÑ…ÑÕÌ„ôô‰‘½¹”ˆ¤í‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰¥¹‰½á½Õ¹Ğˆ¤¹Ñ•áÑ½¹Ñ•¹Ğõ¥¹‰½à¹±•¹Ñ í‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰¥¹‰½á½Õ¹Ñ1…‰•°ˆ¤¹Ñ•áÑ½¹Ñ•¹Ğõ¥¹‰½à¹±•¹Ñ ü‹šr«šVÓB»–—–*o3
+ûdˆè‹šr«šVÓB»–—–*o¿
+ûo
Lˆí½¹ÍĞÍ­¥±±ÌõÉ•…‘)Í½¸ ‰¡½ÍI••¹ÑM­¥±±Ìˆ±mt¤í½¹ÍĞ¹…µ•Ìô¡Í­¥±±Ì¹±•¹Ñ ıÍ­¥±±Ì¹µ…À¡ÌôùÌ¹¹…µ”¤éU1Q}M-%11L¤í‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰É••¹ÑM­¥±±Ìˆ¤¹¥¹¹•É!Q50õ¹…µ•Ì¹µ…À¡¹…µ”ôù€ñÍÁ…¸±…ÍÌô‰‰…‘”ˆø‘í•Í…Á•!Ñµ°¡¹…µ”¥ôğ½ÍÁ…¸ù€¤¹©½¥¸ ˆˆ¥ô(()½¹ÍĞ!=M}=UQAUQLõl)í…Ñ•½Éäè‰!Q50ˆ±•µ½©¤è‹Â~2@ˆ±Ñ¥Ñ±”è‰!½¹‘„ƒ’òš–·–"šzA!Q53‡ˆˆ±ÁÉ½©•Ğè‰!½¹‘„ˆ±É•…Ñ•èˆÈÀÈØ´ÀÜ´ÀÔˆ±‰É…¥¸è‹Ö3–ZÛ¢Ì€¼ƒš*W¢Î¢Ìˆ±Í­¥±°è‹’òš–·–"šzAM­¥±°€¼ƒ®Û–B#š¾S¢òM­¥±°ˆ±‘½İ¹±½…è‰‘½İ¹±½…‘Ì½¡½¹‘„µ…¹…±åÍ¥Ì¹¡Ñµ°ˆ±Ñ…Ìél‹’òš–·–"šz@ˆ°‹Ö3–ZÛš"›V”ˆ°‰!½¹‘„‰t±™…Ù½É¥Ñ”éÑÉÕ”±Í•…É è‰!½¹‘„ƒ’òš–·–"šz@!Q50ƒÖ3–ZÛ¢Ìƒš*W¢Î¢Ìƒ’òš–·–"šzAM­¥±°ƒ®Û–B#š¾S¢òM­¥±°‰ô°)í…Ñ•½Éäè‰A½İ•ÉA½¥¹Ğˆ±•µ½©¤è‹Â~N(ˆ±Ñ¥Ñ±”è‹š?–"§–:kR|Ì¸Àƒš>Cš†#
ç§
“$ˆ±ÁÉ½©•Ğè‹š?–"§–:kR|Ì¸Àˆ±É•…Ñ•èˆÈÀÈØ´ÀÜ´ÀĞˆ±‰É…¥¸è‹’êë’ê/¢Ì€¼ƒÖ3–ZÛ¢Ìˆ±Í­¥±°è‹–"Û–ê›¢¢·¢¢!M­¥±°€¼I='šVÓBM­¥±°ˆ±‘½İ¹±½…è‰‘½İ¹±½…‘Ì½‰•¹•™¥ÑÌ´Ì¸À¹ÁÁÑàˆ±Ñ…Ìél‹š?–"§–:kR|ˆ°‰I=$ˆ°‹š>Cš†#¢ÎšZd‰t±™…Ù½É¥Ñ”éÑÉÕ”±Í•…É è‹š?–"§–:kR|Ì¸ÀA½İ•ÉA½¥¹Ğƒ’êë’ê/¢ÌƒÖ3–ZÛ¢Ìƒ–"Û–ê›¢¢·¢¢!M­¥±°I='šVÓBM­¥±°‰ô°)í…Ñ•½Éäè‰Aˆ±•µ½©¤è‹Â~Nˆ±Ñ¥Ñ±”è‹’â·šrÖ3–ZÛ¢¢#Rìƒ¢ª·ÿ¢7
Ÿ
¿«
ç ˆ±ÁÉ½©•Ğè‰!½¹‘„ˆ±É•…Ñ•èˆÈÀÈØ´ÀÜ´ÀÌˆ±‰É…¥¸è‹Ö3–ZÛ¢Ìˆ±Í­¥±°è‹’òš–·–"šzAM­¥±°€¼ƒ¢Ê‡–.g–"¢M­¥±°ˆ±‘½İ¹±½…è‰‘½İ¹±½…‘Ì½µ¥‘Ñ•É´µÁ±…¸µ¡•­±¥ÍĞ¹Á‘˜ˆ±Ñ…Ìél‹’â·šrÖ3–ZÛ¢¢#Rìˆ°‹¢Ê‡–.dˆ°‹
Ÿ
¿«
ç ‰t±™…Ù½É¥Ñ”é™…±Í”±Í•…É è‰Aƒ’â·šrÖ3–ZÛ¢¢#RìƒÖ3–ZÛ¢Ìƒ’òš–·–"šzAM­¥±°ƒ¢Ê‡–.g–"¢M­¥±°‰ô°)í…Ñ•½Éäè‰5…É­‘½İ¸ˆ±•µ½©¤è‹Â~Ntˆ±Ñ¥Ñ±”è‹
Ã·óO
ç–¶›şHƒš/¦ƒ–2[‡ˆˆ±ÁÉ½©•Ğè‹
Ã·óO
ç–¶›şHˆ±É•…Ñ•èˆÈÀÈØ´ÀÜ´ÀÈˆ±‰É…¥¸è‹–¶›şK¢Ì€¼ƒÖ3–ZÛ¢Ìˆ±Í­¥±°è‹šVgšvC–2YM­¥±°€¼ƒ–ú§şIM­¥±°ˆ±‘½İ¹±½…è‰‘½İ¹±½…‘Ì½±½‰¥Ìµ±•…É¹¥¹œµ¹½Ñ”¹µˆ±Ñ…Ìél‹–¶›şHˆ°‹šVgšvC–2Xˆ°‰5…É­‘½İ¸‰t±™…Ù½É¥Ñ”é™…±Í”±Í•…É è‰5…É­‘½İ¸ƒ
Ã·óO
ç–¶›şHƒ–¶›şK¢ÌƒšVgšvC–2YM­¥±°ƒ–ú§şIM­¥±°‰ô°)í…Ñ•½Éäè‰I•Ù¥•Üˆ±•µ½©¤è‹Â~R4ˆ±Ñ¥Ñ±”è‹š?–"§–:kR–"Û–ê›³O—óÖCšzpˆ±ÁÉ½©•Ğè‹š?–"§–:kR|Ì¸Àˆ±É•…Ñ•èˆÈÀÈØ´ÀÜ´ÀÄˆ±‰É…¥¸è‹’êë’ê/¢Ìˆ±Í­¥±°è‹š?šwšÆë–ºk³O—ñM­¥±°€¼ƒ’û–¢ª³šb9M­¥±°ˆ±‘½İ¹±½…è‰‘½İ¹±½…‘Ì½‰•¹•™¥ÑÌµÉ•Ù¥•Ü¹µˆ±Ñ…Ìél‹³O—ğˆ°‹–"Û–ê›¢¢·¢¢ ˆ°‹’û–¢ª³šb8‰t±™…Ù½É¥Ñ”éÑÉÕ”±Í•…É è‰I•Ù¥•Üƒš?–"§–:kR|Ì¸Àƒ’êë’ê/¢Ìƒš?šwšÆë–ºk³O—ñM­¥±°ƒ’û–¢ª³šb9M­¥±°‰ô)tì)™Õ¹Ñ¥½¸É•¹‘•É=ÕÑÁÕÑÌ ¥í½¹ÍĞ±¥ÍĞõ‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰½ÕÑÁÕÑ1¥ÍĞˆ¤í¥˜ …±¥ÍĞ¥É•ÑÕÉ¸í½¹ÍĞÍ•…É õ‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰½ÕÑÁÕÑM•…É ˆ¤í½¹ÍĞ…Ñ•½Éäõ‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰½ÕÑÁÕÑ…Ñ•½Éäˆ¤í½¹ÍĞ™…Ù½É¥Ñ”õ‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰½ÕÑÁÕÑ…Ù½É¥Ñ”ˆ¤í½¹ÍĞÉ•¹‘•Èô ¤ôùí½¹ÍĞÄô¡Í•…É ü¹Ù…±Õ•ñğˆˆ¤¹ÑÉ¥´ ¤¹Ñ½1½İ•É…Í” ¤í½¹ÍĞ…Ğõ…Ñ•½Éäü¹Ù…±Õ•ñğ‰…±°ˆí½¹ÍĞ™…Øõ™…Ù½É¥Ñ”ü¹Ù…±Õ•ñğ‰…±°ˆí½¹ÍĞ¥Ñ•µÌõ!=M}=UQAUQL¹™¥±Ñ•È¡¥Ñ•´ôùí½¹ÍĞµ…Ñ¡•Í…Ñ•½Éäõ…Ğôôô‰…±°‰ññ¥Ñ•´¹…Ñ•½Éäôôõ…Ğí½¹ÍĞµ…Ñ¡•Í…Ù½É¥Ñ”õ™…Ø„ôô‰™…Ù½É¥Ñ”‰ññ¥Ñ•´¹™…Ù½É¥Ñ”í½¹ÍĞ¡…åÍÑ…¬õ€‘í¥Ñ•´¹Ñ¥Ñ±•ô€‘í¥Ñ•´¹ÁÉ½©•Ñô€‘í¥Ñ•´¹‰É…¥¹ô€‘í¥Ñ•´¹Í­¥±±ô€‘í¥Ñ•´¹Ñ…Ì¹©½¥¸ ˆ€ˆ¥ô€‘í¥Ñ•´¹Í•…É¡õ€¹Ñ½1½İ•É…Í” ¤í½¹ÍĞµ…Ñ¡•ÍM•…É ô…ÅññÄ¹ÍÁ±¥Ğ ½qÌ¬¼¤¹•Ù•Éä¡Ñ•É´ôù¡…åÍÑ…¬¹¥¹±Õ‘•Ì¡Ñ•É´¤¤íÉ•ÑÕÉ¸µ…Ñ¡•Í…Ñ•½Éä˜™µ…Ñ¡•Í…Ù½É¥Ñ”˜™µ…Ñ¡•ÍM•…É¡ô¤í±¥ÍĞ¹¥¹¹•É!Q50õ¥Ñ•µÌ¹±•¹Ñ ı¥Ñ•µÌ¹µ…À¡¥Ñ•´ôù€ñ…ÉÑ¥±”±…ÍÌô‰Á…¹•°½ÕÑÁÕĞµ…Éˆ¥ô‰½ÕÑÁÕĞ´‘í•Í…Á•!Ñµ°¡¥Ñ•´¹…Ñ•½Éä¹Ñ½1½İ•É…Í” ¤¥ô´‘í•Í…Á•!Ñµ°¡¥Ñ•´¹Ñ¥Ñ±”¹É•Á±…” ½qÌ¬½œ°ˆ´ˆ¤¹Ñ½1½İ•É…Í” ¤¥ôˆøñ‘¥Ø±…ÍÌô‰½ÕÑÁÕĞµÑ½ÀˆøñÍÁ…¸±…ÍÌô‰½ÕÑÁÕĞµÑåÁ”ˆø‘í¥Ñ•´¹•µ½©¥ô€‘í•Í…Á•!Ñµ°¡¥Ñ•´¹…Ñ•½Éä¥ôğ½ÍÁ…¸ø‘í¥Ñ•´¹™…Ù½É¥Ñ”üœñÍÁ…¸±…ÍÌô‰™…Ù½É¥Ñ”µÍÑ…ÈˆûŠ¶@ƒ+šÂ_¯–—
(ğ½ÍÁ…¸øœèœôğ½‘¥Øøñ Ìø‘í•Í…Á•!Ñµ°¡¥Ñ•´¹Ñ¥Ñ±”¥ôğ½ Ìøñ‘°±…ÍÌô‰½ÕÑÁÕĞµµ•Ñ„ˆøñ‘¥Øøñ‘ĞùAÉ½©•Ğğ½‘Ğøñ‘ø‘í•Í…Á•!Ñµ°¡¥Ñ•´¹ÁÉ½©•Ğ¥ôğ½‘øğ½‘¥Øøñ‘¥Øøñ‘Ğû’ösš"Cš^”ğ½‘Ğøñ‘ø‘í•Í…Á•!Ñµ°¡¥Ñ•´¹É•…Ñ•¥ôğ½‘øğ½‘¥Øøñ‘¥Øøñ‘Ğû’öÿR¡	É…¥¸ğ½‘Ğøñ‘ø‘í•Í…Á•!Ñµ°¡¥Ñ•´¹‰É…¥¸¥ôğ½‘øğ½‘¥Øøñ‘¥Øøñ‘Ğû’öÿR¡M­¥±°ğ½‘Ğøñ‘ø‘í•Í…Á•!Ñµ°¡¥Ñ•´¹Í­¥±°¥ôğ½‘øğ½‘¥Øøñ‘¥Øøñ‘Ğûš’sÒˆğ½‘Ğøñ‘ø‘í•Í…Á•!Ñµ°¡¥Ñ•´¹Í•…É ¥ôğ½‘øğ½‘¥Øøñ‘¥Øøñ‘Ğû
ÿ
Àğ½‘Ğøñ‘ø‘í¥Ñ•´¹Ñ…Ì¹µ…À¡Ñ…œôù€ñÍÁ…¸±…ÍÌô‰‰…‘”Ñ…œˆøŒ‘í•Í…Á•!Ñµ°¡Ñ…œ¥ôğ½ÍÁ…¸ù€¤¹©½¥¸ ˆ€ˆ¥ôğ½‘øğ½‘¥Øøğ½‘°øñ„±…ÍÌô‰‘½İ¹±½…µ±¥¹¬ˆ¡É•˜ôˆ‘í•Í…Á•!Ñµ°¡¥Ñ•´¹‘½İ¹±½…¥ôˆ‘½İ¹±½…û
›Ï·ó'«Ï
¼ƒŠHğ½„øğ½…ÉÑ¥±”ù€¤¹©½¥¸ ˆˆ¤é€ñÀ±…ÍÌô‰½ÕÑÁÕĞµ•µÁÑäˆûšv‡’îÛ¯–B#=ÕÑÁÕÓ3¢š/“/
+ûo
Oğ½ÀùôímÍ•…É ±…Ñ•½Éä±™…Ù½É¥Ñ•t¹™½É… ¡•°ôù•°ü¹…‘‘Ù•¹Ñ1¥ÍÑ•¹•È ‰¥¹ÁÕĞˆ±É•¹‘•È¤¤ím…Ñ•½Éä±™…Ù½É¥Ñ•t¹™½É… ¡•°ôù•°ü¹…‘‘Ù•¹Ñ1¥ÍÑ•¹•È ‰¡…¹”ˆ±É•¹‘•È¤¤íÉ•¹‘•È ¥ô()½¹ÍĞ!=M}MI!}%9`õl)íÑåÁ”è‰¥Ù¥‘•¹ˆ±Ñ¥Ñ±”è‰¥Ù¥‘•¹µÁ¥É”ˆ±ÕÉ°è‰‘¥Ù¥‘•¹¹¡Ñµ°ˆ±Ñ•áĞè‹’â[–â¿¦7–öOº‡Bƒ¦7–öLƒ–«–úƒ¦G¢z7¢ÎRŒƒn»š¢g¦Ëš6\ƒ’êëR¢«RÇ–ê˜ƒ
ï
¿
ÿóš/š"@ƒ’şwšr'¦*cš~ƒš*W¢Î‰ô°)íÑåÁ”è‰=ÕÑÁÕÑÌˆ±Ñ¥Ñ±”è‰=ÕÑÁÕÑÌ1¥‰É…Éäˆ±ÕÉ°è‰½ÕÑÁÕÑÌ¹¡Ñµ°½ÕÑÁÕÑÌµ±¥‰É…Éäˆ±Ñ•áĞè‰!Q50A½İ•ÉA½¥¹ĞA5…É­‘½İ¸I•Ù¥•Üƒ
ÿ
“#¬AÉ½©•Ğƒ’ösš"Cš^”ƒ’öÿR¡	É…¥¸ƒ’öÿR¡M­¥±°ƒ
›Ï·ó'«Ï
¼ƒš’sÒˆƒ
ÿ
Àƒ+šÂ_¯–—
(ƒš"Cšzs&¤‰ô°)íÑåÁ”è‰=ÕÑÁÕÑÌˆ±Ñ¥Ñ±”è‰=ÕÑÁÕĞ…É‘Ìˆ±ÕÉ°è‰½ÕÑÁÕÑÌ¹¡Ñµ°½ÕÑÁÕĞµ±¥ÍĞµÍ•Ñ¥½¸ˆ±Ñ•áĞè‰!½¹‘„ƒ’òš–·–"šzA!Q53‡ˆƒš?–"§–:kR|Ì¸Àƒš>Cš†#
ç§
“$ƒ’â·šrÖ3–ZÛ¢¢#Rìƒ
Ã·óO
ç–¶›şHƒš/¦ƒ–2[‡ˆƒš?–"§–:kR–"Û–ê›³O—ğ‰ô°)íÑåÁ”è‰…Í¡‰½…Éˆ±Ñ¥Ñ±”è‹’î+š^—¹!=Lˆ±ÕÉ°è‰¥¹‘•à¹¡Ñµ°‘…Í¡‰½…Éˆ±Ñ•áĞè‰…Í¡‰½…Éƒš^—š²…=Lƒ’î+š^—–.W/eAÉ½©•Ğ%¹‰½à	É…¥¸M­¥±°'_·Ï_ !½¹‘„ƒš?–"§–:kR|Ì¸Àƒ
Ã·óO
ç–¶›şHƒš²‡¯¢#
/–V?‰ô°)íÑåÁ”è‰…Í¡‰½…Éˆ±Ñ¥Ñ±”è‹’î+š^—–.W/eAÉ½©•Ğˆ±ÕÉ°è‰¥¹‘•à¹¡Ñµ°‘…Í¡‰½…ÉµÁÉ½©•ÑÌˆ±Ñ•áĞè‰!½¹‘„ƒš?–"§–:kR|Ì¸Àƒ
Ã·óO
ç–¶›şHAÉ½©•ÑÌƒ
ÏSóR£_·Ï_ ƒÖ3–ZÛ¢Ìƒ’êë’ê/¢Ìƒ–¶›şK¢Ì‰ô°)íÑåÁ”è‰M­¥±±Ìˆ±Ñ¥Ñ±”è‰AÉ½©•ĞM­¥±±Ìˆ±ÕÉ°è‰ÁÉ½©•ÑÌ¹¡Ñµ°¡½¹‘„ˆ±Ñ•áĞè‹’òš–·–"šzAM­¥±°ƒ®Û–B#š¾S¢òM­¥±°ƒ¢Ê‡–.g–"¢M­¥±°ƒš:‡R£¢3šf¿–"¢M­¥±°ƒ–"Û–ê›¢¢·¢¢!M­¥±°I='šVÓBM­¥±°ƒ–¾û¢Æ‡–Æ“–"¢M­¥±°ƒ’û–¢ª³šb9M­¥±°ƒ–ú§şIM­¥±°ƒšVgšvC–2YM­¥±°ƒ
Çó
ç–"šzAM­¥±°ƒB¢–ê›'«¯’ösš"AM­¥±°‰ô°)íÑåÁ”è‰AÉ½©•ÑÌˆ±Ñ¥Ñ±”è‰!½¹‘„ˆ±ÕÉ°è‰ÁÉ½©•ÑÌ¹¡Ñµ°¡½¹‘„ˆ±Ñ•áĞè‰!½¹‘„!=LµA(´ÀÀÄƒ’òš–·–"šz@ƒÖ3–ZÛš"›V”ƒ®Û’ê'–«’ö4ƒ¢Ê‡–.dƒ’êë’ê,XMXQ½å½Ñ„9¥ÍÍ…¸ƒ’òš–·–"šzAM­¥±°ƒ®Û–B#š¾S¢òM­¥±°ƒ¢Ê‡–.g–"¢M­¥±°ƒš:‡R£¢3šf¿–"¢M­¥±°‰ô°)íÑåÁ”è‰AÉ½©•ÑÌˆ±Ñ¥Ñ±”è‹š?–"§–:kR|Ì¸Àˆ±ÕÉ°è‰ÁÉ½©•ÑÌ¹¡Ñµ°‰•¹•™¥ÑÌˆ±Ñ•áĞè‹š?–"§–:kR|Ì¸À!=LµA(´ÀÀÈƒ’êë’ê/–"Û–ê˜ƒš?–"§–:kR|ƒš:‡R ƒ–ºkv ƒ
£Ï
Ëó
ã‡Ï ƒRRšœI=$ƒ–"Û–ê›¢¢·¢¢!M­¥±°ƒ–¾û¢Æ‡–Æ“–"¢M­¥±°ƒ’û–¢ª³šb9M­¥±°‰ô°)íÑåÁ”è‰AÉ½©•ÑÌˆ±Ñ¥Ñ±”è‹
Ã·óO
ç–¶›şHˆ±ÕÉ°è‰ÁÉ½©•ÑÌ¹¡Ñµ°±½‰¥Ìˆ±Ñ•áĞè‹
Ã·óO
ç–¶›şH!=LµA(´ÀÀÌƒ–¶›şHƒÖ3–ZÛš"›V”ƒšVgšv@ƒ'«¬ƒ
Çó
ç–"šzAM­¥±°ƒšVgšvC–2YM­¥±°ƒ–ú§şIM­¥±°ƒB¢–ê›'«¯’ösš"AM­¥±°‰ô°)íÑåÁ”è‰AÉ½µÁÑÌˆ±Ñ¥Ñ±”è‰AÉ½µÁĞ1¥‰É…Éäˆ±ÕÉ°è‰ÁÉ½µÁÑÌ¹¡Ñµ°ÁÉ½µÁĞµ±¥‰É…Éäˆ±Ñ•áĞè‹_·Ï_#§
“[§¨$1…Õ¹¡•ÈƒÖ3–ZØƒ’êë’ê,ƒ–¶›şHƒ³O—ğƒš*W¢Î¡…ÑAP±…Õ‘”½‘•à‰ô°)íÑåÁ”è‰AÉ½µÁÑÌˆ±Ñ¥Ñ±”è‹Ö3–ZØˆ±ÕÉ°è‰ÁÉ½µÁÑÌ¹¡Ñµ°µ…¹…•µ•¹Ğˆ±Ñ•áĞè‹’òš–·–"šz@ƒš"›V—³O—ğƒÖ3–ZÛ¢ÌƒO
ãŸÌƒ’ê/š–·š/¦€ƒ®Û’ê'–«’ö4ƒ¢Ê‡–.d-A$‰ô°)íÑåÁ”è‰AÉ½µÁÑÌˆ±Ñ¥Ñ±”è‹’êë’ê,ˆ±ÕÉ°è‰ÁÉ½µÁÑÌ¹¡Ñµ°¡Èˆ±Ñ•áĞè‹–"Û–ê›¢¢·¢¢ ƒš:‡R£¢3šf¼ƒš?–"§–:kR|I=$ƒ–¾û¢Æ‡¢ƒÖ3–ZÛ¢ªË¦†0ƒ¦/R£¢Êƒ¢6Ü‰ô°)íÑåÁ”è‰AÉ½µÁÑÌˆ±Ñ¥Ñ±”è‹–¶›şHˆ±ÕÉ°è‰ÁÉ½µÁÑÌ¹¡Ñµ°±•…É¹¥¹œˆ±Ñ•áĞè‹šVgšvC–2Xƒ–ú§şK'«¬ƒ–¶›şK‡ˆƒ–ß’öO’ú,ƒB¢–ê›'«¬‰ô°)íÑåÁ”è‰AÉ½µÁÑÌˆ±Ñ¥Ñ±”è‹³O—ğˆ±ÕÉ°è‰ÁÉ½µÁÑÌ¹¡Ñµ°É•Ù¥•Üˆ±Ñ•áĞè‹šZ®ƒ³O—ğƒš?šwšÆë–ºk³O—ğƒ¢®[Bš/š"@ƒ–"“šZ·–~ëšêXƒ«
ç
¼‰ô°)íÑåÁ”è‰AÉ½µÁÑÌˆ±Ñ¥Ñ±”è‹š*W¢Îˆ±ÕÉ°è‰ÁÉ½µÁÑÌ¹¡Ñµ°¥¹Ù•ÍÑµ•¹Ğˆ±Ñ•áĞè‹š*W¢Î’î»¢ª°ƒšÆëº_‡ˆƒš"C¦Vß'§
“Cğƒ¢Îšr³¦7–"ƒC«—
£ó
ßŸÌ‰ô°)íÑåÁ”è‰	É…¥¸ˆ±Ñ¥Ñ±”è‰=OšËšÎTˆ±ÕÉ°è‰‰É…¥¸¹¡Ñµ°½¹ÍÑ¥ÑÕÑ¥½¸ˆ±Ñ•áĞè‹š/¦€ƒ’ê/–º£¢¦ ƒš¾S¢òƒÖ3–ZØƒ¢Ê‡–.dƒ’êë’ê,ƒ–â–‚Ğƒn»jƒš*÷¢Æ„ƒ–ß’öLƒš²‡¯¢#
/–V?‰ô°)íÑåÁ”è‰	É…¥¸ˆ±Ñ¥Ñ±”è‰½µÁ…ÍÌˆ±ÕÉ°è‰‰É…¥¸¹¡Ñµ°½µÁ…ÍÌˆ±Ñ•áĞè‹n»jƒšr³¢Î«¢ªË¦†0ƒ–£’öOšr¦¤ƒ¦Vßšr’ú‡–ƒ«
ç
¼ƒš²‡»’âš&,‰ô°)íÑåÁ”è‰	É…¥¸ˆ±Ñ¥Ñ±”è‰	É…¥»’â¢šœˆ±ÕÉ°è‰‰É…¥¸¹¡Ñµ°‰É…¥¹Ìˆ±Ñ•áĞè‹Ö3–ZÛ¢Ìƒ’êë’ê/¢Ìƒ¦G¢z7¢Ìƒš*W¢Î¢Ìƒ–¶›şK¢Ìƒ’öO¦¢O¢¢·¢¢#¢Ìƒš"›V”ƒ®Û’ê'–«’ö4ƒ¢Ê‡–.dƒš:‡R ƒ¢
Ëš"@ƒ–"Û–ê˜ƒš?–"§–:kR|4™ƒ¢Îšr³šRÿ¶X‰ô°)íÑåÁ”è‰	É…¥¸ˆ±Ñ¥Ñ±”è‰	É…¥»»’öÿšZäˆ±ÕÉ°è‰‰É…¥¸¹¡Ñµ°‰É…¥¸µ™±½Üˆ±Ñ•áĞè‰%¹‰½à	É…¥¸M­¥±°AÉ½©•Ğ-¹½İ±•‘”ƒ–>_G
,ƒ¢#
,ƒ–›Bg
,ƒ’şw–¶cg
,ƒš:—Úkg
,‰ô°)íÑåÁ”è‰-¹½İ±•‘”ˆ±Ñ¥Ñ±”è‰I=%ˆ±ÕÉ°è‰­¹½İ±•‘”¹¡Ñµ°É½¥Œˆ±Ñ•áĞè‹š*W’â/¢Îšr°ƒ–"§n(ƒ¢Îšr³–*ç:ƒš"C¦Vß»¢Î¨ƒ’ê/š–·wó#W
§«
¨ƒÖ3–ZÛ¢Ìƒš*W¢Î¢Ì!½¹‘„ƒ
Ã·óO
ç–¶›şHƒ¢Ê‡–.g–"¢M­¥±°ƒ’òš–·–"šzAM­¥±°ƒš*W¢Îƒ’â·Òhƒ
#?’öÿ‰ô°)íÑåÁ”è‰-¹½İ±•‘”ˆ±Ñ¥Ñ±”è‹š?–"§–:kR}I=$ˆ±ÕÉ°è‰­¹½İ±•‘”¹¡Ñµ°‰•¹•™¥ÑÌµÉ½¤ˆ±Ñ•áĞè‹š?–"§–:kR|ƒš*W¢Îƒš:‡R ƒ–ºkv ƒRRšœƒÖ3–ZÛ¢¢¢ªxƒ’êë’ê/¢ÌƒÖ3–ZÛ¢Ìƒš?–"§–:kR|Ì¸ÀI='šVÓBM­¥±°ƒ’û–¢ª³šb9M­¥±°ƒ’êë’ê,ƒ’â·Òhƒšr¢şG¢ş÷–*€‰ô°)íÑåÁ”è‰-¹½İ±•‘”ˆ±Ñ¥Ñ±”è‹š:‡R£¢3šf¼ˆ±ÕÉ°è‰­¹½İ±•‘”¹¡Ñµ°¡¥É¥¹œµ½¹Ñ•áĞˆ±Ñ•áĞè‹šÆ’êë– ƒ’ê/š–·¢ªË¦†0ƒÖæS¢ªË¦†0ƒ>û–‚Ğƒ–g¢s¢š>Cš† ƒšÆ’êëB¢Œƒ’êëšvC–â–‚Ó¢Ìƒ’êë’ê/¢Ì!½¹‘„ƒš:‡R£¢3šf¿–"¢M­¥±°ƒ’êë’ê,ƒ–~ë’8ƒ
#?’öÿ‰ô°)íÑåÁ”è‰-¹½İ±•‘”ˆ±Ñ¥Ñ±”è‹¢Îšr³¦7–"ˆ±ÕÉ°è‰­¹½İ±•‘”¹¡Ñµ°…Á¥Ñ…°µ…±±½…Ñ¥½¸ˆ±Ñ•áĞè‹š*W¢Îƒ¦7–öLƒ¢«’ûš‚«¢Êß4™ƒ¢Îšr°ƒš?šwšÆë–ºhƒ¦Vßšr’ú‡–ƒÖ3–ZÛ¢Ìƒš*W¢Î¢Ìƒ¦G¢z7¢Ì!½¹‘„ƒ’òš–·–"šzAM­¥±°ƒš?šwšÆë–ºk³O—ñM­¥±°ƒÖ3–ZØƒ–şsR ‰ô°)íÑåÁ”è‰-¹½İ±•‘”ˆ±Ñ¥Ñ±”è‹®Û’ê'–«’ö4ˆ±ÕÉ°è‰­¹½İ±•‘”¹¡Ñµ°½µÁ•Ñ¥Ñ¥Ù”µ…‘Ù…¹Ñ…”ˆ±Ñ•áĞè‹’î[’øƒÚgÚkjƒ¦ãÃ
3
,ƒ–"§n(ƒ–òßüƒš"›V—¢¦W’ú„ƒ’òš–·š¾S¢òƒÖ3–ZÛ¢Ìƒš*W¢Î¢Ì!½¹‘„ƒ
Ã·óO
ç–¶›şHƒ®Û–B#š¾S¢òM­¥±°ƒ
Çó
ç–"šzAM­¥±°ƒÖ3–ZØƒ–~ë’8ƒ
#?’öÿ‰ô°)íÑåÁ”è‰-¹½İ±•‘”ˆ±Ñ¥Ñ±”è‹’â·šrÖ3–ZÛ¢¢#Rìˆ±ÕÉ°è‰­¹½İ±•‘”¹¡Ñµ°µ¥‘Ñ•É´µÁ±…¸ˆ±Ñ•áĞè‹š"›V”-A$ƒš*W¢ÎšZç¦tƒš"C¦Vß
ß+«
¨ƒ–«–#¦‚’ö4ƒš:‡R ƒš*W¢ÎóxƒÖ3–ZÛ¢Ìƒš*W¢Î¢Ìƒ’êë’ê/¢Ì!½¹‘„ƒ’òš–·–"šzAM­¥±°ƒš:‡R£¢3šf¿–"¢M­¥±°ƒÖ3–ZØƒ’â·Òhƒšr¢şG¢ş÷–*€‰ô°)íÑåÁ”è‰-¹½İ±•‘”ˆ±Ñ¥Ñ±”è‰-¹½İ±•‘”1½½Àˆ±ÕÉ°è‰­¹½İ±•‘”¹¡Ñµ°­¹½İ±•‘”µ±½½Àˆ±Ñ•áĞè‰%¹‰½àƒšš–şÔ-¹½İ±•‘—
¯ó$AÉ½©•ĞƒšnÓšZÀƒ–/’êë~—¢¶cgó
äƒ–¶›şK¢Ìƒ’öO¦¢O¢¢·¢¢#¢Ìƒ
Ã·óO
ç–¶›şHƒšVgšvC–2YM­¥±°ƒ–ú§şIM­¥±°ƒ–¶›şHƒ–~ë’8ƒšr¢şG¢ş÷–*€‰ô°)íÑåÁ”è‰-¹½İ±•‘”ˆ±Ñ¥Ñ±”è‰-¹½İ±•‘”9…Ù¥…Ñ¥½¸ˆ±ÕÉ°è‰­¹½İ±•‘”¹¡Ñµ°­¹½İ±•‘”µ½¹ÑÉ½±Ìˆ±Ñ•áĞè‹
¯
Ó¨ƒ
ÿ
Àƒ¦nšbO–ê˜ƒ–~ë’8ƒ’â·Òhƒ–şsR ƒšr¢şG¢ş÷–*€ƒ
#?’öÿƒÖ3–ZØƒ’êë’ê,ƒš*W¢Îƒ–¶›şHƒÖæP‰ô)tì()™Õ¹Ñ¥½¸•Í…Á•!Ñµ°¡Ù…±Õ”¥íÉ•ÑÕÉ¸Ù…±Õ”¹É•Á±…” ½l˜ğø‰t½œ±Œôø¡ìˆ˜ˆèˆ™…µÀìˆ°ˆğˆèˆ™±Ğìˆ°ˆøˆèˆ™Ğìˆ°œˆœèˆ™ÅÕ½Ğì‰õmt¤¥ô)™Õ¹Ñ¥½¸¡¥¡±¥¡Ñ5…Ñ ¡Ù…±Õ”±ÅÕ•Éä¥í½¹ÍĞÍ…™”õ•Í…Á•!Ñµ°¡Ù…±Õ”¤í½¹ÍĞÑ•ÉµÌõÅÕ•Éä¹ÑÉ¥´ ¤¹ÍÁ±¥Ğ ½qÌ¬¼¤¹™¥±Ñ•È¡	½½±•…¸¤¹µ…À¡ĞôùĞ¹É•Á±…” ½l¸¨¬ıx‘íô ¥ñmquqqt½œ°‰qp˜ˆ¤¤í¥˜ …Ñ•ÉµÌ¹±•¹Ñ ¥É•ÑÕÉ¸Í…™”íÉ•ÑÕÉ¸Í…™”¹É•Á±…”¡¹•ÜI•áÀ¡€ ‘íÑ•ÉµÌ¹©½¥¸ ‰ğˆ¥ô¥€°‰¤ˆ¤°ˆñµ…É¬øÄğ½µ…É¬øˆ¥ô)™Õ¹Ñ¥½¸¥¹¥Ñ±½‰…±M•…É  ¥í½¹ÍĞ¥¹ÁÕĞõ‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰±½‰…±M•…É ˆ¤í½¹ÍĞ‰½àõ‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å% ‰Í•…É¡I•ÍÕ±ÑÌˆ¤í¥˜ …¥¹ÁÕÑñğ…‰½à¥É•ÑÕÉ¸í½¹ÍĞÉ•¹‘•Èô ¤ôùí½¹ÍĞÄõ¥¹ÁÕĞ¹Ù…±Õ”¹ÑÉ¥´ ¤¹Ñ½1½İ•É…Í” ¤í¥˜ …Ä¥í‰½à¹¥¹¹•É!Q50ôˆˆí‰½à¹±…ÍÍ1¥ÍĞ¹É•µ½Ù” ‰½Á•¸ˆ¤íÉ•ÑÕÉ¹õ½¹ÍĞÑ•ÉµÌõÄ¹ÍÁ±¥Ğ ½qÌ¬¼¤¹™¥±Ñ•È¡	½½±•…¸¤í½¹ÍĞ¡¥ÑÌõ!=M}MI!}%9`¹™¥±Ñ•È¡¥Ñ•´ôùÑ•ÉµÌ¹•Ù•Éä¡Ñ•É´ôù€‘í¥Ñ•´¹Ñ¥Ñ±•ô€‘í¥Ñ•´¹ÑåÁ•ô€‘í¥Ñ•´¹Ñ•áÑõ€¹Ñ½1½İ•É…Í” ¤¹¥¹±Õ‘•Ì¡Ñ•É´¤¤¤¹Í±¥” À°à¤í‰½à¹±…ÍÍ1¥ÍĞ¹…‘ ‰½Á•¸ˆ¤í‰½à¹¥¹¹•É!Q50õ¡¥ÑÌ¹±•¹Ñ ı¡¥ÑÌ¹µ…À¡¥Ñ•´ôù€ñ„±…ÍÌô‰Í•…É µÉ•ÍÕ±Ğˆ¡É•˜ôˆ‘í¥Ñ•´¹ÕÉ±ôˆøñÍÁ…¸ø‘í•Í…Á•!Ñµ°¡¥Ñ•´¹ÑåÁ”¥ôğ½ÍÁ…¸øñÍÑÉ½¹œø‘í¡¥¡±¥¡Ñ5…Ñ ¡¥Ñ•´¹Ñ¥Ñ±”±¥¹ÁÕĞ¹Ù…±Õ”¥ôğ½ÍÑÉ½¹œøñÍµ…±°ø‘í¡¥¡±¥¡Ñ5…Ñ ¡¥Ñ•´¹Ñ•áĞ±¥¹ÁÕĞ¹Ù…±Õ”¥ôğ½Íµ…±°øğ½„ù€¤¹©½¥¸ ˆˆ¤é€ñÀ±…ÍÌô‰Í•…É µ•µÁÑäˆû¢¦Ë–öOg
-!=O¦‚n»3¢š/“/
+ûo
Oğ½Àùôí¥¹ÁÕĞ¹…‘‘Ù•¹Ñ1¥ÍÑ•¹•È ‰¥¹ÁÕĞˆ±É•¹‘•È¤í¥¹ÁÕĞ¹…‘‘Ù•¹Ñ1¥ÍÑ•¹•È ‰™½ÕÌˆ±É•¹‘•È¤í‘½Õµ•¹Ğ¹…‘‘Ù•¹Ñ1¥ÍÑ•¹•È ‰±¥¬ˆ±”ôùí¥˜ …”¹Ñ…É•Ğ¹±½Í•ÍĞ ˆ¹±½‰…°µÍ•…É ˆ¤¥í‰½à¹±…ÍÍ1¥ÍĞ¹É•µ½Ù” ‰½Á•¸ˆ¥õô¥ô)™Õ¹Ñ¥½¸ÍÉ½±±Q½!…Í  ¥í¥˜ …±½…Ñ¥½¸¹¡…Í ¥É•ÑÕÉ¸íÍ•ÑQ¥µ•½ÕĞ  ¤ôùí½¹ÍĞÑ…É•Ğõ‘½Õµ•¹Ğ¹•Ñ±•µ•¹Ñ	å%¡‘•½‘•UI%½µÁ½¹•¹Ğ¡±½…Ñ¥½¸¹¡…Í ¹Í±¥” Ä¤¤¤íÑ…É•Ğü¹ÍÉ½±±%¹Ñ½Y¥•Ü¡í‰•¡…Ù¥½Èè‰Íµ½½Ñ ˆ±‰±½¬è‰ÍÑ…ÉĞ‰ô¤íÑ…É•Ğü¹±…ÍÍ1¥ÍĞ¹…‘ ‰Ñ…É•Ğµ™±…Í ˆ¤íÍ•ÑQ¥µ•½ÕĞ  ¤ôùÑ…É•Ğü¹±…ÍÍ1¥ÍĞ¹É•µ½Ù” ‰Ñ…É•Ğµ™±…Í ˆ¤°ÄØÀÀ¥ô°àÀ¥ô)‘½Õµ•¹Ğ¹…‘‘Ù•¹Ñ1¥ÍÑ•¹•È ‰=5½¹Ñ•¹Ñ1½…‘•ˆ° ¤ôùí¥¹¥Ñ±½‰…±M•…É  ¤íÉ•¹‘•É…Í¡‰½…É ¤íÉ•¹‘•É=ÕÑÁÕÑÌ ¤íÍÉ½±±Q½!…Í  ¥ô¤ì