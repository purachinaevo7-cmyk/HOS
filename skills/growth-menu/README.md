# Growth Menu Loop

毎朝、経営・人事・英語の3枚PowerPoint教材を生成し、ChatGPT通知から開き、ユーザーのアウトプット評価を翌日に反映するためのHOSワークフローです。

## 役割分担

- GitHub Actions: 毎朝05:30 JSTに生成・監査・保存。
- OpenAI Responses API: 公開情報を調べ、当日の教材JSONを生成。
- PowerPoint generator: 編集可能な3枚のPPTXを作成。
- ChatGPT scheduled task: 06:30 JSTに監査済み教材を通知。
- ひーちゃん: ユーザーの回答を評価し、匿名化した学習診断だけを `feedback/latest.json` に反映。

## 除外済み

- Duolingo
- Globis / グロービス
- Udemy / Udemy Business

これらは生成・監査の両方で禁止語として検査します。

## ローカル確認

```bash
python skills/growth-menu/generate_growth_menu.py --offline --date 2026-07-20
python skills/growth-menu/audit_growth_menu.py --date 2026-07-20 --write-report
python -m unittest discover -s skills/growth-menu/tests -p 'test_*.py'
```

## 本番生成

GitHub Secret `OPENAI_API_KEY` が必要です。Repository variable `OPENAI_MODEL` は省略時 `gpt-5-mini` です。

```bash
python skills/growth-menu/generate_growth_menu.py
python skills/growth-menu/audit_growth_menu.py --write-report
```

## フィードバック保存

公開リポジトリのため、生の回答は保存しません。評価後に、一般化・匿名化した診断JSONだけを保存します。

```bash
python skills/growth-menu/record_feedback.py /tmp/redacted_feedback.json
```

翌日の生成は `feedback/latest.json` と直近7日分の教材テーマを読み込みます。
