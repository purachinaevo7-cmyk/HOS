# Stock Watch V2 DESIGN

Stock Watch V2は、60歳時点の金融資産2億円・年間配当600万円を長期目標に、無料データ基盤で取得できる情報だけを使って買い候補を判定します。取得不能データは捏造せず、BUYを抑止します。

## Key points
- Universe: `skills/investment-agent/config/stock_watch_universe.json`。
- Portfolio policy: `skills/investment-agent/config/portfolio_policy.json`。
- Outputs: `outputs/stock_watch_decisions.json`, `outputs/stock_watch_summary.json`, `outputs/portfolio_goal_progress.json`。
- Discord: NO_ALERTは既定で通知なし。WATCH以上だけ短文通知。
- Operations: 夜間は保存中心、朝補完は未取得補完と判定変化時通知。BUY/REVIEW_REQUIREDは即確認。

## BUY confirmation checklist
1. 予算、現金余力、NISA枠を設定する。
2. 最新決算、会社予想、減配/下方修正、重要ニュースを確認する。
3. 単一銘柄8%、業種上限、現金10%を超えないことを確認する。
4. 指値、株数、分割回数、有効期限、見送り条件を確認する。

## Rollback
V2 JSONを退避し、従来の`watchlist.yaml`を使う状態へ戻す。GitHub Actionsは同じentrypointを使うため、必要なら該当コミットをrevertする。
