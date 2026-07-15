# Stock Watch V2 Audit

## 現状構成
- GitHub Actions: `.github/workflows/stock-watch.yml` が夜間通常取得と朝補完取得を実行する。
- Entry point: `skills/investment-agent/daily_stock_check.py`。
- Data fetch: `stock_fetcher.py` がYahoo Finance batch、Yahoo Finance、JPX設定CSV、TradingView、Stooq、Investing.com、TOPIX ETF中央値を試行する。
- Decision: `stock_analyzer.py` が前日比下落率とTOPIX分類でA/B/保留へ分類する。
- Report/Discord: `stock_reporter.py` と `notifier.py` が長文レポートをDiscordへ送る。
- UI: `investment.js` はInvestment CommanderをlocalStorage中心に管理している。

## データフロー
`watchlist.yaml` → fetch providers → daily price JSON → analyzer → reporter → console/GitHub Summary/Discord。朝補完は前夜JSONの未取得銘柄のみ再取得し、既取得データを再利用する。

## 現行判定式
- TOPIXが市場下落閾値以下ならA。
- TOPIXが中立レンジならB。
- 銘柄前日比がvolatility別閾値以下のときだけA/B候補。
- 買いレンジは当日終値からvolatility別の固定パーセントで算出。

## 現行監視銘柄
12銘柄: 5713, 5711, 2768, 7456, 4063, 6981, 8001, 8002, 7832, 9697, 9684, 5698。

## 問題点
- 前日比とTOPIX比較が中心で、52週高値、PER/PBR、配当利回り、業績、ポートフォリオ上限を判定に使えていない。
- 全銘柄の取得成功ログとTOPIX失敗ログが通常通知に混入し、Discordが長い。
- 予算・現金余力・単一銘柄上限・業種上限・分割購入株数が未接続。
- 60歳2億円、年間配当600万円目標との接続がない。
- 無料データ基盤で取得できないfundamentals/newsを補完できない。

## 改修方針
- V2設定をJSON化し、30〜40銘柄を役割別に管理する。
- TOPIXは下落理由分類の補助指標に格下げする。
- BUYは価格、企業状態、還元、ポートフォリオ、予算、データ鮮度の複合条件でのみ出す。
- 不足データはmissing_fields/hard_blocksへ保存し、BUYを抑止する。
- DiscordはWATCH以上のみ短文通知し、詳細はoutputs JSONへ保存する。

## データ取得上の制約
無料fetcherの安定取得対象は価格と前日終値が中心。PER/PBR、配当利回り、決算、ニュースは現時点では必須取得できないため、不足時はBUY_CANDIDATE以下に制限する。

## 投資判断として利用してよい情報
- 既存fetcherで取得した株価、前日終値、取得日、TOPIX/代理指数。
- ユーザーが設定した保有数、平均取得単価、予算、目標、上限。
- 取得日が保存されたfundamentals/valuation/news（将来拡張）。

## 利用してはいけない情報
- 取得できていないPER/PBR/配当/業績/ニュースの推測値。
- 古い日付の価格と別日付の指数を混ぜた判定。
- 「必ず上がる」「絶対買い」など断定表現。
- 実発注や証券口座操作。

## 既知のリスク
- Yahoo/外部無料Providerの仕様変更、Rate Limit、日付不一致。
- 予算と保有株数が未入力だとBUYを出せない。
- localStorage UI設定と実行基盤JSON設定は自動同期されない。
