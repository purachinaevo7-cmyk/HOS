from __future__ import annotations
import json
from pathlib import Path
from typing import Any
TASK_REQUIRED={'task_id','request','target'}
def validate_task(data: dict[str,Any]) -> None:
    miss=TASK_REQUIRED-set(data)
    if miss: raise ValueError(f"Task missing fields: {sorted(miss)}")
    if len(json.dumps(data,ensure_ascii=False))>200_000: raise ValueError('Task JSON too large')
    if not isinstance(data.get('target'), (dict,str)): raise ValueError('target must be object or string')
def validate_json_file(path: Path) -> dict[str,Any]:
    data=json.loads(path.read_text(encoding='utf-8')); validate_task(data); return data
def envelope(agent_id, agent_version, run_id, task_id, step_id, status, data, evidence=None, assumptions=None, missing_information=None, warnings=None, errors=None):
    from datetime import datetime, timezone
    return {'schema_version':'1.0','agent_id':agent_id,'agent_version':agent_version,'run_id':run_id,'task_id':task_id,'step_id':step_id,'status':status,'generated_at':datetime.now(timezone.utc).isoformat(),'data':data or {},'evidence':evidence or [],'assumptions':assumptions or [],'missing_information':missing_information or [],'warnings':warnings or [],'errors':errors or []}


def validate_agent_output_envelope(data: dict[str,Any]) -> None:
    required={"schema_version","agent_id","agent_version","run_id","task_id","step_id","status","generated_at","data","evidence","assumptions","missing_information","warnings","errors"}
    miss=required-set(data)
    if miss: raise ValueError(f"Agent Output Envelope missing fields: {sorted(miss)}")
    if data.get("schema_version")!="1.0": raise ValueError("Agent Output Envelope schema_version must be 1.0")
    if data.get("status") not in {"completed","partial","failed"}: raise ValueError("Agent Output Envelope status invalid")
    if not isinstance(data.get("data"),dict): raise ValueError("Agent Output Envelope data must be object")
