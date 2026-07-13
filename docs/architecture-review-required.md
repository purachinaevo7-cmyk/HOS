# Architecture Review Required

The MVP intentionally keeps some advanced behavior conservative:

- True concurrent execution and cancellation are represented in workflow metadata but execute sequentially in local MVP runner.
- Research providers are fixture/disabled first; production HTTP research needs legal, robots, rate-limit, and source-quality review.
- JSON schemas should be tightened per agent after real sample outputs are reviewed.
- Resume currently preserves run state and supports inspection; automatic continuation from the exact failed step needs a deeper scheduler design.
- Cost accounting for real AI calls is not yet enforced beyond configuration placeholders.
