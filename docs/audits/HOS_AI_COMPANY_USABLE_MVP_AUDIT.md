# HOS AI Company Usable MVP Audit

Date: 2026-07-13
Branch / PR: PR #38 continuation on current working branch
Method: Compared the original full request against repository files, tests, and CLI behavior. This document intentionally does **not** mark the PR complete unless a requirement is implemented and verified in code.

| Requirement | Status | Current implementation | Evidence | Gap / risk | Required change | Verification |
|---|---|---|---|---|---|---|
| Preserve current PR changes | implemented | Continued on current branch; no reset to main. | `git log`, current tree | Push blocked locally by network | Attempt push after commit | `git status`, `git log` |
| AI Company UI | implemented | Static Control Center exists. | `ai-company.html`, `ai-company.js`, `ai-company.css` | UI is static; no direct backend execution from Pages | Keep honest guide labels | `node --check ai-company.js` |
| Task JSON creation screen | implemented | Form creates, previews, copies, downloads, saves Task JSON. | `ai-company.js` | Browser E2E not automated | Add manual checklist | `node --check ai-company.js` |
| Workflow selection | implemented | UI loads `data/workflows.json` into selector. | `ai-company.js`, `data/workflows.json` | Requires regenerated data after registry/workflow edits | `export-agents-ui` | `python -m orchestrator.cli export-agents-ui` |
| GitHub Actions execution path | implemented | `hos-ai-company.yml` validates and runs tasks. | `.github/workflows/hos-ai-company.yml` | Not executed on GitHub from this environment | Use Actions UI after push | YAML inspection, CLI local equivalent |
| Run Viewer | implemented | Static paste/file JSON viewer. | `ai-company.html`, `ai-company.js` | Visualization is JSON-centric, not full timeline | Improve later | `node --check ai-company.js` |
| OpenAICompatibleExecutor | partial | Adapter builds JSON-mode request, requires `OPENAI_API_KEY`, handles 429/5xx/timeout. | `orchestrator/executor.py` | Live API smoke not run; no token cost enforcement | Run with real API key | Unit/doctor; manual API smoke |
| mock and real AI separation | implemented | `build_executor` explicitly selects `mock`, `openai`, or `replay`; openai refuses missing key. | `orchestrator/executor.py`, `.env.example` | Provider-specific response edge cases untested | Add provider fixtures | CLI and tests |
| Multiple workflows | implemented | 5 workflow YAMLs and sample tasks exist. | `workflows/*.yml`, `tasks/inbox/*.sample.json` | Non-investment payloads use generic mock data | Specialize later | 5 mock E2E runs |
| Run-unit persistence | implemented | `runs/<run_id>` with manifest/task/steps/reports/outputs/logs. | `orchestrator/artifacts.py`, `orchestrator/runner.py` | Dry-run creates run dir by design for inspectability | Document behavior | CLI run/inspect/export |
| Artifact Index keyed by run_id | implemented | `outputs/index.json` keeps one entry per `run_id`, preserving multiple runs of same `task_id`. | `orchestrator/services.py` | Existing legacy entries without run_id use task fallback | Migration is best-effort | pytest index test |
| Resume | partial | CLI `resume` safely inspects existing run; full failed-step continuation deferred. | `orchestrator/cli.py`, `docs/architecture-review-required.md` | Not a full scheduler resume | Design scheduler | CLI inspect/resume smoke |
| Strict schema | partial | Task schema and output envelope schema exist; runtime task validation exists. | `schemas/*.json`, `orchestrator/schemas.py` | No third-party JSON Schema validation dependency; nested payloads not fully strict | Add jsonschema or Pydantic later | pytest task/envelope checks |
| Investment Commander import compatibility | implemented | Runner emits `stockAnalysisUpdate` with required fields; tests assert shape. | `orchestrator/runner.py`, `tests/test_hos_v2.py` | Browser import E2E still manual | Add browser automation later | pytest |
| Quickstart | implemented | Local, real AI, and Actions instructions exist. | `docs/QUICKSTART_AI_COMPANY.md` | Needs GitHub URL after push | Update PR after push | docs review |
| Morning Checklist | implemented | Review and operation checklist exists. | `docs/MORNING_START_CHECKLIST.md` | Needs real Pages check after push | Manual after deploy | docs review |
| Research provider | missing | No safe HTTP research provider in PR #38. | code inspection | Original request asked interface/providers | Implement separately before YES status | Architecture review required |
| True parallel execution | missing | Workflow has concurrency metadata but runner is sequential. | `workflow.py`, `runner.py` | Original request asked safe parallel execution | Scheduler design needed | Architecture review required |
| Full cancellation | partial | CLI can mark run cancelled; active process cancellation not implemented. | `orchestrator/cli.py` | Not a running scheduler cancel | Scheduler design needed | Architecture review required |
| API cost governance | missing | Env placeholders exist; enforcement not implemented. | `.env.example` | Max cost not enforced | Add token/cost accounting | Architecture review required |

## Bottom line
PR #38 is **not complete** against the full original request. It is a usable mock-first MVP slice with several critical missing/partial items documented above.
