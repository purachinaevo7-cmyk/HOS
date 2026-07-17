from __future__ import annotations
import json, shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from orchestrator.security import safe_filename, sha256_text
class RunStore:
    def __init__(self, root:Path): self.root=root
    def create(self, run_id:str, task:dict[str,Any], workflow_id:str)->Path:
        d=self.root/'runs'/run_id
        for sub in ['context','steps','reviews','artifacts','reports','outputs','reflections','logs','diagnostics','facts','sources','claims']: (d/sub).mkdir(parents=True,exist_ok=True)
        (d/'task.json').write_text(json.dumps(task,ensure_ascii=False,indent=2),encoding='utf-8')
        (d/'manifest.json').write_text(json.dumps({'run_id':run_id,'task_id':task['task_id'],'workflow_id':workflow_id,'created_at':datetime.now(timezone.utc).isoformat(),'artifacts':{}},ensure_ascii=False,indent=2),encoding='utf-8')
        return d
    def save_step(self, run_dir:Path, step_id:str, output:dict[str,Any])->Path:
        p=run_dir/'steps'/f'{safe_filename(step_id)}.json'; p.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8'); return p
    def save_run(self, run_dir:Path, data:dict[str,Any])->Path:
        p=run_dir/'run.json'; p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); return p
    def write_manifest(self, run_dir:Path, manifest:dict[str,Any])->Path:
        p=run_dir/'manifest.json'; p.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8'); return p
    def export_bundle(self, run_dir:Path, out:Path)->Path:
        if out.exists(): shutil.rmtree(out)
        shutil.copytree(run_dir,out); return out
