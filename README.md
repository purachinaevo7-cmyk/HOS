# 🧠 HOS v0.9 (Hichan Operating System)

思考を資産化するための個人OS。v0.9ではOutputs Libraryを追加し、HTML・PowerPoint・PDF・Markdown・Reviewの成果物を、Project、作成日、使用Brain、使用Skill、ダウンロードリンク、検索キーワード、タグ、お気に入りで管理できるようにします。

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
- Outputs: `outputs.html`
  HTML、PowerPoint、PDF、Markdown、Reviewの成果物を、検索・カテゴリ・お気に入り・タグで探せるOutputs Library。
- Prompts: `prompts.html`
  経営・人事・学習・レビュー・投資のプロンプトをAIへすぐ渡せる形で保存する場所。

## v0.9で追加したこと
- Outputsページを新設。
- OutputカテゴリとしてHTML、PowerPoint、PDF、Markdown、Reviewを追加。
- 各Output Cardにタイトル、Project、作成日、使用Brain、使用Skill、ダウンロードリンク、検索キーワード、タグ、お気に入りを表示。
- Outputsページ内検索、カテゴリ絞り込み、お気に入り絞り込みを追加。
- グローバル検索と全ページナビゲーションにOutputsを追加。
- すべて静的HTML/CSS/JavaScriptだけで動作し、ローカルファイルまたはローカルサーバーで利用可能。

## Philosophy
Think First. Build Second.

## GitHub Actions: Stock Watch

`.github/workflows/stock-watch.yml` は、平日18:00頃（JST）に `scripts/stock_watch.py` を実行するワークフローです。`workflow_dispatch` にも対応しているため、GitHub Actions画面から手動実行できます。

### セットアップ手順

1. GitHubリポジトリの **Settings > Secrets and variables > Actions** を開きます。
2. **New repository secret** から `DISCORD_WEBHOOK_URL` を追加し、DiscordのWebhook URLを登録します。
3. `requirements.txt` に必要なPython依存関係が含まれていることを確認します。
4. GitHubの **Actions > Stock Watch** を開き、必要に応じて **Run workflow** から手動実行します。

### 実行内容

- Python 3.12をセットアップします。
- `requirements.txt` をインストールします。
- `DISCORD_WEBHOOK_URL` を環境変数として渡し、`python scripts/stock_watch.py` を実行します。
- 実行ログは `logs/stock-watch.log` に保存し、ジョブの成功・失敗にかかわらず `stock-watch-logs` artifactとしてアップロードします。
