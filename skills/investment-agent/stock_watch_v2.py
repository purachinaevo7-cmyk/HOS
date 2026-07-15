"""Stock Watch V2 long-term buy-candidate decision engine.

This module deliberately uses only data handed to it by the existing free
fetchers/config files. Missing fundamentals or budgets are never fabricated;
they become DATA_INSUFFICIENT or BUY_CANDIDATE hard blocks.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any

from stock_analyzer import PriceRecord, percent_change

STATUSES = ["NO_ALERT","WATCH","BUY_CANDIDATE","BUY","STRONG_BUY_CANDIDATE","HOLD","DO_NOT_BUY","REVIEW_REQUIRED","DATA_INSUFFICIENT","DATA_ERROR"]
ERROR_CODES = ["PRICE_UNAVAILABLE","PREVIOUS_CLOSE_UNAVAILABLE","INDEX_UNAVAILABLE","FUNDAMENTALS_UNAVAILABLE","VALUATION_UNAVAILABLE","PORTFOLIO_DATA_MISSING","NEWS_UNAVAILABLE","STALE_DATA","PROVIDER_RATE_LIMIT","PROVIDER_BLOCKED","INVALID_RESPONSE","DATE_MISMATCH","DUPLICATE_NOTIFICATION","CONFIGURATION_ERROR"]

@dataclass(frozen=True)
class StockDecision:
    ticker: str; company_name: str; role: str; sector: str; owned: bool
    status: str; score: int; close: float | None; previous_close: float | None
    change_percent: float | None; price_as_of: str | None
    fundamentals_as_of: str | None; valuation_as_of: str | None; news_as_of: str | None; index_as_of: str | None
    generated_at: str; data_quality: str; stale_fields: list[str]; missing_fields: list[str]
    hard_blocks: list[str]; trigger_reason: str; reasons: list[str]
    scores: dict[str, int]; entry_1: float | None; entry_2: float | None; entry_3: float | None
    recommended_shares: int | None; order_lot: int | None; limit_price: float | None; estimated_amount: float | None
    portfolio_weight_after_purchase: float | None; sector_weight_after_purchase: float | None
    monthly_budget_remaining: float | None; annual_budget_remaining: float | None; tranche_number: int | None
    remaining_tranches: int | None; valid_until: str | None; cancel_conditions: list[str]

def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))

def load_universe(path: Path) -> list[dict[str, Any]]:
    return load_json(path).get('universe', [])

def v2_watchlist(universe: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"code": u['ticker'], "name": u['company_name'], "volatility": u.get('volatility','medium')} for u in universe if u.get('watch_enabled', True)]

def generate_entry_levels(close: float | None, change_percent: float | None, volatility: str) -> tuple[float|None,float|None,float|None]:
    if close is None: return None,None,None
    # Temporary data-derived ranges: conservative staged limits below latest close.
    gap = {'large':0.04,'medium':0.06,'high':0.08}.get(volatility,0.06)
    return round(close*(1-gap),2), round(close*(1-gap-0.07),2), round(close*(1-gap-0.15),2)

def _score_price(change: float|None) -> int:
    if change is None: return 0
    if change <= -8: return 15
    if change <= -5: return 12
    if change <= -3: return 9
    if change <= -1: return 5
    return 1

def _score_role(u: dict[str, Any]) -> tuple[int,int,int,int]:
    val = 12 if u.get('dividend_focus') else 6
    qual = 15 if u.get('growth_focus') else 10 if u.get('role') in {'CORE_DIVIDEND','DEFENSIVE','FINANCIAL_INCOME'} else 7
    ret = 12 if u.get('dividend_focus') else 5
    goal = 9 if u.get('role') in {'CORE_DIVIDEND','QUALITY_GROWTH','FINANCIAL_INCOME','DEFENSIVE'} else 6
    return val,qual,ret,goal

def portfolio_weights(universe: list[dict[str,Any]], prices_by_code: dict[str, PriceRecord], policy: dict[str,Any]) -> dict[str, Any]:
    total = float(policy.get('current_financial_assets') or 0)
    by_sector = {s:0.0 for s in policy.get('max_sector_weights', {})}
    by_ticker = {}
    for u in universe:
        shares = u.get('current_shares')
        p = prices_by_code.get(str(u['ticker']))
        if shares is None or not p: continue
        value = float(shares) * p.close
        by_ticker[str(u['ticker'])] = value / total if total else None
        by_sector[u.get('sector','未分類')] = by_sector.get(u.get('sector','未分類'), 0.0) + (value / total if total else 0.0)
    return {'total_assets': total or None, 'by_sector': by_sector, 'by_ticker': by_ticker}

def decide(universe: list[dict[str,Any]], prices: list[PriceRecord], policy: dict[str,Any], topix_change_percent: float|None, trade_date: date) -> list[StockDecision]:
    now = datetime.now(timezone.utc).isoformat()
    prices_by_code = {p.code:p for p in prices}
    weights = portfolio_weights(universe, prices_by_code, policy)
    decisions=[]
    for u in universe:
        if not u.get('watch_enabled', True): continue
        p = prices_by_code.get(str(u['ticker']))
        missing=[]; stale=[]; hard=[]; reasons=[]
        if not p:
            missing += ['price','previous_close']; hard.append('PRICE_UNAVAILABLE')
            status='DATA_ERROR'; change=None; close=None; prev=None; price_as_of=None
        else:
            close,prev,price_as_of=p.close,p.previous_close,p.price_date.isoformat(); change=round(percent_change(close,prev),2)
            if p.price_date != trade_date: stale.append('price'); hard.append('STALE_DATA')
            reasons.append(f"前日比 {change:.2f}%（TOPIXは補助指標 {topix_change_percent if topix_change_percent is not None else '取得不能'}）")
        # Free fetcher has no fundamentals/news valuation feed; mark explicitly.
        missing += ['fundamentals','valuation','news']
        hard += ['FUNDAMENTALS_UNAVAILABLE','VALUATION_UNAVAILABLE','NEWS_UNAVAILABLE']
        if policy.get('monthly_individual_stock_budget') is None or policy.get('annual_individual_stock_budget') is None or policy.get('current_cash_balance') is None:
            hard.append('PORTFOLIO_DATA_MISSING')
        if not u.get('buy_enabled', True): hard.append('CONFIGURATION_ERROR'); reasons.append('WATCH_ONLYまたはbuy_enabled=false')
        sector=u.get('sector','未分類'); sw=weights['by_sector'].get(sector)
        sector_max = policy.get('max_sector_weights',{}).get(sector)
        if sector_max is not None and sw is not None and sw >= sector_max: hard.append('SECTOR_LIMIT_EXCEEDED')
        tw=weights['by_ticker'].get(str(u['ticker']))
        if tw is not None and tw >= float(u.get('max_weight_percent') or policy.get('max_single_stock_weight',0.08)): hard.append('SINGLE_STOCK_LIMIT_EXCEEDED')
        val,qual,ret,goal=_score_role(u); price_score=_score_price(change); portfolio_score=5 if 'PORTFOLIO_DATA_MISSING' in hard else 12
        scores={'valuation_score':val,'quality_score':qual,'shareholder_return_score':ret,'price_opportunity_score':price_score,'portfolio_fit_score':portfolio_score,'goal_alignment_score':goal}
        total=sum(scores.values())
        e1,e2,e3=generate_entry_levels(close, change, u.get('volatility','medium'))
        if p is None: status='DATA_ERROR'
        elif change is not None and change <= -8 and 'NEWS_UNAVAILABLE' in hard: status='REVIEW_REQUIRED'; reasons.append('大幅下落だが下落理由未確認のため購入禁止')
        elif u.get('owned') and total < 65: status='HOLD'
        elif total >= 65 or (change is not None and change <= -5 and total >= 45): status='BUY_CANDIDATE'
        elif total >= 50 or (e1 and close <= e1*1.02): status='WATCH'
        else: status='NO_ALERT'
        if {'FUNDAMENTALS_UNAVAILABLE','VALUATION_UNAVAILABLE'} & set(hard) and status in {'BUY','STRONG_BUY_CANDIDATE'}: status='BUY_CANDIDATE'
        # Budget unknown blocks BUY; therefore recommendations remain null.
        decisions.append(StockDecision(str(u['ticker']),u['company_name'],u['role'],sector,bool(u.get('owned')),status,int(total),close,prev,change,price_as_of,None,None,None,trade_date.isoformat() if topix_change_percent is not None else None,now,'partial' if missing else 'ok',stale,sorted(set(missing)),sorted(set(hard)),(';'.join(reasons[:2]) or 'データ不足'),reasons,scores,e1,e2,e3,None,u.get('minimum_order_lot'),None,None,None,None,policy.get('monthly_individual_stock_budget'),policy.get('annual_individual_stock_budget'),None,None,None,['予算・現金残高未設定','決算/業績/ニュース未確認','業種または単一銘柄上限超過']))
    return decisions

def dedupe(decisions: list[StockDecision], state_path: Path, threshold: float=1.0) -> list[StockDecision]:
    old={}
    if state_path.exists():
        try: old=json.loads(state_path.read_text(encoding='utf-8'))
        except Exception: old={}
    send=[]; new={}
    for d in decisions:
        key=f"{d.generated_at[:10]}:{d.ticker}:{d.status}:{d.score}:{d.trigger_reason}"
        old_price=old.get(d.ticker,{}).get('close')
        changed = old.get(d.ticker,{}).get('status') != d.status or (d.close is not None and old_price is not None and abs((d.close-old_price)/old_price*100) >= threshold)
        if d.status not in {'NO_ALERT','HOLD'} and changed: send.append(d)
        new[d.ticker]={'status':d.status,'close':d.close,'score':d.score,'key':key}
    state_path.parent.mkdir(parents=True,exist_ok=True)
    state_path.write_text(json.dumps(new,ensure_ascii=False,indent=2),encoding='utf-8')
    return send

def write_outputs(decisions: list[StockDecision], universe: list[dict[str,Any]], policy: dict[str,Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    data=[asdict(d) for d in decisions]
    output_dir.joinpath('stock_watch_decisions.json').write_text(json.dumps({'version':2,'decisions':data},ensure_ascii=False,indent=2),encoding='utf-8')
    counts={s:sum(1 for d in decisions if d.status==s) for s in STATUSES}
    output_dir.joinpath('stock_watch_summary.json').write_text(json.dumps({'version':2,'status_counts':counts,'watchlist_count':len(universe),'generated_at':datetime.now(timezone.utc).isoformat()},ensure_ascii=False,indent=2),encoding='utf-8')
    role_counts={}
    for u in universe: role_counts[u['role']]=role_counts.get(u['role'],0)+1
    progress={'current_financial_assets':policy.get('current_financial_assets'),'target_financial_assets':policy.get('target_asset_value_at_age_60'),'target_age':policy.get('target_age'),'years_remaining':None,'current_annual_dividend':None,'target_annual_dividend':policy.get('target_annual_dividend'),'monthly_investment':policy.get('monthly_index_investment'),'estimated_required_return':None,'projected_asset_at_60':None,'projected_dividend_at_60':None,'goal_gap':None,'portfolio_sector_weights':{},'watchlist_role_weights':role_counts,'cash_ratio':None,'last_updated':datetime.now(timezone.utc).isoformat(),'missing_inputs':['current_annual_dividend','monthly_individual_stock_budget','annual_individual_stock_budget','current_cash_balance','current_shares','average_cost']}
    output_dir.joinpath('portfolio_goal_progress.json').write_text(json.dumps(progress,ensure_ascii=False,indent=2),encoding='utf-8')

def render_short(decisions: list[StockDecision], trade_date: date, notify_no_alert: bool=False) -> str | None:
    important=[d for d in decisions if d.status in {'WATCH','BUY_CANDIDATE','BUY','STRONG_BUY_CANDIDATE','REVIEW_REQUIRED','DATA_ERROR'}]
    if not important and not notify_no_alert: return None
    counts={s:sum(1 for d in decisions if d.status==s) for s in STATUSES}
    lines=[f"📊 株式監視V2｜{trade_date.strftime('%Y/%m/%d')}","",f"買い：{counts['BUY']}",f"買い候補：{counts['BUY_CANDIDATE']+counts['STRONG_BUY_CANDIDATE']}",f"接近：{counts['WATCH']}",f"異常：{counts['DATA_ERROR']+counts['REVIEW_REQUIRED']}"]
    for d in important[:8]:
        if d.status=='WATCH': lines.append(f"・🟡 {d.ticker} {d.company_name}: 買い水準接近 / score {d.score}")
        elif d.status in {'BUY_CANDIDATE','STRONG_BUY_CANDIDATE'}: lines.append(f"・🟠 {d.ticker} {d.company_name}: {d.status} / score {d.score} / 予算未設定ならBUY不可")
        elif d.status=='REVIEW_REQUIRED': lines.append(f"・⚠️ {d.ticker} {d.company_name}: 下落理由確認まで購入禁止")
        elif d.status=='DATA_ERROR': lines.append(f"・⚠️ {d.ticker} {d.company_name}: データ取得異常")
    lines.append('結論：BUYは予算・業績・ニュース確認後のみ。実発注は行いません。')
    return '\n'.join(lines)[:800]
