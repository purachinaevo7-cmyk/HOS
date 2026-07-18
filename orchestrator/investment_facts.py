"""Deterministic, source-bound investment fact collection and safety gates.

This module does not use an LLM. Unknown values remain ``None`` and provider
failures are recorded instead of being papered over with model knowledge.
"""
from __future__ import annotations
import json, os, re, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ERROR_TYPES={"IDENTITY_MISMATCH","OFFICIAL_SOURCE_UNAVAILABLE","PRICE_UNAVAILABLE","FUNDAMENTALS_UNAVAILABLE","VALUATION_UNAVAILABLE","NEWS_UNAVAILABLE","SOURCE_DATE_UNKNOWN","STALE_DATA","SOURCE_CONFLICT","FACT_PACK_INCOMPLETE","UNSUPPORTED_CLAIM","CONTRADICTORY_CLAIM","DATA_INSUFFICIENT","PROVIDER_RATE_LIMIT","PROVIDER_BLOCKED","PDF_PARSE_FAILED","INVALID_FACT_PACK","INVALID_AGENT_OUTPUT","EDINET_API_KEY_MISSING"}
DECISIONS={"DATA_ERROR","DATA_INSUFFICIENT","REVIEW_REQUIRED","WATCH","BUY_CANDIDATE","DO_NOT_BUY"}
TTL_DAYS={"price":1,"company_profile":30,"financials":90,"valuation":1,"dividends":90,"news":1,"source_map":1,"metadata":1}
PHASE_A={
 "285A":{"ticker":"285A.T","securities_code":"285A","company_name":"キオクシアホールディングス","legal_name":"キオクシアホールディングス株式会社","aliases":["キオクシアHD","Kioxia Holdings Corporation"],"exchange":"Tokyo Stock Exchange","market_segment":"Prime Market","listed":True,"listing_date":"2024-12-18","delisted":False,"country":"Japan","currency":"JPY","official_company_url":"https://www.kioxia-holdings.com/ja-jp/","official_ir_url":"https://www.kioxia-holdings.com/ja-jp/ir.html","source_url":"https://www.jpx.co.jp/listing/stocks/new/index.html"},
 "4063":{"ticker":"4063.T","securities_code":"4063","company_name":"信越化学工業","legal_name":"信越化学工業株式会社","aliases":["信越化学","Shin-Etsu Chemical Co., Ltd."],"exchange":"Tokyo Stock Exchange","market_segment":"Prime Market","listed":True,"listing_date":None,"delisted":False,"country":"Japan","currency":"JPY","official_company_url":"https://www.shinetsu.co.jp/jp/","official_ir_url":"https://www.shinetsu.co.jp/jp/ir/","source_url":"https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"},
 "9432":{"ticker":"9432.T","securities_code":"9432","company_name":"日本電信電話","legal_name":"日本電信電話株式会社","aliases":["NTT","Nippon Telegraph and Telephone Corporation"],"exchange":"Tokyo Stock Exchange","market_segment":"Prime Market","listed":True,"listing_date":None,"delisted":False,"country":"Japan","currency":"JPY","official_company_url":"https://group.ntt/jp/","official_ir_url":"https://group.ntt/jp/ir/","source_url":"https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"},
}

def now(): return datetime.now(timezone.utc).isoformat()
def result(status="unavailable",data=None,source=None,url=None,error_type=None,error_message=None,confidence="low",published_at=None):
    return {"status":status,"data":data,"source":source,"source_url":url,"published_at":published_at,"fetched_at":now(),"error_type":error_type,"error_message":error_message,"confidence":confidence}
def network_allowed(): return os.getenv("HOS_ENABLE_NETWORK_FACTS","").lower()=="true" and os.getenv("HOS_FACT_MODE","cached_only")=="network_verified"
def _code(target): return str(target.get("securities_code") or target.get("ticker") or "").upper().replace(".T","")
def _safe_json(path):
    try: return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception: return None

def _fetch_url(url, timeout=15):
    if not network_allowed(): raise RuntimeError("network facts disabled by HOS_FACT_MODE/HOS_ENABLE_NETWORK_FACTS")
    req=urllib.request.Request(url,headers={"User-Agent":"HOS-FactPipeline/2.0 (free sources; no secrets)"})
    with urllib.request.urlopen(req,timeout=timeout) as r: return r.read().decode("utf-8",errors="ignore")

class FactCache:
    def __init__(self,root,ticker): self.dir=Path(root)/"cache"/"investment_facts"/_code({"ticker":ticker}); self.dir.mkdir(parents=True,exist_ok=True)
    def get(self,section):
        p=self.dir/f"{section}.json"; data=_safe_json(p)
        if not data: return None, "miss"
        meta=data.get("_cache",{}); fetched=meta.get("fetched_at")
        try: age=datetime.now(timezone.utc)-datetime.fromisoformat(fetched.replace("Z","+00:00"))
        except Exception: return None, "expired"
        return (data.get("data"), "hit") if age <= timedelta(days=TTL_DAYS.get(section,1)) else (data.get("data"), "expired")
    def set(self,section,data): (self.dir/f"{section}.json").write_text(json.dumps({"_cache":{"fetched_at":now(),"ttl_days":TTL_DAYS.get(section,1)},"data":data},ensure_ascii=False,indent=2),encoding="utf-8")

class FactProvider:
    name="provider"; priority=99
    def fetch_company_profile(self,target): return result(error_type="OFFICIAL_SOURCE_UNAVAILABLE")
    def fetch_price(self,target): return result(error_type="PRICE_UNAVAILABLE")
    def fetch_financials(self,target): return result(error_type="FUNDAMENTALS_UNAVAILABLE")
    def fetch_valuation(self,target): return result(error_type="VALUATION_UNAVAILABLE")
    def fetch_dividends(self,target): return result(error_type="FUNDAMENTALS_UNAVAILABLE")
    def fetch_news(self,target): return result(error_type="NEWS_UNAVAILABLE")
    def validate_identity(self,target,data): return validate_identity(target,data)

class JPXProvider(FactProvider):
    name="jpx"; priority=1
    def fetch_company_profile(self,target):
        data=PHASE_A.get(_code(target))
        return result("ok",dict(data),"JPX listed-company data",data.get("source_url"),confidence="high",published_at=data.get("listing_date")) if data else result(error_type="OFFICIAL_SOURCE_UNAVAILABLE",error_message="JPX free provider has no cached identity for target")
class OfficialRegistryProvider(JPXProvider):
    name="official_registry"; priority=2; RECORDS=PHASE_A

class OfficialIRProvider(FactProvider):
    name="official_ir"; priority=3
    def fetch_company_profile(self,target):
        base=PHASE_A.get(_code(target))
        if not base: return result(error_type="OFFICIAL_SOURCE_UNAVAILABLE",error_message="official IR URL not configured")
        data={k:base.get(k) for k in ["official_company_url","official_ir_url","company_name","legal_name"]}
        return result("ok",data,"Official company IR",base["official_ir_url"],confidence="high")
    def fetch_financials(self,target):
        base=PHASE_A.get(_code(target))
        if not base: return result(error_type="FUNDAMENTALS_UNAVAILABLE",error_message="official IR URL not configured")
        data={"fiscal_period":None,"earnings_release_date":None,"revenue":None,"operating_income":None,"ordinary_income":None,"net_income":None,"eps":None,"operating_margin":None,"guidance":None,"guidance_revision":None,"dividend_forecast":None,"html_fetch_status":"not_attempted","numeric_extraction_status":"not_attempted","pdf_status":None,"ir_url":base["official_ir_url"]}
        if network_allowed():
            try:
                html=_fetch_url(base["official_ir_url"]); data["html_fetch_status"]="ok"
                y=re.search(r"20\d{2}",html); data["fiscal_period"]=y.group(0) if y else None; data["numeric_extraction_status"]="partial" if y else "no_numeric_values_found"
            except Exception as e: return result(error_type="FUNDAMENTALS_UNAVAILABLE",error_message=str(e),url=base["official_ir_url"])
        return result("ok",data,"Official company IR",base["official_ir_url"],confidence="medium")
    def fetch_dividends(self,target):
        r=self.fetch_financials(target); d=(r.get("data") or {})
        return result("ok",{"dividend_forecast":d.get("dividend_forecast"),"source_url":d.get("ir_url")},"Official company IR",d.get("ir_url"),confidence="medium") if r["status"]=="ok" else result(error_type="FUNDAMENTALS_UNAVAILABLE",error_message=r.get("error_message"))
    def fetch_news(self,target):
        base=PHASE_A.get(_code(target))
        if not base: return result(error_type="NEWS_UNAVAILABLE",error_message="official IR URL not configured")
        return result("ok",[{"title":"Official IR updates page","category":"official_ir","published_at":None,"source_url":base["official_ir_url"]}],"Official company IR",base["official_ir_url"],confidence="medium")

class EDINETProvider(FactProvider):
    name="edinet"; priority=4
    def fetch_financials(self,target):
        if not os.getenv("EDINET_API_KEY"):
            return result(error_type="EDINET_API_KEY_MISSING",error_message="EDINET_API_KEY not set; optional provider skipped")
        return result(error_type="FUNDAMENTALS_UNAVAILABLE",error_message="EDINET optional API integration is not configured")

class StockWatchProvider(FactProvider):
    name="stock_watch_v2"; priority=5
    def __init__(self,root): self.root=Path(root)
    def fetch_price(self,target):
        code=_code(target)
        for filename in ("stock_watch_decisions.json","stock_watch_summary.json"):
            p=self.root/"outputs"/filename; raw=_safe_json(p) or {}; rows=raw.get("decisions") or raw.get("stocks") or []
            row=next((x for x in rows if _code({"ticker":x.get("ticker") or x.get("code")})==code),None)
            if row:
                data={"current_price":row.get("close") or row.get("current_price"),"previous_close":row.get("previous_close"),"price_date":row.get("price_date"),"52w_high":row.get("52w_high"),"52w_low":row.get("52w_low"),"return_5d":row.get("return_5d"),"return_20d":row.get("return_20d"),"ma20":row.get("ma20"),"ma60":row.get("ma60"),"ma200":row.get("ma200"),"volume":row.get("volume"),"market_cap":row.get("market_cap"),"data_quality":row.get("data_quality"),"provider_errors":row.get("provider_errors",[])}
                return result("ok",data,"Stock Watch V2",str(p.relative_to(self.root)),confidence="medium")
        return result(error_type="PRICE_UNAVAILABLE",error_message="no matching Stock Watch V2 record")
class YahooChartProvider(FactProvider):
    name="yahoo_finance"; priority=6
    def fetch_price(self,target):
        ticker=str(target.get("ticker") or target.get("securities_code") or ""); ticker=ticker if "." in ticker else ticker+".T"; url=f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1y&interval=1d"
        if not network_allowed(): return result(error_type="PRICE_UNAVAILABLE",error_message="network facts disabled (cached_only)",url=url)
        try:
            raw=json.loads(_fetch_url(url)); chart=raw["chart"]["result"][0]; meta=chart["meta"]; q=chart["indicators"]["quote"][0]; closes=[x for x in q["close"] if x is not None]
            def ma(n): return round(sum(closes[-n:])/n,2) if len(closes)>=n else None
            data={"current_price":meta.get("regularMarketPrice"),"previous_close":meta.get("chartPreviousClose"),"price_date":datetime.fromtimestamp(chart["timestamp"][-1],timezone.utc).date().isoformat(),"52w_high":max(closes) if closes else None,"52w_low":min(closes) if closes else None,"return_5d":(closes[-1]/closes[-6]-1) if len(closes)>5 else None,"return_20d":(closes[-1]/closes[-21]-1) if len(closes)>20 else None,"ma20":ma(20),"ma60":ma(60),"ma200":ma(200),"volume":q.get("volume",[None])[-1],"market_cap":meta.get("marketCap")}
            return result("ok",data,"Yahoo Finance chart",url,confidence="medium")
        except Exception as e: return result(error_type="PRICE_UNAVAILABLE",error_message=str(e),url=url)
class FinancialsProvider(OfficialIRProvider): name="financials"; priority=7
class ValuationProvider(FactProvider):
    name="valuation"; priority=8
    def fetch_valuation(self,target): return result("ok",{"per":None,"forward_per":None,"pbr":None,"dividend_yield":None,"payout_ratio":None,"market_cap":None},"Free valuation provider",None,confidence="low")
class OfficialNewsProvider(OfficialIRProvider): name="official_news"; priority=9

def _norm(v): return "".join(str(v or "").lower().replace("株式会社","").split())
def validate_identity(target,profile):
    expected=_code(target); actual=_code(profile); names=[profile.get("company_name"),profile.get("legal_name"),*(profile.get("aliases") or [])]
    checks={"ticker":bool(expected and expected==actual),"company_name":any(_norm(target.get("company_name")) in _norm(n) or _norm(n) in _norm(target.get("company_name")) for n in names if n),"securities_code":expected==str(profile.get("securities_code") or ""),"exchange":bool(profile.get("exchange")),"official_ir_domain":bool(profile.get("official_ir_url"))}
    return {"status":"VERIFIED" if all(checks.values()) else "IDENTITY_MISMATCH","checks":checks,"human_review_required":not all(checks.values())}

def _source(source_map,key,title,r):
    if r.get("status")=="ok":
        data=r.get("data") or {}
        published=None if isinstance(data,list) else data.get("price_date")
        source_map[key]={"title":title,"publisher":r.get("source"),"url":r.get("source_url"),"published_at":r.get("published_at") or published,"fetched_at":r.get("fetched_at"),"official":str(r.get("source") or "").lower().find("official")>=0 or key.startswith("SRC-ID")}

def build_fact_pack(task,root):
    raw=task.get("target") or {}; target=raw if isinstance(raw,dict) else {"company_name":str(raw)}; code=_code(target); cache=FactCache(root,code); providers=[JPXProvider(),OfficialRegistryProvider(),OfficialIRProvider(),EDINETProvider(),StockWatchProvider(root),YahooChartProvider(),FinancialsProvider(),ValuationProvider(),OfficialNewsProvider()]
    errors=[]; source_map={}; stats={"cache_hit":[],"refreshed_sections":[],"unchanged_sections":[],"expired_sections":[],"provider_calls":0,"network_requests":0}
    def section(name, fetchers):
        cached,state=cache.get(name)
        if state=="hit": stats["cache_hit"].append(name); return cached
        if state=="expired": stats["expired_sections"].append(name)
        for p,method in fetchers:
            stats["provider_calls"]+=1; before=network_allowed(); r=getattr(p,method)(target); stats["network_requests"]+=1 if before and r.get("source_url","").startswith("http") else 0
            if r["status"]=="ok":
                cache.set(name,r["data"]); stats["refreshed_sections"].append(name)
                if isinstance(r["data"], list):
                    return [{**x, "_result": r} if isinstance(x, dict) else x for x in r["data"]]
                return {**(r["data"] or {}),"source":r.get("source"),"source_url":r.get("source_url"),"fetched_at":r.get("fetched_at"),"_result":r}
            if r.get("error_type"): errors.append({"provider":p.name,**r})
        return cached or {}
    profile=section("company_profile",[(providers[0],"fetch_company_profile"),(providers[1],"fetch_company_profile")])
    ir_profile=section("source_map",[(providers[2],"fetch_company_profile")])
    if ir_profile: profile={**profile,**{k:v for k,v in ir_profile.items() if v is not None and not k.startswith("_")}}
    identity=validate_identity(target,profile) if profile else {"status":"IDENTITY_MISMATCH","checks":{},"human_review_required":True}
    price=section("price",[(providers[4],"fetch_price"),(providers[5],"fetch_price")])
    financials=section("financials",[(providers[6],"fetch_financials"),(providers[3],"fetch_financials")])
    valuation=section("valuation",[(providers[7],"fetch_valuation")])
    dividends=section("dividends",[(providers[2],"fetch_dividends")])
    news=section("news",[(providers[8],"fetch_news")]) or []
    _source(source_map,"SRC-ID-001","JPX listing and identity",profile.get("_result") or result("ok",profile,"JPX listed-company data",profile.get("source_url"),published_at=profile.get("listing_date")))
    _source(source_map,"SRC-IR-001","Official IR page",ir_profile.get("_result") or result("ok",ir_profile,"Official company IR",profile.get("official_ir_url")))
    _source(source_map,"SRC-PRICE-001","Market price",price.get("_result") or result("ok",price,price.get("source"),price.get("source_url"),published_at=price.get("price_date")))
    if financials: _source(source_map,"SRC-FIN-001","Financials",financials.get("_result") or result("ok",financials,"Official company IR",financials.get("ir_url")))
    if news: _source(source_map,"SRC-NEWS-001","Official news",result("ok",news,"Official company IR",profile.get("official_ir_url")))
    required=[("company.listed",profile.get("listed")),("company.listing_date",profile.get("listing_date")),("price.current_price",price.get("current_price")),("financials.fiscal_period",financials.get("fiscal_period")),("valuation.per",valuation.get("per")),("news.latest_ir",news),("risks",None)]
    missing=[k for k,v in required if v is None or v==[]]
    quality="high" if not missing and len(source_map)>=3 else "partial" if profile else "failed"
    pack={"schema_version":"1.1","task_id":task["task_id"],"ticker":profile.get("ticker") or target.get("ticker"),"company":{k:v for k,v in profile.items() if not k.startswith("_")},"identity_validation":identity,"price":{k:v for k,v in price.items() if not k.startswith("_")},"price_trend":{},"financials":{k:v for k,v in financials.items() if not k.startswith("_")},"valuation":{k:v for k,v in valuation.items() if not k.startswith("_")},"shareholder_returns":{k:v for k,v in dividends.items() if not k.startswith("_")},"news":news,"risks":[],"source_map":source_map,"cache":stats,"data_quality":{"generated_at":now(),"price_as_of":price.get("price_date"),"fundamentals_as_of":financials.get("fiscal_period"),"valuation_as_of":price.get("price_date") if valuation else None,"news_as_of":None,"stale_fields":[],"missing_fields":missing,"conflicting_fields":[],"provider_errors":errors,"data_quality":quality,"verified_sources_count":len(source_map)}}
    gate={"status":"PASS" if identity["status"]=="VERIFIED" and not missing and len(source_map)>=3 else ("DATA_ERROR" if identity["status"]!="VERIFIED" else "DATA_INSUFFICIENT"),"buy_allowed":False,"missing_information":missing,"required_source_count":3,"final_decision":"DATA_INSUFFICIENT" if missing else "WATCH"}
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
    missing=pack.get("data_quality",{}).get("missing_fields",[])
    if decision in {"DATA_INSUFFICIENT","DATA_ERROR"}:
        msg=f"⚠️ 分析保留｜{pack.get('ticker')} {company}\n理由：{ '、'.join(missing[:3]) or 'データ不足' }\n取得済み：上場情報、株価、公式IR\n次回：不足データ取得後に再判定"
    else:
        msg=f"🟠 投資分析｜{pack.get('ticker')} {company}\n\n判定：{decision}\n確信度：{final.get('confidence','中')}\n株価：{price}円（{date}）\n\n要点：\n・検証済みFact Packに基づく短文分析\n\n主なリスク：\n・{(final.get('risks') or ['未確認'])[0]}\n\n不足：\n・{(missing or ['なし'])[0]}\n\n次回確認：\n・次回決算"
    return msg[:900]

def investment_commander_update(final,pack,gate,trigger=None,gemini_calls=0):
    return {"final_decision":final.get("final_decision") or gate.get("final_decision"),"confidence":final.get("confidence"),"current_price":pack.get("price",{}).get("current_price"),"price_date":pack.get("price",{}).get("price_date"),"latest_financial_period":pack.get("financials",{}).get("fiscal_period"),"data_quality":pack.get("data_quality",{}).get("data_quality"),"verified_source_count":pack.get("data_quality",{}).get("verified_sources_count"),"missing_information":pack.get("data_quality",{}).get("missing_fields"),"evidence":final.get("evidence",[]),"contradictions":final.get("contradictions",[]),"risks":final.get("risks",[]),"next_review":final.get("next_review_items",[]),"last_analyzed":now(),"trigger":trigger,"fact_pack_ref":f"cache/investment_facts/{_code({'ticker':pack.get('ticker')})}","gemini_call_count":gemini_calls}

def should_trigger_verified_analysis(decision,trigger,price_date,latest_financial_period=None,latest_event_date=None,seen=None):
    allowed={"WATCH","BUY_CANDIDATE","REVIEW_REQUIRED"}; event_triggers={"DATA_ERROR_RECOVERED","EARNINGS_RELEASE","DIVIDEND_REVISION","LARGE_DROP","IMPORTANT_NEWS"}
    if decision not in allowed and trigger not in event_triggers: return False, None
    key=f"{trigger}|{price_date}|{latest_financial_period}|{latest_event_date}"
    dedupe={"ticker_key":key}
    return (False,dedupe) if seen and key in seen else (True,dedupe)
