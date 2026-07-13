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
export GEMINI_MODEL="gemini-1.5-flash"
export HOS_EXECUTOR=gemini
export HOS_FREE_TIER_MODE=true
export HOS_MAX_AGENT_CALLS=5
export HOS_MAX_RETRIES=1
export HOS_MAX_OUTPUT_TOKENS_PER_AGENT=1200
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
