from __future__ import annotations
import re, urllib.parse
from .models import DocumentCandidate
from . import canonical_url
DOC_PAT=re.compile(r'(決算短信|決算説明|有価証券報告書|earnings|financial results|securities report)',re.I)
PDF_PAT=re.compile(r'\.pdf(?:$|[?#])',re.I)
BAD_PAT=re.compile(r'(/news/\d{8}\.html$|calendar|予定|schedule|一覧$|/ir\.html$)',re.I)

def _text(s): return ' '.join(re.sub('<[^>]+>',' ',s or '').split())
def discover_links(html, base_url, official_domain=True):
    out=[]
    for href,title in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html or '', re.I|re.S):
        text=_text(title); url=urllib.parse.urljoin(base_url, href); blob=text+' '+url
        if not DOC_PAT.search(blob): continue
        dtype='earnings_release' if re.search('決算短信|financial results|earnings',blob,re.I) else 'presentation' if '説明' in blob else 'securities_report' if '有価証券' in blob else 'financial_document'
        c=DocumentCandidate(url=url, canonical_url=canonical_url(url), title=text, document_type=dtype, mime_type='application/pdf' if PDF_PAT.search(url) else 'text/html', official_domain_verified=official_domain, discovery_source_url=base_url, discovery_method='html_link', candidate_score=score_candidate(url,text,dtype,official_domain))
        out.append(c)
    return out

def score_candidate(url,title='',document_type=None,official=False,http_status=None,content_type=None,code=None,company=None,period=None,date=None):
    blob=f'{title} {url}'
    if BAD_PAT.search(blob) and not PDF_PAT.search(url): return -100
    score=0
    score+=40 if official else 0
    score+=25 if PDF_PAT.search(url) else 10
    score+=30 if re.search(r'決算短信|financial results|earnings',blob,re.I) else 0
    score+=10 if re.search(r'IFRS|連結',blob,re.I) else 0
    score+=15 if code and code in blob else 0
    score+=10 if company and company in blob else 0
    score+=10 if period and period in blob else 0
    score+=10 if date and date.replace('-','') in blob else 0
    score+=15 if http_status==200 else (-50 if http_status and http_status>=400 else 0)
    score+=10 if (content_type or '').split(';')[0].lower()=='application/pdf' else 0
    return score

def reject_listing_page(candidate):
    u=(candidate.url or '').lower()
    return not (u.endswith('/ir.html') or u.endswith('/library.html') or u.endswith('/news.html') or ('library/results.html' in u and not u.endswith('.pdf')) or candidate.candidate_score < 0)

def rank_financial_documents(candidates):
    ranked=[c for c in candidates if reject_listing_page(c)]
    return sorted(ranked,key=lambda c:(c.candidate_score,c.published_at or ''),reverse=True)
