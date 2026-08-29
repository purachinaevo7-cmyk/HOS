from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dividend_screener_has_its_own_scheduled_public_data_job():
    text = (ROOT / ".github" / "workflows" / "dividend-screener.yml").read_text(encoding="utf-8")

    assert "name: Japan Dividend Screener" in text
    assert "cron: '30 9 * * 1-5'" in text
    assert "DIVIDEND_SCREENER_DISCORD_WEBHOOK_URL" in text
    assert "HOS_PRIVATE_PROFILE_JSON" not in text
    assert "\n      DISCORD_WEBHOOK_URL:" not in text
    assert "dividend_screener_runner.py" in text
    assert "actions/cache/restore@v4" in text
    assert "actions/cache/save@v4" in text
    assert "git add" not in text
