"""Deterministic, source-bound investment fact collection and safety gates.

This module deliberately does not use an LLM. Unknown values remain ``None`` and
provider failures are recorded instead of being papered over with model knowledge.
"""
from __future__ import annotations
import json, os, urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ERROR_TYPES={"IDENTITY_MISMATCH","OFFICIAL_SOURCE_UNAVAILABLE","PRICE_UNAVAILABLE","FUNDAMENTALS_UNAVAILABLE","VALUATION_UNAVAILABLE","NEWS_UNAVAILABLE","SOURCE_DATE_UNKNOWN","STALE_DATA","SOURCE_CONFLICT","FACT_PACK_INCOMPLETE","UNSUPPORTED_CLAIM","CONTRADICTORY_CLAIM","DATA_INSUFFICIENT","PROVIDER_RATE_LIMIT","PROVIDER_BLOCKED","PDF_PARSE_FAILED","INVALID_FACT_PACK","INVALID_AGENT_OUTPUT"}
PRIORITY={"official_ir":1,"jpx":2,"edinet":3,"official_news":4,"market_data":5,"yahoo_finance":6,"trusted_news":7,"other":8}

def now(): return datetime.now(timezone.utc).isoformat()
def result(status="unavailable",data=None,source=None,url=None,error_type=None,error_message=None,confidence="low"):
    return {"status":status,"data":data,"source":source,"source_url":url,"fetched_at":now(),"error_type":error_type,"error_message":error_message,"confidence":confidence}

class FactProvider:
    name="provider"; priority=99
    def fetch_company_profile(self,target): return result(error_type="OFFICIAL_SOURCE_UNAVAILABLE")
    def fetch_price(self,target): return result(error_type="PRICE_UNAVAILABLE")
    def fetch_price_history(self,target): return result(error_type="PRICE_UNAVAILABLE")
    def fetch_financials(self,target): return result(error_type="FUNDAMENTALS_UNAVAILABLE")
    def fetch_valuation(self,target): return result(error_type="VALUATION_UNAVAILABLE")
    def fetch_dividends(self,target): return result(error_type="FUNDAMENTALS_UNAVAILABLE")
    def fetch_news(self,target): return result(error_type="NEWS_UNAVAILABLE")
    def validate_identity(self,target,data): return validate_identity(target,data)

class OfficialRegistryProvider(FactProvider):
    """Small audited identity registry; facts include their official references."""
    name="official_registry"; priority=1
    RECORDS={"285A":{"ticker":"285A.T","securities_code":"285A","company_name":"キオクシアホールディングス","legal_name":"キオクシアホールディングス株式会社","aliases":["キオクシアHD","Kioxia Holdings Corporation"],"exchange":"Tokyo Stock Exchange","market_segment":"Prime Market","listed":True,"listing_date":"2024-12-18","delisted":False,"country":"Japan","currency":"JPY","official_company_url":"https://www.kioxia-holdings.com/ja-jp/","official_ir_url":"https://www.kioxia-holdings.com/ja-jp/ir.html","source_url":"https://www.jpx.co.jp/listing/stocks/new/index.html"}}
    def fetch_company_profile(self,target):
        code=str(target.get("securities_code") or target.get("ticker") or "").upper().replace(".T","")
        data=self.RECORDS.get(code)
        return result("ok",dict(data),"JPX / official company",data.get("source_url"),confidence="high") if data else result(error_type="OFFICIAL_SOURCE_UNAVAILABLE",error_message="identity is not in audited registry")

class StockWatchProvider(FactProvider):
    name="stock_watch_v2"; priority=5
    def __init__(self,root): self.root=Path(root)
    def fetch_price(self,target):
        code=str(target.get("ticker") or target.get("securities_code") or "").replace(".T","")
        for filename in ("stock_watch_decisions.json","stock_watch_summary.json"):
            p=self.root/"outputs"/filename
            if not p.exists(): continue
            raw=json.loads(p.read_text(encoding="utf-8")); rows=raw.get("decisions") or raw.get("stocks") or []
            row=next((x for x in rows if str(x.get("ticker") or x.get("code") or "").replace(".T","")==code),None)
            if row:
                data={"current_price":row.get("close") or row.get("current_price"),"previous_close":row.get("previous_close"),"price_date":row.get("price_date"),"52w_high":row.get("52w_high"),"52w_low":row.get("52w_low"),"data_quality":row.get("data_quality"),"provider_errors":row.get("provider_errors",[])}
                return result("ok",data,"Stock Watch V2",str(p.relative_to(self.root)),confidence="medium")
        return result(error_type="PRICE_UNAVAILABLE",error_message="no matching Stock Watch V2 record")

class YahooChartProvider(FactProvider):
    name="yahoo_finance"; priority=6
    def fetch_price(self,target):
        ticker=str(target.get("ticker") or ""); ticker=ticker if "." in ticker else ticker+".T"
        url=f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1y&interval=1d"
        if os.getenv("HOS_ENABLE_NETWORK_FACTS","").lower()!="true": return result(error_type="PRICE_UNAVAILABLE",error_message="network facts disabled (set HOS_ENABLE_NETWORK_FACTS=true)")
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"HOS-FactPipeline/1.0"}); raw=json.loads(urllib.request.urlopen(req,timeout=15).read()); chart=raw["chart"]["result"][0]; meta=chart["meta"]; q=chart["indicators"]["quote"][0]; closes=[x for x in q["close"] if x is not None]
            data={"current_price":meta.get("regularMarketPrice"),"previous_close":meta.get("chartPreviousClose"),"open":q["open"][-1],"high":q["high"][-1],"low":q["low"][-1],"volume":q["volume"][-1],"price_date":datetime.fromtimestamp(chart["timestamp"][-1],timezone.utc).date().isoformat(),"52w_high":max(closes) if closes else None,"52w_low":min(closes) if closes else None}
            return result("ok",data,"Yahoo Finance chart",url,confidence="medium")
        except Exception as e: return result(error_type="PRICE_UNAVAILABLE",error_message=str(e),url=url)

def _norm(v): return "".join(str(v or "").lower().replace("株式会社","").split())
def validate_identity(target,profile):
    expected_code=str(target.get("securities_code") or target.get("ticker") or "").replace(".T",""); actual=str(profile.get("securities_code") or profile.get("ticker") or "").replace(".T","")
    names=[profile.get("company_name"),profile.get("legal_name"),*(profile.get("aliases") or [])]
    checks={"ticker":bool(expected_code and expected_code==actual),"company_name":any(_norm(target.get("company_name"))==_norm(n) for n in names),"securities_code":expected_code==str(profile.get("securities_code") or ""),"exchange":bool(profile.get("exchange")),"official_ir_domain":bool(profile.get("official_ir_url"))}
    return {"status":"VERIFIED" if all(checks.values()) else "IDENTITY_MISMATCH","checks":checks,"human_review_required":not all(checks.values())}

def build_fact_pack(task,root):
    raw_target=task.get("target") or {}; target=raw_target if isinstance(raw_target,dict) else {"company_name":str(raw_target)}; providers=[OfficialRegistryProvider(),StockWatchProvider(root),YahooChartProvider()]; errors=[]; source_map={}; profile={}; price={}
    for p in providers:
        r=p.fetch_company_profile(target)
        if r["status"]=="ok": profile=r["data"]; source_map["SRC-ID-001"]={"title":"Official listing and company identity","publisher":r["source"],"url":r["source_url"],"published_at":profile.get("listing_date"),"fetched_at":r["fetched_at"],"official":True}; break
        if r.get("error_type"): errors.append({"provider":p.name,**r})
    identity=validate_identity(target,profile) if profile else {"status":"IDENTITY_MISMATCH","checks":{},"human_review_required":True}
    for p in providers:
        r=p.fetch_price(target)
        if r["status"]=="ok" and r.get("data",{}).get("current_price") is not None:
            price=r["data"]; price.update({"source":r["source"],"source_url":r["source_url"],"fetched_at":r["fetched_at"],"stale":False}); source_map["SRC-PRICE-001"]={"title":"Market price","publisher":r["source"],"url":r["source_url"],"published_at":price.get("price_date"),"fetched_at":r["fetched_at"],"official":False}; break
        if r.get("error_type"): errors.append({"provider":p.name,**r})
    sections={"price":price,"price_trend":{},"financials":{},"valuation":{},"shareholder_returns":{},"news":[],"risks":[]}
    required=[("company.listed",profile.get("listed")),("company.listing_date",profile.get("listing_date")),("price.current_price",price.get("current_price")),("financials.fiscal_period",None),("news.latest_ir",None),("risks",None)]
    missing=[k for k,v in required if v is None or v==[]]
    quality="high" if not missing and len(source_map)>=3 else "partial" if profile else "failed"
    pack={"schema_version":"1.0","task_id":task["task_id"],"ticker":profile.get("ticker") or target.get("ticker"),"company":profile,"identity_validation":identity,**sections,"source_map":source_map,"data_quality":{"generated_at":now(),"price_as_of":price.get("price_date"),"fundamentals_as_of":None,"valuation_as_of":None,"news_as_of":None,"stale_fields":[],"missing_fields":missing,"conflicting_fields":[],"provider_errors":errors,"data_quality":quality,"verified_sources_count":len(source_map)}}
    gate={"status":"PASS" if identity["status"]=="VERIFIED" and not missing and len(source_map)>=3 else ("DATA_ERROR" if identity["status"]!="VERIFIED" else "DATA_INSUFFICIENT"),"buy_allowed":False,"missing_information":missing,"required_source_count":3}
    return pack,gate

def validate_evidence(output,pack):
    data=output.get("data",output); evidence=output.get("evidence") or data.get("evidence") or []; unsupported=[]
    for e in evidence:
        if not e.get("claim") or not e.get("fact_refs") or not e.get("source_refs") or any(s not in pack["source_map"] for s in e.get("source_refs",[])): unsupported.append(e)
    return {"valid":bool(evidence) and not unsupported,"error_type":None if evidence and not unsupported else "UNSUPPORTED_CLAIM","unsupported_claims":unsupported}

def detect_contradictions(output,pack):
    text=json.dumps(output,ensure_ascii=False).lower(); found=[]; company=pack.get("company",{})
    if company.get("listed") and any(x in text for x in ["ipo前","非公開企業","pre-ipo","not yet listed"]): found.append({"claim":"pre-IPO/unlisted","fact_ref":"company.listed","actual":True,"error_type":"CONTRADICTORY_CLAIM"})
    return found
