# HOS Architecture v2

## Vision
HOS operates as a small **HOS AI Company**, not a chatbot. CEO frames requests, assigns work, judges quality, and performs final Markdown integration.

## Scope
This version implements a single-repository, GitHub Pages compatible foundation for registry-driven agents, YAML workflows, dry-run execution, review/rework, artifacts, logs, and reflection.

## Non-goals
No mandatory external AI API, vector database, server process, or autonomous prompt/workflow rewriting.

## System Architecture
Task JSON is accepted by `orchestrator.runner.Orchestrator`, a YAML workflow is loaded by `WorkflowEngine`, enabled agents are loaded from `agents.yaml`, and `MockAgentExecutor` returns JSON-only outputs for local tests.

## Directory Structure
- `agents/`: prompt contracts.
- `agents.yaml`: dynamic registry.
- `workflows/`: dependency source of truth.
- `orchestrator/`: registry, workflow engine, services, runner.
- `outputs/reports`, `outputs/json`, `outputs/logs`, `outputs/reflections`: run artifacts.
- `docs/adr`: architecture decisions.
- `tests/`: pytest coverage.

## Task Lifecycle
Task受付 → Workflow選択 → Agent Registry取得 → Agent実行 → Workflow Context保存 → Creative Challenger → Devil's Advocate → Review → targeted rework if critical → HOS Writer JSON → CEO Markdown → log/reflection.

## Agent Registry
`agents.yaml` defines id, display name, role, prompt path, version, enabled flag, model settings, timeout, tools, output schema, and tags. Unknown or disabled IDs are explicit errors. Prompt/schema paths are validated before execution.

## Workflow Engine
Workflow YAML defines steps with id, agent, action, depends_on, input_mapping, output_key, condition, validation, retry_policy, timeout_seconds, and continue_on_error. The engine validates missing dependencies, cycles, and unknown agents.

## Orchestrator
The Orchestrator validates tasks, chooses/loads workflow, controls step execution, passes context, handles review-triggered rework, saves artifacts, and writes structured logs. It does not hardcode per-agent routing decisions beyond using the configured executor.

## Agent Execution Adapter
`MockAgentExecutor` supports API-key-free deterministic dry-run. Future adapters may read environment variables for OpenAI-compatible providers without logging secrets.

## Workflow Context
All outputs are stored under `context["outputs"][output_key]`. Agents do not communicate directly.

## Review and Retry
Review output uses `approved`, `severity`, `critical_errors`, `warnings`, `missing_information`, `rework_agents`, and `reviewed_output_keys`. Only `critical` triggers rework and the workflow maximum prevents loops.

## Creative Challenger
Runs after base analysis and before review. It evaluates novelty, impact, evidence, feasibility, and learning value, while avoiding novelty-only ideas.

## Devil’s Advocate
Separate from Creative Challenger; it records rejection reasons, broken assumptions, failure scenarios, missing evidence, and disconfirming signals.

## Memory
`MemoryService` stores task history, decisions, preferences, and reflections as JSON files. Agents do not write memory directly.

## Knowledge
`KnowledgeService` stores JSON entries with id, title, content, source, source_date, confidence, timestamps, created_by_agent, version, tags, freshness_status, and next_review_date. Search is keyword/tag based and replaceable later.

## Reflection
Reflection is generated after workflow completion and saved as JSON. It never rewrites prompts or workflow definitions automatically.

## Logging
Structured JSONL logs include run_id, task_id, workflow_id/version, step_id, agent_id/version, status, timestamps, duration, retry_count, error fields, and artifact paths.

## Configuration
Agents are configured in `agents.yaml`; workflows are configured in YAML. API secrets must come from environment variables in future adapters.

## Security
Do not log API keys, secrets, or unnecessary personal data. Dry-run must not fabricate market data.

## Testing
Pytest covers registry, workflow validation, conditions, review rework, CEO-only Markdown, artifact saving, reflection, and dry-run end-to-end. Node test covers existing investment UI logic.

## Extension Rules
Add an agent by adding prompt, schema, registry entry, and workflow reference. Do not add if/elif branches in the Orchestrator for routing.

## Migration Strategy
Keep static pages and existing Investment Commander files intact. Connect new artifacts to UI via future adapters if needed.

## Artifact Index
Each non-dry run updates `outputs/index.json` with task metadata, workflow version, display metadata, tags, keywords, and relative paths for the final report, HOS update JSON, structured log, and reflection. This gives GitHub Pages or other static adapters a single stable manifest instead of requiring directory scans.

## Usable MVP Additions
- Canonical Agent Registry lives at `agents/registry.yml`; legacy `agents.yaml` is retained for compatibility only.
- `orchestrator.cli` provides doctor, validation, run, inspect, resume/cancel status updates, export, and UI data export.
- Run bundles are written to `runs/<run_id>` and legacy `outputs/` paths remain compatible.
- `ai-company.html` is a static GitHub Pages Control Center for task creation, registry viewing, workflow viewing, and run viewing.
- `.github/workflows/hos-ai-company.yml` runs mock/openai executions and uploads bundles.

## Current limitations
The current executor is deterministic mock logic. External market data and real LLM execution are intentionally deferred.
