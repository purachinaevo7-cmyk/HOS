from datetime import date
from pathlib import Path
import importlib.util

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'skills'/'investment-agent'
import sys
sys.path.insert(0, str(BASE))
from stock_analyzer import PriceRecord
from stock_watch_v2 import decide, generate_entry_levels, load_json, load_universe, render_short, v2_watchlist, write_outputs, dedupe


def fixture_policy():
    return load_json(BASE/'config'/'portfolio_policy.json')

def fixture_universe():
    return load_universe(BASE/'config'/'stock_watch_universe.json')

def test_universe_has_40_role_classified_names():
    u=fixture_universe()
    assert len(u)==40
    assert len({x['role'] for x in u})>=8
    assert sum(1 for x in u if x['owned'])==7
    assert all('sector' in x and 'valuation_policy_id' in x for x in u)

def test_v2_watchlist_migrates_to_legacy_fetcher_shape():
    w=v2_watchlist(fixture_universe())
    assert w[0].keys()=={'code','name','volatility'}
    assert len(w)==40

def test_entry_levels_are_staged_below_close():
    e1,e2,e3=generate_entry_levels(1000,-3,'medium')
    assert (e1,e2,e3)==(940,870,790)

def test_budget_unknown_blocks_buy_and_recommendation():
    u=[x for x in fixture_universe() if x['ticker']=='4063']
    prices=[PriceRecord('4063','信越化学工業',3900,4200,date(2026,7,14),'mock','large')]
    d=decide(u,prices,fixture_policy(),-0.5,date(2026,7,14))[0]
    assert d.status=='BUY_CANDIDATE'
    assert d.recommended_shares is None
    assert 'PORTFOLIO_DATA_MISSING' in d.hard_blocks
    assert 'FUNDAMENTALS_UNAVAILABLE' in d.hard_blocks

def test_large_drop_unknown_reason_requires_review():
    u=[x for x in fixture_universe() if x['ticker']=='5713']
    prices=[PriceRecord('5713','住友金属鉱山',900,1000,date(2026,7,14),'mock','high')]
    d=decide(u,prices,fixture_policy(),0.1,date(2026,7,14))[0]
    assert d.status=='REVIEW_REQUIRED'
    assert d.limit_price is None

def test_price_missing_is_data_error():
    u=[x for x in fixture_universe() if x['ticker']=='7203']
    d=decide(u,[],fixture_policy(),None,date(2026,7,14))[0]
    assert d.status=='DATA_ERROR'
    assert 'PRICE_UNAVAILABLE' in d.hard_blocks

def test_short_notification_suppresses_no_alert_only():
    u=[{**fixture_universe()[0], 'owned':False, 'dividend_focus':False, 'growth_focus':False, 'buy_enabled':True}]
    p=fixture_policy(); p['monthly_individual_stock_budget']=100000; p['annual_individual_stock_budget']=1200000; p['current_cash_balance']=1000000
    d=decide(u,[PriceRecord(u[0]['ticker'],u[0]['company_name'],1000,999,date(2026,7,14),'mock','large')],p,0,date(2026,7,14))
    assert render_short(d,date(2026,7,14),False) is None
    assert '株式監視V2' in render_short(d,date(2026,7,14),True)

def test_outputs_and_dedupe(tmp_path):
    u=[x for x in fixture_universe() if x['ticker']=='4063']
    ds=decide(u,[PriceRecord('4063','信越化学工業',3900,4200,date(2026,7,14),'mock','large')],fixture_policy(),-1,date(2026,7,14))
    write_outputs(ds,u,fixture_policy(),tmp_path)
    assert (tmp_path/'stock_watch_decisions.json').exists()
    first=dedupe(ds,tmp_path/'state.json')
    second=dedupe(ds,tmp_path/'state.json')
    assert len(first)==1 and second==[]
