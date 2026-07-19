# HOS Growth Menu Loop 運用・監査仕様

## 1. ゴール

1. 毎朝05:30 JSTに3枚のPowerPoint教材を生成する。
2. 生成後に構造・禁止項目・フォント・プライバシー・リンクを監査する。
3. 監査合格品だけを `outputs/growth-menu/latest.pptx` として公開する。
4. 毎朝06:30 JSTにChatGPTのタスクが短い通知と教材リンクを届ける。
5. ユーザーは同じチャットへ日本語アウトプットと英作文を返す。
6. ひーちゃんは回答を評価し、匿名化した診断のみをGitHubへ記録する。
7. 翌日の生成が最新診断を読み込み、難易度と論点を調整する。

## 2. 教材の固定構成

- 1枚目: 今日の設計、前回評価、重点、完了条件、所要時間。
- 2枚目: 経営・人事、公表資料、見る観点3つ、問い、150〜250字の課題。
- 3枚目: 文法1テーマ、誤り例、正解例、説明、単語5語、英作文1問。

Duolingo、Globis、グロービス、Udemy、Udemy Businessは含めません。

## 3. PowerPoint仕様

- 16:9。
- Yu Gothic UI。
- タイトル20pt、本文16pt、注釈14pt、締め18pt。
- 背景図形とテキストボックスを分離せず、原則として図形内テキスト。
- 編集可能なPPTX。画像化しない。

## 4. 評価ルール

### 経営・人事

- 問いへの回答度。
- 根拠の具体性。
- 業界構造と個社戦略の切り分け。
- 顧客価値とコスト構造の両面。
- 財務と人材への接続。

### 英語

- 主語と動詞。
- 冠詞と単数・複数。
- 接続詞。
- 前置詞と動詞の型。
- 自然なビジネス表現。

評価は、良かった点、改善点、修正文、翌日の重点を返します。GitHubへは生の回答や固有の社内情報を保存せず、一般化した診断だけを保存します。

## 5. セキュリティ

HOSは公開リポジトリです。次をGitHubへ書き込みません。

- 生のユーザー回答。
- 顧客名、候補者名、連絡先。
- 社内限定情報、未公表情報。
- メール本文や会議メモの原文。

公開企業のIR分析でも、保存するフィードバックは「根拠と結論の接続が弱い」のような抽象化された学習診断に限定します。

## 6. 失敗時

- API失敗: 代替教材を勝手に生成せず、workflowを失敗させる。
- 監査失敗: `latest.pptx`をコミットしない。
- 06:30時点で当日分がない: ChatGPTは「未生成・要確認」と短く通知し、古い教材を今日分として扱わない。
- GitHub Pagesに依存せず、通知はraw GitHubの固定URLを使う。

## 7. ChatGPT scheduled task の指示

```text
毎朝、GitHubの purachinaevo7-cmyk/HOS の main ブランチから
outputs/growth-menu/latest.json、outputs/growth-menu/audit/latest.json、
outputs/growth-menu/latest_notification.md を確認する。

Asia/Tokyoの今日の日付と latest.json の date が一致し、
audit/latest.json の status が pass の場合だけ、
latest_notification.mdを基にスマホ向けの短い通知を送る。
PowerPointリンクは次を使う:
https://raw.githubusercontent.com/purachinaevo7-cmyk/HOS/main/outputs/growth-menu/latest.pptx

当日分でない、監査がpassでない、ファイルがない場合は、
古い教材を今日分として出さず「本日の教材は未生成・要確認」と通知する。
Duolingo、Globis、グロービス、Udemyを追加しない。
```

## 8. Codexの役割

Codexはこの仕組みの実装・修正・監査担当です。日次実行は、端末の起動状態に依存しないGitHub Actionsで行います。Codex Automationを併用する場合は、同じコマンドを実行して監査結果をレビュー対象にしますが、二重生成を避けるため本番スケジュールは一方だけにします。
