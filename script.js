function copyPrompt(id){const el=document.getElementById(id);if(!el)return;navigator.clipboard.writeText(el.innerText).then(()=>alert("コピーした。あとはChatGPTかClaudeに貼るだけ。"))}
function buildInboxPrompt(){const val=document.getElementById("inboxText")?.value.trim()||"（ここに未整理の入力を入れる）";const out=`HOS v0.5のInboxに以下の入力を入れます。\n\n入力内容：\n${val}\n\n以下の形式で、事実と解釈を分けながら整理してください。UIテキストは日本語で、日次OSとして次に動ける粒度にしてください。\n\n1. どのBrainで考えるべきか\n- 主Brain：\n- 補助Brain：\n- 理由：\n\n2. 使うSkill\n- 使用Skill：\n- 使う目的：\n\n3. 紐づけるProject\n- 関連Project：\n- 新規Project化の必要性：\n\n4. 事実\n- 入力から確認できる事実：\n- まだ不明な事実：\n\n5. 解釈\n- いま考えられる仮説：\n- 注意すべき思い込み：\n\n6. 次に考える問い\n- 問い1：\n- 問い2：\n- 問い3：\n\n7. 最初のアウトプット案\n- 形式：\n- 見出し案：\n- まず書く内容：`;document.getElementById("inboxPrompt").innerText=out}

const HOS_SEARCH_INDEX=[
{type:"Dashboard",title:"今日のHOS",url:"index.html#dashboard",text:"Dashboard 日次OS 今日動かすProject Inbox Brain Skill AIプロンプト Honda 福利厚生3.0 グロービス学習 次に考える問い"},
{type:"Dashboard",title:"今日動かすProject",url:"index.html#dashboard-projects",text:"Honda 福利厚生3.0 グロービス学習 Projects コピー用プロンプト 経営脳 人事脳 学習脳"},
{type:"Skills",title:"Project Skills",url:"projects.html#honda",text:"企業分析Skill 競合比較Skill 財務分解Skill 採用背景分解Skill 制度設計Skill ROI整理Skill 対象層分解Skill 社内説明Skill 復習Skill 教材化Skill ケース分析Skill 理解度ドリル作成Skill"},
{type:"Projects",title:"Honda",url:"projects.html#honda",text:"Honda HOS-PJ-001 企業分析 経営戦略 競争優位 財務 人事 EV SDV Toyota Nissan 企業分析Skill 競合比較Skill 財務分解Skill 採用背景分解Skill"},
{type:"Projects",title:"福利厚生3.0",url:"projects.html#benefits",text:"福利厚生3.0 HOS-PJ-002 人事制度 福利厚生 採用 定着 エンゲージメント 生産性 ROI 制度設計Skill 対象層分解Skill 社内説明Skill"},
{type:"Projects",title:"グロービス学習",url:"projects.html#globis",text:"グロービス学習 HOS-PJ-003 学習 経営戦略 教材 ドリル ケース分析Skill 教材化Skill 復習Skill 理解度ドリル作成Skill"},
{type:"Brain",title:"OS憲法",url:"brain.html#constitution",text:"構造 事実と解釈 比較 経営 財務 人事 市場 目的 抽象 具体 次に考える問い"},
{type:"Brain",title:"Compass",url:"brain.html#compass",text:"目的 本質課題 全体最適 長期価値 リスク 次の一手"},
{type:"Brain",title:"Brain一覧",url:"brain.html#brains",text:"経営脳 人事脳 金融脳 投資脳 学習脳 体験設計脳 戦略 競争優位 財務 採用 育成 制度 福利厚生 M&A 資本政策"},
{type:"Brain",title:"Brainの使い方",url:"brain.html#brain-flow",text:"Inbox Brain Skill Project Knowledge 受ける 考える 処理する 保存する 接続する"},
{type:"Knowledge",title:"ROIC",url:"knowledge.html#roic",text:"投下資本 利益 資本効率 成長の質 事業ポートフォリオ 経営脳 投資脳 Honda グロービス学習"},
{type:"Knowledge",title:"福利厚生ROI",url:"knowledge.html#benefits-roi",text:"福利厚生 投資 採用 定着 生産性 経営言語 人事脳 経営脳 福利厚生3.0"},
{type:"Knowledge",title:"採用背景",url:"knowledge.html#hiring-context",text:"求人票 事業課題 組織課題 現場 候補者提案 求人理解 人材市場脳 人事脳 Honda"},
{type:"Knowledge",title:"資本配分",url:"knowledge.html#capital-allocation",text:"投資 配当 自社株買い M&A 資本 意思決定 長期価値 経営脳 投資脳 金融脳 Honda"},
{type:"Knowledge",title:"競争優位",url:"knowledge.html#competitive-advantage",text:"他社 継続的 選ばれる 利益 強み 戦略評価 企業比較 経営脳 投資脳 Honda グロービス学習"},
{type:"Knowledge",title:"中期経営計画",url:"knowledge.html#midterm-plan",text:"戦略 KPI 投資方針 成長シナリオ 優先順位 採用 投資テーマ 経営脳 投資脳 人事脳 Honda"}
];

function escapeHtml(value){return value.replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function highlightMatch(value,query){const safe=escapeHtml(value);const terms=query.trim().split(/\s+/).filter(Boolean).map(t=>t.replace(/[.*+?^${}()|[\]\\]/g,"\\$&"));if(!terms.length)return safe;return safe.replace(new RegExp(`(${terms.join("|")})`,"gi"),"<mark>$1</mark>")}
function initGlobalSearch(){const input=document.getElementById("globalSearch");const box=document.getElementById("searchResults");if(!input||!box)return;const render=()=>{const q=input.value.trim().toLowerCase();if(!q){box.innerHTML="";box.classList.remove("open");return}const terms=q.split(/\s+/).filter(Boolean);const hits=HOS_SEARCH_INDEX.filter(item=>terms.every(term=>`${item.title} ${item.type} ${item.text}`.toLowerCase().includes(term))).slice(0,8);box.classList.add("open");box.innerHTML=hits.length?hits.map(item=>`<a class="search-result" href="${item.url}"><span>${escapeHtml(item.type)}</span><strong>${highlightMatch(item.title,input.value)}</strong><small>${highlightMatch(item.text,input.value)}</small></a>`).join(""):`<p class="search-empty">該当するHOS項目が見つかりません。</p>`};input.addEventListener("input",render);input.addEventListener("focus",render);document.addEventListener("click",e=>{if(!e.target.closest(".global-search")){box.classList.remove("open")}})}
function scrollToHash(){if(!location.hash)return;setTimeout(()=>{const target=document.getElementById(decodeURIComponent(location.hash.slice(1)));target?.scrollIntoView({behavior:"smooth",block:"start"});target?.classList.add("target-flash");setTimeout(()=>target?.classList.remove("target-flash"),1600)},80)}
document.addEventListener("DOMContentLoaded",()=>{initGlobalSearch();scrollToHash()});
