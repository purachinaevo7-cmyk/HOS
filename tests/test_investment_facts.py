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
