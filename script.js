function showToast(message){let toast=document.getElementById("hosToast");if(!toast){toast=document.createElement("div");toast.id="hosToast";toast.className="toast";toast.setAttribute("role","status");toast.setAttribute("aria-live","polite");document.body.appendChild(toast)}toast.textContent=message;toast.classList.add("show");clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>toast.classList.remove("show"),2200)}
function copyPrompt(id){const el=document.getElementById(id);if(!el)return;const text=el.innerText;navigator.clipboard.writeText(text).then(()=>{recordSkillUsage(id);showToast("プロンプトをコピーしました")})}
function buildInboxPrompt(){const val=document.getElementById("inboxText")?.value.trim()||"（ここに未整理の入力を入れる）";saveInboxEntry(val);const out=`HOS v0.8のInboxに以下の入力を入れます。\n\n入力内容：\n${val}\n\n以下の形式で、事実と解釈を分けながら整理してください。UIテキストは日本語で、日次OSとして次に動ける粒度にしてください。\n\n1. どのBrainで考えるべきか\n- 主Brain：\n- 補助Brain：\n- 理由：\n\n2. 使うSkill\n- 使用Skill：\n- 使う目的：\n\n3. 紐づけるProject\n- 関連Project：\n- 新規Project化の必要性：\n\n4. 事実\n- 入力から確認できる事実：\n- まだ不明な事実：\n\n5. 解釈\n- いま考えられる仮説：\n- 注意すべき思い込み：\n\n6. 次に考える問い\n- 問い1：\n- 問い2：\n- 問い3：\n\n7. 最初のアウトプット案\n- 形式：\n- 見出し案：\n- まず書く内容：`;document.getElementById("inboxPrompt").innerText=out}

const HOS_PROJECTS=[
{id:"honda",title:"Honda",emoji:"🏍",brain:"経営脳",summary:"経営方針からビジョン、重点投資、KPI、リスクを抜き出し、1ページの分析メモにする。",url:"projects.html#honda",updated:"2026-07-05",skill:"企業分析Skill",theme:"中期経営計画と競争優位",questions:["Hondaの競争優位はEV・SDV時代も維持できるか。","重点投資はどの職種・組織能力を必要としているか。"]},
{id:"benefits",title:"福利厚生3.0",emoji:"👥",brain:"人事脳",summary:"対象層、解く課題、期待効果、運用負荷、説明メッセージを制度設計シートにまとめる。",url:"projects.html#benefits",updated:"2026-07-04",skill:"ROI整理Skill",theme:"福利厚生ROIと言語化",questions:["この制度は誰の困りごとを最も強く解くのか。","経営が投資判断できる指標は何か。"]},
{id:"globis",title:"グロービス学習",emoji:"📚",brain:"学習脳",summary:"直近の学習メモを構造化メモ、HTML教材案、3問ドリルに変換する。",url:"projects.html#globis",updated:"2026-07-03",skill:"教材化Skill",theme:"学習メモの教材化",questions:["この学習内容は、どの業務判断に使えるか。","理解度を確認するには、どんな問いが必要か。"]}
];
const HOS_RECENT_KNOWLEDGE=[
{title:"Knowledge Loop",url:"knowledge.html#knowledge-loop",summary:"Inboxから生まれた概念をProjectで使って更新する循環。"},
{title:"福利厚生ROI",url:"knowledge.html#benefits-roi",summary:"福利厚生を経営投資として説明するための評価軸。"},
{title:"中期経営計画",url:"knowledge.html#midterm-plan",summary:"企業の優先順位と採用・投資テーマを読む入口。"}
];
const DEFAULT_SKILLS=["企業分析Skill","ROI整理Skill","教材化Skill"];
function readJson(key,fallback){try{return JSON.parse(localStorage.getItem(key))??fallback}catch{return fallback}}
function writeJson(key,value){localStorage.setItem(key,JSON.stringify(value))}
function saveInboxEntry(text){if(!text||text.startsWith("（ここに"))return;const entries=readJson("hosInboxEntries",[]);entries.unshift({text,createdAt:new Date().toISOString(),status:"open"});writeJson("hosInboxEntries",entries.slice(0,50))}
function recordSkillUsage(promptId){const skillMap={"prompt-honda":"企業分析Skill","prompt-benefits":"ROI整理Skill","prompt-globis":"教材化Skill",inboxPrompt:"Inbox整理Skill"};const skill=skillMap[promptId]||"プロンプト活用Skill";const skills=readJson("hosRecentSkills",[]).filter(item=>item.name!==skill);skills.unshift({name:skill,usedAt:new Date().toISOString()});writeJson("hosRecentSkills",skills.slice(0,6))}
function resetDashboardLocalData(){localStorage.removeItem("hosInboxEntries");localStorage.removeItem("hosRecentSkills");localStorage.removeItem("hosTodayProject");renderDashboard();showToast("Dashboardのローカル状態を初期化しました")}
function formatDate(value){return new Intl.DateTimeFormat("ja-JP",{month:"numeric",day:"numeric"}).format(new Date(value))}
function currentWeekTheme(project){const week=Math.floor((Date.now()-new Date(new Date().getFullYear(),0,1).getTime())/(7*24*60*60*1000));return HOS_PROJECTS[(HOS_PROJECTS.findIndex(p=>p.id===project.id)+week)%HOS_PROJECTS.length]}
function renderDashboard(){const select=document.getElementById("todayProjectSelect");if(!select)return;select.innerHTML=HOS_PROJECTS.map(p=>`<option value="${p.id}">${p.emoji} ${p.title}</option>`).join("");const saved=localStorage.getItem("hosTodayProject")||HOS_PROJECTS[0].id;select.value=HOS_PROJECTS.some(p=>p.id===saved)?saved:HOS_PROJECTS[0].id;const renderProject=()=>{const project=HOS_PROJECTS.find(p=>p.id===select.value)||HOS_PROJECTS[0];localStorage.setItem("hosTodayProject",project.id);document.getElementById("todayProjectTitle").textContent=`${project.emoji} ${project.title}`;document.getElementById("todayProjectSummary").textContent=project.summary;document.getElementById("todayProjectLink").href=project.url;const theme=currentWeekTheme(project);document.getElementById("weekThemeTitle").textContent=theme.theme;document.getElementById("weekThemeSummary").textContent=`${theme.title}を入口に、${theme.brain}で1つの成果物へ変換する。`;document.getElementById("weekThemeBadge").textContent=theme.skill;document.getElementById("nextQuestions").innerHTML=project.questions.map(q=>`<li>${escapeHtml(q)}</li>`).join("")};select.onchange=renderProject;renderProject();document.getElementById("recentUpdates").innerHTML=HOS_PROJECTS.map(p=>`<a class="mini-row" href="${p.url}"><strong>${p.emoji} ${escapeHtml(p.title)}</strong><span>${formatDate(p.updated)} 更新 · ${escapeHtml(p.skill)}</span></a>`).join("");document.getElementById("recentKnowledge").innerHTML=HOS_RECENT_KNOWLEDGE.map(k=>`<a class="mini-row" href="${k.url}"><strong>${escapeHtml(k.title)}</strong><span>${escapeHtml(k.summary)}</span></a>`).join("");const inbox=readJson("hosInboxEntries",[]).filter(item=>item.status!=="done");document.getElementById("inboxCount").textContent=inbox.length;document.getElementById("inboxCountLabel").textContent=inbox.length?"未整理の入力があります":"未整理の入力はありません";const skills=readJson("hosRecentSkills",[]);const names=(skills.length?skills.map(s=>s.name):DEFAULT_SKILLS);document.getElementById("recentSkills").innerHTML=names.map(name=>`<span class="badge">${escapeHtml(name)}</span>`).join("")}

const HOS_SEARCH_INDEX=[
{type:"Dashboard",title:"今日のHOS",url:"index.html#dashboard",text:"Dashboard 日次OS 今日動かすProject Inbox Brain Skill AIプロンプト Honda 福利厚生3.0 グロービス学習 次に考える問い"},
{type:"Dashboard",title:"今日動かすProject",url:"index.html#dashboard-projects",text:"Honda 福利厚生3.0 グロービス学習 Projects コピー用プロンプト 経営脳 人事脳 学習脳"},
{type:"Skills",title:"Project Skills",url:"projects.html#honda",text:"企業分析Skill 競合比較Skill 財務分解Skill 採用背景分解Skill 制度設計Skill ROI整理Skill 対象層分解Skill 社内説明Skill 復習Skill 教材化Skill ケース分析Skill 理解度ドリル作成Skill"},
{type:"Projects",title:"Honda",url:"projects.html#honda",text:"Honda HOS-PJ-001 企業分析 経営戦略 競争優位 財務 人事 EV SDV Toyota Nissan 企業分析Skill 競合比較Skill 財務分解Skill 採用背景分解Skill"},
{type:"Projects",title:"福利厚生3.0",url:"projects.html#benefits",text:"福利厚生3.0 HOS-PJ-002 人事制度 福利厚生 採用 定着 エンゲージメント 生産性 ROI 制度設計Skill 対象層分解Skill 社内説明Skill"},
{type:"Projects",title:"グロービス学習",url:"projects.html#globis",text:"グロービス学習 HOS-PJ-003 学習 経営戦略 教材 ドリル ケース分析Skill 教材化Skill 復習Skill 理解度ドリル作成Skill"},
{type:"Prompts",title:"Prompt Library",url:"prompts.html#prompt-library",text:"プロンプトライブラリ AI Launcher 経営 人事 学習 レビュー 投資 ChatGPT Claude Codex"},
{type:"Prompts",title:"経営",url:"prompts.html#management",text:"企業分析 戦略レビュー 経営脳 ビジョン 事業構造 競争優位 財務 KPI"},
{type:"Prompts",title:"人事",url:"prompts.html#hr",text:"制度設計 採用背景 福利厚生 ROI 対象者 経営課題 運用負荷"},
{type:"Prompts",title:"学習",url:"prompts.html#learning",text:"教材化 復習ドリル 学習メモ 具体例 理解度ドリル"},
{type:"Prompts",title:"レビュー",url:"prompts.html#review",text:"文章レビュー 意思決定レビュー 論理構成 判断基準 リスク"},
{type:"Prompts",title:"投資",url:"prompts.html#investment",text:"投資仮説 決算メモ 成長ドライバー 資本配分 バリュエーション"},
{type:"Brain",title:"OS憲法",url:"brain.html#constitution",text:"構造 事実と解釈 比較 経営 財務 人事 市場 目的 抽象 具体 次に考える問い"},
{type:"Brain",title:"Compass",url:"brain.html#compass",text:"目的 本質課題 全体最適 長期価値 リスク 次の一手"},
{type:"Brain",title:"Brain一覧",url:"brain.html#brains",text:"経営脳 人事脳 金融脳 投資脳 学習脳 体験設計脳 戦略 競争優位 財務 採用 育成 制度 福利厚生 M&A 資本政策"},
{type:"Brain",title:"Brainの使い方",url:"brain.html#brain-flow",text:"Inbox Brain Skill Project Knowledge 受ける 考える 処理する 保存する 接続する"},
{type:"Knowledge",title:"ROIC",url:"knowledge.html#roic",text:"投下資本 利益 資本効率 成長の質 事業ポートフォリオ 経営脳 投資脳 Honda グロービス学習 財務分解Skill 企業分析Skill 投資 中級 よく使う"},
{type:"Knowledge",title:"福利厚生ROI",url:"knowledge.html#benefits-roi",text:"福利厚生 投資 採用 定着 生産性 経営言語 人事脳 経営脳 福利厚生3.0 ROI整理Skill 社内説明Skill 人事 中級 最近追加"},
{type:"Knowledge",title:"採用背景",url:"knowledge.html#hiring-context",text:"求人票 事業課題 組織課題 現場 候補者提案 求人理解 人材市場脳 人事脳 Honda 採用背景分解Skill 人事 基礎 よく使う"},
{type:"Knowledge",title:"資本配分",url:"knowledge.html#capital-allocation",text:"投資 配当 自社株買い M&A 資本 意思決定 長期価値 経営脳 投資脳 金融脳 Honda 企業分析Skill 意思決定レビューSkill 経営 応用"},
{type:"Knowledge",title:"競争優位",url:"knowledge.html#competitive-advantage",text:"他社 継続的 選ばれる 利益 強み 戦略評価 企業比較 経営脳 投資脳 Honda グロービス学習 競合比較Skill ケース分析Skill 経営 基礎 よく使う"},
{type:"Knowledge",title:"中期経営計画",url:"knowledge.html#midterm-plan",text:"戦略 KPI 投資方針 成長シナリオ 優先順位 採用 投資テーマ 経営脳 投資脳 人事脳 Honda 企業分析Skill 採用背景分解Skill 経営 中級 最近追加"},
{type:"Knowledge",title:"Knowledge Loop",url:"knowledge.html#knowledge-loop",text:"Inbox 概念 Knowledgeカード Project 更新 個人知識ベース 学習脳 体験設計脳 グロービス学習 教材化Skill 復習Skill 学習 基礎 最近追加"},
{type:"Knowledge",title:"Knowledge Navigation",url:"knowledge.html#knowledge-controls",text:"カテゴリ タグ 難易度 基礎 中級 応用 最近追加 よく使う 経営 人事 投資 学習 組織"}
];

function escapeHtml(value){return value.replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function highlightMatch(value,query){const safe=escapeHtml(value);const terms=query.trim().split(/\s+/).filter(Boolean).map(t=>t.replace(/[.*+?^${}()|[\]\\]/g,"\\$&"));if(!terms.length)return safe;return safe.replace(new RegExp(`(${terms.join("|")})`,"gi"),"<mark>$1</mark>")}
function initGlobalSearch(){const input=document.getElementById("globalSearch");const box=document.getElementById("searchResults");if(!input||!box)return;const render=()=>{const q=input.value.trim().toLowerCase();if(!q){box.innerHTML="";box.classList.remove("open");return}const terms=q.split(/\s+/).filter(Boolean);const hits=HOS_SEARCH_INDEX.filter(item=>terms.every(term=>`${item.title} ${item.type} ${item.text}`.toLowerCase().includes(term))).slice(0,8);box.classList.add("open");box.innerHTML=hits.length?hits.map(item=>`<a class="search-result" href="${item.url}"><span>${escapeHtml(item.type)}</span><strong>${highlightMatch(item.title,input.value)}</strong><small>${highlightMatch(item.text,input.value)}</small></a>`).join(""):`<p class="search-empty">該当するHOS項目が見つかりません。</p>`};input.addEventListener("input",render);input.addEventListener("focus",render);document.addEventListener("click",e=>{if(!e.target.closest(".global-search")){box.classList.remove("open")}})}
function scrollToHash(){if(!location.hash)return;setTimeout(()=>{const target=document.getElementById(decodeURIComponent(location.hash.slice(1)));target?.scrollIntoView({behavior:"smooth",block:"start"});target?.classList.add("target-flash");setTimeout(()=>target?.classList.remove("target-flash"),1600)},80)}
document.addEventListener("DOMContentLoaded",()=>{initGlobalSearch();renderDashboard();scrollToHash()});
