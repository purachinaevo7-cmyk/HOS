# Investment Fact Pipeline Design

`build_fact_pack()`はLLMを使わずProviderを優先順に呼ぶ。契約は company profile / price / history / financials / valuation / dividends / news / identity と、共通結果（status, data, source, source_url, fetched_at, error_type, error_message, confidence）。失敗は記録して次Providerへ進むが、銘柄同一性を跨いで混合しない。

Fact Pack v1は company, price, price_trend, financials, valuation, shareholder_returns, news, risks, identity_validation, source_map, data_quality を持つ。Source Map IDをAgent evidenceのsource_refsから参照し、fact_refsはPack内パスを示す。

必須gateは同一性、上場、最新株価、最新決算、最新IR、価格日、主要リスク、3出典。BUY_CANDIDATEにはさらにvaluation、配当、ニュース、portfolioが必要である。現在は自動BUYを常に禁止する。Agent出力にIPO前などPackと相反する記述があればREVIEW_REQUIREDとする。

Run監査物は `fact_pack.json`, `facts/`, `sources/`, `claims/`, `diagnostics/`, `contradictions.json`, `final_decision.json`。Commander向けには `outputs/investment_fact_pack_<task>.json` と `outputs/investment_decision_<task>.json` を生成する。
