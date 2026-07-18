import json
from orchestrator.investment_facts import build_fact_pack, validate_identity, validate_evidence, detect_contradictions, FactProvider

TASK={"task_id":"KIOXIA","target":{"ticker":"285A","company_name":"キオクシアホールディングス"}}
def test_kioxia_is_verified_and_listed(tmp_path):
    pack,gate=build_fact_pack(TASK,tmp_path)
    assert pack["identity_validation"]["status"]=="VERIFIED"
    assert pack["company"]["listed"] is True
    assert pack["company"]["listing_date"]=="2024-12-18"
    assert gate["status"]=="DATA_INSUFFICIENT" and not gate["buy_allowed"]
def test_identity_mismatch():
    got=validate_identity({"ticker":"9999","company_name":"別会社"},{"ticker":"285A.T","securities_code":"285A","company_name":"キオクシア","exchange":"TSE","official_ir_url":"https://example.jp/ir"})
    assert got["status"]=="IDENTITY_MISMATCH" and got["human_review_required"]
def test_ipo_misstatement_is_contradiction(tmp_path):
    pack,_=build_fact_pack(TASK,tmp_path)
    found=detect_contradictions({"claim":"IPO前の非公開企業"},pack)
    assert found and found[0]["error_type"]=="CONTRADICTORY_CLAIM"
def test_evidence_requires_valid_fact_and_source_refs(tmp_path):
    pack,_=build_fact_pack(TASK,tmp_path)
    assert validate_evidence({"evidence":[]},pack)["valid"] is False
    good={"evidence":[{"claim":"上場済み","fact_refs":["company.listed"],"source_refs":["SRC-ID-001"],"confidence":"high"}]}
    assert validate_evidence(good,pack)["valid"] is True
    good["evidence"][0]["source_refs"]=["UNKNOWN"]
    assert validate_evidence(good,pack)["valid"] is False
def test_stock_watch_v2_reuse(tmp_path):
    (tmp_path/"outputs").mkdir(); (tmp_path/"outputs"/"stock_watch_decisions.json").write_text(json.dumps({"decisions":[{"ticker":"285A.T","close":1800,"price_date":"2026-07-15","data_quality":"ok"}]}))
    pack,gate=build_fact_pack(TASK,tmp_path)
    assert pack["price"]["current_price"]==1800
    assert pack["price"]["source"]=="Stock Watch V2"
def test_provider_contract():
    assert set(FactProvider().fetch_price({})) >= {"status","data","source","source_url","fetched_at","error_type","error_message","confidence"}

def test_phase_a_identity_targets(tmp_path):
    for code,name in [("285A","キオクシアホールディングス"),("4063","信越化学工業"),("9432","日本電信電話")]:
        pack,gate=build_fact_pack({"task_id":code,"target":{"ticker":code,"company_name":name}},tmp_path)
        assert pack["identity_validation"]["status"]=="VERIFIED"
        assert pack["company"]["listed"] is True
        assert pack["company"].get("official_ir_url")

def test_cache_hit_and_refresh(tmp_path):
    build_fact_pack(TASK,tmp_path)
    pack,_=build_fact_pack(TASK,tmp_path)
    assert "company_profile" in pack["cache"]["cache_hit"]

def test_valuation_missing_blocks_buy_candidate(tmp_path):
    pack,gate=build_fact_pack(TASK,tmp_path)
    assert "valuation.per" in pack["data_quality"]["missing_fields"]
    assert gate["buy_allowed"] is False

def test_discord_message_length_and_trigger_dedupe(tmp_path):
    from orchestrator.investment_facts import discord_message, should_trigger_verified_analysis
    pack,gate=build_fact_pack(TASK,tmp_path)
    assert len(discord_message({},pack,gate)) <= 900
    ok,key=should_trigger_verified_analysis("WATCH","WATCH","2026-07-18","2026Q1",None,set())
    assert ok and key["ticker_key"]
    ok2,_=should_trigger_verified_analysis("NO_ALERT","NO_ALERT","2026-07-18",seen=set())
    assert not ok2

def test_provider_result_normalization_handles_bad_url_and_types():
    from orchestrator.investment_facts import normalize_provider_result
    got=normalize_provider_result({"status":"mystery","data":[],"source":123,"source_url":None,"error_message":{"token":"secret"}},"bad",dict)
    assert got["status"]=="error"
    assert got["source_url"] is None
    assert got["error_type"]=="INVALID_PROVIDER_RESULT"
    assert got["provider"]=="bad"


def test_section_survives_provider_exception_and_records_error(tmp_path, monkeypatch):
    from orchestrator import investment_facts as f
    class Boom(f.JPXProvider):
        name="boom"
        def fetch_company_profile(self,target):
            raise AttributeError("NoneType has no attribute startswith token=abc")
    monkeypatch.setattr(f, "JPXProvider", Boom)
    pack,gate=f.build_fact_pack(TASK,tmp_path)
    assert pack["company"]["listed"] is True
    err=pack["data_quality"]["provider_errors"][0]
    assert err["error_type"]=="PROVIDER_EXCEPTION"
    assert err["exception_class"]=="AttributeError"


def test_network_requests_use_attempted_network_not_source_url(tmp_path, monkeypatch):
    from orchestrator import investment_facts as f
    class NetValuation(f.ValuationProvider):
        def fetch_valuation(self,target):
            return f.result("ok",{"per":None},"test",None,attempted_network=True,provider=self.name)
    monkeypatch.setattr(f, "ValuationProvider", NetValuation)
    pack,_=f.build_fact_pack(TASK,tmp_path)
    assert pack["cache"]["network_requests"]==1

def test_yahoo_chart_provider_uses_series_previous_close_not_meta():
    from orchestrator.investment_facts import YahooChartProvider
    chart={"timestamp":[1784073600,1784160000,1784246400],"meta":{"regularMarketPrice":52110,"chartPreviousClose":2414},"indicators":{"quote":[{"open":[60000,62000,52000],"high":[61000,63000,53000],"low":[59000,61000,51000],"close":[60000,62110,52110],"volume":[1,2,3]}]}}
    data,err=YahooChartProvider()._parse_chart(chart)
    assert err is None
    assert data["current_price"]==52110
    assert data["previous_close"]==62110
    assert data["change"]==-10000
    assert round(data["change_rate"],4)==-0.1610
    assert data["source_conflict"] is True
    assert data["diagnostics"]["meta_chartPreviousClose"]==2414


def test_yahoo_chart_provider_rejects_array_length_mismatch():
    from orchestrator.investment_facts import YahooChartProvider
    chart={"timestamp":[1,2],"meta":{},"indicators":{"quote":[{"open":[1],"high":[1],"low":[1],"close":[1],"volume":[1]}]}}
    data,err=YahooChartProvider()._parse_chart(chart)
    assert data is None
    assert err["error_type"]=="INVALID_MARKET_DATA"
    assert err["array_lengths"]["timestamp"]==2


def test_285a_fixture_source_map_and_gate_semantics(tmp_path):
    pack,gate=build_fact_pack(TASK,tmp_path)
    assert pack["financials"]["document_discovery_status"] in {"discovery_not_attempted","discovery_page_fetched","candidate_discovered","content_fetched","failed"}
    assert pack["financials"].get("source_document_url") != "https://www.kioxia-holdings.com/ja-jp/ir/news/20260515.html"
    assert all(n["title"]!="Official IR updates page" and n["published_at"] for n in pack["news"])
    assert len([s for s in pack["source_map"].values() if s["source_type"]=="index_page" and s["evidence_eligible"] is False])>=1
    assert len(pack["source_map"])==pack["data_quality"]["total_source_records"]
    assert pack["data_quality"]["duplicate_source_count"]==0
    assert gate["status"]=="DATA_INSUFFICIENT"
    fields={m["field"] for m in pack["data_quality"]["missing_information"]}
    assert {"valuation.per","valuation.per_or_pbr","risks","shareholder_returns.dividend_forecast"} <= fields


def test_285a_candidate_does_not_use_inferred_news_url(tmp_path):
    pack,_=build_fact_pack(TASK,tmp_path)
    fin=pack["financials"]
    assert fin.get("source_document_url") != "https://www.kioxia-holdings.com/ja-jp/ir/news/20260515.html"
    assert fin["html_fetch_status"] in {"fetched","fetch_failed","network_disabled","not_attempted"}
    assert fin["numeric_extraction_status"] in {"parsed","no_numeric_values_found","not_attempted"}


def test_valuation_calculation_unavailable_when_inputs_missing(tmp_path):
    pack,_=build_fact_pack(TASK,tmp_path)
    assert pack["valuation"]["method"]=="calculation_unavailable"


def test_shareholder_returns_records_official_ir_attempt(tmp_path):
    pack,_=build_fact_pack(TASK,tmp_path)
    sr=pack["shareholder_returns"]
    assert sr["source_document_url"]==pack["company"]["official_ir_url"]
    assert sr["fetch_status"] in {"fetched","fetch_failed","network_disabled"}
    assert {"annual_dividend","dividend_forecast","buyback"} <= set(sr)


def test_fact_285a_regression_document_discovery_and_source_semantics(tmp_path, monkeypatch):
    from orchestrator import investment_facts as f
    html='''<html><body>
      <a href="/ja-jp/ir/news/20260515.html">決算発表ニュース</a>
      <a href="https://ssl4.eir-parts.net/doc/285A/tdnet/2815552/00.pdf">2026年3月期 決算短信 PDF</a>
    </body></html>'''
    pdf_text='''%PDF キオクシアホールディングス 285A 2026年3月期 決算短信
      売上収益 2,337,628 営業利益 870,369 親会社の所有者に帰属する当期利益 554,490
      基本的1株当たり当期利益 1024.07 当期利益 554,496 税引前利益 784,095
    '''
    def fake_fetch(url, *args, **kwargs):
        if url == 'https://www.kioxia-holdings.com/ja-jp/ir.html':
            return {"text":html,"raw":html.encode(),"http_status":200,"content_type":"text/html","url":url,"final_url":url}
        if url == 'https://ssl4.eir-parts.net/doc/285A/tdnet/2815552/00.pdf':
            return {"text":pdf_text,"raw":pdf_text.encode(),"http_status":200,"content_type":"application/pdf","url":url,"final_url":url}
        raise RuntimeError('unexpected url '+url)
    monkeypatch.setattr(f, 'network_allowed', lambda: True)
    monkeypatch.setattr(f, 'fetch_http', fake_fetch)
    pack,_=f.build_fact_pack(TASK,tmp_path)
    fin=pack['financials']
    assert fin['source_document_url']=='https://ssl4.eir-parts.net/doc/285A/tdnet/2815552/00.pdf'
    assert fin['authority_chain_verified'] is True
    assert fin['document_validation_status']=='VERIFIED'
    assert fin['revenue']==2337628
    assert fin['operating_income']==870369
    assert fin['net_income']==554490
    assert fin['eps']==1024.07
    assert not any('/news/20260515.html' == (s.get('canonical_url') or '') for s in pack['source_map'].values() if s['source_type']=='financial_document')
    assert sum(1 for s in pack['source_map'].values() if s['canonical_url']=='https://ssl4.eir-parts.net/doc/285A/tdnet/2815552/00.pdf')==1
    assert pack['data_quality']['financial_source_count']>=1


def test_fact_285a_404_is_failed_error_and_missing_attempt(tmp_path, monkeypatch):
    from orchestrator import investment_facts as f
    def fake_fetch(url, *args, **kwargs):
        if url == 'https://www.kioxia-holdings.com/ja-jp/ir.html':
            return {"text":'<a href="https://ssl4.eir-parts.net/doc/285A/tdnet/missing/00.pdf">決算短信</a>',"raw":b'',"http_status":200,"content_type":"text/html","url":url,"final_url":url}
        e=urllib.error.HTTPError(url,404,'Not Found',{},None)
        raise e
    import urllib.error
    monkeypatch.setattr(f, 'network_allowed', lambda: True)
    monkeypatch.setattr(f, 'fetch_http', fake_fetch)
    pack,_=f.build_fact_pack(TASK,tmp_path)
    fin=pack['financials']
    assert fin['document_validation_status']=='FAILED'
    assert fin['source_document_url'] is None
    assert any(e.get('http_status')==404 and e.get('provider')=='financials' for e in pack['data_quality']['provider_errors'])
    assert any(m['field']=='financials.revenue' and m['provider_attempts'] for m in pack['data_quality']['missing_information'])


def test_price_source_url_cache_source_map_and_evidence(tmp_path):
    (tmp_path/'outputs').mkdir()
    (tmp_path/'outputs'/'stock_watch_decisions.json').write_text(json.dumps({'decisions':[{'ticker':'285A.T','close':1800,'previous_close':1790,'price_date':'2026-07-15'}]}))
    pack,_=build_fact_pack(TASK,tmp_path)
    pack2,_=build_fact_pack(TASK,tmp_path)
    assert pack['price']['source_url']==pack2['price']['source_url']=='outputs/stock_watch_decisions.json'
    price_src=[s for s in pack2['source_map'].values() if s['source_type']=='market_data'][0]
    assert price_src['url']=='outputs/stock_watch_decisions.json'
    assert price_src['evidence_eligible'] is True
    from orchestrator.investment_facts import SourceRegistry
    sr=SourceRegistry(); sr.add('SRC-PRICE','Market price',None,'market_data','price','Yahoo Finance chart')
    assert list(sr.map.values())[0]['evidence_eligible'] is False
