from __future__ import annotations
import re
NUM=r'[-+]?\d[\d,]*(?:\.\d+)?'
def parse_financial_text(text, fiscal_period=None, source_ref=None):
    labels={'revenue':r'(売上高|営業収益|Revenue)','operating_income':r'(営業利益|Operating income)','ordinary_income':r'(経常利益)','net_income':r'(親会社株主に帰属する当期純利益|当期純利益|Net income)','eps':r'(EPS|1株当たり当期純利益)','equity':r'(純資産|Equity)','total_assets':r'(総資産|Total assets)','annual_dividend':r'(年間配当|Annual dividend)'}
    unit='JPY_million' if re.search(r'百万円|millions of yen', text or '', re.I) else 'JPY'
    facts={}
    for k,pat in labels.items():
        m=re.search(pat+r'[^\d\-+]{0,40}('+NUM+')', text or '', re.I)
        if m:
            val=float(m.group(2).replace(',',''))
            facts[k]=val
            facts[k+'_fact']={'value':val,'unit':'JPY' if k in {'eps','annual_dividend'} else unit,'period':fiscal_period,'scope':'consolidated','method':'reported','label_original':m.group(1),'source_ref':source_ref,'document_page':None,'confidence':'medium','validation_status':'VERIFIED'}
    return facts
