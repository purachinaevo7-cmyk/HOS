const DIVIDEND_STORAGE_KEY="hosDividendEmpireLiteHoldings";
const DIVIDEND_HIDE_KEY="hosDividendEmpireLiteHidden";
const MASK="••••••";

function cloneSamples(){return structuredClone(DIVIDEND_LITE_SAMPLE_HOLDINGS)}
function readHoldings(){try{return JSON.parse(localStorage.getItem(DIVIDEND_STORAGE_KEY))||cloneSamples()}catch{return cloneSamples()}}
function saveHoldings(holdings){localStorage.setItem(DIVIDEND_STORAGE_KEY,JSON.stringify(holdings))}
function money(value,hidden=false){return hidden?MASK:new Intl.NumberFormat("ja-JP",{style:"currency",currency:"JPY",maximumFractionDigits:0}).format(Math.round(Number(value)||0))}
function number(value){return new Intl.NumberFormat("ja-JP",{maximumFractionDigits:2}).format(Number(value)||0)}
function percent(value){return `${number(value)}%`}
function isHidden(){return localStorage.getItem(DIVIDEND_HIDE_KEY)==="true"}
function setHidden(hidden){localStorage.setItem(DIVIDEND_HIDE_KEY,String(hidden))}
function toRate(value){return Math.max(0,Math.min(1,Number(value)||0))}
function metrics(holding){
  const shares=Number(holding.shares)||0;
  const currentPrice=Number(holding.currentPrice)||0;
  const annualDividendPerShare=Number(holding.annualDividendPerShare)||0;
  const benefitFaceValue=Number(holding.benefitFaceValue)||0;
  const benefitUsageRate=toRate(holding.benefitUsageRate);
  const marketValue=shares*currentPrice;
  const annualDividend=shares*annualDividendPerShare;
  const annualBenefit=benefitFaceValue*benefitUsageRate;
  const totalYield=marketValue?((annualDividend+annualBenefit)/marketValue)*100:0;
  return {...holding,shares,currentPrice,annualDividendPerShare,benefitFaceValue,benefitUsageRate,marketValue,annualDividend,annualBenefit,totalYield};
}
function totals(rows){
  const marketValue=rows.reduce((sum,row)=>sum+row.marketValue,0);
  const annualDividend=rows.reduce((sum,row)=>sum+row.annualDividend,0);
  const annualBenefit=rows.reduce((sum,row)=>sum+row.annualBenefit,0);
  const annualReturn=annualDividend+annualBenefit;
  return {marketValue,annualDividend,annualBenefit,annualReturn,totalYield:marketValue?(annualReturn/marketValue)*100:0};
}
function numericInput(index,field,value,step="1",suffix=""){
  return `<div class="lite-input"><input data-index="${index}" data-field="${field}" type="number" inputmode="decimal" min="0" step="${step}" value="${value}" aria-label="${field}">${suffix?`<span>${suffix}</span>`:""}</div>`;
}
function renderMetric(label,value,sub=""){
  return `<article class="empire-metric lite-metric"><span>${label}</span><strong>${value}</strong>${sub?`<small>${sub}</small>`:""}</article>`;
}
function renderRow(row,index,hidden){
  return `<tr>
    <td><input class="name-input" data-index="${index}" data-field="name" type="text" value="${row.name}" aria-label="銘柄名"></td>
    <td>${numericInput(index,"shares",row.shares,"1")}</td>
    <td>${numericInput(index,"currentPrice",row.currentPrice,"1")}</td>
    <td>${money(row.marketValue,hidden)}</td>
    <td>${numericInput(index,"annualDividendPerShare",row.annualDividendPerShare,"0.1")}</td>
    <td>${money(row.annualDividend,hidden)}</td>
    <td>${numericInput(index,"benefitFaceValue",row.benefitFaceValue,"1")}</td>
    <td>${numericInput(index,"benefitUsageRate",row.benefitUsageRate,"0.01","倍")}</td>
    <td>${money(row.annualBenefit,hidden)}</td>
    <td><b class="gold">${percent(row.totalYield)}</b></td>
    <td><button class="danger small-button" data-delete="${index}" type="button">削除</button></td>
  </tr>`;
}
function renderDividendEmpire(){
  const root=document.getElementById("dividendApp");
  if(!root)return;
  const holdings=readHoldings();
  const hidden=isHidden();
  const rows=holdings.map(metrics);
  const total=totals(rows);
  root.innerHTML=`
    <section class="dividend-hero lite-hero">
      <p class="eyebrow gold">Dividend Empire Lite</p>
      <h2>Dividend Empire Lite</h2>
      <p>保有株、年間配当、株主優待価値をシンプルに確認するローカル資産管理ページです。</p>
      <div class="sample-note">初回表示は架空のサンプルデータのみです。入力した実データはlocalStorageだけに保存され、GitHubや外部サーバーには保存されません。</div>
      <div class="dividend-actions">
        <button id="addHolding" type="button">銘柄を追加</button>
        <button id="resetSamples" class="copy" type="button">サンプルに戻す</button>
        <button id="toggleAmounts" class="copy" type="button">${hidden?"金額を表示":"金額を隠す"}</button>
        <button id="deletePersonalData" class="danger" type="button">個人データを削除</button>
      </div>
    </section>
    <section class="dividend-panel">
      <h2>サマリー</h2>
      <div class="metric-grid lite-summary">
        ${renderMetric("総評価額",money(total.marketValue,hidden))}
        ${renderMetric("年間予想配当",money(total.annualDividend,hidden))}
        ${renderMetric("年間優待価値",money(total.annualBenefit,hidden))}
        ${renderMetric("配当＋優待の合計",money(total.annualReturn,hidden))}
        ${renderMetric("優待込み利回り",percent(total.totalYield),"（配当＋優待）÷総評価額")}
      </div>
    </section>
    <section class="dividend-panel">
      <div class="lite-section-head"><h2>保有銘柄一覧</h2><p>数値を編集すると自動で再計算し、この端末のブラウザに保存します。</p></div>
      <div class="table-wrap"><table class="holdings-table lite-table"><thead><tr>${["銘柄名","保有株数","現在株価","評価額","1株当たり年間配当","年間配当","優待額面","想定利用率","年間優待価値","優待込み利回り","削除"].map(h=>`<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.map((row,index)=>renderRow(row,index,hidden)).join("")}</tbody></table></div>
    </section>
    <section class="dividend-note">入力した資産情報は、この端末のブラウザ内にのみ保存されます。</section>`;
  bindDividend(root,holdings);
}
function bindDividend(root,holdings){
  root.querySelectorAll("input[data-field]").forEach(input=>input.addEventListener("change",event=>{
    const index=Number(event.target.dataset.index);
    const field=event.target.dataset.field;
    holdings[index][field]=field==="name"?event.target.value:Number(event.target.value);
    if(field==="benefitUsageRate")holdings[index][field]=toRate(event.target.value);
    saveHoldings(holdings);
    renderDividendEmpire();
  }));
  root.querySelectorAll("button[data-delete]").forEach(button=>button.addEventListener("click",event=>{
    holdings.splice(Number(event.currentTarget.dataset.delete),1);
    saveHoldings(holdings);
    renderDividendEmpire();
  }));
  root.querySelector("#addHolding").addEventListener("click",()=>{
    holdings.push({name:"新しい銘柄",shares:100,currentPrice:1000,annualDividendPerShare:30,benefitFaceValue:0,benefitUsageRate:0});
    saveHoldings(holdings);
    renderDividendEmpire();
  });
  root.querySelector("#resetSamples").addEventListener("click",()=>{localStorage.removeItem(DIVIDEND_STORAGE_KEY);renderDividendEmpire();showToast("サンプルデータに戻しました")});
  root.querySelector("#toggleAmounts").addEventListener("click",()=>{setHidden(!isHidden());renderDividendEmpire()});
  root.querySelector("#deletePersonalData").addEventListener("click",()=>{localStorage.removeItem(DIVIDEND_STORAGE_KEY);localStorage.removeItem(DIVIDEND_HIDE_KEY);renderDividendEmpire();showToast("個人データを削除しました")});
}

document.addEventListener("DOMContentLoaded",renderDividendEmpire);
