# HOS AI Company Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| OpenAI run fails | `OPENAI_API_KEY` absent | Add API key; do not expect ChatGPT Plus to work as API auth. |
| Task rejected | `validate-task` | Ensure `task_id`, `request`, and `target` exist. |
| UI has no agents | `data/agents.json` missing | Run `python -m orchestrator.cli export-agents-ui`. |
| Investment import fails | JSON shape | Use `runs/<run_id>/outputs/investment_commander.json`. |
