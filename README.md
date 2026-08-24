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


## 長期運用の設計原則
HOSは単なるチャットボットではなく、**HOS AI Company**という仮想企業として動作する個人OSです。

### Company Model
- HOS Orchestratorは、基本的に自ら専門作業を行わない。
- CEOは、依頼整理、担当割当、品質判断、最終統合のみを担当する。
- 各Agentは、明確に区切られた担当範囲を持つ独立した専門家として振る舞う。
- Agentは、他Agentの担当範囲へ介入したり、他Agentの成果物を書き換えたりしない。

### Orchestration Model
- Agent同士は直接通信しない。
- Agent間の情報受け渡しは、必ずOrchestratorとWorkflow contextを経由する。
- Agentの依存関係はWorkflow定義のみで管理する。
- Agentの追加、削除、実行順序変更は、Agent同士の依存をハードコードせず、Workflowを書き換えるだけで実現できる構造にする。

### Output Contract
- 全Agentは、成果物をJSON形式のみで返却する。
- Markdown文章は、最終統合時にCEOのみが生成する。
- 専門Agentはレポート素材を構造化データとして返してよいが、最終Markdown文書は生成しない。

### Extensibility
- 新Agentは、Agent定義を追加し、Workflowへ登録し、Orchestrator管理のcontextで入力を受け取るプラグイン形式で追加する。
- 将来的に100人程度のAgentまで増えることを前提に設計する。
- WorkflowをAgent依存関係の唯一の情報源にし、HOSを直接結合なしで拡張できる状態に保つ。

## GitHub Actions: Stock Watch

`.github/workflows/stock-watch-diagnostic.yml` runs the production entrypoint
`skills/investment-agent/stock_watch_runner.py`. It requires exactly two
private delivery inputs: `DISCORD_WEBHOOK_URL` and
`HOS_PRIVATE_PROFILE_JSON`. The latter contains all household targets,
balances, holdings, strategy steps, and execution state.

Public logs, GitHub Summary, artifacts, and commits contain only a value-free
heartbeat. Details are rendered only to Discord. See
[`docs/PRIVATE_PROFILE_SETUP.md`](docs/PRIVATE_PROFILE_SETUP.md).

## HOS v2 AI Company dry-run

Run the investment vertical slice without external API keys:

```bash
python -m orchestrator.runner tasks/inbox/investment_analysis.sample.json
```

Use `--dry-run` to validate execution without writing artifacts:

```bash
python -m orchestrator.runner tasks/inbox/investment_analysis.sample.json --dry-run
```

Architecture details are in `docs/HOS_Architecture_v2.md` and ADRs in `docs/adr/`.


## HOS AI Company Usable MVP

Open `ai-company.html` to create Task JSON, inspect the Agent Registry, view workflows, and paste Run bundle JSON into the Run Viewer.

Core commands:

```bash
python -m orchestrator.cli doctor
python -m orchestrator.cli validate-agents
python -m orchestrator.cli validate-workflows
python -m orchestrator.cli run tasks/inbox/investment_analysis.sample.json --executor mock
```

GitHub Actions workflow: `.github/workflows/hos-ai-company.yml`. It uploads a `hos-run-<run_id>` artifact containing run metadata, step outputs, final report, HOS update JSON, Investment Commander JSON, reflection, logs, and diagnostics.

Manual GitHub Actions runs accept exactly one repository-relative `Repository task path` format when `Task JSON payload` is empty: include the full path under `tasks/inbox/`, for example `tasks/inbox/FACT-285A-RETRY-001.json`. Do not enter only the filename; the workflow does not prepend `tasks/inbox/` internally.

Real AI execution uses `--executor openai` and requires `OPENAI_API_KEY`; it never reports success by silently falling back to mock. See `docs/QUICKSTART_AI_COMPANY.md`. Current audited status and known constraints are documented in `docs/HOS_AI_COMPANY_STATUS_2026-07-13.md`.


## Gemini free-tier AI Company execution

HOS AI Company can run against Google Gemini API without requiring OpenAI paid API usage. Use `--executor gemini`, set `GEMINI_API_KEY`, and prefer the 5-agent `investment_analysis_free` workflow for free-tier tests. Usage is written to `runs/<run_id>/usage.json`; quota exhaustion produces partial/failed results and never auto-switches to OpenAI or mock. See `docs/QUICKSTART_GEMINI_FREE.md`, `docs/SECURITY_AI_COMPANY.md`, and `docs/OPERATIONS_AI_COMPANY.md`.

## Stock Watch

Stock Watch is a long-term household portfolio monitor. Public configuration is
non-actionable; the live strategy is private. Missing fundamentals, valuation,
official-IR evidence, budget, cash-floor, holding reconciliation, or freshness
data blocks purchases. `PURCHASE_READY` does not place an order, and HOS has no
automatic buy or sell capability.

### Gemini structured-output smoke test

Gemini executor uses official Structured Output (`responseSchema`) for agent-specific data and builds the HOS envelope locally. Set `GEMINI_MODEL=gemini-2.5-flash` or another validated generateContent model, then run `python -m orchestrator.cli gemini-smoke-test` or dispatch the GitHub Action with `gemini_smoke_test=true` for a single-call connectivity/schema check.

## Verified Investment Fact Pipeline
Investment workflows now build a deterministic Fact Pack before any Gemini agent runs. Agents may only use its `fact_refs` and `source_map`; missing data produces `DATA_INSUFFICIENT`, contradictions produce `REVIEW_REQUIRED`, and automatic BUY/orders are prohibited. See [design](docs/INVESTMENT_FACT_PIPELINE_DESIGN.md), [operations](docs/INVESTMENT_FACT_PIPELINE_OPERATIONS.md), [source policy](docs/INVESTMENT_SOURCE_POLICY.md), and [evidence policy](docs/INVESTMENT_EVIDENCE_POLICY.md).


## Verified Investment Analysis Lite

The recommended investment workflow is `investment_analysis_verified_lite`: Python builds a source-bound Fact Pack first, then Gemini is limited to two calls (analysis + review/integration). Use `fact_pack_only=true` to generate Fact Pack artifacts without Gemini. Network providers require both `HOS_FACT_MODE=network_verified` and `HOS_ENABLE_NETWORK_FACTS=true`; paid APIs and OpenAI fallback are not automatic.
