const IC_KEY='hosInvestmentCommander.v1';
const IC_META_KEY='hosInvestmentCommander.meta.v1';
const THEMES=['é«˜é…å½“','å¢—é…','æ ªä¸»å„ªå¾…','AI','åŠå°Žä½“','ãƒ‡ãƒ¼ã‚¿ã‚»ãƒ³ã‚¿ãƒ¼','éŠ€è¡Œ','ä¿é™º','å•†ç¤¾','å†…éœ€','æˆé•·æ ª','å‰²å®‰æ ª','æš´è½æ‹¾ã„','é•·æœŸä¿æœ‰','è¶£å‘³æž '];
const PURPOSES=['é…å½“','å¢—é…','å„ªå¾…','æˆé•·','å‰²å®‰','å®‰å®š','ãƒ†ãƒ¼ãƒžæŠ•è³‡','æš´è½æ‹¾ã„','è¶£å‘³','é•·æœŸä¿æœ‰'];
const STATUSES=['ä»Šé€±ã®å€™è£œ','æœ€å„ªå…ˆèª¿æŸ»','è³¼å…¥å€™è£œ','è²·å€¤å¾…ã¡','é•·æœŸç›£è¦–','æ±ºç®—å¾…ã¡','ä¿æœ‰ä¸­','æ…Žé‡','è¦‹é€ã‚Š','åˆ†æžçµ‚äº†'];
const COMPANY_RANKS=['S','A','B','C','D'];
const PRICE_RANKS=['å‰²å®‰','ã‚„ã‚„å‰²å®‰','å¦¥å½“','ã‚„ã‚„å‰²é«˜','å‰²é«˜','è©•ä¾¡ä¸èƒ½'];
const OVERALL_DECISIONS=['æœ€å„ªå…ˆã§èª¿æŸ»','è³¼å…¥å€™è£œ','æ¡ä»¶ä»˜ãè³¼å…¥å€™è£œ','è²·å€¤å¾…ã¡','æ±ºç®—ç¢ºèªå¾…ã¡','é•·æœŸç›£è¦–','æ…Žé‡','è¦‹é€ã‚Š','è©•ä¾¡æœªå®Œäº†'];
const INVESTMENT_ACTIONS=['ä»Šã™ãèª¿æŸ»','è²·å€¤åˆ°é”æ™‚ã«å†ç¢ºèª','æ±ºç®—å¾Œã«å†è©•ä¾¡','æ ªä¾¡èª¿æ•´å¾…ã¡','ç¶™ç¶šä¿æœ‰','æ–°è¦è³¼å…¥ã¯è¦‹é€ã‚Š','æƒ…å ±ä¸è¶³ã®ãŸã‚ä¿ç•™'];
const RISKS=['æ¥­ç¸¾æ‚ªåŒ–','æ¸›é…æ‡¸å¿µ','å„ªå¾…å»ƒæ­¢æ‡¸å¿µ','å‰²é«˜','æ™¯æ°—æ•æ„Ÿ','å•†å“å¸‚æ³ä¾å­˜','é‡‘åˆ©å½±éŸ¿','ç‚ºæ›¿å½±éŸ¿','è¦åˆ¶ãƒªã‚¹ã‚¯','ç«¶äº‰æ¿€åŒ–','è²¡å‹™æ‚ªåŒ–','ã‚¬ãƒãƒŠãƒ³ã‚¹æ‡¸å¿µ','æ ªä¾¡æ€¥é¨°å¾Œ','æƒ…å ±ä¸è¶³','æ±ºç®—ç¢ºèªå‰','ãƒ†ãƒ¼ãƒžéŽç†±','æµå‹•æ€§ä½Žã„','ãã®ä»–'];
const SCORE_MAX={dividend:15,shareholderReturn:10,growth:15,financialHealth:15,valuation:15,competitiveAdvantage:10,theme:10,priceLevel:5,userFit:5};
const SCORE_LABELS={dividend:'é…å½“é­…åŠ›',shareholderReturn:'å¢—é…ãƒ»é‚„å…ƒå§¿å‹¢',growth:'åˆ©ç›Šæˆé•·æ€§',financialHealth:'è²¡å‹™å¥å…¨æ€§',valuation:'å‰²å®‰åº¦',competitiveAdvantage:'ç«¶äº‰å„ªä½æ€§',theme:'æŠ•è³‡ãƒ†ãƒ¼ãƒž',priceLevel:'æ ªä¾¡æ°´æº–',userFit:'ä¸–å¸¯æ–¹é‡ã¨ã®é©åˆ'};
function n(v){return v===''||v==null?null:Number(v)} function arr(v){return Array.isArray(v)?v:(v?String(v).split(/[;ã€|]/).map(s=>s.trim()).filter(Boolean):[])}
function yen(v){return v==null||Number.isNaN(v)?'æœªå–å¾—':Number(v).toLocaleString('ja-JP')} function pct(v){return v==null||Number.isNaN(v)?'æœªå–å¾—':`${Number(v).toFixed(1)}%`} function txt(v){return v==null||v===''?'æœªå–å¾—':String(v)}
function today(){return new Date().toISOString().slice(0,10)}
function totalScore(scores={}){return Object.keys(SCORE_MAX).reduce((s,k)=>s+Math.min(Math.max(Number(scores[k]??0),0),SCORE_MAX[k]),0)}
function clamp100(v){return Math.min(Math.max(Number(v??0),0),100)}
function defaultCompanyRank(score){if(score>=90)return 'S'; if(score>=75)return 'A'; if(score>=60)return 'B'; if(score>=40)return 'C'; return 'D'}
function defaultPriceRank(score){if(score>=80)return 'å‰²å®‰'; if(score>=65)return 'ã‚„ã‚„å‰²å®‰'; if(score>=45)return 'å¦¥å½“'; if(score>=25)return 'ã‚„ã‚„å‰²é«˜'; if(score>0)return 'å‰²é«˜'; return 'è©•ä¾¡ä¸èƒ½'}
function calcOverallScore(companyScore,priceScore){return Math.round(clamp100(companyScore)*0.6+clamp100(priceScore)*0.4)}
function autoDecision(stock){const missing=!stock.scores||Object.keys(SCORE_MAX).some(k=>stock.scores[k]==null); if(missing)return 'è©•ä¾¡æœªå®Œäº†'; const s=stock.hiScore??totalScore(stock.scores); if(s>=90)return 'æœ€å„ªå…ˆã§èª¿æŸ»'; if(s>=80)return 'æœ‰åŠ›å€™è£œ'; if(s>=70)return 'æ¡ä»¶ä»˜ãå€™è£œ'; if(s>=60)return 'æ…Žé‡ã«ç¢ºèª'; return 'å„ªå…ˆåº¦ä½Ž'}
function targetDiff(stock){const p=n(stock.marketData?.price), t=n(stock.decision?.targetPrice); return p==null||t==null?null:p-t}
function targetDiffRate(stock){const d=targetDiff(stock), t=n(stock.decision?.targetPrice); return d==null||!t?null:d/t*100}
function targetStatus(stock){const r=targetDiffRate(stock); if(r==null)return 'æœªå–å¾—'; if(r<=0)return 'å¸Œæœ›æ ªä¾¡åˆ°é”'; if(r<=3)return 'ç›®å‰'; if(r<=10)return 'æŽ¥è¿‘ä¸­'; return 'å¾…æ©Ÿ'}
function overdue(stock,base=new Date()){return stock.nextReviewAt && new Date(stock.nextReviewAt)<new Date(base.toISOString().slice(0,10))}
function normalizeStock(raw){const md=raw.marketData||{}; const scores=raw.scores||{}; const dec=raw.decision||{}; const ceRaw=raw.companyEvaluation||{}; const peRaw=raw.priceEvaluation||{}; const oeRaw=raw.overallEvaluation||{}; const price=n(md.price??raw['ç¾åœ¨æ ªä¾¡']); const high52=n(md.high52Week??raw['52é€±é«˜å€¤']); const ceScore=n(ceRaw.score??raw['ä¼šç¤¾è©•ä¾¡ã‚¹ã‚³ã‚¢']); const peScore=n(peRaw.score??raw['æ ªä¾¡è©•ä¾¡ã‚¹ã‚³ã‚¢']); const overallManual=oeRaw.score??raw['ç·åˆã‚¹ã‚³ã‚¢']??raw.hiScore??raw['HIã‚¹ã‚³ã‚¢']; const s={code:String(raw.code||raw['éŠ˜æŸ„ã‚³ãƒ¼ãƒ‰']||'').trim(),name:raw.name||raw['éŠ˜æŸ„å']||'',market:raw.market||raw['å¸‚å ´']||'',sector:raw.sector||raw['æ¥­ç¨®']||'',companySummary:raw.companySummary||'',revenueSource:raw.revenueSource||'',themes:arr(raw.themes||raw['æŠ•è³‡ãƒ†ãƒ¼ãƒž']),registeredAt:raw.registeredAt||today(),updatedAt:today(),lastAnalyzedAt:raw.lastAnalyzedAt||raw['æœ€çµ‚åˆ†æžæ—¥']||raw.analysisDate||today(),nextReviewAt:raw.nextReviewAt||raw['æ¬¡å›žè¦‹ç›´ã—æ—¥']||oeRaw.nextReviewAt||'',marketData:{price,priceDate:md.priceDate||raw['æ ªä¾¡å¯¾è±¡æ—¥']||'',marketCap:n(md.marketCap),per:n(md.per??raw.PER),pbr:n(md.pbr??raw.PBR),roe:n(md.roe??raw.ROE),dividendYield:n(md.dividendYield??raw['é…å½“åˆ©å›žã‚Š']),annualDividendPerShare:n(md.annualDividendPerShare),revenueGrowth:n(md.revenueGrowth),operatingProfitGrowth:n(md.operatingProfitGrowth),equityRatio:n(md.equityRatio),high52Week:high52,low52Week:n(md.low52Week??raw['52é€±å®‰å€¤'])},scores:Object.fromEntries(Object.keys(SCORE_MAX).map(k=>[k,n(scores[k])??0])),companyEvaluation:{score:ceScore??0,rank:ceRaw.rank||raw['ä¼šç¤¾è©•ä¾¡ãƒ©ãƒ³ã‚¯']||defaultCompanyRank(ceScore??0),comment:ceRaw.comment||raw['ä¼šç¤¾è©•ä¾¡ã‚³ãƒ¡ãƒ³ãƒˆ']||'',competitiveAdvantage:n(ceRaw.competitiveAdvantage??raw['ç«¶äº‰å„ªä½'])??0,growth:n(ceRaw.growth??raw['æˆé•·æ€§'])??0,profitability:n(ceRaw.profitability??raw['åŽç›Šæ€§'])??0,financialHealth:n(ceRaw.financialHealth??raw['è²¡å‹™å¥å…¨æ€§'])??0,shareholderReturn:n(ceRaw.shareholderReturn??raw['æ ªä¸»é‚„å…ƒå§¿å‹¢'])??0,managementTrust:n(ceRaw.managementTrust??raw['çµŒå–¶ã®ä¿¡é ¼æ€§'])??0,businessDurability:n(ceRaw.businessDurability??raw['äº‹æ¥­ã®æŒç¶šæ€§'])??0},priceEvaluation:{score:peScore??0,rank:peRaw.rank||raw['æ ªä¾¡è©•ä¾¡ãƒ©ãƒ³ã‚¯']||defaultPriceRank(peScore??0),comment:peRaw.comment||raw['æ ªä¾¡è©•ä¾¡ã‚³ãƒ¡ãƒ³ãƒˆ']||'',currentPrice:price,priceDate:md.priceDate||raw['æ ªä¾¡å¯¾è±¡æ—¥']||'',targetPrice:n(dec.targetPrice??oeRaw.targetPrice??raw['å¸Œæœ›æ ªä¾¡']),per:n(md.per??raw.PER),pbr:n(md.pbr??raw.PBR),dividendYield:n(md.dividendYield??raw['é…å½“åˆ©å›žã‚Š']),high52Week:high52,low52Week:n(md.low52Week??raw['52é€±å®‰å€¤']),dropFrom52Week:price!=null&&high52?((price-high52)/high52*100):null,priceLevel:n(peRaw.priceLevel??raw['æ ªä¾¡æ°´æº–'])??0,valuation:n(peRaw.valuation??raw['å‰²å®‰åº¦'])??0,dividendAttractiveness:n(peRaw.dividendAttractiveness)??0,marketPosition:n(peRaw.marketPosition??raw['éœ€çµ¦çŠ¶æ³'])??0,momentum:n(peRaw.momentum??raw['éŽç†±æ„Ÿ'])??0},decision:{status:dec.status||raw['ã‚¹ãƒ†ãƒ¼ã‚¿ã‚¹']||oeRaw.decision||'è³¼å…¥å€™è£œ',priority:dec.priority||raw['è³¼å…¥å„ªå…ˆåº¦']||'',targetPrice:n(dec.targetPrice??oeRaw.targetPrice??raw['å¸Œæœ›æ ªä¾¡']),investmentReasons:arr(dec.investmentReasons||oeRaw.investmentReasons||raw['ä¸»ãªæŠ•è³‡ç†ç”±']),mainRisk:dec.mainRisk||oeRaw.mainRisk||raw['æœ€å¤§ã®ãƒªã‚¹ã‚¯']||'',reasonsNotToBuy:arr(dec.reasonsNotToBuy||oeRaw.reasonsToWait),watchPoints:arr(dec.watchPoints||oeRaw.nextCheckPoints),reasonToHold:dec.reasonToHold||'',overrideJudgement:dec.judgement||raw['åˆ¤å®š']||oeRaw.decision||''},riskFlags:arr(raw.riskFlags),investmentPurposes:arr(raw.investmentPurposes),sources:raw.sources||raw['æƒ…å ±å…ƒ']||[],analysisHistory:raw.analysisHistory||[],memo:raw.memo||''}; s.marketData.dropFrom52Week=s.priceEvaluation.dropFrom52Week; s.overallEvaluation={score:n(overallManual)??calcOverallScore(s.companyEvaluation.score,s.priceEvaluation.score),decision:oeRaw.decision||s.decision.overrideJudgement||'',action:oeRaw.action||'',investmentReasons:s.decision.investmentReasons,reasonsToWait:arr(oeRaw.reasonsToWait||s.decision.reasonsNotToBuy),mainRisk:s.decision.mainRisk,nextCheckPoints:s.decision.watchPoints,nextReviewAt:oeRaw.nextReviewAt||s.nextReviewAt,manualOverride:overallManual!=null}; if(overallManual==null&&!ceScore&&!peScore)s.overallEvaluation.score=totalScore(s.scores); s.hiScore=n(raw.hiScore??raw['HIã‚¹ã‚³ã‚¢'])??s.overallEvaluation.score; if(!s.overallEvaluation.decision)s.overallEvaluation.decision=autoDecision(s); s.judgement=s.overallEvaluation.decision; s.analyzedAt=raw.analyzedAt||raw.analysisMeta?.analyzedAt||s.lastAnalyzedAt;
 s.priceDate=raw.priceDate||raw.analysisMeta?.priceDate||s.marketData.priceDate;
 s.financialDataDate=raw.financialDataDate||raw.analysisMeta?.financialDataDate||'';
 s.newsCheckedAt=raw.newsCheckedAt||raw.analysisMeta?.newsCheckedAt||'';
 s.validUntil=raw.validUntil||raw.analysisMeta?.validUntil||'';
 s.nextReviewAt=raw.nextReviewAt||raw.analysisMeta?.nextReviewAt||s.nextReviewAt||'';
 s.nextEarningsDate=raw.nextEarningsDate||raw.analysisMeta?.nextEarningsDate||'';
 s.lastEarningsDate=raw.lastEarningsDate||raw.analysisMeta?.lastEarningsDate||'';
 s.reviewTriggers=arr(raw.reviewTriggers||raw.analysisMeta?.reviewTriggers);
 s.recommendedThisWeek=!!raw.recommendedThisWeek;
 s.recommendationWeek=raw.recommendationWeek||'';
 s.recommendationRank=n(raw.recommendationRank);
 s.recommendationReason=raw.recommendationReason||'';
 s.recommendationGeneratedAt=raw.recommendationGeneratedAt||'';
 s.recommendationValidUntil=raw.recommendationValidUntil||'';
 s.freshnessStatus=raw.freshnessStatus||'';
 s.freshnessReasons=arr(raw.freshnessReasons);
 s.priceAtAnalysis=n(raw.priceAtAnalysis??raw.analysisMeta?.priceAtAnalysis??s.marketData.price);
 if(!s.analysisHistory.length){s.analysisHistory=[analysisSnapshot(s,raw)]}
 const fresh=evaluateFreshness(s); s.freshnessStatus=raw.freshnessStatus||fresh.status; s.freshnessReasons=s.freshnessReasons.length?s.freshnessReasons:fresh.reasons;
 return s}
function analysisSnapshot(s,raw={}){return {analysisDate:raw.analysisDate||s.lastAnalyzedAt||today(),priceDate:s.marketData.priceDate,currentPrice:s.marketData.price,companyScore:s.companyEvaluation.score,companyRank:s.companyEvaluation.rank,priceScore:s.priceEvaluation.score,priceRank:s.priceEvaluation.rank,overallScore:s.overallEvaluation.score,overallDecision:s.overallEvaluation.decision,hiScore:s.hiScore,targetPrice:s.decision.targetPrice,investmentReasons:s.decision.investmentReasons,mainRisk:s.decision.mainRisk,earnings:raw.earnings||raw['æ±ºç®—å†…å®¹']||'',businessChange:raw.businessChange||raw['æ¥­ç¸¾å¤‰åŒ–']||'',priceChange:raw.priceChange||raw['æ ªä¾¡å¤‰åŒ–']||'',changeReason:raw.changeReason||raw['è©•ä¾¡å¤‰æ›´ç†ç”±']||'',nextCheckPoints:s.decision.watchPoints,nextReviewAt:s.nextReviewAt,sources:s.sources}}
function latestHistory(s){return [...(s.analysisHistory||[])].sort((a,b)=>String(b.analysisDate).localeCompare(String(a.analysisDate)))}
function analysisDiff(s){const h=latestHistory(s); const cur=h[0], prev=h[1]; if(!cur||!prev)return null; return {previous:prev,current:cur,companyChange:`${txt(prev.companyRank)}â†’${txt(cur.companyRank)}`,priceChange:`${txt(prev.priceRank)}â†’${txt(cur.priceRank)}`,decisionChange:`${txt(prev.overallDecision||prev.judgement)}â†’${txt(cur.overallDecision||cur.judgement)}`,hiScoreChange:(cur.hiScore??cur.overallScore??0)-(prev.hiScore??prev.overallScore??0),targetPriceChange:(cur.targetPrice??0)-(prev.targetPrice??0),changeReason:cur.changeReason||'æœªç™»éŒ²'}}
let icLastLoadError='';
function normalizeStoredStock(x){const s=normalizeStock(x||{}); if(x&&x.analysisHistory&&x.analysisHistory.length)s.analysisHistory=x.analysisHistory; return s}
function loadStocks(){try{icLastLoadError=''; const raw=JSON.parse(localStorage.getItem(IC_KEY)); const rows=Array.isArray(raw)?raw:(raw?.stocks||[]); return rows.map(normalizeStoredStock).filter(s=>s.code)}catch(e){icLastLoadError=e.message||'ä¿å­˜ãƒ‡ãƒ¼ã‚¿ã‚’èª­ã¿è¾¼ã‚ã¾ã›ã‚“'; return []}} function saveStocks(stocks){localStorage.setItem(IC_KEY,JSON.stringify(stocks));}
function upsertStocks(incoming,mode='update'){const stocks=loadStocks(); incoming.forEach(ns=>{if(!ns.code)return; const i=stocks.findIndex(s=>s.code===ns.code); if(i<0)stocks.push(ns); else if(mode==='history')stocks[i].analysisHistory=[...(stocks[i].analysisHistory||[]),...(ns.analysisHistory?.length?ns.analysisHistory:[{analysisDate:ns.lastAnalyzedAt||today(),title:'JSONè¿½åŠ åˆ†æž',summary:ns.decision.investmentReasons.join(' / '),hiScore:ns.hiScore,judgement:ns.judgement,currentPrice:ns.marketData.price,targetPrice:ns.decision.targetPrice,mainRisk:ns.decision.mainRisk}])]; else if(mode==='update')stocks[i]={...stocks[i],...ns,analysisHistory:[...(stocks[i].analysisHistory||[]),...(ns.analysisHistory||[])]};}); saveStocks(stocks); return stocks}
function parseJsonInput(text){const ok=[],errors=[]; try{const root=JSON.parse(text); (Array.isArray(root)?root:(root.stocks||(root.code?[root]:[]))).forEach((x,i)=>{try{const s=normalizeStock(x); if(!s.code)throw Error('éŠ˜æŸ„ã‚³ãƒ¼ãƒ‰ãªã—'); ok.push(s)}catch(e){errors.push(`${i+1}: ${e.message}`)}})}catch(e){const chunks=text.split(/\n(?=\s*\{)/); chunks.forEach((c,i)=>{try{ok.push(normalizeStock(JSON.parse(c)))}catch(err){errors.push(`${i+1}: ä¸æ­£JSON`)}})} return {ok,errors}}
function parseCSV(text){const lines=text.trim().split(/\r?\n/); const head=lines.shift().split(',').map(h=>h.trim()); const ok=[],errors=[]; lines.forEach((line,i)=>{try{const cols=line.split(','); const obj={}; head.forEach((h,j)=>obj[h]=cols[j]); const s=normalizeStock(obj); if(!s.code)throw Error('éŠ˜æŸ„ã‚³ãƒ¼ãƒ‰ãªã—'); ok.push(s)}catch(e){errors.push(`${i+2}: ${e.message}`)}}); return {ok,errors}}
function toCSV(stocks){const head=['éŠ˜æŸ„ã‚³ãƒ¼ãƒ‰','éŠ˜æŸ„å','å¸‚å ´'ßNýÞÚ$z{-®éÜj×Ü™HŽŒKŒœÛÝ\˜ÙWÜ]X[]WÜØÛÜ™HŽŒKŒ™œ™\Ú™\Ü×ÜØÛÜ™HŽŒKŒœÙ[XÝYÜ›ÝšY\ˆŽœ›˜[YK˜][\YÜ›ÝšY\œÈŽ˜][\Y™˜[˜XÚ×Ý\ÙYŽ˜][\ŒKœ™Z™XÝYØØ[™Y]\ÈŽœ™Z™XÝYÎ‹LWKœÙ[XÝ[Û—Ü™X\ÛÛˆŽˆ˜ÛÛ\]H›ÝšY\ˆ™\Ý[ŸBˆ[^ÈœÝ]\ÈŽœ–ÈœÝ]\È—K™]HŽ—Ø]XÚÜÙ[XÝ[ÛŠ]KÙ[–Èœ›Ý™[˜[˜ÙH—JKœ›Ý™[˜[˜ÙHŽœ–Èœ›Ý™[˜[˜ÙH—KœÙ[XÝ[ÛˆŽœÙ[˜][\ÈŽœ‹™Ù]
˜][\ÈŠHÜˆ×_NÈØXÚKœÙ]
˜[YK[ŠNÈÝ]ÖÈœ™Yœ™\ÚYÜÙXÝ[ÛœÈ—K˜\[™
˜[YJNÈ™]\›ˆ[–È™]H—BˆYˆ–ÈœÝ]\È—H[ˆÈ›ÚÈ‹œ\X[ŸH[™]H›Ý[ˆ
›Û™KßK×JH[™ØÏ˜™\ÝÜØÛÜ™N‚ˆ™\ÝJ]K‹›˜[YJNÈ™\ÝÜØÛÜ™O\ØÂˆ[ÙN‚ˆYˆ›Ý‹™Ù]
—Ù\œ›Ü—Ü™XÛÜ™YŠN‚ˆ\œ›ÜœË˜\[™
Èœ›ÝšY\ˆŽœ›˜[YKœ›ÝšY\—ØÛ\ÜÈŽœ—×ØÛ\Ü××Ë—×Û˜[YW×Ë›Y]ÙŽ›KœÙXÝ[ÛˆŽ›˜[YK˜][\Ž˜][\™˜[˜XÚ×ÛÜ™\ˆŽ˜][\
ŠœŸJBˆYˆ™\Ý‚ˆ]K‹˜[YOX™\ÝÈÙ[^È˜ÛÛ\][™\Ü×ÜØÛÜ™HŽ˜™\ÝÜØÛÜ™K˜[Y][Û—ÜØÛÜ™HŽŒKœÛÝ\˜ÙWÜ]X[]WÜØÛÜ™HŽŒK™œ™\Ú™\Ü×ÜØÛÜ™HŽŒKœÙ[XÝYÜ›ÝšY\ˆŽœ˜[YK˜][\YÜ›ÝšY\œÈŽ˜][\Y™˜[˜XÚ×Ý\ÙYŽ›[Š][\Y
OŒKœ™Z™XÝYØØ[™Y]\ÈŽœ™Z™XÝYœÙ[XÝ[Û—Ü™X\ÛÛˆŽˆ˜™\Ý\X[Y\ˆ^]\Ý[™È›ÝšY\œÈŸBˆ[^ÈœÝ]\ÈŽœ–ÈœÝ]\È—K™]HŽ—Ø]XÚÜÙ[XÝ[ÛŠ]KÙ[–Èœ›Ý™[˜[˜ÙH—JKœ›Ý™[˜[˜ÙHŽœ–Èœ›Ý™[˜[˜ÙH—KœÙ[XÝ[ÛˆŽœÙ[˜][\ÈŽœ‹™Ù]
˜][\ÈŠHÜˆ×_NÈØXÚKœÙ]
˜[YK[ŠNÈÝ]ÖÈœ™Yœ™\ÚYÜÙXÝ[ÛœÈ—K˜\[™
˜[YJNÈ™]\›ˆ[–È™]H—Bˆ™]\›ˆ
ØXÚY™Ù]
™]HŠHYˆ\Ú[œÝ[˜ÙJØXÚYXÝ
H[™™]Hˆ[ˆØXÚY[ÙHØXÚY
HÜˆ
×HYˆ˜[YOOH›™]ÜÈˆ[ÙHßJBˆ›Ùš[O\ÙXÝ[ÛŠ˜ÛÛ\[žWÜ›Ùš[H‹Ê›ÝšY\œÖÌK™™]ÚØÛÛ\[žWÜ›Ùš[HŠK
›ÝšY\œÖÌWK™™]ÚØÛÛ\[žWÜ›Ùš[HŠWJNÈ\—Ü›Ùš[O\ÙXÝ[ÛŠœÛÝ\˜ÙWÛX\‹Ê›ÝšY\œÖÌ—K™™]ÚØÛÛ\[žWÜ›Ùš[HŠWJBˆYˆ\—Ü›Ùš[Nˆ›Ùš[O^ÊŠœ›Ùš[K
ŠžÚÎˆ›ÜˆËˆ[ˆ\—Ü›Ùš[Kš][\Ê
HYˆˆ\È›Ý›Û™H[™›ÝËœÝ\ÝÚ]
—ÈŠH[™È›Ý[ˆÈœÛÝ\˜ÙH‹œÛÝ\˜ÙWÝ\›‹™™]ÚYØ]Ÿ__BˆY[]O]˜[Y]WÚY[]J\™Ù]›Ùš[JHYˆ›Ùš[H[ÙHÈœÝ]\ÈŽˆ’QS•UWÓRTÓPUÒ‹˜ÚXÚÜÈŽžßKš[X[—Ü™]šY]×Ü™\]Z\™YŽ•Y_BˆšXÙO\ÙXÝ[ÛŠœšXÙH‹Ê›ÝšY\œÖÍK™™]ÚÜšXÙHŠK
›ÝšY\œÖÍWK™™]ÚÜšXÙHŠWJNÈš[˜[˜ÚX[Ï\ÙXÝ[ÛŠ™š[˜[˜ÚX[È‹Ê›ÝšY\œÖÍ—K™™]ÚÙš[˜[˜ÚX[ÈŠK
›ÝšY\œÖÌ×K™™]ÚÙš[˜[˜ÚX[ÈŠWJNÈ˜[X][Û\ÙXÝ[ÛŠ˜[X][Ûˆ‹Ê›ÝšY\œÖÍ×K™™]ÚÝ˜[X][ÛˆŠWJNÈ]šY[™Ï\ÙXÝ[ÛŠ™]šY[™È‹Ê›ÝšY\œÖÌ—K™™]ÚÙ]šY[™ÈŠWJNÂˆœ›ÛH˜[X][Û—ØØ[Ý[]Üˆ[\ÜØ[Ý[]H\ÈØØ[×Ý˜[ˆØ[ÏWØØ[×Ý˜[
šXÙHYˆ\Ú[œÝ[˜ÙJšXÙKXÝ
H[ÙHßKš[˜[˜ÚX[ÈYˆ\Ú[œÝ[˜ÙJš[˜[˜ÚX[ËXÝ
H[ÙHßK]šY[™ÈYˆ\Ú[œÝ[˜ÙJ]šY[™ËXÝ
H[ÙHßJBˆYˆ\Ú[œÝ[˜ÙJ˜[X][Û‹XÝ
H[™›Ý[žJ˜[X][Û‹™Ù]
ÊH\È›Ý›Û™H›ÜˆÈ[ˆ
œ\ˆ‹œœˆ‹™]šY[™ÞZY[‹›X\šÙ]ØØ\ŠJN‚ˆØ[×Ý˜[Y\Ï^ÚÎˆ›ÜˆËˆ[ˆØ[Ëš][\Ê
HYˆÈ[ˆÈœ\ˆ‹œœˆ‹™]šY[™ÞZY[‹œ^[Ý]Ü˜][È‹›X\šÙ]ØØ\ŸH[™ˆ\È›Ý›Û™_Bˆ˜[X][Û^ÊŠ˜[X][Û‹
Š˜Ø[×Ý˜[Y\Ë›Y]ÙŽˆ˜Ø[Ý[]YˆYˆØ[×Ý˜[Y\È[ÙH˜Ø[Ý[][Û—Ý[˜]˜Z[X›H‹™›Ü›][HŽˆ›X\šÙ]ØØ\XÝ\œ™[ÜšXÙJŠÚ\™\×ÛÝ]Ý[™[™Ë]™X\Ý\žWÜÚ\™\ÊNÈ\[X\šÙ]ØØ\Û™]Ú[˜ÛÛYWØ]šX]X›NÈœ[X\šÙ]ØØ\Ù\]Z]H‹˜\×ÛÙˆŽœšXÙK™Ù]
œšXÙWÙ]HŠHYˆØ[×Ý˜[Y\È[ÙH›Û™Kš[œ]Ù˜XÝÜ™YœÈŽ–ÈœšXÙK˜Ý\œ™[ÜšXÙH‹™š[˜[˜ÚX[ËœÚ\™\×ÛÝ]Ý[™[™È‹™š[˜[˜ÚX[Ë™X\Ý\žWÜÚ\™\È‹™š[˜[˜ÚX[Ë›™]Ú[˜ÛÛYWØ]šX]X›H‹™š[˜[˜ÚX[Ë™\]Z]H—KœÛÝ\˜ÙWÜ™YœÈŽ–×_Bˆ™]ÜÏ\ÙXÝ[ÛŠ›™]ÜÈ‹Ê›ÝšY\œÖÎK™™]ÚÛ™]ÜÈŠWJHÜˆ×BˆÜTÛÝ\˜ÙT™YÚ\ÝžJ
NÈÜ‹˜Y
”ÔËRQ‹’”\Ý[™È[™Y[]H‹›Ùš[K™Ù]
œÛÝ\˜ÙWÝ\›ŠK›\Ý[™×Ü™XÛÜ™‹šY[]H‹’”‹›Ùš[K™Ù]
›\Ý[™×Ù]HŠKÙ™šXÚX[Q˜[ÙK^˜O^ÈœÛÝ\˜ÙWØ]]Üš]WÝ\HŽˆ™^Ú[™ÙWØ]]Üš]H‹œÛÝ\˜ÙWÝ\ÝÛ]™[Žˆ˜]]Üš]]]™H‹˜]]Üš]WÙÛXZ[—Ý™\šYšYYŽ•YK˜ÛÛ\[žWÛÙ™šXÚX[Ž‘˜[ÙK˜ÛÛ[Ù™]ÚYŽ•YK˜ÛÛ[Ý™\šYšYYŽ•YK›Y]Y]WÝ™\šYšYYŽ•Y_JBˆYˆ›Ùš[K™Ù]
›Ù™šXÚX[Ú\—Ý\›ŠNˆÜ‹˜Y
”ÔËRTˆ‹“Ù™šXÚX[Tˆ[˜[˜ÙH‹›Ùš[K™Ù]
›Ù™šXÚX[Ú\—Ý\›ŠKš[™^ÜYÙH‹š\—Û˜]šYØ][Ûˆ‹“Ù™šXÚX[ÛÛ\[žHTˆ‹›Û™KÙ™šXÚX[UYJBˆYˆšXÙK™Ù]
˜Ý\œ™[ÜšXÙHŠH[™šXÙK™Ù]
œšXÙWÙ]HŠNˆÜ‹˜Y
”ÔËT’PÑH‹“X\šÙ]šXÙH‹šXÙK™Ù]
œÛÝ\˜ÙWÝ\›ŠK›X\šÙ]Ù]H‹œšXÙH‹šXÙK™Ù]
œÛÝ\˜ÙHŠKšXÙK™Ù]
œšXÙWÙ]HŠKÙ™šXÚX[Q˜[ÙJBˆXZ›Ü—Ùš[X[žJš[˜[˜ÚX[Ë™Ù]
ÊH\È›Ý›Û™H›ÜˆÈ[ˆ
œ™]™[YH‹›Ü\˜][™×Ú[˜ÛÛYH‹›™]Ú[˜ÛÛYH‹™\ÈŠJNÈš[—ÙØÏYš[˜[˜ÚX[Ë™Ù]
œÛÝ\˜ÙWÙØÝ[Y[Ý\›ŠH[™Ø[›ÛšXØ[Ý\›
š[˜[˜ÚX[Ë™Ù]
œÛÝ\˜ÙWÙØÝ[Y[Ý\›ŠJHOXØ[›ÛšXØ[Ý\›
›Ùš[K™Ù]
›Ù™šXÚX[Ú\—Ý\›ŠJBˆYˆš[—ÙØÎˆÜ‹˜Y
”ÔËQ’Sˆ‹‘š[˜[˜ÚX[ØÝ[Y[‹š[˜[˜ÚX[Ë™Ù]
œÛÝ\˜ÙWÙØÝ[Y[Ý\›ŠK™š[˜[˜ÚX[ÙØÝ[Y[‹™š[˜[˜ÚX[È‹“Ù™šXÚX[ÛÛ\[žHTˆ‹š[˜[˜ÚX[Ë™Ù]
™X\›š[™Ü×Ü™[X\ÙWÙ]HŠKš[˜[˜ÚX[Ë™Ù]
œÛÝ\˜ÙWÙØÝ[Y[Ý]HŠKš\ØØ[Ü\š[ÙYš[˜[˜ÚX[Ë™Ù]
™š\ØØ[Ü\š[ÙŠK˜[Y][Û—ÜÝ]\ÏH•‘T’Q’QQˆYˆXZ›Ü—Ùš[ˆ[ÙH
‘RSQˆYˆš[˜[˜ÚX[Ë™Ù]
™ØÝ[Y[Ý˜[Y][Û—ÜÝ]\ÈŠOOH‘RSQˆ[ÙH”T•PSŠK]šY[˜ÙWÙ[YÚX›O[XZ›Ü—Ùš[ˆ[™š[˜[˜ÚX[Ë™Ù]
™ØÝ[Y[Ý˜[Y][Û—ÜÝ]\ÈŠOOH•‘T’Q’QQ‹Ù™šXÚX[UYK^˜O^È˜ÛÛ[Ù™]ÚYŽ™š[˜[˜ÚX[Ë™Ù]
™ØÝ[Y[Ù\ØÛÝ™\žWÜÝ]\ÈŠH[ˆÈ˜ÛÛ[Ù™]ÚY‹™^˜XÝ[Û—ÜÝXØÙYYYŸK˜ÛÛ[Ý™\šYšYYŽ™š[˜[˜ÚX[Ë™Ù]
™ØÝ[Y[Ý˜[Y][Û—ÜÝ]\ÈŠOOH•‘T’Q’QQ‹™ØÝ[Y[ÚY[]WÝ™\šYšYYŽ™š[˜[˜ÚX[Ë™Ù]
™ØÝ[Y[Ý˜[Y][Û—ÜÝ]\ÈŠOOH•‘T’Q’QQ‹˜]]Üš]WØÚZ[—Ý™\šYšYYŽ˜›ÛÛ
š[˜[˜ÚX[Ë™Ù]
˜]]Üš]WØÚZ[—Ý™\šYšYYŠJK›[šÙYÙœ›ÛWÛÙ™šXÚX[ÜYÙHŽ˜›ÛÛ
š[˜[˜ÚX[Ë™Ù]
›[šÙYÙœ›ÛWÛÙ™šXÚX[ÜYÙHŠJKœ›ÝšY\ˆŽˆ›Ù™šXÚX[Ú\ˆ‹œÝ\Ü×Ù˜XÝÜ™YœÈŽ–È™š[˜[˜ÚX[Ëœ™]™[YH‹™š[˜[˜ÚX[Ë›Ü\˜][™×Ú[˜ÛÛYH‹™š[˜[˜ÚX[Ë›™]Ú[˜ÛÛYH‹™š[˜[˜ÚX[Ë™\È—K˜ÛÛ[Ú\ÚŽ™š[˜[˜ÚX[Ë™Ù]
˜ÛÛ[Ú\ÚŠ_JBˆÛX[—Û™]ÜÏVÛˆ›Üˆˆ[ˆ™]ÜÈYˆ\Ú[œÝ[˜ÙJ‹XÝ
H[™‹™Ù]
]HŠHOH“Ù™šXÚX[Tˆ\]\ÈYÙHˆ[™‹™Ù]
œX›\ÚYØ]ŠH[™‹™Ù]
œÛÝ\˜ÙWÝ\›ŠH[™‹™Ù]
œÛÝ\˜ÙWÝ\HŠOOH›Ù™šXÚX[Û™]Ü×Ø\XÛH—Bˆ›Üˆˆ[ˆÛX[—Û™]ÜÖÎWNˆÜ‹˜Y
”ÔËS‘UÔÈ‹“Ù™šXÚX[™]ÜÈ‹‹™Ù]
œÛÝ\˜ÙWÝ\›ŠK›Ù™šXÚX[Û™]Ü×Ø\XÛH‹›™]ÜÈ‹“Ù™šXÚX[ÛÛ\[žHTˆ‹‹™Ù]
œX›\ÚYØ]ŠK‹™Ù]
]HŠK˜[Y][Û—ÜÝ]\ÏH•‘T’Q’QQˆYˆ‹™Ù]
˜ÛÛ[Ý™\šYšYYŠH[ÙH”T•PS‹]šY[˜ÙWÙ[YÚX›OX›ÛÛ
‹™Ù]
˜ÛÛ[Ý™\šYšYYŠHÜˆ‹™Ù]
›Y]Y]WÙ]šY[˜ÙWÙ[YÚX›HŠJKÙ™šXÚX[X›ÛÛ
‹™Ù]
›Ù™šXÚX[ŠJK^˜O^È˜ÛÛ[Ù™]ÚYŽ˜›ÛÛ
‹™Ù]
˜ÛÛ[Ù™]ÚYŠJK˜ÛÛ[Ý™\šYšYYŽ˜›ÛÛ
‹™Ù]
˜ÛÛ[Ý™\šYšYYŠJK›Y]Y]WÝ™\šYšYYŽ˜›ÛÛ
‹™Ù]
›Y]Y]WÝ™\šYšYYŠJK˜ÛÛ[Ú\ÚŽ›‹™Ù]
˜ÛÛ[Ú\ÚŠ_JBˆYˆ[žJ˜[X][Û‹™Ù]
ÊH\È›Ý›Û™H›ÜˆÈ[ˆ
œ\ˆ‹œœˆ‹™]šY[™ÞZY[‹›X\šÙ]ØØ\ŠJNˆÜ‹˜Y
”ÔËUS‹•˜[X][Ûˆ]H‹˜[X][Û‹™Ù]
œÛÝ\˜ÙWÝ\›ŠK˜[X][Û—Ù]H‹˜[X][Ûˆ‹˜[X][Û‹™Ù]
œÛÝ\˜ÙHŠKšXÙK™Ù]
œšXÙWÙ]HŠK]šY[˜ÙWÙ[YÚX›OUYJBˆZ\ÜÚ[™ÏV×Bˆ›Üˆˆ[ˆÈœšXÙK˜Ý\œ™[ÜšXÙH‹œšXÙKœ™]š[Ý\×ØÛÜÙH‹œšXÙK˜Ú[™ÙH‹œšXÙK˜Ú[™ÙWÜ˜]H‹œšXÙKœšXÙWÙ]H—N‚ˆÝ\\šXÙK™Ù]
‹œÜ]
‹ˆŠVÌWJNÂˆYˆÝ\ˆ\È›Û™NˆZ\ÜÚ[™Ë˜\[™
ÛZ\ÜÚ[™Ê‹›Z\ÜÚ[™ÈŠJBˆš[—Ø][\ÏVÞÈœ›ÝšY\ˆŽ˜K™Ù]
œ›ÝšY\ˆŠK\›Ž˜K™Ù]
\›ŠKšÜÝ]\ÈŽ˜K™Ù]
šÜÝ]\ÈŠK™\œ›Ü—Ý\HŽ˜K™Ù]
™\œ›Ü—Ý\HŠ_H›ÜˆH[ˆš[˜[˜ÚX[Ë™Ù]
œ›ÝšY\—Ø][\È‹×JHYˆK™Ù]
™\œ›Ü—Ý\HŠWHYˆ\Ú[œÝ[˜ÙJš[˜[˜ÚX[ËXÝ
H[ÙH×Bˆ›Üˆˆ[ˆÈ™š[˜[˜ÚX[Ë™š\ØØ[Ü\š[Ù‹™š[˜[˜ÚX[Ë™X\›š[™Ü×Ü™[X\ÙWÙ]H‹™š[˜[˜ÚX[Ëœ™]™[YH‹™š[˜[˜ÚX[Ë›Ü\˜][™×Ú[˜ÛÛYH‹™š[˜[˜ÚX[Ë›™]Ú[˜ÛÛYH‹™š[˜[˜ÚX[Ë™\È—N‚ˆYˆš[˜[˜ÚX[Ë™Ù]
‹œÜ]
‹ˆŠVÌWJH\È›Û™NˆZ\ÜÚ[™Ë˜\[™
ÛZ\ÜÚ[™Ê‹™ØÝ[Y[Ù™]ÚÙ˜Z[YˆYˆš[—Ø][\È[ÙH›Z\ÜÚ[™È‹][\ÏYš[—Ø][\Ë™]žXX›OQ˜[ÙHYˆš[—Ø][\È[ÙHYJJBˆYˆ›ÝÛX[—Û™]ÜÎˆZ\ÜÚ[™È
ÏH×ÛZ\ÜÚ[™Ê›™]ÜË›]\ÝÝ]HŠKÛZ\ÜÚ[™Ê›™]ÜË›]\ÝÜX›\ÚYØ]ŠKÛZ\ÜÚ[™Ê›™]ÜË›]\ÝÜÛÝ\˜ÙWÝ\›ŠWBˆYˆ]šY[™Ë™Ù]
™]šY[™Ù›Ü™XØ\ÝŠH\È›Û™H[™]šY[™Ë™Ù]
˜[›X[Ù]šY[™ŠH\È›Û™H[™]šY[™Ë™Ù]
™]šY[™Ù›Ü™XØ\ÝÜÝ]\ÈŠH›Ý[ˆÈ[™XÚYY‹››ÝÙ\ØÛÜÙYŸNˆZ\ÜÚ[™Ë˜\[™
ÛZ\ÜÚ[™ÊœÚ\™ZÛ\—Ü™]\›œË™]šY[™Ù›Ü™XØ\Ý‹›Z\ÜÚ[™ÈŠJBˆ[Yˆ]šY[™Ë™Ù]
™]šY[™Ù›Ü™XØ\ÝÜÝ]\ÈŠOOH[™XÚYYŽˆZ\ÜÚ[™Ë˜\[™
ÛZ\ÜÚ[™ÊœÚ\™ZÛ\—Ü™]\›œË™]šY[™Ù›Ü™XØ\Ý‹[™XÚYY‹È•VWÐÐS‘QUH—K™]žXX›OQ˜[ÙJJBˆYˆ˜[X][Û‹™Ù]
œ\ˆŠH\È›Û™H[™˜[X][Û‹™Ù]
œœˆŠH\È›Û™NˆZ\ÜÚ[™Ë˜\[™
ÛZ\ÜÚ[™Ê˜[X][Û‹œ\ˆ‹›Z\ÜÚ[™È‹È•VWÐÐS‘QUH—JJNÈZ\ÜÚ[™Ë˜\[™
ÛZ\ÜÚ[™Ê˜[X][Û‹œ\—ÛÜ—Üœˆ‹›Z\ÜÚ[™È‹È•VWÐÐS‘QUH—JJBˆš[˜[ÙXÚ\Ú[Û—ÛZ\ÜÚ[™Ï[Z\ÜÚ[™ÊÖ×ÛZ\ÜÚ[™Êœš\ÚÜÈ‹›Z\ÜÚ[™È‹È•ÐUÒ‹•VWÐÐS‘QUH—JWBˆÛÝ[Ï\Ü‹˜ÛÝ[Ê
NÈ]X[]OHšYÚˆYˆ›ÝZ\ÜÚ[™È[™ÛÝ[ÖÈ™]šY[˜ÙWÙ[YÚX›WÜÛÝ\˜ÙWØÛÝ[—OLÈ[ÙHœ\X[ˆYˆ›Ùš[H[ÙH™˜Z[Y‚ˆO^È™Ù[™\˜]YØ]Ž››ÝÊ
KœšXÙWØ\×ÛÙˆŽœšXÙK™Ù]
œšXÙWÙ]HŠK™[™[Y[[×Ø\×ÛÙˆŽ™š[˜[˜ÚX[Ë™Ù]
™š\ØØ[Ü\š[ÙŠK˜[X][Û—Ø\×ÛÙˆŽœšXÙK™Ù]
œšXÙWÙ]HŠHYˆ˜[X][Ûˆ[ÙH›Û™K›™]Ü×Ø\×ÛÙˆŽ˜ÛX[—Û™]ÜÖÌK™Ù]
œX›\ÚYØ]ŠHYˆÛX[—Û™]ÜÈ[ÙH›Û™KœÝ[WÙšY[ÈŽ–×K›Z\ÜÚ[™×ÙšY[ÈŽ–ÛVÈ™šY[—H›ÜˆH[ˆš[˜[ÙXÚ\Ú[Û—ÛZ\ÜÚ[™×K›Z\ÜÚ[™×Ú[™›Ü›X][ÛˆŽ™š[˜[ÙXÚ\Ú[Û—ÛZ\ÜÚ[™Ë˜ÛÛ™›XÝ[™×ÙšY[ÈŽ–ÈœšXÙKœ™]š[Ý\×ØÛÜÙH—HYˆšXÙK™Ù]
œÛÝ\˜ÙWØÛÛ™›XÝŠH[ÙH×KœÛÝ\˜ÙWØÛÛ™›XÝÈŽœšXÙK™Ù]
™XYÛ›ÜÝXÜÈŠHYˆšXÙK™Ù]
œÛÝ\˜ÙWØÛÛ™›XÝŠH[ÙHßKœ›ÝšY\—Ù\œ›ÜœÈŽ™\œ›ÜœË™]WÜ]X[]HŽœ]X[]K™\šYšYYÜÛÝ\˜Ù\×ØÛÝ[Ž˜ÛÝ[ÖÈ™]šY[˜ÙWÙ[YÚX›WÜÛÝ\˜ÙWØÛÝ[—K
Š˜ÛÝ[ßBˆXÚÏ^ÈœØÚ[XWÝ™\œÚ[ÛˆŽˆŒKŒˆ‹\Ú×ÚYŽ\ÚÖÈ\Ú×ÚY—KXÚÙ\ˆŽœ›Ùš[K™Ù]
XÚÙ\ˆŠHÜˆ\™Ù]™Ù]
XÚÙ\ˆŠK˜ÛÛ\[žHŽžÚÎˆ›ÜˆËˆ[ˆ›Ùš[Kš][\Ê
HYˆ›ÝËœÝ\ÝÚ]
—ÈŠ_KšY[]WÝ˜[Y][ÛˆŽšY[]KœšXÙHŽžÚÎˆ›ÜˆËˆ[ˆšXÙKš][\Ê
HYˆ›ÝËœÝ\ÝÚ]
—ÈŠ_KœšXÙWÝ™[™ŽžßK™š[˜[˜ÚX[ÈŽžÚÎˆ›ÜˆËˆ[ˆš[˜[˜ÚX[Ëš][\Ê
HYˆ›ÝËœÝ\ÝÚ]
—ÈŠ_K˜[X][ÛˆŽžÚÎˆ›ÜˆËˆ[ˆ˜[X][Û‹š][\Ê
HYˆ›ÝËœÝ\ÝÚ]
—ÈŠ_KœÚ\™ZÛ\—Ü™]\›œÈŽžÚÎˆ›ÜˆËˆ[ˆ]šY[™Ëš][\Ê
HYˆ›ÝËœÝ\ÝÚ]
—ÈŠ_K›™]ÜÈŽ˜ÛX[—Û™]ÜËœš\ÚÜÈŽ–×KœÛÝ\˜ÙWÛX\ŽœÜ‹›X\˜ØXÚHŽœÝ]Ë™]WÜ]X[]HŽ™_BˆØ]ÚÙšY[Ï^ÈœšXÙK˜Ý\œ™[ÜšXÙH‹œšXÙKœ™]š[Ý\×ØÛÜÙH‹œšXÙK˜Ú[™ÙH‹œšXÙK˜Ú[™ÙWÜ˜]H‹œšXÙKœšXÙWÙ]H‹™š[˜[˜ÚX[Ë™š\ØØ[Ü\š[Ù‹™š[˜[˜ÚX[Ë™X\›š[™Ü×Ü™[X\ÙWÙ]H‹™š[˜[˜ÚX[Ëœ™]™[YH‹™š[˜[˜ÚX[Ë›Ü\˜][™×Ú[˜ÛÛYH‹™š[˜[˜ÚX[Ë›™]Ú[˜ÛÛYH‹›™]ÜË›]\ÝÝ]H‹›™]ÜË›]\ÝÜX›\ÚYØ]‹›™]ÜË›]\ÝÜÛÝ\˜ÙWÝ\›ŸBˆØ]ÚÛZ\ÜÚ[™ÏVÛH›ÜˆH[ˆZ\ÜÚ[™ÈYˆVÈ™šY[—H[ˆØ]ÚÙšY[×BˆØ]WÜÝ]\ÏH‘UWÑT”“ÔˆˆYˆY[]VÈœÝ]\È—HOH•‘T’Q’QQˆ[ÙH‘UWÒS”ÕQ‘’PÒQS•ˆYˆØ]ÚÛZ\ÜÚ[™ÈÜˆÛÝ[ÖÈ™]šY[˜ÙWÙ[YÚX›WÜÛÝ\˜ÙWØÛÝ[—OÈ[ÙH”TÔÈ‚ˆØ]O^ÈœÝ]\ÈŽ™Ø]WÜÝ]\Ë˜^WØ[ÝÙYŽ‘˜[ÙK›Z\ÜÚ[™×Ú[™›Ü›X][ÛˆŽ›Z\ÜÚ[™Ëœ™\]Z\™YÜÛÝ\˜ÙWØÛÝ[ŽŒË™˜XÝÜXÚ×ÙØ]HŽžÈœÝ]\ÈŽ™Ø]WÜÝ]\Ë›Z\ÜÚ[™×Ú[™›Ü›X][ÛˆŽØ]ÚÛZ\ÜÚ[™Ëœ™\]Z\™YÜÛÝ\˜ÙWØÛÝ[ŽŒßK™š[˜[Ú[™\ÝY[ÙXÚ\Ú[Û—ÙØ]HŽžÈœÝ]\ÈŽˆ‘UWÒS”ÕQ‘’PÒQS•ˆYˆš[˜[ÙXÚ\Ú[Û—ÛZ\ÜÚ[™È[ÙH”TÔÈ‹›Z\ÜÚ[™×Ú[™›Ü›X][ÛˆŽ™š[˜[ÙXÚ\Ú[Û—ÛZ\ÜÚ[™ßK™š[˜[ÙXÚ\Ú[ÛˆŽˆ‘UWÒS”ÕQ‘’PÒQS•ˆYˆš[˜[ÙXÚ\Ú[Û—ÛZ\ÜÚ[™È[ÙH•ÐUÒŸBˆ™]\›ˆXÚËØ]B™Yˆ˜[Y]WÙ]šY[˜ÙJÝ]]XÚÊN‚ˆ]O[Ý]]™Ù]
™]H‹Ý]]
NÈ]šY[˜ÙO[Ý]]™Ù]
™]šY[˜ÙHŠHÜˆ]K™Ù]
™]šY[˜ÙHŠHÜˆ×NÈ[œÝ\ÜYV×Bˆ›ÜˆH[ˆ]šY[˜ÙN‚ˆYˆ›ÝK™Ù]
˜ÛZ[HŠHÜˆ›ÝK™Ù]
™˜XÝÜ™YœÈŠHÜˆ›ÝK™Ù]
œÛÝ\˜ÙWÜ™YœÈŠHÜˆ[žJÈ›Ý[ˆXÚÖÈœÛÝ\˜ÙWÛX\—H›ÜˆÈ[ˆK™Ù]
œÛÝ\˜ÙWÜ™YœÈ‹×JJNˆ[œÝ\ÜY˜\[™
JBˆ™]\›ˆÈ˜[YŽ˜›ÛÛ
]šY[˜ÙJH[™›Ý[œÝ\ÜY™\œ›Ü—Ý\HŽ“›Û™HYˆ]šY[˜ÙH[™›Ý[œÝ\ÜY[ÙH•S”ÕTÔ•QÐÓRSH‹[œÝ\ÜYØÛZ[\ÈŽ[œÝ\ÜYB™Yˆ]XÝØÛÛ˜YXÝ[ÛœÊÝ]]XÚÊN‚ˆ^ZœÛÛ‹™[\ÊÝ]][œÝ\™WØ\ØÚZOQ˜[ÙJK›ÝÙ\Š
NÈ›Ý[™V×NÈÛÛ\[žO\XÚË™Ù]
˜ÛÛ\[žH‹ßJBˆYˆÛÛ\[žK™Ù]
›\ÝYŠH[™[žJ[ˆ^›Üˆ[ˆÈš\ùbcH‹ºgg¹ak:e¢ù/ y©kH‹œ™KZ\È‹››ÝY]\ÝY—JNˆ›Ý[™˜\[™
È˜ÛZ[HŽˆœ™KRTËÝ[›\ÝY‹™˜XÝÜ™YˆŽˆ˜ÛÛ\[žK›\ÝY‹˜XÝX[Ž•YK™\œ›Ü—Ý\HŽˆÓÓ•QPÕÔ–WÐÓRSHŸJBˆYˆ˜^Hˆ[ˆ^[™˜^WØØ[™Y]Hˆ›Ý[ˆ^ˆ›Ý[™˜\[™
È˜ÛZ[HŽˆ•VH\È›Ý[ÝÙY[ˆ[š]X[Ü\˜][Ûˆ‹™˜XÝÜ™YˆŽˆœÛXÞK›X^ÙXÚ\Ú[Ûˆ‹˜XÝX[Žˆ•VWÐÐS‘QUH‹™\œ›Ü—Ý\HŽˆÓÓ•QPÕÔ–WÐÓRSHŸJBˆ™]\›ˆ›Ý[™™Yˆ\ØÛÜ™ÛY\ÜØYÙJš[˜[XÚËØ]JN‚ˆÛÛ\[žO\XÚË™Ù]
˜ÛÛ\[žH‹ßJK™Ù]
˜ÛÛ\[žWÛ˜[YHŠHÜˆXÚË™Ù]
XÚÙ\ˆŠNÈXÚ\Ú[ÛYš[˜[™Ù]
™š[˜[ÙXÚ\Ú[ÛˆŠHÜˆØ]K™Ù]
™š[˜[ÙXÚ\Ú[ÛˆŠHÜˆØ]K™Ù]
œÝ]\ÈŠNÈšXÙO\XÚË™Ù]
œšXÙH‹ßJK™Ù]
˜Ý\œ™[ÜšXÙHŠNÈ]O\XÚË™Ù]
œšXÙH‹ßJK™Ù]
œšXÙWÙ]HŠBˆÛÝV×NÈZ\ÜÏV×NÈO\XÚË™Ù]
™]WÜ]X[]H‹ßJNÈZ\ÜÚ[™Ï\Ù]
K™Ù]
›Z\ÜÚ[™×ÙšY[È‹×JJBˆYˆXÚË™Ù]
˜ÛÛ\[žH‹ßJK™Ù]
›\ÝYŠNˆÛÝ˜\[™
¹."¹h-9 áyh,HŠBˆYˆšXÙH\È›Ý›Û™NˆÛÝ˜\[™
¹¨*¹/¨HŠBˆYˆK™Ù]
š[™^ÜYÙWØÛÝ[‹
NˆÛÝ˜\[™
’T¹aiycèùè®º*£HŠBˆ›ÜˆX™[šY[[ˆÊ¹§ 9¥¬9¬n¹ë¥ù¥l9`)‹™š[˜[˜ÚX[Ëœ™]™[YHŠK
¸àä8àê¸àéxàª8àï8à­øàéøàìÈ‹˜[X][Û‹œ\—ÛÜ—ÜœˆŠK
¸àê¸à®xà«È‹œš\ÚÜÈŠK
ºacyodù áyh,H‹œÚ\™ZÛ\—Ü™]\›œË™]šY[™Ù›Ü™XØ\ÝŠWN‚ˆYˆšY[[ˆZ\ÜÚ[™ÎˆZ\ÜË˜\[™
X™[
BˆšXÙWÛ[™OYˆ¹¨*¹/¨{ï&žÜšXÙ_ya¡ˆŠÊˆ»ï"Ù]_{ï"HˆYˆ]H[ÙHˆŠHYˆšXÙH\È›Ý›Û™H[ÙH¹¨*¹/¨{ï&¹cå¹o¥øàiøàcxàfˆ‚ˆ\ÙÏYˆ¸¦¨;î#È9b!¹§¤9/çyåf{ïgÜXÚË™Ù]
	ÝXÚÙ\‰Ê_HØÛÛ\[ž_W¹b)9k¦»ï&žÙXÚ\Ú[ÛŸWžÜšXÙWÛ[™_W¹cå¹o¥ù®"8àoûï&—‹HŠÈ—‹H‹š›Ú[ŠÛÝÜˆÈ¸àj¸àeÈ—JJÈ—¹§*¹cå¹o¥ûï&—‹HŠÈ—‹H‹š›Ú[ŠZ\ÜÈÜˆÈ¸àj¸àeÈ—JBˆ™]\›ˆ\ÙÖÎŽLB™Yˆ[™\ÝY[ØÛÛ[X[™\—Ý\]Jš[˜[XÚËØ]KšYÙÙ\S›Û™KÙ[Z[šWØØ[ÏL
N‚ˆ\XÚË™Ù]
œšXÙH‹ßJNÈ\XÚË™Ù]
™š[˜[˜ÚX[È‹ßJNÈO\XÚË™Ù]
™]WÜ]X[]H‹ßJNÈ™]ÜÏJXÚË™Ù]
›™]ÜÈŠHÜˆÓ›Û™WJVÌBˆ™]\›ˆÈ™š[˜[ÙXÚ\Ú[ÛˆŽ™š[˜[™Ù]
™š[˜[ÙXÚ\Ú[ÛˆŠHÜˆØ]K™Ù]
™š[˜[ÙXÚ\Ú[ÛˆŠK˜ÛÛ™šY[˜ÙHŽ™š[˜[™Ù]
˜ÛÛ™šY[˜ÙHŠK˜Ý\œ™[ÜšXÙHŽœ™Ù]
˜Ý\œ™[ÜšXÙHŠKœ™]š[Ý\×ØÛÜÙHŽœ™Ù]
œ™]š[Ý\×ØÛÜÙHŠK˜Ú[™ÙHŽœ™Ù]
˜Ú[™ÙHŠK˜Ú[™ÙWÜ˜]HŽœ™Ù]
˜Ú[™ÙWÜ˜]HŠKœšXÙWÙ]HŽœ™Ù]
œšXÙWÙ]HŠK›]\ÝÙš\ØØ[Ü\š[ÙŽ™‹™Ù]
™š\ØØ[Ü\š[ÙŠK™X\›š[™Ü×Ü™[X\ÙWÙ]HŽ™‹™Ù]
™X\›š[™Ü×Ü™[X\ÙWÙ]HŠK™]WÜ]X[]HŽ™Kš[™\[™[ÜÛÝ\˜ÙWØÛÝ[Ž™K™Ù]
š[™\[™[ÜÛÝ\˜ÙWØÛÝ[ŠK™]šY[˜ÙWÙ[YÚX›WÜÛÝ\˜ÙWØÛÝ[Ž™K™Ù]
™]šY[˜ÙWÙ[YÚX›WÜÛÝ\˜ÙWØÛÝ[ŠK›Z\ÜÚ[™×Ú[™›Ü›X][ÛˆŽ™K™Ù]
›Z\ÜÚ[™×Ú[™›Ü›X][ÛˆŠKœÛÝ\˜ÙWØÛÛ™›XÝÈŽ™K™Ù]
œÛÝ\˜ÙWØÛÛ™›XÝÈŠK˜ÛÜœÜ˜]WØXÝ[Û—Ü™]šY]ÈŽœ™Ù]
˜ÛÜœÜ˜]WØXÝ[Û—Ù]XÝYŠK›]\ÝÛÙ™šXÚX[Û™]ÜÈŽ›™]ÜË˜[X][Û—ÜÝ]\ÈŽœXÚË™Ù]
˜[X][Ûˆ‹ßJK™Ù]
œÝ]\ÈŠK™]šY[™ÜÝ]\ÈŽœXÚË™Ù]
œÚ\™ZÛ\—Ü™]\›œÈ‹ßJK™Ù]
œÝ]\ÈŠK™]šY[˜ÙHŽ™š[˜[™Ù]
™]šY[˜ÙH‹×JK˜ÛÛ˜YXÝ[ÛœÈŽ™š[˜[™Ù]
˜ÛÛ˜YXÝ[ÛœÈ‹×JKœš\ÚÜÈŽ™š[˜[™Ù]
œš\ÚÜÈ‹×JK›™^Ü™]šY]ÈŽ™š[˜[™Ù]
›™^Ü™]šY]×Ú][\È‹×JK›\ÝØ[˜[^™YŽ››ÝÊ
KšYÙÙ\ˆŽšYÙÙ\‹™˜XÝÜXÚ×Ü™YˆŽ™ˆ˜ØXÚKÚ[™\ÝY[Ù˜XÝËÞ×ØÛÙJÉÝXÚÙ\‰ÎœXÚË™Ù]
	ÝXÚÙ\‰Ê_J_H‹™Ù[Z[šWØØ[ØÛÝ[Ž™Ù[Z[šWØØ[ßB™YˆÚÝ[ÝšYÙÙ\—Ý™\šYšYYØ[˜[\Ú\ÊXÚ\Ú[Û‹šYÙÙ\‹šXÙWÙ]K]\ÝÙš[˜[˜ÚX[Ü\š[ÙS›Û™K]\ÝÙ]™[Ù]OS›Û™KÙY[S›Û™JN‚ˆ[ÝÙY^È•ÐUÒ‹•VWÐÐS‘QUH‹”‘U’QU×Ô‘TURT‘QŸNÈ]™[^È‘UWÑT”“Ô—Ô‘PÓÕ‘T‘Q‹‘PT“’S‘Ô×Ô‘SPTÑH‹‘U’QS‘Ô‘U’TÒSÓˆ‹“T‘ÑWÑ“Ô‹’STÔ•S•Ó‘UÔÈŸBˆYˆXÚ\Ú[Ûˆ›Ý[ˆ[ÝÙY[™šYÙÙ\ˆ›Ý[ˆ]™[ˆ™]\›ˆ˜[ÙK›Û™BˆÙ^OYˆžÝšYÙÙ\Ÿ_ÜšXÙWÙ]__Û]\ÝÙš[˜[˜ÚX[Ü\š[Ù_Û]\ÝÙ]™[Ù]_HŽÈ^ÈXÚÙ\—ÚÙ^HŽšÙ^_Bˆ™]\›ˆ
˜[ÙK
HYˆÙY[ˆ[™Ù^H[ˆÙY[ˆ[ÙH
YK
B