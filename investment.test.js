const assert=require('assert'); global.localStorage={m:{},getItem(k){return this.m[k]||null},setItem(k,v){this.m[k]=v},removeItem(k){delete this.m[k]}};
const ic=require('./investment.js');
const sample={code:'1111',name:'A',marketData:{price:970},decision:{targetPrice:1000,status:'今週の候補',investmentReasons:['r'],mainRisk:'risk'},scores:{dividend:15,shareholderReturn:10,growth:15,financialHealth:15,valuation:15,competitiveAdvantage:10,theme:10,priceLevel:5,userFit:5},themes:['AI','高配当'],investmentPurposes:['配当','長期保有'],riskFlags:['割高'],lastAnalyzedAt:'2026-01-01',nextReviewAt:'2026-01-02'};
let s=ic.normalizeStock(sample);
assert.equal(ic.totalScore(s.scores),100); assert.equal(ic.autoDecision(s),'最優先で調査'); assert.equal(ic.targetDiff(s),-30); assert.equal(ic.targetDiffRate(s),-3); assert.equal(ic.targetStatus(s),'希望株価到達'); assert.equal(ic.overdue(s,new Date('2026-07-11')),true);
assert.equal(ic.normalizeStock({code:'2'}).marketData.price,null); assert.equal(ic.rankStocks([s,ic.normalizeStock({code:'2',hiScore:10})])[0].code,'1111'); assert.equal(ic.filterStocks([s],{q:'AI'}).length,1); assert.equal(ic.filterStocks([s],{theme:'高配当'}).length,1);
let parsed=ic.parseJsonInput(JSON.stringify({app:'Investment Commander',stocks:[sample,{name:'bad'}]})); assert.equal(parsed.ok.length,1); assert(parsed.errors.length>=1);
let partial=ic.parseJsonInput('{bad}\n'+JSON.stringify(sample)); assert.equal(partial.ok.length,1);
ic.saveStocks([s]); ic.upsertStocks([ic.normalizeStock({...sample,name:'B'})],'update'); assert.equal(ic.loadStocks()[0].name,'B'); ic.upsertStocks([ic.normalizeStock({...sample,analysisHistory:[{title:'h'}]})],'history'); assert.equal(ic.loadStocks()[0].analysisHistory.length>0,true);
let csv='銘柄コード,銘柄名,現在株価,希望株価,HIスコア,投資テーマ\n3333,C,100,90,70,AI|半導体'; assert.equal(ic.parseCSV(csv).ok[0].code,'3333'); let out=ic.toCSV([s]); assert(out.includes('銘柄コード'));
let backup=JSON.stringify({app:'Investment Commander',stocks:[sample]}); ic.saveStocks(ic.parseJsonInput(backup).ok); assert.equal(ic.loadStocks().length,1); assert.equal(ic.preset('今すぐ見る',[s]).length,1);

let modern=ic.normalizeStock({code:'4444',name:'D',riskFlags:['業績悪化'],companyEvaluation:{score:85,rank:'A'},priceEvaluation:{score:35,rank:'割高'},overallEvaluation:{decision:'決算確認待ち',action:'決算後に再評価',investmentReasons:['AI'],mainRisk:'期待未達',nextCheckPoints:['決算'],nextReviewAt:'2026-07-31'},marketData:{price:77000},decision:{targetPrice:60000}});
assert.equal(modern.companyEvaluation.rank,'A'); assert.equal(modern.priceEvaluation.rank,'割高'); assert.equal(modern.overallEvaluation.score,65); assert.equal(modern.hiScore,65);
assert.equal(ic.specialRanking('良い会社だが買値待ち',[modern]).length,1);
let cheap=ic.normalizeStock({code:'5555',companyEvaluation:{score:55,rank:'C'},priceEvaluation:{score:80,rank:'割安'},riskFlags:['情報不足']});
assert.equal(ic.specialRanking('会社は普通だが株価妙味あり',[cheap]).length,1);
let hist=ic.normalizeStock({code:'6666',analysisHistory:[{analysisDate:'2026-01-01',companyRank:'B',priceRank:'妥当',overallDecision:'買値待ち',hiScore:60,targetPrice:1000},{analysisDate:'2026-02-01',companyRank:'A',priceRank:'割高',overallDecision:'決算確認待ち',hiScore:55,targetPrice:900,changeReason:'株価上昇'}]});
assert.equal(ic.analysisDiff(hist).decisionChange,'買値待ち→決算確認待ち');
assert.equal(ic.filterStocks([hist],{changed:true}).length,1); assert.equal(ic.filterStocks([hist],{down:true}).length,1);

console.log('investment commander tests passed');

// Freshness management / ChatGPT integration tests
const freshBase='2026-07-11';
let fresh=ic.normalizeStock({code:'7000',name:'Fresh',analyzedAt:'2026-06-20',marketData:{price:100,priceDate:'2026-07-10'},companyEvaluation:{score:80,rank:'A'},priceEvaluation:{score:60,rank:'妥当'},overallEvaluation:{decision:'購入候補'},financialDataDate:'2026-07-01',newsCheckedAt:'2026-07-05',validUntil:'2026-08-01',nextReviewAt:'2026-08-01',sources:['IR']});
assert.equal(ic.evaluateFreshness(fresh,freshBase).status,'最新');
assert.equal(ic.evaluateFreshness({...fresh,analyzedAt:'2026-06-01'},freshBase).status,'要更新');
assert.equal(ic.evaluateFreshness({...fresh,analyzedAt:'2026-05-01'},freshBase).status,'古い');
assert.equal(ic.evaluateFreshness({...fresh,validUntil:'2026-07-10'},freshBase).status,'更新期限切れ');
assert.equal(ic.evaluateFreshness({...fresh,nextReviewAt:'2026-07-10'},freshBase).status,'要更新');
assert.equal(ic.evaluateFreshness({...fresh,nextEarningsDate:'2026-07-10',analysisHistory:[]},freshBase).status,'決算通過');
assert.equal(ic.evaluateFreshness({...fresh,priceAtAnalysis:100,marketData:{...fresh.marketData,price:116}},freshBase,{priceChangeThreshold:15}).status,'株価急変');
assert.equal(ic.evaluateFreshness({...fresh,validUntil:'2026-07-10',nextEarningsDate:'2026-07-10',analysisHistory:[]},freshBase).status,'決算通過');
assert.equal(ic.reviewPriority({...fresh,nextEarningsDate:'2026-07-10',analysisHistory:[]}), '緊急');
let req=ic.generateReanalysisRequest([{...fresh,status:'要更新',reasons:['期限接近'],reviewPriority:'中'}]); assert.equal(req.requestType,'reanalyzeStocks'); assert.equal(req.stocks[0].reviewTriggers.length,0);
let prompt=ic.generateChatGPTPrompt([{...fresh,status:'要更新',reasons:['期限接近'],reviewPriority:'中'}]); assert(prompt.includes('HOS更新用JSON'));
let update={app:'Investment Commander',responseType:'stockAnalysisUpdate',version:1,generatedAt:'2026-07-31T18:00:00+09:00',stocks:[{code:'7000',name:'Fresh',analysisMeta:{analyzedAt:'2026-07-31',priceDate:'2026-07-31',financialDataDate:'2026-07-31',newsCheckedAt:'2026-07-31',validUntil:'2026-08-31',nextReviewAt:'2026-10-31',reviewTriggers:['次回決算']},marketData:{price:null,priceDate:'2026-07-31'},companyEvaluation:{score:82,rank:'A'},priceEvaluation:{score:65,rank:'妥当'},overallEvaluation:{score:75,decision:'購入候補',action:'買値到達時に再確認',investmentReasons:['成長'],mainRisk:'競争',nextCheckPoints:['決算']},targetPrice:null,sources:['IR'],analysisHistoryEntry:{analysisDate:'2026-07-31',decision:'購入候補'}}]};
assert.equal(ic.validateUpdateJson(update).responseType,'stockAnalysisUpdate');
ic.saveStocks([fresh]); let previews=ic.importUpdateJson(update,'latest',true); let updated=ic.loadStocks()[0]; assert.equal(updated.marketData.price,100); assert.equal(updated.companyEvaluation.score,82); assert(updated.analysisHistory.length>=2); assert(previews[0].diff.some(d=>d.label==='会社評価スコア'&&d.changed));
let histOnly={...update,stocks:[{...update.stocks[0],companyEvaluation:{score:90,rank:'S'}}]}; ic.importUpdateJson(histOnly,'history',true); assert.equal(ic.loadStocks()[0].companyEvaluation.score,82);
let weekly={app:'Investment Commander',responseType:'weeklyRecommendations',version:1,week:ic.isoWeek(new Date('2026-07-11')),generatedAt:'2026-07-11T00:00:00+09:00',validUntil:'2026-07-12T23:59:59+09:00',recommendations:[{code:'7000',rank:1,reason:'最新分析',requiredAction:'確認',mainRisk:'リスク'}]}; ic.saveWeeklyRecommendations(weekly); assert.equal(ic.currentWeeklyRecommendations(new Date('2026-07-11')).length,1); assert.equal(ic.currentWeeklyRecommendations(new Date('2026-07-20')).length,0);
let backupObj={app:'Investment Commander',version:1,stocks:[updated]}; ic.saveStocks(ic.parseJsonInput(JSON.stringify(backupObj)).ok); assert.equal(ic.loadStocks()[0].code,'7000');
console.log('freshness and reanalysis tests passed');
