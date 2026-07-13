# HOS AI Company Usable MVP Audit

Date: 2026-07-13  
Branch: work  
Basis: local code inspection and test execution plan. `main` remote is unavailable in this workspace, so the current branch is treated as the existing PR branch.

| Requirement | Current implementation | Evidence | Gap | Required change | Verification | Status |
|---|---|---|---|---|---|---|
| Agent Registry | Legacy `agents.yaml` exists; canonical registry added at `agents/registry.yml`. | `orchestrator/registry.py`, `agents/registry.yml` | Legacy fields were too small and UI export absent. | Add canonical fields, duplicate/disabled/schema/provider validation, UI export. | `python -m orchestrator.cli validate-agents` | Improved |
| Workflow Engine | YAML workflow engine exists. | `orchestrator/workflow.py`, `workflows/investment_analysis.yml` | Lacked output_key duplicate checks and UI export. | Add validation and CLI visualization/export. | `python -m orchestrator.cli validate-workflows` | Improved |
| Orchestrator | Runner executes workflow and writes artifacts. | `orchestrator/runner.py` | Mock logic was embedded and run bundles missing. | Add adapter module, run persistence, CLI bundle export. | `python -m orchestrator.cli run ...` | Improved |
| Executor | Mock executor existed inside runner. | `orchestrator/runner.py` | Real AI/replay selection was unclear. | Add `DeterministicMockExecutor`, `OpenAICompatibleExecutor`, `ReplayExecutor`; no API-key auto-success. | `python -m orchestrator.cli doctor` | Improved |
| Schema | Agent schemas were minimal. | `schemas/agent_outputs/*.json` | No common envelope. | Add formal schemas for task/run/artifact/HOS update/investment update. | `python -m orchestrator.cli validate-task ...` | Partial |
| Review / Rework | Critical review can trigger targeted rerun. | `tests/test_hos_v2.py` | Rework history not persisted per run. | Persist run manifest and logs; document resume limits. | `python -m orchestrator.cli inspect-run <run_id>` | Partial |
| Task lifecycle | CLI runner existed. | `README.md` | User could not create task from UI. | Add AI Company Control Center static UI. | `node --check ai-company.js` | Improved |
| Artifact structure | Legacy outputs and index exist. | `outputs/`, previous commit | No run bundle. | Add `runs/<run_id>` with manifest/task/run/artifacts. | `python -m orchestrator.cli export-run <run_id>` | Improved |
| UI | Existing HOS pages exist. | `index.html`, `style.css` | No AI Company UI. | Add `ai-company.html/js/css`; nav link. | Static serve / JS checks | Improved |
| GitHub Actions | Stock workflows exist. | `.github/workflows/*.yml` | No AI Company workflow dispatch. | Add `.github/workflows/hos-ai-company.yml`. | YAML text inspection / action smoke command | Improved |
| Investment Commander | Parser exists. | `investment.js` | HOS update not directly shaped for import. | Generate `investment_commander.json`; add mapper test. | `pytest -q`, `node --test investment.test.js` | Improved |
| GitHub Pages | Static pages exist. | `*.html` | New data export absent. | Add `data/agents.json`, `data/workflows.json`. | `python -m orchestrator.cli export-agents-ui` | Improved |
| Secrets | No sanitizer module. | code inspection | Need redaction and path safety. | Add `orchestrator/security.py`; use in logs. | sanitizer unit test | Improved |
| Docs reproducibility | README had dry-run only. | `README.md` | No morning-use guide. | Add quickstart, ops, troubleshooting, security, checklist. | docs review | Improved |

## Assumptions
- Network push may be blocked in this environment; final push is attempted and result is reported honestly.
- External web research remains disabled/fixture-based until a safe provider is reviewed.

## Architecture Review Required
- Full JSON Schema coverage for every nested agent-specific payload should be tightened after MVP usage feedback.
- True parallel execution, cancellation semantics, and cost accounting need a deeper design pass before production use.
