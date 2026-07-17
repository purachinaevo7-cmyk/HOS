# Investment Fact Pipeline Operations

1. Taskのticker/company_nameを確認する。2. 必要なら `HOS_ENABLE_NETWORK_FACTS=true` としてRun（Yahooのみ、無料、失敗時fallback）。3. `runs/<id>/fact_pack.json` のidentity、日付、missing/conflict/provider_errorsを確認。4. source URL本文を人が照合。5. diagnostics gateとcontradictionsを確認。6. DATA_INSUFFICIENT/REVIEW_REQUIREDなら判断を利用せず再取得する。

公式IR不可はOFFICIAL_SOURCE_UNAVAILABLE、株価不可はPRICE_UNAVAILABLE、PDF抽出不可はPDF_PARSE_FAILEDとして保持する。無料範囲は内蔵registry、既存Stock Watch V2成果物、opt-in Yahoo chartであり、EDINET keyは将来optional。Gemini無料枠を維持し、OpenAI/有料APIは不要。Known limitationは監査文書を参照。
