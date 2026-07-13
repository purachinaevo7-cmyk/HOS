from __future__ import annotations
import hashlib, re
from pathlib import Path
SECRET_PATTERNS=[re.compile(r"sk-[A-Za-z0-9_-]{20,}"),re.compile(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*[^\s,]+")]
def redact_secret(value: str) -> str:
    text=str(value)
    for pat in SECRET_PATTERNS: text=pat.sub('[REDACTED]', text)
    return text
def safe_filename(name: str) -> str:
    cleaned=re.sub(r'[^A-Za-z0-9._-]+','-',name).strip('.-')
    return cleaned[:120] or 'artifact'
def ensure_child(root: Path, candidate: Path) -> Path:
    root=root.resolve(); path=(root/candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if root not in path.parents and path != root: raise ValueError('path traversal blocked')
    return path
def sha256_text(text: str) -> str: return hashlib.sha256(text.encode('utf-8')).hexdigest()
