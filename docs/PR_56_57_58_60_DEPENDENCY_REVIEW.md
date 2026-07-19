# PR #56/#57/#58/#60 dependency review

Date: 2026-07-19

## Goal

Merge only PR #60 as the final deliverable, while avoiding an implicit dependency on PR #56, PR #57, or PR #58.

## Observed PR metadata

| PR | Branch | Scope | Files shown by GitHub | Relationship to PR #60 |
| --- | --- | --- | --- | --- |
| #56 | `codex/285a-verified-fact-pipeline` | First-pass 285A verified fact discovery diagnostics and official IR/PDF parsing hardening. | `orchestrator/investment_facts/__init__.py`, `orchestrator/runner.py`, `requirements.txt` | Conceptually overlaps with #60. Treat #60 as the superseding implementation; do not merge #56 separately unless a line-by-line review finds unique behavior that #60 intentionally omitted. |
| #57 | `codex/pr-github-actions` | Regression test for the existing HOS AI Company workflow dispatch contract. | `tests/test_actions_workflow.py` | Independent of #60. Not needed for the #60 final deliverable because it does not change the investment fact pipeline. |
| #58 | `codex/pr-github-actions-0i9ig5` | Duplicate of #57 with the same title, description, and test-file-only scope. | `tests/test_actions_workflow.py` | Independent duplicate of #57. Not needed for #60. |
| #60 | `codex-9uii3q` | Harden Kioxia verified fact extraction: PDF/AES support, document identity checks, numeric extraction, dividend semantics, official news discovery, Yahoo metadata diagnostics, URL canonicalization, and regression fixtures/tests. | `orchestrator/investment_facts/__init__.py`, `requirements.txt`, `tests/fixtures/285A_2026_earnings_text.pdf`, `tests/test_investment_facts.py` | Desired final deliverable. |

## Dependency conclusion

1. PR #60 is the only PR that should be merged as the final deliverable.
2. PR #56 should not be merged separately because its core investment-fact-pipeline scope is superseded by PR #60, which covers the same problem area and adds broader regression coverage.
3. PR #57 and PR #58 should not block PR #60. They only add a workflow-dispatch regression test and do not change runtime code used by the verified investment fact pipeline.
4. PR #57 and PR #58 are mutually redundant: both have the same title, motivation, description, commit subject, and single-file test-only scope.

## Main-merge readiness checks performed locally

The local branch already contains the HOS AI Company workflow dispatch contract that PR #57/#58 test for: `name: HOS AI Company`, `workflow_dispatch`, and `task_json` are present in `.github/workflows/hos-ai-company.yml`.

The local branch could not fetch GitHub PR refs directly with `git ls-remote` because outbound Git HTTPS was blocked by the environment (`CONNECT tunnel failed, response 403`). GitHub PR metadata was therefore checked through the web-rendered PR pages, and local merge-readiness was checked against the repository files available in this workspace.

## Recommended merge plan

1. Use PR #60 as the integration branch/final PR.
2. Close #56 as superseded by #60 after confirming reviewers do not require its `orchestrator/runner.py` changes; #60's declared scope intentionally concentrates the final fix in `orchestrator/investment_facts/__init__.py`, `requirements.txt`, and regression tests/fixture.
3. Close #57 and #58 as unnecessary duplicates for the #60 deliverable. If desired, keep one of them for a separate workflow-test cleanup, but do not make #60 depend on either.
4. Before merging #60, run the full test suite on the branch that contains #60 and confirm GitHub reports it as mergeable into `main`.
