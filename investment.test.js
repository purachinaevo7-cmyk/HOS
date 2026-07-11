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
