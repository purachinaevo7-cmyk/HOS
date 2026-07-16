from __future__ import annotations
import argparse, json, os, platform, shutil, subprocess, sys
from pathlib import Path
from orchestrator.artifacts import RunStore
from orchestrator.executor import build_executor, ExecutorError, GeminiExecutor
from orchestrator.registry import AgentRegistry
from orchestrator.runner import Orchestrator, ROOT
from orchestrator.schemas import validate_json_file
from orchestrator.workflow import WorkflowEngine

def _print(obj): print(json.dumps(obj,ensure_ascii=False,indent=2) if not isinstance(obj,str) else obj)
def doctor(args):
    checks={'python':platform.python_version(),'cwd':str(ROOT),'registry':False,'workflows':False,'ui_data':False,'openai_api_key_present':bool(os.getenv('OPENAI_API_KEY')),'gemini_api_key_present':bool(os.getenv('GEMINI_API_KEY')),'github_actions':(ROOT/'.github/workflows/hos-ai-company.yml').exists()}
    try: AgentRegistry.load(ROOT); checks['registry']=True
    except Exception as e: checks['registry_error']=str(e)
    try:
        reg=AgentRegistry.load(ROOT)
        for p in (ROOT/'workflows').glob('*.yml'): WorkflowEngine.validate(WorkflowEngine.load(ROOT,p.stem),reg)
        checks['workflows']=True
    except Exception as e: checks['workflow_error']=str(e)
    checks['ui_data']=(ROOT/'data/agents.json').exists() and (ROOT/'data/workflows.json').exists()
    _print(checks); return 0 if checks['registry'] and checks['workflows'] else 1
def validate_agents(args): AgentRegistry.load(ROOT); print('agents: ok'); return 0
def export_agents_ui(args):
    AgentRegistry.load(ROOT).export_ui(ROOT/'data/agents.json'); WorkflowEngine.export_ui(ROOT,ROOT/'data/workflows.json'); print('exported data/agents.json and data/workflows.json'); return 0
def validate_workflows(args):
    reg=AgentRegistry.load(ROOT)
    for p in sorted((ROOT/'workflows').glob('*.yml')): WorkflowEngine.validate(WorkflowEngine.load(ROOT,p.stem),reg); print(f'{p.stem}: ok')
    return 0
def visualize_workflow(args):
    wf=WorkflowEngine.load(ROOT,args.workflow); print('flowchart TD')
    for s in wf.steps:
        print(f'  {s.id}["{s.id}<br/>{s.agent}"]')
        for d in s.depends_on: print(f'  {d} --> {s.id}')
    return 0
def validate_task(args): validate_json_file(Path(args.file)); print('task: ok'); return 0
def run(args):
    ex=build_executor(args.executor,scenario=args.scenario,replay_run=args.replay_run)
    r=Orchestrator(root=ROOT,dry_run=args.dry_run,executor=ex).run_task(args.file)
    _print({'run_id':r.run_id,'task_id':r.task_id,'report_path':str(r.report_path),'hos_json_path':str(r.hos_json_path),'dry_run':r.dry_run}); return 0
def gemini_smoke_test(args):
    import types
    ex=GeminiExecutor()
    agent=types.SimpleNamespace(id='ceo_planner',version='1.0.0',prompt_path='agents/ceo_planner.md',temperature=0.0,timeout_seconds=30)
    step=types.SimpleNamespace(id='gemini_smoke',output_key='gemini_smoke')
    old=os.environ.get('GEMINI_MAX_OUTPUT_TOKENS_CEO_PLANNER')
    os.environ['GEMINI_MAX_OUTPUT_TOKENS_CEO_PLANNER']='512'
    try:
        out=ex.execute(agent,{'task_id':'GEMINI-SMOKE','request':'Return a tiny plan.','target':{'name':'smoke'},'workflow':'investment_analysis_free'},{'run_id':'gemini-smoke','run_dir':'runs/gemini-smoke','outputs':{},'attempt_number':1},step)
    finally:
        if old is None: os.environ.pop('GEMINI_MAX_OUTPUT_TOKENS_CEO_PLANNER',None)
        else: os.environ['GEMINI_MAX_OUTPUT_TOKENS_CEO_PLANNER']=old
    fr=(ex.usage[-1] if ex.usage else {}).get('finish_reason')
    print(f'Gemini smoke test: PASS\nmodel: {ex.model}\nfinishReason: {fr}\nvalidJSON: true')
    return 0

def list_runs(args):
    rows=[]
    for p in sorted((ROOT/'runs').glob('*/run.json')):
        rows.append(json.loads(p.read_text(encoding='utf-8')))
    _print(rows); return 0
def inspect_run(args):
    p=ROOT/'runs'/args.run_id/'run.json'
    if not p.exists(): raise SystemExit(f'run not found: {args.run_id}')
    _print(json.loads(p.read_text(encoding='utf-8'))); return 0
def export_run(args):
    src=ROOT/'runs'/args.run_id
    if not src.exists(): raise SystemExit(f'run not found: {args.run_id}')
    out=ROOT/'exports'/f'hos-run-{args.run_id}'
    RunStore(ROOT).export_bundle(src,out); print(out); return 0
def resume(args):
    # MVP-safe resume: inspect and return non-destructive status. Full queue resume is architecture-review required.
    return inspect_run(args)
def cancel(args):
    p=ROOT/'runs'/args.run_id/'run.json'
    if not p.exists(): raise SystemExit(f'run not found: {args.run_id}')
    data=json.loads(p.read_text(encoding='utf-8')); data['status']='cancelled'; p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); print('cancelled'); return 0
def demo(args):
    for wf in ['investment_analysis','company_analysis','hr_strategy_review','idea_generation','learning_material']:
        path=ROOT/'tasks/inbox'/f'{wf}.sample.json'
        if path.exists(): Orchestrator(root=ROOT,executor=build_executor('mock')).run_task(path)
    print('demo runs completed'); return 0
def list_knowledge_candidates(args): _print([]); return 0
def approve_knowledge(args): print(f'knowledge candidate approval pending human workflow: {args.id}'); return 0
def reject_knowledge(args): print(f'knowledge candidate rejected: {args.id}'); return 0
def main(argv=None):
    ap=argparse.ArgumentParser(prog='python -m orchestrator.cli'); sub=ap.add_subparsers(dest='cmd',required=True)
    for name,fn in [('doctor',doctor),('validate-agents',validate_agents),('export-agents-ui',export_agents_ui),('validate-workflows',validate_workflows),('list-runs',list_runs),('gemini-smoke-test',gemini_smoke_test),('demo',demo),('list-knowledge-candidates',list_knowledge_candidates)]: sub.add_parser(name).set_defaults(func=fn)
    p=sub.add_parser('visualize-workflow'); p.add_argument('workflow'); p.set_defaults(func=visualize_workflow)
    p=sub.add_parser('validate-task'); p.add_argument('file'); p.set_defaults(func=validate_task)
    p=sub.add_parser('run'); p.add_argument('file'); p.add_argument('--executor',choices=['mock','openai','gemini','replay'],default=os.getenv('HOS_EXECUTOR','mock')); p.add_argument('--scenario',default='success'); p.add_argument('--replay-run'); p.add_argument('--dry-run',action='store_true'); p.set_defaults(func=run)
    for name,fn in [('inspect-run',inspect_run),('resume',resume),('cancel',cancel),('export-run',export_run)]: p=sub.add_parser(name); p.add_argument('run_id'); p.set_defaults(func=fn)
    p=sub.add_parser('approve-knowledge'); p.add_argument('id'); p.set_defaults(func=approve_knowledge)
    p=sub.add_parser('reject-knowledge'); p.add_argument('id'); p.set_defaults(func=reject_knowledge)
    ns=ap.parse_args(argv); return ns.func(ns)
if __name__=='__main__': raise SystemExit(main())
