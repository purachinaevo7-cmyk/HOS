# HOS Sauna Review Pipeline

## 目的

サウナレビューを文章のまま散らかさず、訪問ログとして蓄積し、施設ランキング・再訪履歴・特徴検索に使える状態へ変換します。

## 構成

- `sauna.html`: サウナレビュー・ダッシュボード
- `sauna.js`: 集計、検索、絞り込み、施設別履歴の表示
- `sauna.css`: 専用スタイル
- `data/sauna/reviews.json`: 正式な訪問ログ
- `data/sauna/summary.json`: 自動生成される施設別集計
- `tools/sauna_review_import.py`: レビューテンプレートの解析・追加・重複防止
- `.github/ISSUE_TEMPLATE/sauna-review.yml`: スマホ入力フォーム
- `.github/workflows/sauna-review-import.yml`: 自動取込・コミット

## スマホから追加する

1. GitHubのHOSリポジトリで **Issues → New issue → サウナレビュー追加** を開く。
2. ChatGPTで完成させたレビュー全文を貼る。
3. 訪問日が分かる場合は `YYYY-MM-DD` で入力する。
4. Issueを送信する。
5. GitHub Actionsがレビューを解析し、`reviews.json` と `summary.json` を更新する。
6. 成功時はIssueへ結果をコメントし、自動で閉じる。

Cloudflare Pagesが`main`ブランチと連携していれば、その後のデプロイで `sauna.html` に反映されます。

## ローカルまたはCodexから追加する

```bash
python tools/sauna_review_import.py   --input /path/to/review.txt   --date 2026-07-26   --source chatgpt
```

解析だけ確認する場合:

```bash
python tools/sauna_review_import.py   --input /path/to/review.txt   --check
```

## 対応テンプレート

`-` と `*` のどちらの箇条書きでも解析できます。`訪問日`は任意です。

```text
施設名：
訪問日：

🔥 一言まとめ（キャッチコピー）：

総合評価（10点満点）：

- 好きだった点
  #サウナ：
  #水風呂：
  #外気浴：
  #導線：
  #混み具合：

- 微妙だった点：

- 混雑（時間帯）：

- メモ（次回の入り方・持ち物・リピ条件）：
```

## データ運用

- 同じレビュー本文はハッシュで判定し、二重登録しません。
- 同じ施設でも別日のレビューは別レコードとして追加します。
- 施設別ランキングは全訪問の平均点です。
- `detail_level: score_only` の旧レビューは初期移行データです。再訪時に詳細レビューを追加すると施設履歴が育ちます。
- タグは本文の語句から決定論的に付与します。AIによる勝手な評価補完は行いません。

## 次の拡張候補

- 訪問時刻と曜日による混雑傾向
- 所在地・緯度経度を使った地図
- 料金、滞在時間、移動時間を含むコスパ
- 「短時間で仕上げたい」「景色重視」など条件別レコメンド
- 写真との紐付け
