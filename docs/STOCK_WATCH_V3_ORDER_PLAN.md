# Stock Watch V3 private order-plan contract

Live order plans are private household data. They are supplied only through the
`HOS_PRIVATE_PROFILE_JSON` GitHub Actions Secret and must not be committed,
printed, uploaded as an artifact, or copied to GitHub Summary.

## Public contract

The public repository provides the evaluator and a schema. A private strategy
uses generic account IDs such as `member_a` and `member_b`; private display
names are resolved only while rendering the Discord report.

Each order must include a fixed limit price, an explicit step id, a decision
status, and a verified holding baseline when its share calculation depends on
an existing position. `completed_step_ids` are private execution state and are
never inferred from a balance change.

## Purchase authority

`PURCHASE_READY` is emitted only when all of the following are true:

- the strategy is active and registered;
- the current step is the first incomplete step;
- the fixed limit is reached using fresh price data;
- the earnings assessment is POSITIVE and verified from official IR;
- account buying power, account budget, household budget, cash floor, and
  concentration checks pass;
- the daily order cap is not exhausted; and
- no execution-reconciliation, data-quality, or condition-review block exists.

HOS never submits an order or a sell order. A `PURCHASE_READY` notification is
an instruction to review a fixed-limit order manually, not an execution API.
