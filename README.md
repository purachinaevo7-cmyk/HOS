# 🧠 HOS v0.8 (Hichan Operating System)

思考を資産化するための個人OS。v0.8ではHomeを「本物のDashboard」に更新し、今日のProject、最近更新、最近追加Knowledge、Inbox件数、最近使ったSkill、今週の学習テーマ、次に考える問いをローカルで確認できるようにします。

## Pages
- Home / Dashboard: `index.html`  
  今日動かすProjectを選び、最近更新、最近追加Knowledge、Inbox件数、最近使ったSkill、今週の学習テーマ、次に考える問いを確認する日次入口。
- Inbox: `inbox.html`  
  雑な入力をBrain、Skill、Project、事実、解釈、次の問い、最初のアウトプット案へ整理する場所。整理プロンプト作成時にローカルInbox件数へ反映します。
- Brain: `brain.html`  
  OS憲法、Compass、Brainの使い方、稼働ProjectごとのBrain使用例を確認する場所。
- Projects: `projects.html`  
  Honda、福利厚生3.0、グロービス学習を、目的・使用Brain・使用Skill・現状メモ・思考ログ・次アクション・成果物・次に考える問い・AIプロンプトまで含む稼働ワークスペースとして育てる場所。
- Knowledge: `knowledge.html`  
  ROIC、福利厚生ROI、採用背景などの概念を、カテゴリ・タグ・難易度・最近追加・よく使う付きのKnowledge Cardとして育てる場所。

## v0.8で追加したこと
- Homeをv0.8 Dashboardとして再設計。
- 「今日のProject」を選択式にし、選択内容をlocalStorageへ保存。
- 「最近更新」「最近追加Knowledge」「Inbox件数」「最近使ったSkill」「今週の学習テーマ」「次に考える問い」をDashboard Widget化。
- Inbox整理プロンプト作成とAI Launchコピーをローカル状態へ連動。
- すべて静的HTML/CSS/JavaScriptだけで動作し、ローカルファイルまたはローカルサーバーで利用可能。

## Philosophy
Think First. Build Second.
