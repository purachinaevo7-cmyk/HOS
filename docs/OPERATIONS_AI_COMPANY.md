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
