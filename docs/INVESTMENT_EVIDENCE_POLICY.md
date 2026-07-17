# Investment Evidence Policy

重要主張（上場、業績、財務、競争力、成長、配当、valuation、risk、decision）は `claim`, `fact_refs`, `source_refs`, `confidence` を必須とする。source_refsはFact Packのsource_mapに存在しなければならない。根拠なしはUNSUPPORTED_CLAIM、Packとの不一致はCONTRADICTORY_CLAIMである。

不足は削除せずmissing_informationへ列挙する。evidenceがない分析、identity mismatch、古い/不足データ、source conflictは投資判断に使ってはならず、DATA_INSUFFICIENTまたはREVIEW_REQUIREDとする。Fact Packがgateを通り、人が出典本文を確認した場合にのみ検証テストへ進める。本システムは注文を行わない。
