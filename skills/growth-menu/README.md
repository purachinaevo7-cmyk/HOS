# Growth Menu Loop

毎朝、経営・人事・英文法を学ぶ5ページのPDF授業を生成し、1ページ目の画像プレビューとともにChatGPT通知から開き、ユーザーのアウトプット評価を翌日に反映するHOSワークフローです。

## PDFの役割

PDFは提出用紙ではなく、次の5ページからなる授業資料です。

1. 学習マップ
2. 会社・事業スナップショット
3. 経営・人事の理論授業
4. ケースへの当てはめ
5. 英文法の授業

会社ケースでは、会社名、顧客、提供価値、ビジネスモデル、価値を生む流れ、主要な規模指標、情報の時点、公式出典を先に示します。一般化した業界ケースでは、会社情報の代わりに事業モデルと構造を示します。

提出案内はPDFに入れず、朝のChatGPT通知だけに表示します。

## 配布形式

- 主配布：`outputs/growth-menu/latest.pdf`
- 画像プレビュー：`outputs/growth-menu/latest-preview.png`
- PowerPointはPDF生成時の一時ファイルとしてのみ使い、配布・保存しません。
- PDF変換にはLibreOffice Impressを使用します。

## 生成方式

- 本番は `GEMINI_API_KEY` を使い、Gemini無料枠を1日1回呼び出します。
- OpenAI APIは使用しません。
- OpenAIや有料モデルへのフォールバックはありません。
- Google検索グラウンディングも使用しません。
- Geminiは教材シードの説明を整えるだけです。会社・事業情報は `company_seeds.json`、ケース事実は `curriculum_seeds.json` から固定します。
- API未設定・無料枠上限・モデルエラーの場合は、古い教材や別プロバイダーへ黙って切り替えず、生成を失敗させます。

## 除外済み

- Duolingo
- Globis / グロービス
- Udemy / Udemy Business

生成と監査の両方で混入を拒否します。

## ローカル確認

LibreOfficeと日本語フォントが必要です。

```bash
python skills/growth-menu/generate_growth_menu.py --offline --date 2026-07-20
python skills/growth-menu/audit_growth_menu.py --date 2026-07-20 --write-report
python -m unittest discover -s skills/growth-menu/tests -p 'test_*.py'
```

## 本番生成

```bash
export GEMINI_API_KEY="..."
export GEMINI_MODEL="gemini-2.5-flash"
python skills/growth-menu/generate_growth_menu.py
python skills/growth-menu/audit_growth_menu.py --write-report
```

## フィードバック

学習後、ユーザーはChatGPTへ次の3点を返します。

1. 今日理解したこと
2. ケースに対する自分の見解
3. 5ページ目の英作文

ひーちゃんは回答を評価し、生の回答ではなく匿名化した診断だけを `feedback/latest.json` に保存します。翌日のテーマ選択と英文法の重点はこの診断を参照します。
