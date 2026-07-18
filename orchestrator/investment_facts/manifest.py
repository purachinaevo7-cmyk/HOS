from __future__ import annotations
import hashlib,json,os,tempfile
from datetime import datetime, timezone
from pathlib import Path
REQUIRED=['task.json','run.json','usage.json','fact_pack.json','source_map.json','provider_errors.json','diagnostics.json','diagnostics/data_sufficiency_gate.json','discord_message.txt','investment_commander_update.json']
def atomic_write_json(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(dir=str(path.parent),prefix=path.name,suffix='.tmp')
    with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2)
    os.replace(tmp,path)
def build_manifest(run_dir, run_id=None, task_id=None, workflow_id=None):
    run_dir=Path(run_dir); arts={}; complete=True
    for rel in REQUIRED:
        p=run_dir/rel; exists=p.exists(); valid=None
        if p.suffix=='.json' and exists:
            try: json.loads(p.read_text(encoding='utf-8')); valid=True
            except Exception: valid=False
        elif exists: valid=True
        if not exists: complete=False
        sha=hashlib.sha256(p.read_bytes()).hexdigest() if exists else None
        arts[rel]={'filename':p.name,'relative_path':rel,'media_type':'application/json' if p.suffix=='.json' else 'text/plain','size_bytes':p.stat().st_size if exists else 0,'sha256':sha,'created_at':datetime.now(timezone.utc).isoformat(),'schema_version':'1.0','valid_json':valid,'required':True,'status':'complete' if exists and valid is not False else 'missing' if not exists else 'invalid'}
    m={'run_id':run_id,'task_id':task_id,'workflow_id':workflow_id,'generated_at':datetime.now(timezone.utc).isoformat(),'artifact_count':len(arts),'required_artifacts_complete':complete and all(a['status']=='complete' for a in arts.values()),'artifacts':arts,'manifest_schema_version':'1.0'}
    atomic_write_json(run_dir/'manifest.json',m); return m
