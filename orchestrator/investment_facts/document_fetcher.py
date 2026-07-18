from __future__ import annotations
import hashlib, json
from pathlib import Path
from . import fetch_http, now
class DocumentFetcher:
    def __init__(self, root=None, max_bytes=5_000_000, timeout=20): self.root=Path(root) if root else None; self.max_bytes=max_bytes; self.timeout=timeout
    def fetch(self,url):
        h=fetch_http(url,self.timeout,None,self.max_bytes,0); raw=h.get('text','').encode('utf-8',errors='ignore'); sha=hashlib.sha256(raw).hexdigest()
        return {'source_url':url,'final_url':h.get('url') or url,'fetched_at':now(),'content_type':h.get('content_type'),'http_status':h.get('http_status'),'sha256':sha,'size_bytes':len(raw),'text':h.get('text'),'content_fetched':True}
