# HOS AI Company Operations

- Use `mock` for safe morning smoke tests.
- Use `openai` only after `OPENAI_API_KEY` is configured as a GitHub secret or local environment variable.
- Review `runs/<run_id>/run.json`, `reports/final.md`, `outputs/hos_update.json`, and `outputs/investment_commander.json` before acting.
- Knowledge candidates are never auto-approved. Use `list-knowledge-candidates`, then approve/reject after human review.
