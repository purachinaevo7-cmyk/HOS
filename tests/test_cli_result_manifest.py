import json
from pathlib import Path

from orchestrator import cli


def test_cli_json_output_is_single_object_despite_stdout_logs(tmp_path, capsys, monkeypatch):
    output=tmp_path/'result.json'
    monkeypatch.setattr(cli, 'ROOT', Path(__file__).resolve().parents[1])
    assert cli.main(['run','tasks/inbox/investment_analysis.sample.json','--executor','mock','--dry-run','--json-output',str(output)]) == 0
    stdout=capsys.readouterr().out
    assert 'free_tier_mode' in stdout  # executor/orchestrator logging remains on stdout
    result=json.loads(output.read_text(encoding='utf-8'))
    assert set(('run_id','task_id','status','report_path','hos_json_path','usage_path','dry_run')) <= result.keys()
    assert result['run_id']
    assert result['status']=='completed'
    assert result['dry_run'] is True
    assert (cli.ROOT/'runs'/result['run_id']).is_dir()
    assert Path(result['usage_path']).is_file()
    # json.load consuming the whole file proves it is not JSON Lines or concatenated JSON.
    with output.open(encoding='utf-8') as stream:
        assert json.load(stream)==result
