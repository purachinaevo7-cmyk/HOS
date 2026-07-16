# HOS AI Company Operations

## Modes

- `mock`: deterministic local execution.
- `gemini`: Google Gemini API execution for free-tier-oriented runs.
- `openai`: OpenAI-compatible API execution.
- `replay`: inspect stored run steps.

## Gemini free-tier operation

Use `investment_analysis_free` with:

```bash
export HOS_EXECUTOR=gemini
export HOS_FREE_TIER_MODE=true
export HOS_MAX_AGENT_CALLS=5
export HOS_MAX_RETRIES=1
python -m orchestrator.cli run <task.json> --executor gemini
```

The orchestrator prints estimated calls before running, records actual calls during execution, and writes `runs/<run_id>/usage.json`.

Quota exhaustion yields partial output when possible; it never auto-routes to OpenAI or mock.

## Gemini structured output operations

Gemini execution is schema-first: HOS sends an agent data JSON Schema and wraps the returned data in the Agent Output Envelope locally. Do not rely on prompt-only "Return ONLY JSON" behavior. If an agent has no Gemini data schema, execution stops before the API call.

For `MAX_TOKENS`, inspect the run diagnostic JSON and either increase `GEMINI_MAX_OUTPUT_TOKENS_<AGENT_ID>` or shorten the task. HOS will retry at most once in free-tier mode and then save a partial run. For malformed JSON, use the sanitized diagnostic file; do not mark repaired JSON as completed unless explicitly reviewed. For 503, HOS preserves the sanitized response body, records Retry-After, retries once, and never switches to OpenAI or mock automatically.
