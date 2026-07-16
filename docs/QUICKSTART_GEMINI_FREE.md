# Gemini Free Tier Quickstart

This guide runs HOS AI Company with Google Gemini API free-tier settings, without requiring OpenAI paid API usage.

## 1. Get a Gemini API key

1. Open Google AI Studio.
2. Create or select a project.
3. Create an API key.
4. Store it securely. Do not paste it into tasks, prompts, logs, screenshots, or Git history.

## 2. Local run

```bash
cp .env.example .env
export GEMINI_API_KEY="your-key"
export GEMINI_MODEL="gemini-2.5-flash"
export HOS_EXECUTOR=gemini
export HOS_FREE_TIER_MODE=true
export HOS_MAX_AGENT_CALLS=5
export HOS_MAX_RETRIES=1
export GEMINI_MAX_OUTPUT_TOKENS_DEFAULT=2048
export GEMINI_MAX_OUTPUT_TOKENS_CEO=3000
python -m orchestrator.cli run tasks/inbox/investment_analysis.sample.json --executor gemini
```

For the 5-agent Lite workflow, set `workflow` to `investment_analysis_free` in the task JSON.

## 3. GitHub Actions

1. Repository → Settings → Secrets and variables → Actions.
2. Add repository secret `GEMINI_API_KEY`.
3. Run **HOS AI Company** manually.
4. Choose `executor=gemini`.
5. Use workflow `investment_analysis_free` for free-tier tests.
6. Download the `hos-run-<run_id>` artifact and inspect `usage.json`.

## Free-tier cautions

- Free tier availability, quota, rate limit, and model access are not guaranteed.
- Do not enter personal information, credentials, unpublished financial data, or confidential business information.
- If quota is exhausted, HOS marks the step/run partial or failed and writes the error into run artifacts.
- HOS does **not** switch from Gemini to OpenAI API automatically.
- HOS does **not** silently switch to mock.
- Missing `GEMINI_API_KEY` fails explicitly.

## Structured Output hardening (updated 2026-07-16)

HOS now sends Gemini `generationConfig.responseMimeType=application/json` **and** a formal `responseSchema` for the agent-specific `data` object. Gemini does not generate the HOS Agent Output Envelope; HOS deterministically wraps `schema_version`, `agent_id`, `agent_version`, `run_id`, `task_id`, `step_id`, `status`, `generated_at`, `usage_metadata`, `warnings`, `errors`, and `missing_information` after strict JSON parsing.

Default model: `gemini-2.5-flash`. This default was selected on 2026-07-16 after checking Google's Gemini API structured-output documentation, which documents JSON Schema structured output for Gemini API generateContent. HOS validates `GEMINI_MODEL` at startup by listing available models and checking `generateContent` support; it does not guess or auto-switch to paid/OpenAI/mock providers.

Token limits are configurable with `GEMINI_MAX_OUTPUT_TOKENS_DEFAULT=2048`, `GEMINI_MAX_OUTPUT_TOKENS_CEO=3000`, and agent-specific `GEMINI_MAX_OUTPUT_TOKENS_<AGENT_ID>` overrides. The built-in initial limits are ceo_planner 1200, researcher 2000, base_analyst 2400, devils_advocate 1600, and ceo_integrator 3000.

### One-call smoke test

GitHub Actions workflow_dispatch has `gemini_smoke_test=true`. In this mode HOS performs exactly one short structured-output call, validates JSON parsing, prints `Gemini smoke test: PASS`, the model, finishReason, and validJSON, and skips the full investment workflow.

### finishReason handling

HOS records finishReason, finishMessage, safetyRatings, candidate count, response length, usageMetadata, model, agent id, step id, attempt, and output token limit before parsing. `MAX_TOKENS` is treated as `OUTPUT_TRUNCATED`, not as a generic JSONDecodeError. `SAFETY`, `RECITATION`, and `MALFORMED_RESPONSE` become `INVALID_PROVIDER_RESPONSE` diagnostics.

Malformed JSON and provider failures are saved under `runs/<run_id>/diagnostics/gemini_<step_id>_<attempt>.json` with SHA-256, parse location when available, sanitized prefixes/suffixes, usage metadata, and no API key. 503 responses preserve sanitized provider body and Retry-After, retry at most once, and are counted as calls.

Partial runs keep completed agent outputs and write `usage.json` with planned, actual, successful, failed, retry calls, calls by agent, token usage by agent, finish reasons, and provider errors.
