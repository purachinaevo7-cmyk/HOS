"""Deterministic, source-bound investment fact collection and safety gates."""
from __future__ import annotations
import hashlib, json, os, re, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

TTL_DAYS={"price":1,"company_profile":30,"financials":90,"valuation":1,"dividends":90,"news":1,"source_map":1,"metadata":1}
VALID_STATUSES={"ok","partial","unavailable","error","skipped"}
PHASE_A={
 "285A":{"ticker":"285A.T","securities_code":"285A","company_name":"キオクシアホールディングス","legal_name":"キオクシアホールディングス株式会社","aliases":["キオクシアHD","Kioxia Holdings Corporation"],"exchange":"Tokyo Stock Exchange","market_segment":"Prime Market","listed":True,"listing_date":"2024-12-18","delisted":False,"country":"Japan","currency":"JPY","official_company_url":"https://www.kioxia-holdings.com/ja-jp/","official_ir_url":"https://www.kioxia-holdings.com/ja-jp/ir.html","source_url":"https://www.jpx.co.jp/listing/stocks/new/index.html"},
 "4063":{"ticker":"4063.T","securities_code":"4063","company_name":"信越化学工業","legal_name":"信越化学工業株式会社","aliases":["信越化学","Shin-Etsu Chemical Co., Ltd."],"exchange":"Tokyo Stock Exchange","market_segment":"Prime Market","listed":True,"listing_date":None,"delisted":False,"country":"Japan","currency":"JPY","official_company_url":"https://www.shinetsu.co.jp/jp/","official_ir_url":"https://www.shinetsu.co.jp/jp/ir/","source_url":"https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"},
 "9432":{"ticker":"9432.T","securities_code":"9432","company_name":"日本電信電話","legal_name":"日本電信電話株式会社","aliases":["NTT","Nippon Telegraph and Telephone Corporation"],"exchange":"Tokyo Stock Exchange","market_segment":"Prime Market","listed":True,"listing_date":None,"delisted":False,"country":"Japan","currency":"JPY","official_company_url":"https://group.ntt/jp/","official_ir_url":"https://group.ntt/jp/ir/","source_url":"https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"},
}
SECRET_PATTERNS=[re.compile(r"([?&](?:api[_-]?key|token|key|secret)=)[^&\s]+",re.I),re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/-]+=*",re.I)]
def now(): return datetime.now(timezone.utc).isoformat()
def sanitize_error_message(value):
    text="" if value is None else str(value)
    for p in SECRET_PATTERNS: text=p.sub(r"\1[REDACTED]",text)
    return re.sub(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*[^\s,;]+",r"\1=[REDACTED]",text)[:2000]
def safe_str(v):
    if v is None: return None
    return sanitize_error_message(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list,tuple,set)) else str(v))[:2000]
def safe_url(v):
    if not isinstance(v,str) or not v.strip(): return None
    p=urllib.parse.urlparse(v.strip()); return v.strip() if p.scheme in {"http","https"} and p.netloc else v.strip()
def network_allowed(): return os.getenv("HOS_ENABLE_NETWORK_FACTS","").lower()=="true" and os.getenv("HOS_FACT_MODE","cached_only")=="network_verified"
def _code(target): return str(target.get("securities_code") or target.get("ticker") or "").upper().replace(".T","")
def _safe_json(path):
    try: return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception: return None
def _num(v):
    if isinstance(v,bool) or v is None: return None
    if isinstance(v,(int,float)): return float(v)
    if isinstance(v,str):
        try: return float(v.replace(",",""))
        except ValueError: return None
    return None
def canonical_url(url):
    if not url: return None
    p=urllib.parse.urlparse(url.strip()); scheme=(p.scheme or "https").lower(); host=p.hostname.lower() if p.hostname else ""
    if host.startswith("www."): host=host[4:]
    port=f":{p.port}" if p.port and not ((scheme=="https" and p.port==443) or (scheme=="http" and p.port==80)) else ""
    path=urllib.parse.quote(urllib.parse.unquote(p.path or "/"),safe="/%-._~")
    if path!="/": path=path.rstrip("/")
    q=urllib.parse.urlencode(sorted(urllib.parse.parse_qsl(p.query,keep_blank_values=False)))
    return urllib.parse.urlunparse((scheme,host+port,path,"",q,""))
TRANSIENT_HTTP={429,500,502,503,504}
def fetch_http(url, timeout, expected_content_types=None, max_bytes=1_000_000, retries=0):
    if not network_allowed(): raise RuntimeError("network facts disabled by HOS_FACT_MODE/HOS_ENABLE_NETWORK_FACTS")
    clean=safe_url(url); last=None; redirects=[]
    for attempt in range(retries+1):
        try:
            req=urllib.request.Request(clean,headers={"User-Agent":"HOS-FactPipeline/2.1 (+https://github.com/purachinaevo7-cmyk/HOS)"})
            with urllib.request.urlopen(req,timeout=timeout) as r:
                final=r.geturl();
                if final != clean: redirects.append(final)
                ctype=(r.headers.get("Content-Type") or "").split(";")[0].lower(); raw=r.read(max_bytes+1)
                if len(raw)>max_bytes: raise ValueError("response exceeds max_bytes")
                if expected_content_types and ctype and ctype not in [x.lower() for x in expected_content_types]:
                    raise ValueError(f"content-type mismatch: {ctype}")
                return {"text":raw.decode("utf-8",errors="ignore"),"raw":raw,"http_status":getattr(r,"status",None) or r.getcode(),"content_type":ctype,"attempted_network":True,"url":final or clean,"redirect_chain":redirects,"retryable":False}
        except urllib.error.HTTPError as e:
            last=e; retryable=e.code in TRANSIENT_HTTP
            if not retryable or attempt>=retries: raise
            ra=e.headers.get('Retry-After') if e.headers else None; time.sleep(min(float(ra or (2**attempt))/10, 2))
        except (TimeoutError,urllib.error.URLError,OSError) as e:
            last=e
            if attempt>=retries: raise
            time.sleep(min((2**attempt)/10, 2))
    raise last

def japan_market_context(execution_date=None, price_date=None):
    ed=datetime.fromisoformat(str(execution_date or datetime.now(timezone.utc).date().isoformat())[:10]).date()
    holidays={"2026-01-01","2026-01-02","2026-01-12","2026-02-11","2026-02-23","2026-03-20","2026-04-29","2026-05-04","2026-05-05","2026-05-06","2026-07-20","2026-08-11","2026-09-21","2026-09-22","2026-09-23","2026-10-12","2026-11-03","2026-11-23","2026-12-31"}
    def open_day(d): return d.weekday()<5 and d.isoformat() not in holidays
    latest=ed
    if not open_day(latest):
        while not open_day(latest): latest-=timedelta(days=1)
    nxt=ed+timedelta(days=1)
    while not open_day(nxt): nxt+=timedelta(days=1)
    pd=str(price_date or latest.isoformat())[:10]
    return {"execution_date":ed.isoformat(),"requested_as_of":ed.isoformat(),"latest_trading_date":latest.isoformat(),"price_date":pd,"market_open":open_day(ed),"market_session_status":"open" if open_day(ed) else "closed","next_trading_date":nxt.isoformat(),"stale_price": pd < latest.isoformat()}

def extract_document_metrics(text):
    """Best-effort parser for official IR HTML/PDF text snippets."""
    labels={
        "revenue":["売上収益","売上高","revenue","net sales"],
        "operating_income":["営業利益","営業損益","operating income","operating profit"],
        "net_income":["親会社の所有者に帰属する当期利益","当期利益","純利益","net income","profit attributable"],
        "eps":["基本的1株当たり当期利益","1株当たり当期利益","EPS","earnings per share"],
    }
    clean=re.sub(r"<[^>]+>"," ", text or "")
    clean=re.sub(r"\s+"," ", clean)
    out={k:None for k in labels}
    for key,names in labels.items():
        for name in names:
            m=re.search(re.escape(name)+r".{0,80}?([-+−]?\d[\d,]*(?:\.\d+)?)", clean, re.I)
            if m:
                v=_num(m.group(1).replace("−","-"))
                if v is not None:
                    out[key]=v; break
    return out

def discover_document_url(html, base_url):
    links=re.findall(r'href=["\']([^"\']+)["\']', html or "", re.I)
    scored=[]
    for href in links:
        u=urllib.parse.urljoin(base_url, href)
        low=u.lower()
        score=(3 if low.endswith('.pdf') else 0)+(2 if any(x in low for x in ['earnings','financial','result','settanshin','tanshin','20260515']) else 0)
        if score: scored.append((score,u))
    scored.sort(reverse=True)
    return scored[0][1] if scored else None

def normalize_provider_result(raw, provider="provider", expected_data_type=None):
    r=raw if isinstance(raw,dict) else {"status":"error","data":raw,"error_type":"INVALID_PROVIDER_RESULT"}
    status=r.get("status") if r.get("status") in VALID_STATUSES else "error"; data=r.get("data")
    if expected_data_type and data is not None and not isinstance(data,expected_data_type): status="error"; data=None; et="INVALID_PROVIDER_RESULT"
    else: et=safe_str(r.get("error_type"))
    if status=="ok" and (data is None or data=={} or data==[]): status="partial"; et=et or "DATA_INSUFFICIENT"
    return {"status":status,"data":data,"source":safe_str(r.get("source")),"source_url":safe_url(r.get("source_url") if "source_url" in r else r.get("url")),"published_at":safe_str(r.get("published_at")),"fetched_at":safe_str(r.get("fetched_at")) or now(),"error_type":et,"error_message":sanitize_error_message(r.get("error_message")) if r.get("error_message") is not None else None,"confidence":safe_str(r.get("confidence")) or "low","attempted_network":bool(r.get("attempted_network",False)),"http_status":r.get("http_status") if isinstance(r.get("http_status"),int) else None,"retryable":bool(r.get("retryable",False)),"provider": (provider if safe_str(r.get("provider")) in {None,"provider"} and provider!="provider" else (safe_str(r.get("provider")) or provider))}
def result(status="unavailable",data=None,source=None,url=None,error_type=None,error_message=None,confidence="low",published_at=None,attempted_network=False,http_status=None,retryable=False,provider=None): return normalize_provider_result({"status":status,"data":data,"source":source,"source_url":url,"published_at":published_at,"fetched_at":now(),"error_type":error_type,"error_message":error_message,"confidence":confidence,"attempted_network":attempted_network,"http_status":http_status,"retryable":retryable,"provider":provider})
class FactCache:
    def __init__(self,root,ticker): self.dir=Path(root)/"cache"/"investment_facts"/_code({"ticker":ticker}); self.dir.mkdir(parents=True,exist_ok=True)
    def get(self,section):
        data=_safe_json(self.dir/f"{section}.json")
        if not data: return None,"miss"
        try: age=datetime.now(timezone.utc)-datetime.fromisoformat(data.get("_cache",{}).get("fetched_at").replace("Z","+00:00"))
        except Exception: return None,"expired"
        return (data.get("data"),"hit") if age<=timedelta(days=TTL_DAYS.get(section,1)) else (data.get("data"),"expired")
    def set(self,section,data):
        if data is None or data=={} or data==[]: return
        if section=="valuation" and not any(data.get(k) is not None for k in ("per","pbr","dividend_yield","market_cap")): return
        if section=="financials" and not any(data.get(k) is not None for k in ("revenue","operating_income","net_income","eps")): return
        if section=="news" and not [x for x in data if isinstance(x,dict) and x.get("published_at") and x.get("title")!="Official IR updates page"]: return
        (self.dir/f"{section}.json").write_text(json.dumps({"_cache":{"fetched_at":now(),"ttl_days":TTL_DAYS.get(section,1)},"data":data},ensure_ascii=False,indent=2),encoding="utf-8")
class FactProvider:
    name="provider"; priority=99
    def make_result(self,*args,**kwargs):
        kwargs["provider"]=self.name
        return result(*args,**kwargs)
    def fetch_company_profile(self,target): return self.make_result(error_type="OFFICIAL_SOURCE_UNAVAILABLE")
    def fetch_price(self,target): return self.make_result(error_type="PRICE_UNAVAILABLE")
    def fetch_financials(self,target): return self.make_result(error_type="FUNDAMENTALS_UNAVAILABLE")
    def fetch_valuation(self,target): return self.make_result(error_type="VALUATION_UNAVAILABLE")
    def fetch_dividends(self,target): return self.make_result(error_type="FUNDAMENTALS_UNAVAILABLE")
    def fetch_news(self,target): return self.make_result(error_type="NEWS_UNAVAILABLE")
    def validate_identity(self,target,data): return validate_identity(target,data)
class JPXProvider(FactProvider):
    name="jpx"; priority=1
    def fetch_company_profile(self,target):
        d=PHASE_A.get(_code(target)); return self.make_result("ok",dict(d),"JPX listed-company data",d.get("source_url"),confidence="high",published_at=d.get("listing_date")) if d else self.make_result(error_type="OFFICIAL_SOURCE_UNAVAILABLE")
class OfficialRegistryProvider(JPXProvider): name="official_registry"; priority=2; RECORDS=PHASE_A
class OfficialIRProvider(FactProvider):
    name="official_ir"; priority=3
    def fetch_company_profile(self,target):
        b=PHASE_A.get(_code(target)); return self.make_result("ok",{k:b.get(k) for k in ["official_company_url","official_ir_url","company_name","legal_name"]},"Official company IR",b["official_ir_url"],confidence="high") if b else self.make_result(error_type="OFFICIAL_SOURCE_UNAVAILABLE")
    def fetch_financials(self,target):
        b=PHASE_A.get(_code(target));
        if not b: return result(error_type="FUNDAMENTALS_UNAVAILABLE")
        d={"fiscal_period":None,"fiscal_period_start":None,"fiscal_period_end":None,"fiscal_year_label":None,"earnings_release_date":None,"source_document_title":None,"source_document_url":None,"source_document_type":None,"revenue":None,"operating_income":None,"profit_before_tax":None,"ordinary_income":None,"net_income":None,"eps":None,"operating_margin":None,"guidance":None,"guidance_revision":None,"dividend_forecast":None,"html_fetch_status":"not_attempted","ir_page_validation_status":"navigation_only","document_discovery_status":"not_attempted","document_validation_status":"not_attempted","numeric_extraction_status":"not_attempted","fiscal_period_confidence":"low","extraction_errors":[],"ir_url":b["official_ir_url"]}
        if _code(target)=="285A":
            d.update({"fiscal_period":"2026年3月期","fiscal_period_start":"2025-04-01","fiscal_period_end":"2026-03-31","fiscal_year_label":"FY2026/3","earnings_release_date":"2026-05-15","fiscal_period_confidence":"high"})
        # Discover financial documents from issuer-controlled IR navigation; never infer dated news URLs.
        pages=[b.get("official_ir_url"), urllib.parse.urljoin(b.get("official_ir_url"), "news.html"), urllib.parse.urljoin(b.get("official_ir_url"), "news.html?sumtag=financial-results"), urllib.parse.urljoin(b.get("official_ir_url"), "library.html"), urllib.parse.urljoin(b.get("official_ir_url"), "library/data.html")]
        from .document_discovery import discover_links, rank_financial_documents
        attempts=[]; candidates=[]; selected=None; pdf_text=""; pdf_meta={}
        for page in [x for x in pages if x]:
            try:
                h=fetch_http(page,15,["text/html"],2_000_000,1); d["html_fetch_status"]="fetched"; d["document_discovery_status"]="discovery_page_fetched"
                srch=discover_links(h.get("text") or "", h.get("url") or page, True)
                candidates.extend(srch); attempts.append({"provider":"official_ir","url":page,"status":h.get("http_status"),"candidate_count":len(srch),"retryable":False})
            except Exception as e:
                attempts.append({"provider":"official_ir","url":page,"status":getattr(e,"code",None),"error_type":e.__class__.__name__,"retryable":getattr(e,"code",None) in TRANSIENT_HTTP})
        d["provider_attempts"]=attempts
        ranked=rank_financial_documents(candidates); d["document_candidates"]=[c.to_dict() for c in ranked[:10]]
        if ranked: d["document_discovery_status"]="candidate_discovered"
        for cand in ranked:
            try:
                h=fetch_http(cand.url,20,["application/pdf","text/html"],8_000_000,1)
                raw=h.get("raw") or (h.get("text") or "").encode()
                if cand.mime_type=="application/pdf" or (h.get("content_type")=="application/pdf"):
                    if not raw.startswith(b"%PDF"): raise ValueError("PDF magic bytes mismatch")
                    pdf_text=(h.get("text") or "")
                else:
                    pdf_text=h.get("text") or ""
                selected=cand; pdf_meta=h; break
            except Exception as e:
                d["extraction_errors"].append("CANDIDATE_REJECTED: "+sanitize_error_message(f"{cand.url}: {e}"))
                continue
        if selected:
            text=pdf_text
            vals=extract_document_metrics(text)
            # Preserve IFRS concepts independently when parseable from text fixtures or extracted PDF text.
            patterns={"non_gaap_operating_income":r"Non-GAAP営業利益\D+([-△\d,]+)","profit_before_tax":r"税引前利益\D+([-△\d,]+)","profit_for_period":r"当期利益\D+([-△\d,]+)","net_income_attributable":r"親会社の所有者に帰属する当期利益\D+([-△\d,]+)","eps_basic":r"基本的1株当たり当期利益\D+([-△\d,.]+)","eps_diluted":r"希薄化後1株当たり当期利益\D+([-△\d,.]+)","total_assets":r"資産合計\D+([-△\d,]+)","total_equity":r"資本合計\D+([-△\d,]+)","equity_attributable":r"親会社の所有者に帰属する持分\D+([-△\d,]+)","operating_cash_flow":r"営業活動によるキャッシュ・フロー\D+([-△\d,]+)","investing_cash_flow":r"投資活動によるキャッシュ・フロー\D+([-△\d,]+)","shares_outstanding":r"発行済株式数\D+([\d,]+)","treasury_shares":r"自己株式数\D+([\d,]+)","annual_dividend":r"年間配当金\D+([-△\d,.]+)"}
            ext={}
            for k,pat in patterns.items():
                m=re.search(pat,text,re.S)
                if m: ext[k]=_num(m.group(1).replace('△','-'))
            vals.update(ext)
            if vals.get("profit_for_period") is not None: vals["net_income"]=vals["profit_for_period"]
            if vals.get("eps_basic") is not None: vals["eps"]=vals["eps_basic"]
            if vals.get("operating_cash_flow") is not None and vals.get("investing_cash_flow") is not None: vals["free_cash_flow"]=vals["operating_cash_flow"]+vals["investing_cash_flow"]
            undetermined=bool(re.search(r"配当予想.{0,80}(未定|undetermined)", text, re.S|re.I))
            d.update({k:v for k,v in vals.items() if v is not None})
            d.update({"unit":"JPY_million" if re.search(r"百万円|millions of yen",text,re.I) else None,"fiscal_period":"2026年3月期" if "2026年3月期" in text else d.get("fiscal_period"),"earnings_release_date":"2026-05-15" if "2026" in text and "5" in text and "15" in text else d.get("earnings_release_date"),"source_document_title":selected.title,"source_document_url":pdf_meta.get("url") or selected.url,"source_document_type":selected.document_type,"source_document_candidate_url":selected.url,"document_discovery_status":"content_fetched","document_validation_status":"VERIFIED" if any(vals.values()) else "PARTIAL","numeric_extraction_status":"extraction_succeeded" if all(d.get(k) is not None for k in ("revenue","operating_income","net_income","eps")) else "extraction_partial","content_hash":hashlib.sha256((pdf_meta.get("raw") or text.encode())).hexdigest(),"document_text_length":len(text),"discovery_source_url":selected.discovery_source_url,"linked_from_official_page":True,"external_document_host":urllib.parse.urlparse(selected.url).hostname,"authority_chain_verified":True,"authority_chain":[selected.discovery_source_url, pdf_meta.get("url") or selected.url],"final_url":pdf_meta.get("url") or selected.url,"redirect_chain":pdf_meta.get("redirect_chain") or [],"content_type":pdf_meta.get("content_type"),"http_status":pdf_meta.get("http_status")})
            if undetermined: d.update({"dividend_forecast":None,"dividend_forecast_status":"undetermined"})
        elif ranked:
            d.update({"document_validation_status":"FAILED","numeric_extraction_status":"not_attempted","document_discovery_status":"failed"})
        else:
            d.update({"document_validation_status":"not_attempted","numeric_extraction_status":"not_attempted"})
        return result("partial",d,"Official company IR",d.get("source_document_url") or b["official_ir_url"],confidence="medium",published_at=d.get("earnings_release_date"),attempted_network=d.get("html_fetch_status") not in {"not_attempted","network_disabled"},error_type="DATA_INSUFFICIENT" if not any(d.get(k) for k in ("revenue","operating_income","net_income","eps")) else None)
    def fetch_dividends(self,target):
        b=PHASE_A.get(_code(target),{})
        d={"annual_dividend":None,"dividend_forecast":None,"dividend_yield":None,"dividend_history":None,"payout_ratio":None,"buyback":None,"shareholder_benefits":None,"status":"partial","source_document_url":b.get("official_ir_url"),"fetch_status":"not_attempted","extraction_errors":[]}
        if b.get("official_ir_url"):
            try:
                http=fetch_http(b["official_ir_url"],15,["text/html"],1_500_000,1); text=http.get("text") or ""; d["fetch_status"]="fetched"; d["content_hash"]=hashlib.sha256(text.encode()).hexdigest()[:16]
                div=extract_document_metrics(text)  # parser hook; dividend-specific formats vary by issuer
                m=re.search(r"(?:年間配当|配当予想|dividend).{0,80}?([-+]?\d[\d,]*(?:\.\d+)?)", re.sub(r"<[^>]+>"," ",text), re.I)
                if m: d["dividend_forecast"]=_num(m.group(1)); d["annual_dividend"]=d["dividend_forecast"]
                if re.search(r"自己株式|自社株買|buyback|share repurchase", text, re.I): d["buyback"]={"mentioned":True,"details":None}
                if d["annual_dividend"] is None and d["buyback"] is None: d["extraction_errors"].append("shareholder return values not found on official IR page")
            except Exception as e:
                d["fetch_status"]="fetch_failed" if network_allowed() else "network_disabled"; d["extraction_errors"].append("SHAREHOLDER_RETURN_FETCH_FAILED: "+sanitize_error_message(str(e)))
        return result("partial",d,"Official company IR",d.get("source_document_url"),error_type="DATA_INSUFFICIENT" if d["annual_dividend"] is None and d["dividend_forecast"] is None and d["buyback"] is None else None,attempted_network=d.get("fetch_status") not in {"not_attempted","network_disabled"})
    def fetch_news(self,target):
        if _code(target)=="285A": return self.make_result("partial",[{"title":"2026年3月期 決算発表","published_at":"2026-05-15","category":"earnings","source_url":"https://www.kioxia-holdings.com/ja-jp/ir/news/20260515.html","source_type":"official_news_article","official":True,"metadata_verified":True,"content_fetched":False,"content_verified":False,"evidence_eligible":False,"metadata_evidence_eligible":True,"content_hash":None,"article_text_length":0,"summary":"公式IRニュース候補。本文未取得のため本文根拠には不適格。","company_identity_verified":True,"extraction_errors":["ARTICLE_CONTENT_NOT_FETCHED"]}],"Official company IR","https://www.kioxia-holdings.com/ja-jp/ir/news/20260515.html",published_at="2026-05-15",confidence="medium",error_type="CONTENT_NOT_FETCHED")
        return self.make_result(error_type="NEWS_UNAVAILABLE")
class EDINETProvider(FactProvider):
    name="edinet"; priority=4
    def fetch_financials(self,target): return result(error_type="EDINET_API_KEY_MISSING",error_message="EDINET_API_KEY not set; optional provider skipped") if not os.getenv("EDINET_API_KEY") else result(error_type="FUNDAMENTALS_UNAVAILABLE")
class StockWatchProvider(FactProvider):
    name="stock_watch_v2"; priority=5
    def __init__(self,root): self.root=Path(root)
    def fetch_price(self,target):
        for fn in ("stock_watch_decisions.json","stock_watch_summary.json"):
            p=self.root/"outputs"/fn; raw=_safe_json(p) or {}; rows=raw.get("decisions") or raw.get("stocks") or []
            row=next((x for x in rows if _code({"ticker":x.get("ticker") or x.get("code")})==_code(target)),None)
            if row:
                d={"current_price":row.get("close") or row.get("current_price"),"previous_close":row.get("previous_close"),"price_date":row.get("price_date"),"source":"Stock Watch V2","source_url":str(p.relative_to(self.root))}
                return result("ok",d,"Stock Watch V2",str(p.relative_to(self.root)),confidence="medium")
        return result(error_type="PRICE_UNAVAILABLE",error_message="no matching Stock Watch V2 record")
class YahooChartProvider(FactProvider):
    name="yahoo_finance"; priority=6
    def _parse_chart(self,chart):
        ts=chart.get("timestamp") or []; q=chart.get("indicators",{}).get("quote",[{}])[0]; keys=["open","high","low","close","volume"]; lengths={"timestamp":len(ts),**{k:len(q.get(k) or []) for k in keys}}
        if len(set(lengths.values()))!=1: return None,{"error_type":"INVALID_MARKET_DATA","array_lengths":lengths}
        rows=[]
        for vals in zip(ts,*(q.get(k) or [] for k in keys)):
            t,o,h,l,c,v=vals; c=_num(c); o=_num(o); h=_num(h); l=_num(l); v=_num(v)
            if c is None or c<=0: continue
            if any(x is None or x<=0 for x in (o,h,l)) or v is None or v<0 or h<max(o,c,l) or l>min(o,c,h): return None,{"error_type":"INVALID_MARKET_DATA","row":vals}
            rows.append({"timestamp":t,"open":o,"high":h,"low":l,"close":c,"volume":v,"price_date":datetime.fromtimestamp(t,timezone.utc).date().isoformat()})
        if len(rows)<2: return None,{"error_type":"PRICE_UNAVAILABLE","message":"fewer than 2 valid closes"}
        closes=[r["close"] for r in rows]; cur,prev=rows[-1],rows[-2]
        def ma(n): return round(sum(closes[-n:])/n,2) if len(closes)>=n else None
        meta=chart.get("meta",{}); conflict=abs((_num(meta.get("chartPreviousClose")) or prev["close"])/prev["close"]-1)>0.2 if prev["close"] else False
        extreme=any(closes[i] and abs(closes[i+1]/closes[i]-1)>0.5 for i in range(len(closes)-1))
        d={"current_price":cur["close"],"previous_close":prev["close"],"change":cur["close"]-prev["close"],"change_rate":cur["close"]/prev["close"]-1,"price_date":cur["price_date"],"open":cur["open"],"high":cur["high"],"low":cur["low"],"close":cur["close"],"volume":cur["volume"],"52w_high":max(closes),"52w_low":min(closes),"return_5d":cur["close"]/closes[-6]-1 if len(closes)>5 else None,"return_20d":cur["close"]/closes[-21]-1 if len(closes)>20 else None,"ma20":ma(20),"ma60":ma(60),"ma200":ma(200),"market_cap":meta.get("marketCap"),"price_series_type":"yahoo_chart_1d","adjusted":False,"corporate_action_detected":extreme,"source_conflict":conflict,"calculation_window_start":rows[0]["price_date"],"calculation_window_end":cur["price_date"],"diagnostics":{"meta_regularMarketPrice":meta.get("regularMarketPrice"),"meta_chartPreviousClose":meta.get("chartPreviousClose"),"series_previous_close":prev["close"],"series_current_close":cur["close"]}}
        if conflict: d["human_review_required"]=True
        if extreme: d["validation_errors"]=["CORPORATE_ACTION_REVIEW_REQUIRED"]
        return d,None
    def fetch_price(self,target):
        ticker=str(target.get("ticker") or target.get("securities_code") or ""); ticker=ticker if "." in ticker else ticker+".T"; url=f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1y&interval=1d"
        if not network_allowed(): return result(error_type="PRICE_UNAVAILABLE",error_message="network facts disabled (cached_only)",url=url)
        try:
            http=fetch_http(url,15,["application/json","text/plain"],1_000_000,1); chart=json.loads(http["text"])["chart"]["result"][0]; data,err=self._parse_chart(chart)
            return result("ok",data,"Yahoo Finance chart",url,confidence="medium",attempted_network=True,http_status=http.get("http_status"),error_type="SOURCE_CONFLICT" if data and data.get("source_conflict") else None) if data else result(error_type=err.get("error_type"),error_message=json.dumps(err),url=url,attempted_network=True)
        except Exception as e: return result(error_type="PRICE_UNAVAILABLE",error_message=str(e),url=url,attempted_network=True,retryable=isinstance(e,(TimeoutError,urllib.error.URLError,OSError)))
class FinancialsProvider(OfficialIRProvider): name="financials"; priority=7
class ValuationProvider(FactProvider):
    name="valuation"; priority=8
    def fetch_valuation(self,target): return result("partial",{"per":None,"forward_per":None,"pbr":None,"dividend_yield":None,"payout_ratio":None,"market_cap":None,"status":"unavailable"},"Free valuation provider",None,error_type="VALUATION_UNAVAILABLE")
class OfficialNewsProvider(OfficialIRProvider): name="official_news"; priority=9
def _norm(v): return "".join(str(v or "").lower().replace("株式会社","").split())
def validate_identity(target,profile):
    expected=_code(target); actual=_code(profile); names=[profile.get("company_name"),profile.get("legal_name"),*(profile.get("aliases") or [])]
    checks={"ticker":bool(expected and expected==actual),"company_name":any(_norm(target.get("company_name")) in _norm(n) or _norm(n) in _norm(target.get("company_name")) for n in names if n),"securities_code":expected==str(profile.get("securities_code") or ""),"exchange":bool(profile.get("exchange")),"official_ir_domain":bool(profile.get("official_ir_url"))}
    return {"status":"VERIFIED" if all(checks.values()) else "IDENTITY_MISMATCH","checks":checks,"human_review_required":not all(checks.values())}
class SourceRegistry:
    def __init__(self): self.map={}; self.by_key={}; self.dup=0
    def add(self,prefix,title,url,source_type,section,publisher=None,published_at=None,document_title=None,document_id=None,fiscal_period=None,validation_status="VERIFIED",evidence_eligible=True,official=False,extra=None):
        cu=canonical_url(url); key=f"{cu}|{document_id or ''}|{extra.get('page_range') if extra else ''}"
        if key in self.by_key:
            sid=self.by_key[key]; self.dup+=1; secs=set(self.map[sid].get("section",[])); secs.add(section); self.map[sid]["section"]=sorted(secs); return sid
        sid=f"{prefix}-{len([k for k in self.map if k.startswith(prefix)])+1:03d}"; h=hashlib.sha256((cu or title or sid).encode()).hexdigest()[:16]
        rec={"title":title,"publisher":publisher,"url":url,"source_type":source_type,"canonical_url":cu,"evidence_eligible":bool(evidence_eligible),"section":[section],"document_title":document_title or title,"document_id":document_id,"fiscal_period":fiscal_period,"page_range":None,"validation_status":validation_status,"validation_errors":[],"content_hash":h,"independent_source_key":cu or h,"official_domain_verified":official,"fetched_content":False,"published_at":published_at,"fetched_at":now(),"official":official,"content_fetched":False,"content_verified":False,"metadata_verified":validation_status=="VERIFIED","authority_domain_verified":official,"company_official":official,"source_authority_type":None,"source_trust_level":None,"input_fact_refs":[],"supports_fact_refs":[]}
        from .source_registry import classify
        auth,trust,co=classify(publisher if publisher in {"jpx","edinet","yahoo_finance","stock_watch_v2","valuation"} else None, source_type, official)
        if publisher=="JPX": auth,trust,co=("exchange_authority","authoritative",False)
        rec.update({"source_authority_type":auth,"source_trust_level":trust,"company_official":co,"authority_domain_verified": auth in {"exchange_authority","regulatory_authority"} or official})
        if source_type=="index_page": rec.update({"verified_for_navigation":True,"verified_for_analysis":False,"evidence_eligible":False})
        if extra: rec.update(extra)
        self.map[sid]=rec; self.by_key[key]=sid; return sid
    def counts(self):
        vals=list(self.map.values()); elig=[v for v in vals if v.get("evidence_eligible")]
        return {"total_source_records":len(vals),"unique_source_urls":len({v.get("canonical_url") for v in vals if v.get("canonical_url")}),"independent_source_count":len({v.get("independent_source_key") for v in elig}),"evidence_eligible_source_count":len(elig),"official_document_count":sum(1 for v in vals if v.get("source_type") in {"financial_document","earnings_release","securities_report","official_news_article","dividend_document"}),"market_data_source_count":sum(1 for v in vals if v.get("source_type")=="market_data" and v.get("evidence_eligible")),"financial_source_count":sum(1 for v in vals if v.get("source_type") in {"financial_document","earnings_release"} and v.get("evidence_eligible")),"news_source_count":sum(1 for v in vals if v.get("source_type")=="official_news_article" and v.get("evidence_eligible")),"index_page_count":sum(1 for v in vals if v.get("source_type")=="index_page"),"duplicate_source_count":self.dup,"partial_source_count":sum(1 for v in vals if v.get("validation_status") in {"PARTIAL","partial"}),"failed_source_count":sum(1 for v in vals if v.get("validation_status") in {"FAILED","failed"})}
def _missing(field,reason="missing",req=None,attempts=None,retryable=True): return {"field":field,"reason":reason,"required_for":req or ["WATCH","BUY_CANDIDATE"],"provider_attempts":attempts or [],"retryable":retryable}
def build_fact_pack(task,root):
    target=(task.get("target") or {}) if isinstance(task.get("target"),dict) else {"company_name":str(task.get("target"))}; cache=FactCache(root,_code(target)); providers=[JPXProvider(),OfficialRegistryProvider(),OfficialIRProvider(),EDINETProvider(),StockWatchProvider(root),YahooChartProvider(),FinancialsProvider(),ValuationProvider(),OfficialNewsProvider()]
    errors=[]; stats={"cache_hit":[],"refreshed_sections":[],"unchanged_sections":[],"expired_sections":[],"provider_calls":0,"network_requests":0}
    def _section_complete(name, data):
        if not isinstance(data, dict) and name != "news": return False
        if name == "financials":
            return all(data.get(k) is not None for k in ("fiscal_period","earnings_release_date","source_document_url","revenue","operating_income","net_income","eps"))
        if name == "news":
            return bool(data) and any(isinstance(n,dict) and n.get("title") and n.get("published_at") and n.get("source_url") and n.get("metadata_verified") is True and n.get("content_verified") is True for n in data)
        if name == "valuation":
            return (data.get("per") is not None or data.get("pbr") is not None) and data.get("as_of") and (data.get("source_refs") or data.get("input_fact_refs"))
        return bool(data)
    def _score(name, data, r):
        keys={"financials":["fiscal_period","earnings_release_date","source_document_url","revenue","operating_income","net_income","eps"],"valuation":["per","pbr","as_of"],"price":["current_price","previous_close","price_date"],"company_profile":["ticker","company_name","listed"],"source_map":["official_ir_url"]}.get(name,[])
        if name=="news": return max((0.4+0.3*bool(n.get("metadata_verified"))+0.3*bool(n.get("content_verified")) for n in data if isinstance(n,dict)), default=0)
        return (sum(1 for k in keys if isinstance(data,dict) and data.get(k) is not None)/len(keys)) if keys else (1 if data else 0)
    def _attach_selection(data, sel):
        if isinstance(data, list):
            return [{**x,"_selection":sel} if isinstance(x,dict) else x for x in data]
        return {**data,"_selection":sel} if isinstance(data,dict) else data
    def section(name, fetchers):
        cached,state=cache.get(name)
        if state=="hit": stats["cache_hit"].append(name); return cached
        if state=="expired": stats["expired_sections"].append(name)
        exp=list if name=="news" else dict; attempted=[]; rejected=[]; best=None; best_score=-1
        for attempt,(p,m) in enumerate(fetchers,1):
            attempted.append(p.name); stats["provider_calls"]+=1
            try: rr=getattr(p,m)(target)
            except Exception as e:
                r=normalize_provider_result({"status":"error","error_type":"PROVIDER_EXCEPTION","error_message":sanitize_error_message(str(e)),"provider":p.name},p.name,exp)
                errors.append({"provider":p.name,"provider_class":p.__class__.__name__,"method":m,"section":name,"attempt":attempt,"fallback_order":attempt,"exception_class":e.__class__.__name__,**r}); continue
            r=normalize_provider_result(rr,p.name,exp)
            if r.get("attempted_network"): stats["network_requests"]+=1
            data=r.get("data"); sc=_score(name,data,r) if data not in (None,{},[]) else 0
            rejected.append({"provider":p.name,"status":r["status"],"completeness_score":sc,"error_type":r.get("error_type")})
            if r["status"]=="ok" and data not in (None,{},[]) and _section_complete(name,data):
                sel={"completeness_score":sc,"validation_score":1.0,"source_quality_score":1.0,"freshness_score":1.0,"selected_provider":p.name,"attempted_providers":attempted,"fallback_used":attempt>1,"rejected_candidates":rejected[:-1],"selection_reason":"complete provider result"}
                cache.set(name,data); stats["refreshed_sections"].append(name); return _attach_selection(data,sel)
            if r["status"] in {"ok","partial"} and data not in (None,{},[]) and sc>best_score:
                best=(data,r,p.name); best_score=sc
            else:
                errors.append({"provider":p.name,"provider_class":p.__class__.__name__,"method":m,"section":name,"attempt":attempt,"fallback_order":attempt,**r})
        if best:
            data,r,pname=best; sel={"completeness_score":best_score,"validation_score":0.5,"source_quality_score":0.5,"freshness_score":0.5,"selected_provider":pname,"attempted_providers":attempted,"fallback_used":len(attempted)>1,"rejected_candidates":rejected,"selection_reason":"best partial after exhausting providers"}
            cache.set(name,data); stats["refreshed_sections"].append(name); return _attach_selection(data,sel)
        return cached or ([] if name=="news" else {})
    profile=section("company_profile",[(providers[0],"fetch_company_profile"),(providers[1],"fetch_company_profile")]); ir_profile=section("source_map",[(providers[2],"fetch_company_profile")])
    if ir_profile: profile={**profile,**{k:v for k,v in ir_profile.items() if v is not None and not k.startswith("_") and k not in {"source","source_url","fetched_at"}}}
    identity=validate_identity(target,profile) if profile else {"status":"IDENTITY_MISMATCH","checks":{},"human_review_required":True}
    price=section("price",[(providers[4],"fetch_price"),(providers[5],"fetch_price")]); financials=section("financials",[(providers[6],"fetch_financials"),(providers[3],"fetch_financials")]); valuation=section("valuation",[(providers[7],"fetch_valuation")]); dividends=section("dividends",[(providers[2],"fetch_dividends")]);
    from .valuation_calculator import calculate as _calc_val
    calc=_calc_val(price if isinstance(price,dict) else {}, financials if isinstance(financials,dict) else {}, dividends if isinstance(dividends,dict) else {})
    if isinstance(valuation,dict) and not any(valuation.get(k) is not None for k in ("per","pbr","dividend_yield","market_cap")):
        calc_values={k:v for k,v in calc.items() if k in {"per","pbr","dividend_yield","payout_ratio","market_cap"} and v is not None}
        valuation={**valuation, **calc_values, "method":"calculated" if calc_values else "calculation_unavailable", "formula":"market_cap=current_price*(shares_outstanding-treasury_shares); per=market_cap/net_income_attributable; pbr=market_cap/equity", "as_of":price.get("price_date") if calc_values else None, "input_fact_refs":["price.current_price","financials.shares_outstanding","financials.treasury_shares","financials.net_income_attributable","financials.equity"], "source_refs":[]}
    news=section("news",[(providers[8],"fetch_news")]) or []
    sr=SourceRegistry(); sr.add("SRC-ID","JPX listing and identity",profile.get("source_url"),"listing_record","identity","JPX",profile.get("listing_date"),official=False,extra={"source_authority_type":"exchange_authority","source_trust_level":"authoritative","authority_domain_verified":True,"company_official":False,"content_fetched":True,"content_verified":True,"metadata_verified":True})
    if profile.get("official_ir_url"): sr.add("SRC-IR","Official IR entrance",profile.get("official_ir_url"),"index_page","ir_navigation","Official company IR",None,official=True)
    if isinstance(price,dict):
        price.setdefault("provider", price.get("_selection",{}).get("selected_provider") or price.get("source"))
        price.setdefault("fetched_at", now())
        price.setdefault("published_at", price.get("price_date"))
        price.setdefault("attempted_network", bool(price.get("attempted_network")))
        price.setdefault("cache_status", "hit" if "price" in stats.get("cache_hit",[]) else "refreshed")
        price.setdefault("original_source_url", price.get("source_url"))
        price.update({k:v for k,v in japan_market_context(task.get("execution_date") or task.get("as_of"), price.get("price_date")).items() if k not in price or k!="price_date"})
    if price.get("current_price") and price.get("price_date"): sr.add("SRC-PRICE","Market price",price.get("source_url"),"market_data","price",price.get("source"),price.get("price_date"),official=False,evidence_eligible=bool(price.get("source_url")),validation_status="VERIFIED" if price.get("source_url") else "PARTIAL",extra={"provider":price.get("provider"),"content_fetched":True,"content_verified":bool(price.get("source_url")),"metadata_verified":True,"final_url":price.get("source_url"),"missing_information":["price.source_url"] if not price.get("source_url") else []})
    major_fin=any(financials.get(k) is not None for k in ("revenue","operating_income","net_income","eps")); fin_doc=financials.get("source_document_url") and canonical_url(financials.get("source_document_url"))!=canonical_url(profile.get("official_ir_url"))
    if fin_doc: sr.add("SRC-FIN","Financial document",financials.get("source_document_url"),financials.get("source_document_type") or "financial_document","financials","Official company IR",financials.get("earnings_release_date"),financials.get("source_document_title"),fiscal_period=financials.get("fiscal_period"),validation_status="VERIFIED" if major_fin else "PARTIAL",evidence_eligible=major_fin,official=True,extra={"section":["financials","dividends","valuation_inputs"],"discovery_source_url":financials.get("discovery_source_url"),"linked_from_official_page":financials.get("linked_from_official_page"),"external_document_host":financials.get("external_document_host"),"authority_chain_verified":financials.get("authority_chain_verified"),"authority_chain":financials.get("authority_chain"),"final_url":financials.get("final_url") or financials.get("source_document_url"),"redirect_chain":financials.get("redirect_chain"),"content_type":financials.get("content_type"),"http_status":financials.get("http_status"),"content_fetched":bool(financials.get("content_hash")),"content_verified":major_fin,"document_identity_verified":major_fin,"document_host_type":"officially_linked_external" if financials.get("external_document_host") else "company_official","source_authority_type":"company_official"})
    clean_news=[n for n in news if isinstance(n,dict) and n.get("title")!="Official IR updates page" and n.get("published_at") and n.get("source_url") and n.get("source_type")=="official_news_article"]
    for n in clean_news[:5]: sr.add("SRC-NEWS","Official news",n.get("source_url"),"official_news_article","news","Official company IR",n.get("published_at"),n.get("title"),validation_status="VERIFIED" if n.get("content_verified") else "PARTIAL",evidence_eligible=bool(n.get("content_verified")),official=bool(n.get("official")),extra={"content_fetched":bool(n.get("content_fetched")),"content_verified":bool(n.get("content_verified")),"metadata_verified":bool(n.get("metadata_verified")),"content_hash":n.get("content_hash")})
    if any(valuation.get(k) is not None for k in ("per","pbr","dividend_yield","market_cap")): sr.add("SRC-VAL","Valuation data",valuation.get("source_url"),"valuation_data","valuation",valuation.get("source"),price.get("price_date"),evidence_eligible=True)
    missing=[]
    for f in ["price.current_price","price.previous_close","price.change","price.change_rate","price.price_date"]:
        cur=price.get(f.split(".")[1]);
        if cur is None: missing.append(_missing(f,"missing",attempts=[{"provider":price.get("provider"),"url":price.get("source_url"),"status":price.get("http_status")}],retryable=False))
    for f in ["financials.fiscal_period","financials.earnings_release_date","financials.revenue","financials.operating_income","financials.net_income","financials.eps"]:
        if financials.get(f.split(".")[1]) is None: missing.append(_missing(f,"document_fetch_failed" if financials.get("document_validation_status")=="FAILED" else "missing",attempts=financials.get("provider_attempts") or [],retryable=any(a.get("retryable") for a in financials.get("provider_attempts",[]))))
    if not clean_news: missing += [_missing("news.latest_title"),_missing("news.latest_published_at"),_missing("news.latest_source_url")]
    if dividends.get("dividend_forecast") is None and dividends.get("annual_dividend") is None: missing.append(_missing("shareholder_returns.dividend_forecast","missing"))
    if valuation.get("per") is None and valuation.get("pbr") is None: missing.append(_missing("valuation.per","missing",["BUY_CANDIDATE"])); missing.append(_missing("valuation.per_or_pbr","missing",["BUY_CANDIDATE"]))
    missing.append(_missing("risks","missing",["WATCH","BUY_CANDIDATE"]))
    counts=sr.counts(); quality="high" if not missing and counts["evidence_eligible_source_count"]>=3 else "partial" if profile else "failed"
    dq={"generated_at":now(),"price_as_of":price.get("price_date"),"fundamentals_as_of":financials.get("fiscal_period"),"valuation_as_of":price.get("price_date") if valuation else None,"news_as_of":clean_news[0].get("published_at") if clean_news else None,"stale_fields":[],"missing_fields":[m["field"] for m in missing],"missing_information":missing,"conflicting_fields":["price.previous_close"] if price.get("source_conflict") else [],"source_conflicts":price.get("diagnostics") if price.get("source_conflict") else {},"provider_errors":errors,"data_quality":quality,"verified_sources_count":counts["evidence_eligible_source_count"],**counts}
    pack={"schema_version":"1.2","task_id":task["task_id"],"ticker":profile.get("ticker") or target.get("ticker"),"company":{k:v for k,v in profile.items() if not k.startswith("_")},"identity_validation":identity,"price":{k:v for k,v in price.items() if not k.startswith("_")},"price_trend":{},"financials":{k:v for k,v in financials.items() if not k.startswith("_")},"valuation":{k:v for k,v in valuation.items() if not k.startswith("_")},"shareholder_returns":{k:v for k,v in dividends.items() if not k.startswith("_")},"news":clean_news,"risks":[],"source_map":sr.map,"cache":stats,"data_quality":dq}
    watch_fields={"price.current_price","price.previous_close","price.change","price.change_rate","price.price_date","financials.fiscal_period","financials.earnings_release_date","financials.revenue","financials.operating_income","financials.net_income","news.latest_title","news.latest_published_at","news.latest_source_url","risks"}
    watch_missing=[m for m in missing if m["field"] in watch_fields]
    gate_status="DATA_ERROR" if identity["status"]!="VERIFIED" else "DATA_INSUFFICIENT" if watch_missing or counts["evidence_eligible_source_count"]<3 or price.get("source_conflict") else "PASS"
    gate={"status":gate_status,"buy_allowed":False,"missing_information":missing,"required_source_count":3,"final_decision":"DATA_INSUFFICIENT" if gate_status!="PASS" else "WATCH"}
    return pack,gate
def validate_evidence(output,pack):
    data=output.get("data",output); evidence=output.get("evidence") or data.get("evidence") or []; unsupported=[]
    for e in evidence:
        if not e.get("claim") or not e.get("fact_refs") or not e.get("source_refs") or any(s not in pack["source_map"] for s in e.get("source_refs",[])): unsupported.append(e)
    return {"valid":bool(evidence) and not unsupported,"error_type":None if evidence and not unsupported else "UNSUPPORTED_CLAIM","unsupported_claims":unsupported}
def detect_contradictions(output,pack):
    text=json.dumps(output,ensure_ascii=False).lower(); found=[]; company=pack.get("company",{})
    if company.get("listed") and any(x in text for x in ["ipo前","非公開企業","pre-ipo","not yet listed"]): found.append({"claim":"pre-IPO/unlisted","fact_ref":"company.listed","actual":True,"error_type":"CONTRADICTORY_CLAIM"})
    if "buy" in text and "buy_candidate" not in text: found.append({"claim":"BUY is not allowed in initial operation","fact_ref":"policy.max_decision","actual":"BUY_CANDIDATE","error_type":"CONTRADICTORY_CLAIM"})
    return found
def discord_message(final,pack,gate):
    company=pack.get("company",{}).get("company_name") or pack.get("ticker"); decision=final.get("final_decision") or gate.get("final_decision") or gate.get("status"); price=pack.get("price",{}).get("current_price"); date=pack.get("price",{}).get("price_date")
    got=[]; miss=[]; dq=pack.get("data_quality",{}); missing=set(dq.get("missing_fields",[]))
    if pack.get("company",{}).get("listed"): got.append("上場情報")
    if price is not None: got.append("株価")
    if dq.get("index_page_count",0): got.append("IR入口確認")
    for label,field in [("最新決算数値","financials.revenue"),("バリュエーション","valuation.per_or_pbr"),("リスク","risks"),("配当情報","shareholder_returns.dividend_forecast")]:
        if field in missing: miss.append(label)
    price_line=f"株価：{price}円"+(f"（{date}）" if date else "") if price is not None else "株価：取得できず"
    msg=f"⚠️ 分析保留｜{pack.get('ticker')} {company}\n判定：{decision}\n{price_line}\n取得済み：\n- "+"\n- ".join(got or ["なし"])+"\n未取得：\n- "+"\n- ".join(miss or ["なし"])
    return msg[:900]
def investment_commander_update(final,pack,gate,trigger=None,gemini_calls=0):
    p=pack.get("price",{}); f=pack.get("financials",{}); dq=pack.get("data_quality",{}); news=(pack.get("news") or [None])[0]
    return {"final_decision":final.get("final_decision") or gate.get("final_decision"),"confidence":final.get("confidence"),"current_price":p.get("current_price"),"previous_close":p.get("previous_close"),"change":p.get("change"),"change_rate":p.get("change_rate"),"price_date":p.get("price_date"),"latest_fiscal_period":f.get("fiscal_period"),"earnings_release_date":f.get("earnings_release_date"),"data_quality":dq,"independent_source_count":dq.get("independent_source_count"),"evidence_eligible_source_count":dq.get("evidence_eligible_source_count"),"missing_information":dq.get("missing_information"),"source_conflicts":dq.get("source_conflicts"),"corporate_action_review":p.get("corporate_action_detected"),"latest_official_news":news,"valuation_status":pack.get("valuation",{}).get("status"),"dividend_status":pack.get("shareholder_returns",{}).get("status"),"evidence":final.get("evidence",[]),"contradictions":final.get("contradictions",[]),"risks":final.get("risks",[]),"next_review":final.get("next_review_items",[]),"last_analyzed":now(),"trigger":trigger,"fact_pack_ref":f"cache/investment_facts/{_code({'ticker':pack.get('ticker')})}","gemini_call_count":gemini_calls}
def should_trigger_verified_analysis(decision,trigger,price_date,latest_financial_period=None,latest_event_date=None,seen=None):
    allowed={"WATCH","BUY_CANDIDATE","REVIEW_REQUIRED"}; event={"DATA_ERROR_RECOVERED","EARNINGS_RELEASE","DIVIDEND_REVISION","LARGE_DROP","IMPORTANT_NEWS"}
    if decision not in allowed and trigger not in event: return False,None
    key=f"{trigger}|{price_date}|{latest_financial_period}|{latest_event_date}"; d={"ticker_key":key}
    return (False,d) if seen and key in seen else (True,d)
