# 日本株・連続増配スクリーナー

`.github/workflows/dividend-screener.yml` は、長期連続増配または累進配当方針を確認できた日本株を、平日18:30 JSTに評価してDiscordへ送る公開データ専用ジョブです。

## 初回設定

1. GitHubの **Settings → Secrets and variables → Actions** に、専用Webhookの `DIVIDEND_SCREENER_DISCORD_WEBHOOK_URL` を追加する。
2. Actions画面から **Japan Dividend Screener** を手動実行し、最初は `dry_run=true` でデータ取得と文面を確認する。
3. `dry_run=false` で一度だけ実行し、対象Discordチャンネルへの到着を確認する。

既存の `DISCORD_WEBHOOK_URL` は世帯のStock Watch専用です。このジョブには再利用せず、別チャンネル用のWebhookを使います。

## 判定方法

- 最新終値は市場データから取得する。
- 年間配当は `skills/investment-agent/config/dividend_screener_universe.json` に記録した企業IRの**通常配当**だけを使う。
- 過去5〜10年の実績普通配当を各月末株価で割り、P50・P75・最大・現在利回りの歴史的パーセンタイルを計算する。
- 現在予想に特別配当が含まれる銘柄は順位付けから除外する。リコーリース（8566）はこの確認用の除外対象である。
- `valid_through` を過ぎたIR情報、株価未取得、履歴不足は `データ要確認` とし、前回の正常な状態を上書きしない。

順位差分はGitHub Actions Cacheに保存する公開銘柄の順位・格付・利回り指標だけから算出します。キャッシュを削除した場合、次回は初回スナップショットとして通知されます。

## IR更新時のメンテナンス

決算や配当予想修正が出たら、対象銘柄の `official_ir` を更新します。

- `url`: 会社IRまたはJPXの開示URL
- `source_as_of`: その予想を示す開示日
- `ordinary_annual_per_share`: 通常の会社予想年間配当
- `special_annual_per_share`: 特別・記念配当の年間部分
- `valid_through`: この会社予想を使ってよい最終日

TDnetの機械取得は有料APIまたはJ-QuantsのTDnetアドオンを要するため、契約・資格情報なしには有効化しません。現時点では、一次情報URLを明示した設定値を使い、期限切れを自動的に停止する方式です。

## 安全境界

このジョブは、`HOS_PRIVATE_PROFILE_JSON`、既存保有、注文、口座残高、購入可否を読まず、書きません。Discord通知は調査用であり、自動売買・売却・注文を行いません。
