# Fact Provider Matrix

| Provider | Section | Free tier behavior | Network gated | Notes |
|---|---|---:|---:|---|
| JPXProvider | identity/listing | cached Phase A records, fallback-safe | no | Identity Validation primary source for Phase A. |
| OfficialRegistryProvider | identity/listing | audited static fallback | no | Keeps existing registry fallback behavior. |
| OfficialIRProvider | profile/financials/dividends | official company IR URL only | yes for HTML | Missing values remain null; no model completion. |
| EDINETProvider | financial filings | optional only | yes if configured | `EDINET_API_KEY` absence never stops pipeline. |
| StockWatchProvider | price | reuses Stock Watch V2 artifacts | no | Preferred cached price source. |
| YahooChartProvider | price/technical | free Yahoo chart endpoint | yes | Used only when network verified mode is enabled. |
| ValuationProvider | valuation | null-safe placeholders | no | Missing valuation blocks BUY_CANDIDATE. |
| OfficialNewsProvider | official news | official IR updates page only | yes for HTML | No SNS or anonymous sources. |
