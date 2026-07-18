from pathlib import Path

import json

import pytest

from scripts.extract_hos_run_id import extract_run_id


def test_hos_ai_company_workflow_is_manually_dispatchable_on_pr_branch():
    text=Path('.github/workflows/hos-ai-company.yml').read_text()
    assert 'name: HOS AI Company' in text
    assert 'workflow_dispatch:' in text
    assert 'task_json:' in text


def test_github_actions_gemini_timeout_input_reflected():
    text=Path('.github/workflows/hos-ai-company.yml').read_text()
    assert 'gemini_timeout_seconds:' in text
    assert "default: '90'" in text
    assert 'GEMINI_TIMEOUT_SECONDS: ${{ inputs.gemini_timeout_seconds' in text


def test_actions_uses_result_manifest_and_validates_artifact_paths():
    text=Path('.github/workflows/hos-ai-company.yml').read_text()
    assert '| tee hos-run-result.json' not in text
    assert '--json-output hos-run-result.json' in text
    assert 'scripts/extract_hos_run_id.py hos-run-result.json' in text
    for path in ('runs/${{ steps.run.outputs.run_id }}/', 'runs/${{ steps.run.outputs.run_id }}/usage.json', 'outputs/index.json', 'hos-run-result.json'):
        assert path in text


def test_extract_run_id_success_and_errors(tmp_path):
    runs=tmp_path/'runs'; (runs/'run-1').mkdir(parents=True)
    manifest=tmp_path/'result.json'
    manifest.write_text(json.dumps({'run_id':'run-1'}),encoding='utf-8')
    assert extract_run_id(manifest,runs)=='run-1'

    with pytest.raises(ValueError,match='not generated'):
        extract_run_id(tmp_path/'missing.json',runs)
    manifest.write_text('{bad',encoding='utf-8')
    with pytest.raises(ValueError,match='invalid'):
        extract_run_id(manifest,runs)
    manifest.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='no run_id'):
        extract_run_id(manifest,runs)
    manifest.write_text(json.dumps({'run_id':'missing-run'}),encoding='utf-8')
    with pytest.raises(ValueError,match='run directory'):
        extract_run_id(manifest,runs)
