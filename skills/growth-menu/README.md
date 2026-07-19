# Growth Menu Loop

毎朝、経営・人事・英文法を学ぶ4枚のPowerPoint授業を生成し、ChatGPT通知から開き、ユーザーのアウトプット評価を翌日に反映するHOSワークフローです。

## PowerPointの役割

PowerPointは提出用紙ではなく、次の4枚からなる授業資料です。

1. 学習マップ
2. 経営・人事の理論授業
3. ケースへの当てはめ
4. 英文法の授業

提出案内はPowerPointに入れず、朝のChatGPT通知だけに表示します。

## 生成方式

- 本番は `GEMINI_API_KEY` を使い、Gemini無料枠を1日1回呼び出します。
- OpenAI APIは使用しません。
- OpenAIや有料モデルへのフォールバックはありません。
- Google検索グラウンディングも使用しません。
- Geminiは教材シードの説明を整えるだけで、ケースの観察事実はリポジトリ内の `curriculum_seeds.json` から固定します。
- API未設定・無料枠上限・モデルエラーの場合は、古い教材や別プロバイダーへ黙って切り替えず、生成を失敗させます。

## 除外済み

- Duolingo
- Globis / グロービス
- Udemy / Udemy Business

生成と監査の両方で混入を拒否します。

## ローカル確認

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
3. スライド4の英作文

ひーちゃんは回答を評価し、生の回答ではなく匿名化した診断だけを `feedback/latest.json` に保存します。翌日のテーマ選択と英文法の重点はこの診断を参照します。
