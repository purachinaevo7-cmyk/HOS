# Investment Fact Pipeline Audit

## 現状フロー（改修前）
`investment_analysis*.yml` は planner → researcher → base analyst → devil's advocate → CEO integration の会議フローを定義していたが、LLM呼出し前に企業同一性・株価・決算を取得する決定論的ステップはなかった。Taskと先行Agent文章がそのままContextとなり、`researcher`は「調査観点」の自由作文だった。従って推論は最初のplannerから開始され、鮮度の機械判定、source map、claim-to-source検証は存在しなかった。

## 原因
* Gemini Structured OutputはJSONの形だけを保証し、内容の真偽を保証しない。
* evidence/missing_informationはenvelope上で空配列が許可され、重要主張との対応検証がなかった。
* 株価取得（Stock Watch V2/Yahoo）とAI Company Runの接続がなく、IR/JPX/EDINETの取得結果もContextに注入されなかった。
* CEOが先行出力にない事実を追加でき、`listed=true`と「IPO前」を照合するgateがなかった。

## 改修
LLMより先にFact Packを生成し、identity validation、source map、data sufficiency gateをContextへ注入する。各step後にevidence参照と上場矛盾を診断し、Run配下へ保存する。未知値はnull/欠落として保持し、DATA_INSUFFICIENTに倒す。

## Known limitations
内蔵公式registryは現在キオクシアHDのみ。JPXページの構造化取得、EDINET API、IR PDF数値抽出、報道検索は未実装。Yahoo network取得は明示opt-inで、利用条件・ブロック・遅延の影響を受ける。決算、valuation、newsが欠ける現状のfixtureは意図的にDATA_INSUFFICIENTとなる。
