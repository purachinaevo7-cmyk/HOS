AUTHORITY={
 'jpx':('exchange_authority','authoritative',False),
 'official_registry':('exchange_authority','authoritative',False),
 'official_ir':('company_official','primary',True),
 'financials':('company_official','primary',True),
 'official_news':('company_official','primary',True),
 'edinet':('regulatory_authority','authoritative',False),
 'yahoo_finance':('third_party_market_data','secondary',False),
 'stock_watch_v2':('third_party_market_data','secondary',False),
 'valuation':('derived','derived',False),
}
def classify(provider=None, source_type=None, official=False):
    if source_type == 'market_data': return ('third_party_market_data','secondary',False)
    if source_type in {'valuation_data','derived_valuation'}: return ('derived','derived',False)
    if provider in AUTHORITY: return AUTHORITY[provider]
    if official: return ('company_official','primary',True)
    return ('unknown','unknown',False)
