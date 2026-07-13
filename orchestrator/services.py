from __future__ import annotations
from pathlib import Path
from typing import Any
import json
from datetime import datetime, timezone

class JsonRepository:
    def __init__(self, root: Path, rel: str): self.path=root/rel; self.path.mkdir(parents=True, exist_ok=True)
    def save(self, name: str, data: dict[str,Any]) -> Path:
        p=self.path/name; p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); return p

class MemoryService:
    categories={"task_history","decisions","preferences","reflections"}
    def __init__(self, root: Path): self.repo=JsonRepository(root,"outputs/memory")
    def save(self, category: str, item_id: str, data: dict[str,Any]) -> Path:
        if category not in self.categories: raise ValueError(f"Unknown memory category: {category}")
        return self.repo.save(f"{category}-{item_id}.json", data)

class KnowledgeService:
    def __init__(self, root: Path): self.repo=JsonRepository(root,"outputs/knowledge")
    def save_entry(self, entry: dict[str,Any]) -> Path:
        now=datetime.now(timezone.utc).isoformat(); entry.setdefault('created_at',now); entry.setdefault('updated_at',now)
        required=["id","title","content","source","source_date","confidence","created_by_agent","version","tags","freshness_status","next_review_date"]
        miss=[k for k in required if k not in entry]
        if miss: raise ValueError(f"Knowledge entry missing fields: {miss}")
        return self.repo.save(f"{entry['id']}.json", entry)
    def search(self, keyword: str = "", tags: list[str]|None = None) -> list[dict[str,Any]]:
        results=[]
        for p in self.repo.path.glob('*.json'):
            data=json.loads(p.read_text(encoding='utf-8'))
            if keyword and keyword not in json.dumps(data,ensure_ascii=False): continue
            if tags and not set(tags).issubset(set(data.get('tags',[]))): continue
            results.append(data)
        return results


class ArtifactIndexService:
    """Maintains a static JSON index for generated HOS artifacts."""
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "outputs" / "index.json"

    def update(self, entry: dict[str, Any]) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entries: list[dict[str, Any]] = []
        if self.path.exists():
            current = json.loads(self.path.read_text(encoding="utf-8"))
            entries = current.get("artifacts", []) if isinstance(current, dict) else []
        entries = [e for e in entries if e.get("task_id") != entry.get("task_id")]
        now = datetime.now(timezone.utc).isoformat()
        entry = {**entry, "indexed_at": now}
        entries.append(entry)
        entries.sort(key=lambda e: e.get("created_at") or e.get("indexed_at", ""), reverse=True)
        payload = {"version": "1.0.0", "updated_at": now, "artifacts": entries}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.path

    def list(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        current = json.loads(self.path.read_text(encoding="utf-8"))
        return current.get("artifacts", []) if isinstance(current, dict) else []
