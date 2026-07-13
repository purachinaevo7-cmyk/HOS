# HOS AI Company Quickstart

## Morning local start

```bash
python -m orchestrator.cli doctor
python -m orchestrator.cli validate-agents
python -m orchestrator.cli validate-workflows
python -m orchestrator.cli validate-task tasks/inbox/investment_analysis.sample.json
python -m orchestrator.cli run tasks/inbox/investment_analysis.sample.json --executor mock
python -m orchestrator.cli list-runs
```

Open `ai-company.html` from GitHub Pages or a local static server:

```bash
python -m http.server 8000
# http://localhost:8000/ai-company.html
```

## Windows / macOS / Linux

Use Python 3.12. On Windows, run the same commands from PowerShell. On macOS/Linux, run from a shell in the repository root.

## Real AI setup

ChatGPT Plus and OpenAI API are separate. ChatGPT Plus does **not** provide an API key. Create an OpenAI API key, then:

```bash
export HOS_EXECUTOR=openai
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://api.openai.com/v1
python -m orchestrator.cli run tasks/inbox/investment_analysis.sample.json --executor openai
```

If `OPENAI_API_KEY` is missing, the OpenAI executor fails and does not silently switch to mock.

## GitHub Actions

Run **HOS AI Company** from the Actions tab. Paste Task JSON from `ai-company.html` into `task_json`, choose `mock` or `openai`, then download the `hos-run-<run_id>` artifact.
