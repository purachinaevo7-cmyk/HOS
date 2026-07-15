from pathlib import Path


def test_github_actions_gemini_timeout_input_reflected():
    text=Path('.github/workflows/hos-ai-company.yml').read_text()
    assert 'gemini_timeout_seconds:' in text
    assert "default: '90'" in text
    assert 'GEMINI_TIMEOUT_SECONDS: ${{ inputs.gemini_timeout_seconds' in text
