# HOS AI Company Security

- API keys are read from environment variables or GitHub Secrets only.
- `GEMINI_API_KEY` and `OPENAI_API_KEY` must never be committed or pasted into tasks.
- Gemini and OpenAI executors refuse to run without their own required key and do not fall back to mock.
- Quota exhaustion does not trigger paid OpenAI execution.
- Do not submit personal information, credentials, unpublished company information, or other confidential data to external AI providers.
- Run Viewer surfaces sanitized error messages so operators can see rate-limit, quota, timeout, and server failures without exposing secrets.
