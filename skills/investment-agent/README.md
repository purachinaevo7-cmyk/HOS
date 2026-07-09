# HOS Investment Agent

毎営業日、日本株の監視銘柄について終値・前日終値を取得し、TOPIX と比較して「相場要因の下げ」「個別要因っぽい下げ」を判定し、翌営業日の買いレンジ付き通知文を生成する HOS スキルです。

## ディレクトリ構成

```text
skills/investment-agent/
  README.md
  daily_stock_check.py      # 実行入口
  stock_fetcher.py          # データ取得層
  stock_analyzer.py         # 判定ロジック
  stock_reporter.py         # レポート生成
  config/
    watchlist.yaml
    thresholds.yaml
    buy_ranges.yaml
  data/
    daily_prices/
  tests/
    test_stock_analyzer.py
```

## 監視銘柄

`config/watchlist.yaml` で管理します。ウォッチ外銘柄は出力しません。

- 5713, 5711, 2768, 7456, 4063, 6981, 8001, 8002, 7832, 9697, 9684, 5698

## 判定ルール

### TOPIX 判定

- TOPIX 前日比が `-1.0%` 以下: `(A) 相場要因の下げ`
- TOPIX 前日比が `-0.5%〜+0.5%` 以内: `(B) 個別要因っぽい下げ`
- TOPIX データが未取得・日付不一致: A/B 判定保留

### 銘柄しきい値

`config/thresholds.yaml` で管理します。

- 大型: 8001, 8002, 4063, 6981 → `-2.0%`
- ボラ中: 2768, 7832, 9697, 9684, 5711, 7456 → `-3.0%`
- ボラ高: 5713, 5698 → `-4.0%`

### 買いレンジ

`config/buy_ranges.yaml` で管理します。

- 大型: 終値の `-0.5%〜-1.2%`
- ボラ中: 終値の `-1.0%〜-2.0%`
- ボラ高: 終値の `-1.5%〜-3.0%`

## データ取得設計

`stock_fetcher.py` の `PriceProvider` インターフェースにより、銘柄を 1 つずつ順番に取得します。まとめ取得に失敗して全銘柄を未取得扱いにしないため、プロバイダ失敗時も次のプロバイダ・次の銘柄へ進みます。

現在は以下のプロバイダを用意しています。

1. `YFinancePriceProvider`: `yfinance` がインストールされている場合のみ利用
2. `MockPriceProvider`: 外部 API 未設定でも判定・レポート生成まで通すための mock データ

取得データの日付が当日または直近営業日と一致しない場合、そのデータは使いません。取得できた銘柄のみ判定対象にし、未取得銘柄は理由付きで別枠表示します。

## 使い方

### mock データだけで実行

```bash
python skills/investment-agent/daily_stock_check.py --mock
```

### yfinance があれば yfinance → mock の順に再試行

```bash
python skills/investment-agent/daily_stock_check.py
```

### テスト

```bash
python -m pytest skills/investment-agent/tests
```

## 実行例

```text
2026/07/09
TOPIX前日比：-1.15%
指数ソース：一致

(A) 相場要因の下げ
- 5713 住友金属鉱山: 終値 4,280.00 / 前日終値 4,485.00 / 下落率 -4.57% / 買いレンジ 4,151.60〜4,215.80
...

全銘柄確認状況
- 取得済み
  - 5713 住友金属鉱山（mock）
- 未取得
  - 5698 エンビプロHD: 要確認（データ未取得） - mock: データなし

翌営業日の買い方
- 寄りは避けて指値分割。買いレンジ内で複数回に分け、データ未取得銘柄は約定前に必ず再確認する。

本日の結論
07/09のニュースだよ。要確認（データ未取得）を最優先。取得済み銘柄だけで暫定判定し、未取得銘柄は断定しない。
```
