def calculate(price, financials, dividends):
    cur=price.get('current_price'); shares=financials.get('shares_outstanding'); treasury=financials.get('treasury_shares') or 0; ni=financials.get('net_income_attributable') or financials.get('net_income'); equity=financials.get('equity'); annual=dividends.get('annual_dividend') or financials.get('annual_dividend')
    out={'per':None,'pbr':None,'dividend_yield':None,'payout_ratio':None,'market_cap':None,'status':'partial','facts':{}}
    if cur and shares and shares>treasury:
        mc=cur*(shares-treasury); out['market_cap']=mc
        if ni and ni>0: out['per']=mc/ni
        if equity and equity>0: out['pbr']=mc/equity
        if annual is not None: out['dividend_yield']=annual/cur if cur else None
        if annual is not None and ni and ni>0: out['payout_ratio']=(annual*(shares-treasury))/ni
    return out
