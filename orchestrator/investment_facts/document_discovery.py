from __future__ import annotations
import re, urllib.parse
from .models import DocumentCandidate
from . import canonical_url
DOC_PAT=re.compile(r'(決算短信|決算説明|有価証券報告書|earnings|financial results|securities report)',re.I)
PDF_PAT=re.compile(r'\.pdf(?:$|[?#])',re.I)
def discover_links(html, base_url, official_domain=True):
    out=[]
    for href,title in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html or '', re.I|re.S):
        text=re.sub('<[^>]+>',' ',title); url=urllib.parse.urljoin(base_url, href)
        if DOC_PAT.search(text+' '+url):
            dtype='earnings_release' if '短信' in text else 'presentation' if '説明' in text else 'securities_report' if '有価証券' in text else 'financial_document'
            out.append(DocumentCandidate(url=url, canonical_url=canonical_url(url), title=' '.join(text.split()), document_type=dtype, mime_type='application/pdf' if PDF_PAT.search(url) else 'text/html', official_domain_verified=official_domain, discovery_source_url=base_url, discovery_method='html_link', candidate_score=0.5))
    return out
def reject_listing_page(candidate):
    u=(candidate.url or '').lower(); return not (u.endswith('/ir.html') or 'library/results.html' in u and not u.endswith('.pdf'))
def rank_financial_documents(candidates):
    weights={'earnings_release':100,'presentation':80,'securities_report':70,'financial_document':50}
    ranked=[c for c in candidates if reject_listing_page(c)]
    for c in ranked: c.candidate_score=max(c.candidate_score, weights.get(c.document_type,10))
    return sorted(ranked,key=lambda c:(c.candidate_score,c.published_at or ''),reverse=True)
