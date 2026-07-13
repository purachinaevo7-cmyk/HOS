# HOS AI Company Security

- API keys are read only from environment variables or GitHub Secrets.
- OpenAI executor refuses to run without `OPENAI_API_KEY` and does not auto-fallback to mock.
- Secret redaction, safe filenames, task size limits, and path traversal guards are implemented in `orchestrator/security.py`.
- Prohibited without approval gate: email sending, stock orders, pushing to main, external publishing, deployment, destructive deletion, and personal information transmission.
- Logs must not contain raw provider responses or API keys.
